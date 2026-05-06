#!/usr/bin/env python3
"""
JARVIS Daily Brief Generator — 每日工作简报生成器
从摄入事件、决策日志、Git历史、Vault变更中汇聚信息，生成五段式Markdown日报。

用法:
  python3 daily_brief_gen.py                      # 生成今天日报
  python3 daily_brief_gen.py --date 2026-05-06     # 指定日期
  python3 daily_brief_gen.py --output <path>       # 指定输出路径
  python3 daily_brief_gen.py --print               # 输出到stdout而非文件
"""

import os
import sys
import json
import argparse
import subprocess
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VAULT_ROOT = os.path.dirname(SCRIPT_DIR)
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
_DB_DIR = os.environ.get(
    "JARVIS_DATA_DIR",
    os.path.expanduser("~/.jarvis/data")
)
DB_PATH = os.path.join(_DB_DIR, "jarvis.db")
EVENTS_FILE = os.path.join(DATA_DIR, "ingestion_events.jsonl")
EMAIL_EVENTS_FILE = os.path.join(DATA_DIR, "email_events.jsonl")

OUTPUT_DIR = os.path.join(VAULT_ROOT, "26年中集环科工作区", "日简报")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# ── 数据采集 ──────────────────────────────────────────────────────

def get_ingestion_events(hours: int = 24) -> list:
    """获取最近N小时的摄入事件"""
    if not os.path.exists(EVENTS_FILE):
        return []
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    events = []
    with open(EVENTS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                event = json.loads(line)
                if event["timestamp"] >= cutoff:
                    events.append(event)
    return events


def get_email_events(hours: int = 24) -> list:
    """获取最近N小时的邮件摄入事件"""
    if not os.path.exists(EMAIL_EVENTS_FILE):
        return []
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    events = []
    with open(EMAIL_EVENTS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    event = json.loads(line)
                    if event.get("timestamp", "") >= cutoff:
                        events.append(event)
                except json.JSONDecodeError:
                    continue
    return events


def get_recent_decisions(hours: int = 24) -> list:
    """获取最近N小时的决策"""
    if not os.path.exists(DB_PATH):
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
        rows = conn.execute(
            """SELECT id, domain, title, context, chosen, rationale, tags,
                      confidence, status, created_at
               FROM decisions
               WHERE created_at >= ?
               ORDER BY created_at DESC""",
            (cutoff,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def get_stale_decisions(days: int = 14) -> list:
    """获取超过N天未关闭的决策"""
    if not os.path.exists(DB_PATH):
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        rows = conn.execute(
            """SELECT id, domain, title, context, chosen, tags, confidence,
                      created_at, status
               FROM decisions
               WHERE status = 'open' AND created_at < ?
               ORDER BY created_at ASC""",
            (cutoff,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def get_kv_memories(category: str = "work") -> list:
    """获取指定类别的KV记忆"""
    if not os.path.exists(DB_PATH):
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT key, value, updated_at FROM memory_kv WHERE category = ? ORDER BY updated_at DESC",
            (category,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def get_git_changes(hours: int = 24) -> list:
    """获取 vault 的 git 变更记录"""
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


def get_recent_vault_notes(hours: int = 24) -> list:
    """扫描 vault 中最近修改的笔记（排除非工作区）"""
    cutoff = datetime.now() - timedelta(hours=hours)
    notes = []
    work_dir = os.path.join(VAULT_ROOT, "26年中集环科工作区")

    for root, dirs, files in os.walk(work_dir):
        # 跳过日简报和 . 开头的目录
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if not f.endswith(".md"):
                continue
            filepath = os.path.join(root, f)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                if mtime >= cutoff:
                    # 提取 frontmatter
                    title = f.replace(".md", "")
                    note_type = ""
                    status = ""
                    priority = ""
                    with open(filepath, "r", encoding="utf-8") as fh:
                        content = fh.read(2000)
                        if content.startswith("---"):
                            end = content.find("---", 3)
                            if end > 0:
                                fm = content[3:end]
                                for line in fm.split("\n"):
                                    parts = line.split(":", 1)
                                    if len(parts) == 2:
                                        key = parts[0].strip()
                                        val = parts[1].strip().strip('"').strip("'")
                                        if key == "title":
                                            title = val
                                        elif key == "type":
                                            note_type = val
                                        elif key == "status":
                                            status = val
                                        elif key == "priority":
                                            priority = val
                    rel_path = os.path.relpath(filepath, work_dir)
                    notes.append({
                        "path": rel_path,
                        "title": title,
                        "type": note_type,
                        "status": status,
                        "priority": priority,
                        "mtime": mtime.strftime("%Y-%m-%dT%H:%M:%S"),
                    })
            except (OSError, UnicodeDecodeError):
                pass

    notes.sort(key=lambda x: x["mtime"], reverse=True)
    return notes


def get_p0_action_items() -> list:
    """从重点行动计划中提取 P0 事项"""
    actions_dir = os.path.join(VAULT_ROOT, "26年中集环科工作区", "重点行动计划")
    if not os.path.isdir(actions_dir):
        return []

    items = []
    for root, dirs, files in os.walk(actions_dir):
        for f in files:
            if not f.endswith(".md"):
                continue
            filepath = os.path.join(root, f)
            try:
                with open(filepath, "r", encoding="utf-8") as fh:
                    content = fh.read()
                    has_p0 = False
                    title = f.replace(".md", "")
                    owner = ""

                    if content.startswith("---"):
                        end = content.find("---", 3)
                        if end > 0:
                            fm = content[3:end]
                            for line in fm.split("\n"):
                                parts = line.split(":", 1)
                                if len(parts) == 2:
                                    key = parts[0].strip()
                                    val = parts[1].strip().strip('"').strip("'")
                                    if key == "title":
                                        title = val
                                    elif key == "priority" and val == "P0":
                                        has_p0 = True
                                    elif key == "owner":
                                        owner = val

                    # 提取未完成的任务
                    tasks = []
                    for line in content.split("\n"):
                        stripped = line.strip()
                        if stripped.startswith("- [ ]"):
                            tasks.append(stripped[6:].strip())

                    items.append({
                        "file": f,
                        "title": title,
                        "owner": owner,
                        "priority": "P0" if has_p0 else "",
                        "open_tasks": tasks,
                    })
            except (OSError, UnicodeDecodeError):
                pass
    return items


# ── 日报组装 ──────────────────────────────────────────────────────

def generate_brief(date_str: str = None) -> str:
    """生成完整日报 Markdown"""
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

    # 快览数据
    total_p0_tasks = sum(len(a["open_tasks"]) for a in action_items if a["priority"] == "P0")
    total_p1_tasks = sum(len(a["open_tasks"]) for a in action_items if a["priority"] == "P1")
    meetings_today = [n for n in vault_notes if n["type"] == "会议纪要"]
    new_emails_p0 = [e for e in email_events if e.get("priority") == "P0"]
    new_emails_p1 = [e for e in email_events if e.get("priority") == "P1"]

    # 判断是否有实质性更新
    has_activity = bool(
        vault_notes or ingestion_events or email_events or
        recent_decisions or git_changes
    )

    # ── 组装 Markdown ──
    lines = []
    lines.append("---")
    lines.append(f'title: "每日工作简报 {date_str}"')
    lines.append("type: 日简报")
    lines.append(f"tags: [日简报, {today.year}, daily-brief]")
    lines.append("status: 自动生成")
    lines.append("priority: P1")
    lines.append(f"date: {date_str}")
    lines.append("aliases:")
    lines.append(f'  - "Daily Brief {date_str}"')
    lines.append("---")
    lines.append("")
    lines.append(f"# 每日工作简报 {date_str}")
    lines.append("")
    lines.append(f"> 自动生成于 {now.strftime('%Y-%m-%d %H:%M')} · 周{weekday_cn}")

    # ── 0. 快览仪表板 ──
    lines.append("")
    lines.append("## 快览")
    lines.append("")
    lines.append(f"| 指标 | 数量 |")
    lines.append(f"|------|------|")
    lines.append(f"| P0 待办行动项 | **{total_p0_tasks}** |")
    lines.append(f"| P1 待办行动项 | {total_p1_tasks} |")
    lines.append(f"| 今日会议记录 | {len(meetings_today)} |")
    lines.append(f"| 新摄入文件 | {len(ingestion_events)} |")
    lines.append(f"| 新邮件 (P0/P1/总计) | {len(new_emails_p0)} / {len(new_emails_p1)} / {len(email_events)} |")
    lines.append(f"| 待关闭决策 (>14天) | {len(stale_decisions)} |")
    if not has_activity:
        lines.append(f"| 状态 | 今日暂无活动更新 |")
    lines.append("")

    # ── 0b. 邮件摘要 ──
    if email_events:
        total_attachments_ingested = 0
        for e in email_events:
            if e.get("attachments"):
                total_attachments_ingested += sum(1 for a in e["attachments"] if a.get("ingested"))

        if total_attachments_ingested > 0:
            lines.append(f"> 今日从邮件自动摄入 **{total_attachments_ingested}** 个附件，已存入 `_inbox/邮件附件/`")

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

    # ── 1. 今日关键活动 ──
    lines.append("")
    lines.append("## 1. 今日关键活动")
    lines.append("")
    if vault_notes:
        # 按类型分组
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

    # ── 2. 会议摘要 ──
    lines.append("## 2. 会议摘要")
    lines.append("")
    meetings = [n for n in vault_notes if n["type"] == "会议纪要"]
    if meetings:
        for m in meetings:
            lines.append(f"### {m['title']}")
            lines.append("")
            lines.append(f"- **状态**: {m['status']}")
            lines.append(f"- **时间**: {m.get('date', '未记录')}")
            # 尝试读取会议纪要的关键内容
            filepath = os.path.join(VAULT_ROOT, "26年中集环科工作区", m["path"])
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                    # 提取行动项
                    in_tasks = False
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

    # ── 3. 行动项追踪 ──
    lines.append("## 3. 行动项追踪")
    lines.append("")

    # 辅助：判断任务是否过期
    def is_overdue(task_text: str) -> bool:
        """检查任务截止日期是否已过"""
        import re
        # 匹配 【3月】【4月10日】【5月30日】 等格式
        month_map = {
            "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
            "7": 7, "8": 8, "9": 9, "10": 10, "11": 11, "12": 12,
        }
        match = re.findall(r'【(\d+)月(\d+)?日?】', task_text)
        for m in match:
            month = month_map.get(m[0], 0)
            day = int(m[1]) if m[1] else 1
            if month == 0:
                continue
            deadline = datetime(today.year, month, min(day, 28))
            if deadline < today.replace(hour=0, minute=0, second=0):
                return True
        # 也匹配单独的月份标记如【12月】
        match_month = re.findall(r'【(\d+)月】', task_text)
        for m in match_month:
            month = month_map.get(m, 0)
            if month and month < today.month:
                return True
        return False

    lines.append("| 行动项 | 来源 | 负责人 | 状态 | 优先级 |")
    lines.append("|--------|------|--------|------|--------|")

    # 从重点行动计划中提取开放任务
    open_task_count = 0
    overdue_count = 0
    for item in action_items[:8]:
        for task in item["open_tasks"][:2]:
            priority = item["priority"] or "P1"
            owner = item.get("owner", "") or "-"
            overdue = is_overdue(task)
            if overdue:
                status_text = "过期"
                overdue_count += 1
            else:
                status_text = "待办"
            lines.append(f"| {task[:50]} | [[{item['file']}]] | {owner} | {status_text} | {priority} |")
            open_task_count += 1

    if open_task_count == 0:
        lines.append("| 暂无待办行动项 | - | - | - | - |")

    if overdue_count > 0:
        lines.append("")
        lines.append(f"> 其中 **{overdue_count}** 项已过原定截止时间，请确认是否需要更新或关闭。")

    lines.append("")

    # ── 4. KPI与数据变更 ──
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
                    # 提取关键数字
                    for line in content.split("\n")[:50]:
                        if any(kw in line for kw in ["%", "亿", "万", "同比", "环比", "完成率"]):
                            lines.append(f"  - {line.strip()}")
                        if len(lines) > 20:
                            break
            except Exception:
                pass
    else:
        lines.append("今日无经营数据变更。")
    lines.append("")

    # ── 5. 市场与行业动态 ──
    lines.append("## 5. 市场与行业动态")
    lines.append("")
    market_notes = []
    for root, dirs, files in os.walk(
        os.path.join(VAULT_ROOT, "26年中集环科工作区", "市场情报")
    ):
        for f in files:
            if f.endswith(".md"):
                mtime = datetime.fromtimestamp(os.path.getmtime(os.path.join(root, f)))
                if mtime >= today.replace(hour=0, minute=0, second=0):
                    market_notes.append(f)

    industry_notes = []
    for root, dirs, files in os.walk(
        os.path.join(VAULT_ROOT, "26年中集环科工作区", "行业研究")
    ):
        for f in files:
            if f.endswith(".md"):
                mtime = datetime.fromtimestamp(os.path.getmtime(os.path.join(root, f)))
                if mtime >= today.replace(hour=0, minute=0, second=0):
                    industry_notes.append(f)

    if market_notes or industry_notes:
        for m in market_notes:
            lines.append(f"- 📈 市场情报更新: [[市场情报/{m}]]")
        for i in industry_notes:
            lines.append(f"- 📚 行业研究更新: [[行业研究/{i}]]")
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
    """写入日报文件"""
    filename = f"每日工作简报_{date_str}.md"
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath


def main():
    import io
    # Fix Windows GBK encoding for stdout
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="JARVIS 日报生成器")
    parser.add_argument("--date", help="日期 (YYYY-MM-DD), 默认今天")
    parser.add_argument("--output", help="输出路径")
    parser.add_argument("--print", action="store_true", help="输出到stdout而非文件")
    args = parser.parse_args()

    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    content = generate_brief(date_str)

    if args.print:
        print(content)
    else:
        filepath = write_brief(content, date_str)
        sys.stderr.write(f"日报已生成: {filepath}\n")
        print(filepath)


if __name__ == "__main__":
    main()
