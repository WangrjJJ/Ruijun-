#!/usr/bin/env python3
"""
JARVIS Weekly Report Generator — 周报生成器
汇总本周日报、邮件、决策、行动项，生成结构化周报。

用法:
  python3 weekly_report_gen.py                     # 生成本周周报
  python3 weekly_report_gen.py --date 2026-05-07    # 指定日期所在周
  python3 weekly_report_gen.py --week 18            # 指定周数
  python3 weekly_report_gen.py --print              # 输出到stdout
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VAULT_ROOT = os.path.dirname(SCRIPT_DIR)

sys.path.insert(0, SCRIPT_DIR)
from jarvis_common import (
    get_email_events, get_email_full_bodies, get_recent_decisions,
    get_stale_decisions, scan_vault_frontmatter, get_p0_action_items,
    get_week_boundaries, call_llm, load_config,
    WORK_AREA, OUTPUT_DIR_WEEKLY, EMAIL_EVENTS_FILE,
)

os.makedirs(OUTPUT_DIR_WEEKLY, exist_ok=True)

BRIEF_DIR = os.path.join(WORK_AREA, "日简报")


# ── 数据收集 ──────────────────────────────────────────────────────

def get_daily_briefs_in_week(monday: datetime, sunday: datetime) -> list:
    """加载本周所有日报"""
    briefs = []
    if not os.path.isdir(BRIEF_DIR):
        return briefs

    for i in range(7):
        d = monday + timedelta(days=i)
        date_str = d.strftime("%Y-%m-%d")
        filepath = os.path.join(BRIEF_DIR, f"每日工作简报_{date_str}.md")
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            briefs.append({"date": date_str, "path": filepath, "content": content})
    return briefs


def get_week_email_stats(monday: datetime, sunday: datetime) -> dict:
    """统计本周邮件"""
    events = get_email_events(24 * 10)  # 最近10天，再手动过滤
    week_events = []
    monday_str = monday.strftime("%Y-%m-%d")
    sunday_str = (sunday + timedelta(days=1)).strftime("%Y-%m-%d")
    for e in events:
        received = e.get("email_received", "")[:10]
        if monday_str <= received <= sunday_str:
            week_events.append(e)

    p0 = [e for e in week_events if e.get("priority") == "P0"]
    p1 = [e for e in week_events if e.get("priority") == "P1"]
    return {
        "total": len(week_events),
        "p0": len(p0),
        "p1": len(p1),
        "top_senders": _top_senders(week_events),
        "p0_p1_list": p0 + p1[:5],
    }


def _top_senders(events: list, top_n: int = 5) -> list:
    counts = {}
    for e in events:
        sender = e.get("sender_name", "?")
        counts[sender] = counts.get(sender, 0) + 1
    return sorted(counts.items(), key=lambda x: x[1], reverse=True)[:top_n]


def get_action_completion(monday: datetime, sunday: datetime) -> dict:
    """统计本周行动项完成情况"""
    items = get_p0_action_items()
    total_open = 0
    p0_open = 0
    p1_open = 0
    for item in items:
        n = len(item.get("open_tasks", []))
        total_open += n
        if item.get("priority") == "P0":
            p0_open += n
        else:
            p1_open += n
    return {"total_open": total_open, "p0_open": p0_open, "p1_open": p1_open}


# ── AI 周报摘要 ──────────────────────────────────────────────────

def generate_weekly_summary(briefs: list, email_stats: dict,
                            decisions: list, action_stats: dict) -> str:
    """LLM 生成周报摘要"""
    parts = [f"本周共{briefs.__len__()}个工作日。请根据以下信息生成周报摘要（300字以内），用中文。"]
    parts.append("格式：1)本周关键进展 2)重要决策 3)风险与阻塞 4)下周重点。")

    if email_stats["total"] > 0:
        parts.append(f"\n【邮件】共{email_stats['total']}封，P0紧急{email_stats['p0']}封，P1重要{email_stats['p1']}封。")
        for e in email_stats.get("p0_p1_list", [])[:5]:
            parts.append(f"- {e.get('priority','')}: {e.get('sender_name','?')} — {e.get('subject','')}")

    if decisions:
        parts.append(f"\n【决策】本周{len(decisions)}条。")
        for d in decisions[:5]:
            parts.append(f"- {d['title']} → {d.get('chosen', '')[:80]}")

    if action_stats:
        parts.append(f"\n【行动项】P0待办{action_stats['p0_open']}项，P1待办{action_stats['p1_open']}项。")

    if briefs:
        parts.append("\n【日报摘要】")
        for b in briefs:
            # 提取日报中的 AI 摘要行
            for line in b["content"].split("\n"):
                if "AI 摘要" in line or "快览" in line:
                    continue
            # 取前200字符作为上下文
            body = b["content"]
            if "---" in body:
                body = body.split("---", 2)[-1] if body.count("---") >= 2 else body
            snippet = " ".join([l for l in body.split("\n") if l.strip() and not l.startswith("#") and not l.startswith(">")][:3])
            if snippet:
                parts.append(f"- {b['date']}: {snippet[:150]}")

    if len(parts) <= 2:
        return "本周暂无足够数据生成AI摘要。"

    return call_llm("\n".join(parts),
                    system="你是中集环科企管部副总经理的工作助理。生成简洁周报摘要，不超过300字。",
                    max_tokens=500)


# ── 周报组装 ──────────────────────────────────────────────────────

def generate_week_report(date_str: str = None, use_ai: bool = True) -> str:
    if date_str is None:
        today = datetime.now()
    else:
        today = datetime.strptime(date_str, "%Y-%m-%d")

    monday, sunday, week_num = get_week_boundaries(today)
    week_label = f"W{week_num}"
    now = datetime.now()

    # 收集数据
    briefs = get_daily_briefs_in_week(monday, sunday)
    email_stats = get_week_email_stats(monday, sunday)
    week_decisions = get_recent_decisions(24 * 7)
    stale_decisions = get_stale_decisions(14)
    action_stats = get_action_completion(monday, sunday)
    all_notes = scan_vault_frontmatter()
    action_notes = [n for n in all_notes if n["type"] == "重点行动计划"]

    # AI 摘要
    ai_summary = ""
    if use_ai:
        ai_summary = generate_weekly_summary(briefs, email_stats, week_decisions, action_stats)

    # ── 组装 Markdown ──
    lines = []
    lines.append("---")
    lines.append(f'title: "周报 {week_label}"')
    lines.append("type: 周报")
    lines.append(f"tags: [周报, {today.year}, {week_label}]")
    lines.append("status: 自动生成")
    lines.append("priority: P1")
    lines.append(f"date: {today.strftime('%Y-%m-%d')}")
    lines.append(f"week: {week_label}")
    lines.append(f"period: \"{monday.strftime('%Y-%m-%d')} ~ {sunday.strftime('%Y-%m-%d')}\"")
    lines.append("---")
    lines.append("")
    lines.append(f"# 周报 {week_label}")
    lines.append("")
    lines.append(f"> {monday.strftime('%Y-%m-%d')} ~ {sunday.strftime('%Y-%m-%d')} · 自动生成于 {now.strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # AI 摘要
    if ai_summary and not ai_summary.startswith("["):
        lines.append("## 周报摘要")
        lines.append("")
        lines.append(f"> {ai_summary}")
        lines.append("")

    # ── 1. 快览仪表板 ──
    lines.append("## 快览")
    lines.append("")
    lines.append("| 指标 | 数量 |")
    lines.append("|------|------|")
    lines.append(f"| 本周日报数 | {len(briefs)} |")
    lines.append(f"| 本周邮件 (P0/P1/总计) | {email_stats['p0']} / {email_stats['p1']} / {email_stats['total']} |")
    lines.append(f"| 本周决策 | {len(week_decisions)} |")
    lines.append(f"| P0 待办行动项 | **{action_stats['p0_open']}** |")
    lines.append(f"| P1 待办行动项 | {action_stats['p1_open']} |")
    lines.append(f"| 待关闭决策 (>14天) | {len(stale_decisions)} |")
    lines.append("")

    # ── 2. 邮件摘要 ──
    if email_stats["total"] > 0:
        lines.append("## 1. 本周邮件")
        lines.append("")
        if email_stats["top_senders"]:
            lines.append("**高频发件人**:")
            for sender, count in email_stats["top_senders"]:
                lines.append(f"- {sender}: {count}封")
        if email_stats.get("p0_p1_list"):
            lines.append("")
            lines.append("**P0/P1 关键邮件**:")
            for e in email_stats["p0_p1_list"][:8]:
                lines.append(f"- [{e.get('priority','')}] **{e.get('sender_name','?')}**: {e.get('subject','')} ({e.get('email_received','')[:10]})")
        lines.append("")

    # ── 3. 重点行动进展 ──
    lines.append("## 2. 重点行动进展")
    lines.append("")
    lines.append("| 行动计划 | 待办数 | 负责人 | 状态 |")
    lines.append("|----------|--------|--------|------|")
    for a in action_notes:
        owner = a.get("owner", "") or "-"
        status = a.get("status", "") or "-"
        n_tasks = len(a.get("open_tasks", []))
        lines.append(f"| [[{a['path']}|{a['title']}]] | {n_tasks} | {owner} | {status} |")
    lines.append("")

    # ── 4. 本周决策 ──
    if week_decisions:
        lines.append("## 3. 本周决策")
        lines.append("")
        for d in week_decisions[:10]:
            lines.append(f"- [#{d['id']}] **{d['title']}** ({d.get('domain','')})")
            if d.get("chosen"):
                lines.append(f"  决策: {d['chosen'][:120]}")
            if d.get("rationale"):
                lines.append(f"  理由: {d['rationale'][:120]}")
        lines.append("")

    # ── 5. 待办与阻塞 ──
    lines.append("## 4. 待办与阻塞")
    lines.append("")
    p0_items = [a for a in action_notes if a["priority"] == "P0" and a["open_tasks"]]
    if p0_items:
        lines.append("### P0 待办")
        for item in p0_items:
            for task in item["open_tasks"][:3]:
                lines.append(f"- [ ] {task[:80]} — [[{item['path']}]]")
    else:
        lines.append("无 P0 待办。")

    if stale_decisions:
        lines.append("")
        lines.append("### 长期未关闭决策")
        for d in stale_decisions[:5]:
            lines.append(f"- [#{d['id']}] **{d['title']}** ({d['domain']}) — {d['created_at'][:10]}")
    lines.append("")

    # ── 6. 下周展望 ──
    lines.append("## 5. 下周展望")
    lines.append("")
    _, _, next_week = get_week_boundaries(today + timedelta(days=7))
    lines.append(f"下周 W{next_week} 重点关注：")
    lines.append("")
    # 从行动计划中提取含截止日期的任务
    for a in action_notes:
        for d in a.get("deadlines", [])[:2]:
            lines.append(f"- {d[:100]} — [[{a['path']}]]")
    lines.append("")

    # ── 附加：日报索引 ──
    if briefs:
        lines.append("## 附：本周日报索引")
        lines.append("")
        for b in briefs:
            weekday = ["一","二","三","四","五","六","日"][datetime.strptime(b['date'], "%Y-%m-%d").weekday()]
            lines.append(f"- [[日简报/每日工作简报_{b['date']}|{b['date']} 周{weekday}]]")

    return "\n".join(lines)


def write_report(content: str, week_num: int):
    filename = f"周报_W{week_num}.md"
    filepath = os.path.join(OUTPUT_DIR_WEEKLY, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath


def main():
    import io
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="JARVIS 周报生成器")
    parser.add_argument("--date", help="参考日期 (YYYY-MM-DD)")
    parser.add_argument("--week", type=int, help="指定周数")
    parser.add_argument("--print", action="store_true", help="输出到stdout")
    parser.add_argument("--no-ai", action="store_true", help="跳过AI摘要")
    args = parser.parse_args()

    if args.week:
        import datetime as _dt
        today = datetime.now()
        jan1 = _dt.date(today.year, 1, 1)
        days_offset = (args.week - 1) * 7 - jan1.weekday()
        target = (jan1 + timedelta(days=days_offset + 3))  # mid-week
        date_str = target.strftime("%Y-%m-%d")
    else:
        date_str = args.date

    content = generate_week_report(date_str, use_ai=not args.no_ai)

    if args.print:
        print(content)
    else:
        _, _, week_num = get_week_boundaries(datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.now())
        filepath = write_report(content, week_num)
        sys.stderr.write(f"周报已生成: {filepath}\n")
        print(filepath)


if __name__ == "__main__":
    main()
