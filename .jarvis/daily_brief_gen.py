#!/usr/bin/env python3
"""
JARVIS Daily Brief Generator — 每日工作简报生成器
从摄入事件、决策日志、Git历史、Vault变更中汇聚信息，生成五段式Markdown日报。
含 AI 摘要 + 健康检查状态。

用法:
  python3 daily_brief_gen.py                      # 生成今天日报
  python3 daily_brief_gen.py --date 2026-05-06     # 指定日期
  python3 daily_brief_gen.py --print               # 输出到stdout而非文件
  python3 daily_brief_gen.py --no-ai               # 跳过AI摘要（快速模式）
"""

import os
import sys
import json
import argparse
import subprocess
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VAULT_ROOT = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(SCRIPT_DIR, "data")

sys.path.insert(0, SCRIPT_DIR)
from jarvis_common import (
    load_config, get_ingestion_events, get_email_events,
    get_email_full_bodies, get_recent_decisions, get_stale_decisions,
    get_kv_memories, get_recent_vault_notes, get_p0_action_items,
    call_llm, archive_jsonl, OUTPUT_DIR_DAILY,
)

os.makedirs(OUTPUT_DIR_DAILY, exist_ok=True)


# ── 健康检查 ──────────────────────────────────────────────────────

def health_check() -> dict:
    """检查各子系统状态，返回状态字典"""
    status = {
        "outlook": "unknown",
        "siliconflow_api": "unknown",
        "deepseek_api": "unknown",
        "index": "unknown",
        "db": "unknown",
        "disk_free_gb": 0,
    }
    # 磁盘空间
    try:
        import shutil
        free = shutil.disk_usage(VAULT_ROOT).free
        status["disk_free_gb"] = round(free / (1024**3), 1)
    except Exception:
        pass

    # 索引完整性
    emb_path = os.path.join(DATA_DIR, "embeddings.npy")
    meta_path = os.path.join(DATA_DIR, "metadata.json")
    info_path = os.path.join(DATA_DIR, "index_info.json")
    if all(os.path.exists(p) for p in [emb_path, meta_path, info_path]):
        try:
            with open(info_path, "r") as f:
                info = json.load(f)
            age_hours = (datetime.now() - datetime.fromisoformat(info.get("indexed_at", "2000-01-01T00:00:00"))).total_seconds() / 3600
            status["index"] = f"OK ({info.get('total_chunks', 0)} chunks, {age_hours:.0f}h ago)"
        except Exception:
            status["index"] = "corrupt"
    else:
        status["index"] = "missing"

    # DB
    from jarvis_common import DB_PATH
    if os.path.exists(DB_PATH):
        status["db"] = f"OK ({os.path.getsize(DB_PATH)//1024}KB)"
    else:
        status["db"] = "missing"

    # API
    cfg = load_config()
    try:
        import requests
        r = requests.post(
            f"{cfg['api_base']}/embeddings",
            headers={"Authorization": f"Bearer {cfg['api_key']}"},
            json={"model": cfg["embedding_model"], "input": "ping"},
            timeout=10,
        )
        status["siliconflow_api"] = "OK" if r.status_code == 200 else f"HTTP {r.status_code}"
    except Exception as e:
        status["siliconflow_api"] = f"down ({str(e)[:50]})"

    # DeepSeek
    try:
        result = call_llm("ping", system="回复OK", max_tokens=10)
        status["deepseek_api"] = "OK" if "error" not in result.lower() and result else "unexpected"
    except Exception as e:
        status["deepseek_api"] = f"down ({str(e)[:50]})"

    return status


# ── AI 摘要 ────────────────────────────────────────────────────────

def generate_ai_summary(date_str: str, ingestion_events: list,
                        email_events: list, vault_notes: list,
                        decisions: list) -> str:
    """调用 LLM 生成当日工作智能摘要"""
    # 收集素材
    parts = [f"今天是{date_str}。请根据以下信息生成一份简洁的工作日报摘要（200字以内），用中文。"]
    parts.append("请突出：最重要的1-2件事、需要关注的风险/阻塞、明天的优先级建议。")

    if email_events:
        p0_emails = [e for e in email_events if e.get("priority") == "P0"]
        p1_emails = [e for e in email_events if e.get("priority") == "P1"]
        parts.append(f"\n【邮件】共{len(email_events)}封新邮件，其中P0紧急{len(p0_emails)}封，P1重要{len(p1_emails)}封。")
        for e in p0_emails[:3]:
            parts.append(f"- P0: {e.get('sender_name', '?')} — {e.get('subject', '')}")
        for e in p1_emails[:3]:
            parts.append(f"- P1: {e.get('sender_name', '?')} — {e.get('subject', '')}")

    if ingestion_events:
        parts.append(f"\n【文件摄入】共{len(ingestion_events)}个新文件。")
        for e in ingestion_events[:5]:
            parts.append(f"- [{e.get('file_type', '')}] {e.get('file_name', '')}: {e.get('summary', '')[:80]}")

    if vault_notes:
        parts.append(f"\n【笔记变更】共{len(vault_notes)}个笔记更新。")
        for n in vault_notes[:5]:
            parts.append(f"- {n['title']} ({n.get('type', '')}) [{n.get('status', '')}]")

    if decisions:
        parts.append(f"\n【决策】今日{len(decisions)}条新决策。")
        for d in decisions[:3]:
            parts.append(f"- {d['title']} ({d.get('domain', '')})")

    if len(parts) <= 2:
        return "今日暂无足够活动数据供AI摘要。"

    prompt = "\n".join(parts)
    return call_llm(prompt, system="你是中集环科企管部副总经理的工作助理。用简洁中文输出日报摘要，不超过200字。", max_tokens=300)


# ── Git 变更 ──────────────────────────────────────────────────────

def get_git_changes(hours: int = 24) -> list:
    try:
        result = subprocess.run(
            ["git", "log", f"--since={hours}.hours.ago",
             "--pretty=format:%h|%ai|%s", "--name-only"],
            capture_output=True, text=True,
            cwd=VAULT_ROOT, timeout=15,
        )
        if result.returncode != 0:
            return []
        changes = []
        lines = result.stdout.strip().split("\n")
        current_commit = None
        for line in lines:
            if "|" in line and len(line.split("|")[0]) < 10:
                parts = line.split("|", 2)
                current_commit = {
                    "hash": parts[0].strip(),
                    "time": parts[1].strip()[:19] if len(parts) > 1 else "",
                    "message": parts[2].strip() if len(parts) > 2 else "",
                    "files": [],
                }
                changes.append(current_commit)
            elif line.strip() and current_commit is not None:
                current_commit["files"].append(line.strip())
        return changes
    except Exception:
        return []


# ── 日报组装 ──────────────────────────────────────────────────────

def generate_brief(date_str: str = None, use_ai: bool = True) -> str:
    now = datetime.now()
    if date_str is None:
        today = now
        date_str = today.strftime("%Y-%m-%d")
    else:
        today = datetime.strptime(date_str, "%Y-%m-%d")

    weekday_cn = ["一", "二", "三", "四", "五", "六", "日"][today.weekday()]

    # 收集数据
    ingestion_events = get_ingestion_events(24)
    email_events = get_email_events(24)
    recent_decisions = get_recent_decisions(24)
    stale_decisions = get_stale_decisions(14)
    git_changes = get_git_changes(24)
    vault_notes = get_recent_vault_notes(24)
    action_items = get_p0_action_items()
    work_memories = get_kv_memories("work")

    # 健康检查
    health = health_check()
    health_ok = all(
        v in ("OK", "unknown") or (isinstance(v, str) and v.startswith("OK"))
        for v in health.values() if v not in (0, 0.0, "unknown")
    )

    # AI 摘要
    ai_summary = ""
    if use_ai and (vault_notes or email_events or ingestion_events or recent_decisions):
        ai_summary = generate_ai_summary(date_str, ingestion_events, email_events,
                                          vault_notes, recent_decisions)

    # 快览数据
    total_p0_tasks = sum(len(a["open_tasks"]) for a in action_items if a["priority"] == "P0")
    total_p1_tasks = sum(len(a["open_tasks"]) for a in action_items if a["priority"] == "P1")
    meetings_today = [n for n in vault_notes if n["type"] == "会议纪要"]
    new_emails_p0 = [e for e in email_events if e.get("priority") == "P0"]
    new_emails_p1 = [e for e in email_events if e.get("priority") == "P1"]
    has_activity = bool(vault_notes or ingestion_events or email_events or recent_decisions or git_changes)

    # ── 组装 Markdown ──
    lines = []
    lines.append("---")
    lines.append(f'title: "每日工作简报 {date_str}"')
    lines.append("type: 日简报")
    lines.append(f"tags: [日简报, {today.year}, daily-brief]")
    lines.append("status: 自动生成")
    lines.append("priority: P1")
    lines.append(f"date: {date_str}")
    lines.append("---")
    lines.append("")
    lines.append(f"# 每日工作简报 {date_str}")
    lines.append("")
    lines.append(f"> 自动生成于 {now.strftime('%Y-%m-%d %H:%M')} · 周{weekday_cn}")

    # ── 0. 健康状态 ──
    health_icon = "✓" if health_ok else "⚠"
    lines.append(f"> 系统状态: {health_icon} "
                 f"API(SiliconFlow:{health['siliconflow_api']}, DeepSeek:{health['deepseek_api']}) "
                 f"| 索引:{health['index']} | DB:{health['db']} "
                 f"| 磁盘空闲:{health['disk_free_gb']}GB")
    lines.append("")

    # ── 0b. AI 摘要 ──
    if ai_summary and not ai_summary.startswith("["):
        lines.append("## 🤖 AI 摘要")
        lines.append("")
        lines.append(f"> {ai_summary}")
        lines.append("")

    # ── 1. 快览仪表板 ──
    lines.append("## 快览")
    lines.append("")
    lines.append("| 指标 | 数量 |")
    lines.append("|------|------|")
    lines.append(f"| P0 待办行动项 | **{total_p0_tasks}** |")
    lines.append(f"| P1 待办行动项 | {total_p1_tasks} |")
    lines.append(f"| 今日会议记录 | {len(meetings_today)} |")
    lines.append(f"| 新摄入文件 | {len(ingestion_events)} |")
    lines.append(f"| 新邮件 (P0/P1/总计) | {len(new_emails_p0)} / {len(new_emails_p1)} / {len(email_events)} |")
    lines.append(f"| 待关闭决策 (>14天) | {len(stale_decisions)} |")
    lines.append(f"| 系统健康 | {'正常' if health_ok else '异常'} |")
    if not has_activity:
        lines.append("| 状态 | 今日暂无活动更新 |")
    lines.append("")

    # ── 2. 邮件摘要 ──
    if email_events:
        total_attachments = 0
        for e in email_events:
            if e.get("attachments"):
                total_attachments += sum(1 for a in e["attachments"] if a.get("ingested"))
        if total_attachments > 0:
            lines.append(f"> 今日从邮件自动摄入 **{total_attachments}** 个附件，已存入 `_inbox/邮件附件/`")
        if new_emails_p0:
            lines.append("")
            lines.append("### 紧急邮件")
            for e in new_emails_p0:
                att = e.get("attachments", [])
                att_str = ""
                if att:
                    ingested = [a for a in att if a.get("ingested")]
                    if ingested:
                        att_str = f" [附件: {', '.join(a['file_name'] for a in ingested)}]"
                    else:
                        att_str = " [含附件]"
                lines.append(f"- [P0] **{e.get('sender_name', '?')}**: {e.get('subject', '')}{att_str}")
            lines.append("")
        if new_emails_p1:
            lines.append("### 重要邮件")
            for e in new_emails_p1[:5]:
                lines.append(f"- [P1] **{e.get('sender_name', '?')}**: {e.get('subject', '')}")
            lines.append("")

    # ── 3. 今日关键活动 ──
    lines.append("")
    lines.append("## 1. 今日关键活动")
    lines.append("")
    if vault_notes:
        meetings = [n for n in vault_notes if n["type"] == "会议纪要"]
        action_updates = [n for n in vault_notes if n["type"] == "重点行动计划"]
        data_updates = [n for n in vault_notes if n["type"] == "经营数据"]
        others = [n for n in vault_notes if n["type"] not in ("会议纪要", "重点行动计划", "经营数据")]
        if meetings:
            lines.append("### 会议")
            for m in meetings[:5]:
                lines.append(f"- **{m['title']}** `{m['status']}` — [[{m['path']}]]")
            lines.append("")
        if action_updates:
            lines.append("### 行动计划更新")
            for a in action_updates[:5]:
                lines.append(f"- **{a['title']}** `{a['priority']}` — [[{a['path']}]]")
            lines.append("")
        if data_updates:
            lines.append("### 数据更新")
            for d in data_updates[:3]:
                lines.append(f"- **{d['title']}** — [[{d['path']}]]")
            lines.append("")
        if others:
            lines.append("### 其他更新")
            for o in others[:5]:
                lines.append(f"- **{o['title']}** `{o['type']}` — [[{o['path']}]]")
            lines.append("")
    else:
        lines.append("今日无 vault 变更记录。")
        lines.append("")

    # ── 4. 会议摘要 ──
    lines.append("## 2. 会议摘要")
    lines.append("")
    meetings = [n for n in vault_notes if n["type"] == "会议纪要"]
    if meetings:
        for m in meetings:
            lines.append(f"### {m['title']}")
            lines.append("")
            lines.append(f"- **状态**: {m['status']}")
            filepath = os.path.join(VAULT_ROOT, "26年中集环科工作区", m["path"])
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                    tasks = []
                    for line in content.split("\n"):
                        if line.strip().startswith("- [ ]") or line.strip().startswith("- [x]"):
                            tasks.append(line.strip())
                    if tasks:
                        lines.append("")
                        lines.append("**行动项**:")
                        for t in tasks:
                            lines.append(f"- {t}")
            except Exception:
                pass
            lines.append("")
    else:
        lines.append("今日无会议记录。")
        lines.append("")

    # ── 5. 行动项追踪 ──
    lines.append("## 3. 行动项追踪")
    lines.append("")

    def is_overdue(task_text: str) -> bool:
        import re
        month_map = {"1":1,"2":2,"3":3,"4":4,"5":5,"6":6,"7":7,"8":8,"9":9,"10":10,"11":11,"12":12}
        match = re.findall(r'【(\d+)月(\d+)?日?】', task_text)
        for m in match:
            month = month_map.get(m[0], 0)
            day = int(m[1]) if m[1] else 1
            if month == 0: continue
            deadline = datetime(today.year, month, min(day, 28))
            if deadline < today.replace(hour=0, minute=0, second=0):
                return True
        match_month = re.findall(r'【(\d+)月】', task_text)
        for m in match_month:
            month = month_map.get(m, 0)
            if month and month < today.month:
                return True
        return False

    lines.append("| 行动项 | 来源 | 负责人 | 状态 | 优先级 |")
    lines.append("|--------|------|--------|------|--------|")
    open_task_count = 0
    overdue_count = 0
    for item in action_items[:8]:
        for task in item["open_tasks"][:2]:
            priority = item["priority"] or "P1"
            owner = item.get("owner", "") or "-"
            overdue = is_overdue(task)
            status_text = "过期" if overdue else "待办"
            if overdue: overdue_count += 1
            lines.append(f"| {task[:50]} | [[{item['file']}]] | {owner} | {status_text} | {priority} |")
            open_task_count += 1
    if open_task_count == 0:
        lines.append("| 暂无待办行动项 | - | - | - | - |")
    if overdue_count > 0:
        lines.append("")
        lines.append(f"> 其中 **{overdue_count}** 项已过原定截止时间。")
    lines.append("")

    # ── 6. KPI与数据变更 ──
    lines.append("## 4. KPI与数据变更")
    lines.append("")
    data_notes = [n for n in vault_notes if n["type"] == "经营数据"]
    if data_notes:
        for d in data_notes:
            lines.append(f"- **[[{d['path']}|{d['title']}]]** — 状态: {d['status']}")
            filepath = os.path.join(VAULT_ROOT, "26年中集环科工作区", d["path"])
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                    for line in content.split("\n")[:50]:
                        if any(kw in line for kw in ["%", "亿", "万", "同比", "环比", "完成率"]):
                            lines.append(f"  - {line.strip()}")
                        if len(lines) > 20: break
            except Exception:
                pass
    else:
        lines.append("今日无经营数据变更。")
    lines.append("")

    # ── 7. 市场与行业动态 ──
    lines.append("## 5. 市场与行业动态")
    lines.append("")
    market_notes = []
    market_dir = os.path.join(VAULT_ROOT, "26年中集环科工作区", "市场情报")
    if os.path.isdir(market_dir):
        for root, dirs, files in os.walk(market_dir):
            for f in files:
                if f.endswith(".md"):
                    mtime = datetime.fromtimestamp(os.path.getmtime(os.path.join(root, f)))
                    if mtime >= today.replace(hour=0, minute=0, second=0):
                        market_notes.append(f)
    industry_notes = []
    industry_dir = os.path.join(VAULT_ROOT, "26年中集环科工作区", "行业研究")
    if os.path.isdir(industry_dir):
        for root, dirs, files in os.walk(industry_dir):
            for f in files:
                if f.endswith(".md"):
                    mtime = datetime.fromtimestamp(os.path.getmtime(os.path.join(root, f)))
                    if mtime >= today.replace(hour=0, minute=0, second=0):
                        industry_notes.append(f)
    if market_notes or industry_notes:
        for m in market_notes:
            lines.append(f"- 市场情报更新: [[市场情报/{m}]]")
        for i in industry_notes:
            lines.append(f"- 行业研究更新: [[行业研究/{i}]]")
    else:
        lines.append("今日无市场/行业动态更新。")
    lines.append("")

    # ── 附加：摄入文件 ──
    if ingestion_events:
        lines.append("---")
        lines.append("")
        lines.append("## [摄入] 今日摄入文件")
        lines.append("")
        for e in ingestion_events:
            lines.append(f"- **[{e['file_type']}]** {e['file_name']} — {e['summary'][:100]}")
            if e.get("key_topics"):
                lines.append(f"  标签: {', '.join(e['key_topics'])}")
        lines.append("")

    # ── 附加：过期待决策提醒 ──
    if stale_decisions:
        lines.append("---")
        lines.append("")
        lines.append("## [提醒] 待关闭决策（>14天）")
        lines.append("")
        for d in stale_decisions[:5]:
            lines.append(f"- [#{d['id']}] **{d['title']}** ({d['domain']}) — 创建于 {d['created_at'][:10]}")
            if d.get("context"):
                lines.append(f"  背景: {d['context'][:80]}")
        lines.append("")

    return "\n".join(lines)


def write_brief(content: str, date_str: str):
    filename = f"每日工作简报_{date_str}.md"
    filepath = os.path.join(OUTPUT_DIR_DAILY, filename)
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

    parser = argparse.ArgumentParser(description="JARVIS 日报生成器")
    parser.add_argument("--date", help="日期 (YYYY-MM-DD), 默认今天")
    parser.add_argument("--print", action="store_true", help="输出到stdout而非文件")
    parser.add_argument("--no-ai", action="store_true", help="跳过AI摘要")
    args = parser.parse_args()

    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    content = generate_brief(date_str, use_ai=not args.no_ai)

    if args.print:
        print(content)
    else:
        filepath = write_brief(content, date_str)
        sys.stderr.write(f"日报已生成: {filepath}\n")
        print(filepath)

    # 归档旧事件
    from jarvis_common import EVENTS_FILE, EMAIL_EVENTS_FILE
    for fp in [EVENTS_FILE, EMAIL_EVENTS_FILE]:
        n = archive_jsonl(fp, max_days=30)
        if n:
            sys.stderr.write(f"归档 {os.path.basename(fp)}: {n} 条\n")


if __name__ == "__main__":
    main()
