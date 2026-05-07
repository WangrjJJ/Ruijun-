#!/usr/bin/env python3
"""
JARVIS Common — 公共模块
DB连接、配置加载、frontmatter扫描、决策查询等共享函数。
"""

import os
import sys
import json
import sqlite3
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VAULT_ROOT = os.path.dirname(SCRIPT_DIR)
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
_DB_DIR = os.environ.get("JARVIS_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".jarvis", "data")
DB_PATH = os.path.join(_DB_DIR, "jarvis.db")
EVENTS_FILE = os.path.join(DATA_DIR, "ingestion_events.jsonl")
EMAIL_EVENTS_FILE = os.path.join(DATA_DIR, "email_events.jsonl")
WORK_AREA = os.path.join(VAULT_ROOT, "26年中集环科工作区")

# 输出目录
OUTPUT_DIR_DAILY = os.path.join(WORK_AREA, "日简报")
OUTPUT_DIR_WEEKLY = os.path.join(WORK_AREA, "周计划")


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    # api_key 优先从环境变量读取
    cfg["api_key"] = os.environ.get("JARVIS_API_KEY") or os.environ.get("SILICONFLOW_API_KEY") or cfg.get("api_key", "")
    return cfg


def get_db() -> sqlite3.Connection:
    """获取决策日志数据库连接"""
    os.makedirs(_DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_ingestion_events(hours: int = 24) -> list:
    if not os.path.exists(EVENTS_FILE):
        return []
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    events = []
    with open(EVENTS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    event = json.loads(line)
                    if event["timestamp"] >= cutoff:
                        events.append(event)
                except json.JSONDecodeError:
                    continue
    return events


def get_email_events(hours: int = 24) -> list:
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


def get_email_full_bodies(email_events: list) -> list:
    """从邮件事件中提取完整正文（需 email_ingestion 保留 body 字段）"""
    bodies = []
    for e in email_events:
        if e.get("body"):
            bodies.append({
                "sender": e.get("sender_name", ""),
                "subject": e.get("subject", ""),
                "priority": e.get("priority", ""),
                "body": e["body"],
            })
    return bodies


def get_recent_decisions(hours: int = 24) -> list:
    if not os.path.exists(DB_PATH):
        return []
    try:
        conn = get_db()
        cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
        rows = conn.execute(
            """SELECT id, domain, title, context, chosen, rationale, tags,
                      confidence, status, created_at
               FROM decisions WHERE created_at >= ? ORDER BY created_at DESC""",
            (cutoff,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def get_stale_decisions(days: int = 14) -> list:
    if not os.path.exists(DB_PATH):
        return []
    try:
        conn = get_db()
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        rows = conn.execute(
            """SELECT id, domain, title, context, chosen, tags, confidence,
                      created_at, status
               FROM decisions WHERE status = 'open' AND created_at < ?
               ORDER BY created_at ASC""",
            (cutoff,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def get_kv_memories(category: str = "work") -> list:
    if not os.path.exists(DB_PATH):
        return []
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT key, value, updated_at FROM memory_kv WHERE category = ? ORDER BY updated_at DESC",
            (category,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def scan_vault_frontmatter(base_dir: str = None) -> list:
    """扫描工作区所有笔记的 frontmatter，返回结构化列表"""
    if base_dir is None:
        base_dir = WORK_AREA
    notes = []
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("日简报", "周计划")]
        for f in files:
            if not f.endswith(".md"):
                continue
            filepath = os.path.join(root, f)
            try:
                with open(filepath, "r", encoding="utf-8") as fh:
                    content = fh.read(5000)
                    note = {
                        "file": f,
                        "path": os.path.relpath(filepath, base_dir),
                        "title": f.replace(".md", ""),
                        "type": "", "status": "", "priority": "",
                        "owner": "", "policy_nr": "", "tags": [],
                        "open_tasks": [], "deadlines": [],
                    }
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
                                        note["title"] = val
                                    elif key == "type":
                                        note["type"] = val
                                    elif key == "status":
                                        note["status"] = val
                                    elif key == "priority":
                                        note["priority"] = val
                                    elif key == "owner":
                                        note["owner"] = val
                                    elif key == "policy_nr":
                                        note["policy_nr"] = val
                                    elif key == "tags":
                                        val = val.strip("[]").strip()
                                        note["tags"] = [t.strip().strip('"').strip("'") for t in val.split(",") if t.strip()]
                    body = content[end + 3:] if content.startswith("---") and "---" in content[3:] else content
                    for line in body.split("\n"):
                        stripped = line.strip()
                        if stripped.startswith("- [ ]"):
                            task = stripped[6:].strip()
                            note["open_tasks"].append(task)
                            for kw in ["【", "截止", "deadline", "DDL"]:
                                if kw in task:
                                    note["deadlines"].append(task)
                        elif any(kw in stripped for kw in ["截止", "deadline:", "DDL:", "时限"]):
                            note["deadlines"].append(stripped)
                    notes.append(note)
            except (OSError, UnicodeDecodeError):
                pass
    return notes


def get_recent_vault_notes(hours: int = 24) -> list:
    cutoff = datetime.now() - timedelta(hours=hours)
    notes = []
    for root, dirs, files in os.walk(WORK_AREA):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if not f.endswith(".md"):
                continue
            filepath = os.path.join(root, f)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                if mtime >= cutoff:
                    title = f.replace(".md", "")
                    note_type = status = priority = ""
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
                                        if key == "title": title = val
                                        elif key == "type": note_type = val
                                        elif key == "status": status = val
                                        elif key == "priority": priority = val
                    rel_path = os.path.relpath(filepath, WORK_AREA)
                    notes.append({
                        "path": rel_path, "title": title, "type": note_type,
                        "status": status, "priority": priority,
                        "mtime": mtime.strftime("%Y-%m-%dT%H:%M:%S"),
                    })
            except (OSError, UnicodeDecodeError):
                pass
    notes.sort(key=lambda x: x["mtime"], reverse=True)
    return notes


def get_p0_action_items() -> list:
    actions_dir = os.path.join(WORK_AREA, "重点行动计划")
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
                                    if key == "title": title = val
                                    elif key == "priority" and val == "P0": has_p0 = True
                                    elif key == "owner": owner = val
                    tasks = []
                    for line in content.split("\n"):
                        stripped = line.strip()
                        if stripped.startswith("- [ ]"):
                            tasks.append(stripped[6:].strip())
                    items.append({
                        "file": f, "title": title, "owner": owner,
                        "priority": "P0" if has_p0 else "",
                        "open_tasks": tasks,
                    })
            except (OSError, UnicodeDecodeError):
                pass
    return items


def get_week_boundaries(today: datetime = None) -> tuple:
    if today is None:
        today = datetime.now()
    weekday = today.weekday()
    monday = today - timedelta(days=weekday)
    sunday = monday + timedelta(days=6)
    week_num = monday.isocalendar()[1]
    return monday, sunday, week_num


def call_llm(prompt: str, system: str = "", max_tokens: int = 500) -> str:
    """调用 DeepSeek API 做文本摘要/分析"""
    api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("DEEPSEEK_API_KEY") or ""
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
    if not api_key:
        return "[LLM未配置API Key]"
    try:
        import requests
        r = requests.post(
            f"{base_url}/messages",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "deepseek-v4-flash"),
                "max_tokens": max_tokens,
                "system": system or "你是中集环科企管部副总经理的工作助理。用简洁中文回答。",
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"[LLM调用失败: {e}]"


def archive_jsonl(filepath: str, max_days: int = 30):
    """将超过 max_days 天的事件归档到 data/archive/YYYY-MM.jsonl"""
    if not os.path.exists(filepath):
        return
    archive_dir = os.path.join(os.path.dirname(filepath), "archive")
    os.makedirs(archive_dir, exist_ok=True)
    cutoff = (datetime.now() - timedelta(days=max_days)).strftime("%Y-%m-%dT%H:%M:%S")

    keep = []
    archive_buckets = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                ts = event.get("timestamp", "")
                if ts >= cutoff:
                    keep.append(line)
                else:
                    month_key = ts[:7] if len(ts) >= 7 else "unknown"
                    archive_buckets.setdefault(month_key, []).append(line)
            except json.JSONDecodeError:
                keep.append(line)

    if archive_buckets:
        for month_key, lines in archive_buckets.items():
            archive_path = os.path.join(archive_dir, f"{month_key}.jsonl")
            with open(archive_path, "a", encoding="utf-8") as f:
                f.writelines(lines)
        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(keep)
        total_archived = sum(len(v) for v in archive_buckets.values())
        return total_archived
    return 0
