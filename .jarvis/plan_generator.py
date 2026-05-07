#!/usr/bin/env python3
"""
JARVIS Plan Generator — 次日计划 + 当周计划生成器
从 Vault 中提取 P0/P1 事项、过期待决策、行动计划里程碑，生成结构化的计划和提醒。

用法:
  python3 plan_generator.py                     # 生成明日计划 + 本周计划
  python3 plan_generator.py --tomorrow           # 仅生成明日计划
  python3 plan_generator.py --week               # 仅生成本周计划
  python3 plan_generator.py --date 2026-05-07    # 指定日期
  python3 plan_generator.py --print              # 输出到stdout
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VAULT_ROOT = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(SCRIPT_DIR, "data")

sys.path.insert(0, SCRIPT_DIR)
from jarvis_common import (
    scan_vault_frontmatter, get_stale_decisions, get_recent_decisions,
    get_week_boundaries, OUTPUT_DIR_DAILY, OUTPUT_DIR_WEEKLY,
)

os.makedirs(OUTPUT_DIR_DAILY, exist_ok=True)
os.makedirs(OUTPUT_DIR_WEEKLY, exist_ok=True)
WORK_AREA = os.path.join(VAULT_ROOT, "26年中集环科工作区")


# ── 明日计划 ──────────────────────────────────────────────────────

def generate_tomorrow_plan(date_str: str = None) -> str:
    if date_str is None:
        tomorrow = datetime.now() + timedelta(days=1)
    else:
        tomorrow = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)

    date_str_tomorrow = tomorrow.strftime("%Y-%m-%d")
    weekday_cn = ["一", "二", "三", "四", "五", "六", "日"][tomorrow.weekday()]
    notes = scan_vault_frontmatter()

    p0_items = [n for n in notes if n["priority"] == "P0" and n["open_tasks"]]
    p1_items = [n for n in notes if n["priority"] == "P1" and n["open_tasks"]]
    in_progress = [n for n in notes if n["status"] in ("执行中", "生效中") and n.get("open_tasks")]
    stale = get_stale_decisions(14)

    lines = []
    lines.append("---")
    lines.append(f'title: "明日计划 {date_str_tomorrow}"')
    lines.append("type: 日计划")
    lines.append(f"tags: [日计划, {tomorrow.year}, daily-plan]")
    lines.append("status: 自动生成")
    lines.append("priority: P1")
    lines.append(f"date: {date_str_tomorrow}")
    lines.append("---")
    lines.append("")
    lines.append(f"# 明日计划 {date_str_tomorrow}")
    lines.append("")
    lines.append(f"> 周{weekday_cn} · 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    lines.append("## P0 — 必须完成")
    lines.append("")
    p0_count = 0
    for item in p0_items[:5]:
        for task in item["open_tasks"][:2]:
            owner = f"（{item['owner']}）" if item.get("owner") else ""
            lines.append(f"- [ ] **{task[:60]}** — [[{item['path']}]]{owner}")
            p0_count += 1
    if p0_count == 0:
        lines.append("暂无 P0 待办。")
    lines.append("")

    lines.append("## P1 — 应该完成")
    lines.append("")
    p1_count = 0
    for item in p1_items[:5]:
        for task in item["open_tasks"][:2]:
            owner = f"（{item['owner']}）" if item.get("owner") else ""
            lines.append(f"- [ ] {task[:60]} — [[{item['path']}]]{owner}")
            p1_count += 1
    if p1_count == 0:
        lines.append("暂无 P1 待办。")
    lines.append("")

    if in_progress:
        lines.append("## 进行中")
        lines.append("")
        for item in in_progress[:5]:
            lines.append(f"- **{item['title']}** `{item['status']}` — [[{item['path']}]]")
            for task in item["open_tasks"][:2]:
                lines.append(f"  - [ ] {task[:60]}")
        lines.append("")

    lines.append("## 提醒")
    lines.append("")
    if stale:
        lines.append("### 待关闭决策（>14天）")
        for d in stale[:3]:
            lines.append(f"- [#{d['id']}] **{d['title']}** ({d['domain']}) — {d['created_at'][:10]}")
        lines.append("")

    _, _, week_num = get_week_boundaries()
    lines.append(f"### 本周 W{week_num} 优先级校准")
    lines.append("")
    action_notes = [n for n in notes if n["type"] == "重点行动计划"]
    for a in action_notes:
        for task in a.get("deadlines", [])[:3]:
            lines.append(f"- {task[:80]} — [[{a['path']}]]")
    lines.append("")

    return "\n".join(lines)


# ── 本周计划 ──────────────────────────────────────────────────────

def generate_week_plan(date_str: str = None) -> str:
    if date_str is None:
        today = datetime.now()
    else:
        today = datetime.strptime(date_str, "%Y-%m-%d")

    monday, sunday, week_num = get_week_boundaries(today)
    week_label = f"W{week_num}"

    notes = scan_vault_frontmatter()
    stale = get_stale_decisions(14)
    recent_decisions = get_recent_decisions(168)

    action_notes = [n for n in notes if n["type"] == "重点行动计划"]
    strategy_notes = [n for n in notes if n["type"] == "战略框架"]

    lines = []
    lines.append("---")
    lines.append(f'title: "本周计划 {week_label}"')
    lines.append("type: 周计划")
    lines.append(f"tags: [周计划, {today.year}, {week_label}]")
    lines.append("status: 自动生成")
    lines.append("priority: P1")
    lines.append(f"date: {today.strftime('%Y-%m-%d')}")
    lines.append(f"week: {week_label}")
    lines.append(f"period: \"{monday.strftime('%Y-%m-%d')} ~ {sunday.strftime('%Y-%m-%d')}\"")
    lines.append("---")
    lines.append("")
    lines.append(f"# 本周计划 {week_label}")
    lines.append("")
    lines.append(f"> {monday.strftime('%Y-%m-%d')} ~ {sunday.strftime('%Y-%m-%d')} · 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # 周决策摘要
    if recent_decisions:
        lines.append("## 本周决策")
        lines.append("")
        for d in recent_decisions[:5]:
            lines.append(f"- [#{d['id']}] **{d['title']}** ({d['domain']}) — {d.get('chosen', '')[:60]}")
        lines.append("")

    # 本周重点行动
    lines.append("## 1. 本周关键行动")
    lines.append("")
    lines.append("| 行动计划 | P0待办 | 负责人 | 状态 |")
    lines.append("|----------|--------|--------|------|")
    for a in action_notes:
        owner = a.get("owner", "") or "-"
        status = a.get("status", "") or "-"
        lines.append(f"| [[{a['path']}|{a['title']}]] | {len(a.get('open_tasks', []))} | {owner} | {status} |")
    lines.append("")

    # 待办汇总
    lines.append("## 2. 本周待办汇总")
    lines.append("")
    lines.append("| 优先级 | 行动项 | 来源 | 负责人 |")
    lines.append("|--------|--------|------|--------|")
    all_tasks = []
    for a in action_notes:
        for task in a.get("open_tasks", []):
            all_tasks.append({
                "priority": a.get("priority", "P2"),
                "task": task,
                "source": a["path"],
                "owner": a.get("owner", "-"),
            })
    all_tasks.sort(key=lambda x: (0 if x["priority"] == "P0" else 1 if x["priority"] == "P1" else 2))
    for t in all_tasks[:15]:
        lines.append(f"| {t['priority']} | {t['task'][:60]} | [[{t['source']}]] | {t['owner']} |")
    if not all_tasks:
        lines.append("| - | 暂无待办 | - | - |")
    lines.append("")

    # 里程碑
    lines.append("## 3. 里程碑与截止日")
    lines.append("")
    deadlines = []
    for a in action_notes:
        for d in a.get("deadlines", []):
            deadlines.append({"deadline": d, "source": a["path"], "title": a["title"]})
    if deadlines:
        for d in deadlines[:10]:
            lines.append(f"- {d['deadline'][:100]} — [[{d['source']}|{d['title']}]]")
    else:
        lines.append("本周无明确的截止日记录。")
    lines.append("")

    # 战略同步
    lines.append("## 4. 战略举措同步")
    lines.append("")
    for s in strategy_notes[:6]:
        lines.append(f"- **[[{s['path']}|{s['title']}]]** `{s.get('status', '')}` `{s.get('priority', '')}`")
    if not strategy_notes:
        lines.append("暂无战略框架更新。")
    lines.append("")

    # 提醒
    if stale:
        lines.append("## 5. 提醒")
        lines.append("")
        lines.append("### 待关闭决策")
        for d in stale[:5]:
            lines.append(f"- [#{d['id']}] **{d['title']}** ({d['domain']}) — 创建于 {d['created_at'][:10]}")
        lines.append("")

    return "\n".join(lines)


def write_plan(content: str, plan_type: str, date_str: str = None):
    if date_str is None:
        now = datetime.now()
    else:
        now = datetime.strptime(date_str, "%Y-%m-%d")

    if plan_type == "tomorrow":
        tomorrow = now + timedelta(days=1)
        filename = f"明日计划_{tomorrow.strftime('%Y-%m-%d')}.md"
        filepath = os.path.join(OUTPUT_DIR_DAILY, filename)
    elif plan_type == "week":
        _, _, week_num = get_week_boundaries(now)
        filename = f"本周计划_W{week_num}.md"
        filepath = os.path.join(OUTPUT_DIR_WEEKLY, filename)
    else:
        raise ValueError(f"未知计划类型: {plan_type}")

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

    parser = argparse.ArgumentParser(description="JARVIS 计划生成器")
    parser.add_argument("--tomorrow", action="store_true", help="仅生成明日计划")
    parser.add_argument("--week", action="store_true", help="仅生成本周计划")
    parser.add_argument("--date", help="参考日期 (YYYY-MM-DD)")
    parser.add_argument("--print", action="store_true", help="输出到stdout")
    args = parser.parse_args()

    date_str = args.date
    results = []

    if not args.tomorrow and not args.week:
        args.tomorrow = True
        args.week = True

    if args.tomorrow:
        content = generate_tomorrow_plan(date_str)
        if args.print:
            print(content)
        else:
            filepath = write_plan(content, "tomorrow", date_str)
            results.append(("明日计划", filepath))

    if args.week:
        content = generate_week_plan(date_str)
        if args.print:
            print(content)
        else:
            filepath = write_plan(content, "week", date_str)
            results.append(("本周计划", filepath))

    for name, path in results:
        sys.stderr.write(f"{name}已生成: {path}\n")
        print(path)


if __name__ == "__main__":
    main()
