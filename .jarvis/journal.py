#!/usr/bin/env python3
"""
JARVIS Decision Journal — 决策日志 + 结构化记忆
记录、查询、复盘个人决策（工作/投资），跨会话KV记忆。

用法:
  python3 journal.py log --domain investment --title "BTC Buy Low行权价调整"
  python3 journal.py list --domain work --days 30
  python3 journal.py show --id 1
  python3 journal.py review --id 1 --score 4 --result "未被行权，恐贪回升"
  python3 journal.py stats
  python3 journal.py memory set btc_bias "震荡偏空" --category investment
  python3 journal.py memory get btc_bias
"""

import os
import sys
import json
import sqlite3
import argparse
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "jarvis.db")

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS decisions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    domain      TEXT NOT NULL CHECK (domain IN ('work', 'investment')),
    title       TEXT NOT NULL,
    context     TEXT DEFAULT '',
    options     TEXT DEFAULT '',
    chosen      TEXT DEFAULT '',
    rationale   TEXT DEFAULT '',
    risk_notes  TEXT DEFAULT '',
    tags        TEXT DEFAULT '',
    confidence  INTEGER DEFAULT 3 CHECK (confidence BETWEEN 1 AND 5),
    status      TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'closed', 'abandoned')),
    created_at  TEXT NOT NULL
                DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
    updated_at  TEXT NOT NULL
                DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

CREATE TABLE IF NOT EXISTS reviews (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id   INTEGER NOT NULL REFERENCES decisions(id),
    outcome_score INTEGER CHECK (outcome_score BETWEEN 1 AND 5),
    actual_result TEXT DEFAULT '',
    lesson        TEXT DEFAULT '',
    would_change  TEXT DEFAULT '',
    reviewed_at   TEXT NOT NULL
                  DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

CREATE TABLE IF NOT EXISTS memory_kv (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    category    TEXT DEFAULT 'general',
    updated_at  TEXT NOT NULL
                DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_decisions_domain  ON decisions(domain);
CREATE INDEX IF NOT EXISTS idx_decisions_status  ON decisions(status);
CREATE INDEX IF NOT EXISTS idx_decisions_created ON decisions(created_at);
CREATE INDEX IF NOT EXISTS idx_reviews_decision  ON reviews(decision_id);
CREATE INDEX IF NOT EXISTS idx_memory_category   ON memory_kv(category);
"""


# ── 数据库初始化 ─────────────────────────────────────────────

def init_db():
    """幂等初始化数据库，返回connection"""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    return conn


def row_to_dict(row):
    """sqlite3.Row → dict"""
    if row is None:
        return None
    return dict(row)


def out(data):
    """JSON输出到stdout"""
    print(json.dumps(data, ensure_ascii=False, indent=2))


# ── log: 记录新决策 ──────────────────────────────────────────

def cmd_log(args):
    conn = init_db()
    cur = conn.execute(
        """INSERT INTO decisions (domain, title, context, options, chosen,
           rationale, risk_notes, tags, confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (args.domain, args.title, args.context or "", args.options or "",
         args.chosen or "", args.rationale or "", args.risk or "",
         args.tags or "", args.confidence)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM decisions WHERE id = ?",
                       (cur.lastrowid,)).fetchone()
    conn.close()
    out({"status": "created", "decision": row_to_dict(row)})


# ── list: 查询决策列表 ───────────────────────────────────────

def cmd_list(args):
    conn = init_db()
    conditions = []
    params = []

    if args.domain:
        conditions.append("domain = ?")
        params.append(args.domain)
    if args.filter_status:
        conditions.append("status = ?")
        params.append(args.filter_status)
    if args.tag:
        conditions.append("tags LIKE ?")
        params.append(f"%{args.tag}%")
    if args.days:
        cutoff = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%dT%H:%M:%S")
        conditions.append("created_at >= ?")
        params.append(cutoff)

    where = " AND ".join(conditions) if conditions else "1=1"
    limit = args.limit or 20
    params.append(limit)

    rows = conn.execute(
        f"""SELECT id, domain, title, tags, confidence, status, created_at
            FROM decisions WHERE {where}
            ORDER BY created_at DESC LIMIT ?""",
        params
    ).fetchall()
    conn.close()

    out({"count": len(rows), "decisions": [row_to_dict(r) for r in rows]})


# ── show: 查看决策详情 + 复盘 ─────────────────────────────────

def cmd_show(args):
    conn = init_db()
    decision = conn.execute("SELECT * FROM decisions WHERE id = ?",
                            (args.id,)).fetchone()
    if not decision:
        out({"error": f"决策 #{args.id} 不存在"})
        conn.close()
        return

    reviews = conn.execute(
        "SELECT * FROM reviews WHERE decision_id = ? ORDER BY reviewed_at",
        (args.id,)
    ).fetchall()
    conn.close()

    result = row_to_dict(decision)
    result["reviews"] = [row_to_dict(r) for r in reviews]
    out(result)


# ── review: 添加复盘评价 ─────────────────────────────────────

def cmd_review(args):
    conn = init_db()
    decision = conn.execute("SELECT * FROM decisions WHERE id = ?",
                            (args.id,)).fetchone()
    if not decision:
        out({"error": f"决策 #{args.id} 不存在"})
        conn.close()
        return

    conn.execute(
        """INSERT INTO reviews (decision_id, outcome_score, actual_result,
           lesson, would_change)
           VALUES (?, ?, ?, ?, ?)""",
        (args.id, args.score, args.result or "", args.lesson or "",
         args.change or "")
    )

    # 自动关闭open状态的决策
    if decision["status"] == "open":
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        conn.execute(
            "UPDATE decisions SET status = 'closed', updated_at = ? WHERE id = ?",
            (now, args.id)
        )

    conn.commit()

    # 返回完整决策+复盘
    updated = conn.execute("SELECT * FROM decisions WHERE id = ?",
                           (args.id,)).fetchone()
    reviews = conn.execute(
        "SELECT * FROM reviews WHERE decision_id = ? ORDER BY reviewed_at",
        (args.id,)
    ).fetchall()
    conn.close()

    result = row_to_dict(updated)
    result["reviews"] = [row_to_dict(r) for r in reviews]
    out(result)


# ── stats: 统计分析 ──────────────────────────────────────────

def cmd_stats(args):
    conn = init_db()
    domain_filter = ""
    params = []
    if args.domain:
        domain_filter = "WHERE domain = ?"
        params = [args.domain]

    # 总数
    total = conn.execute(
        f"SELECT COUNT(*) FROM decisions {domain_filter}", params
    ).fetchone()[0]

    # 按状态
    by_status = {}
    for row in conn.execute(
        f"SELECT status, COUNT(*) as cnt FROM decisions {domain_filter} GROUP BY status",
        params
    ):
        by_status[row["status"]] = row["cnt"]

    # 按域
    by_domain = {}
    if not args.domain:
        for row in conn.execute(
            "SELECT domain, COUNT(*) as cnt FROM decisions GROUP BY domain"
        ):
            by_domain[row["domain"]] = row["cnt"]

    # 已复盘数
    reviewed_q = """SELECT COUNT(DISTINCT d.id) FROM decisions d
                    JOIN reviews r ON r.decision_id = d.id"""
    if args.domain:
        reviewed_q += " WHERE d.domain = ?"
    reviewed_count = conn.execute(reviewed_q, params).fetchone()[0]

    # 平均outcome_score
    avg_q = """SELECT AVG(r.outcome_score) FROM reviews r
               JOIN decisions d ON d.id = r.decision_id"""
    if args.domain:
        avg_q += " WHERE d.domain = ?"
    avg_row = conn.execute(avg_q, params).fetchone()
    avg_outcome = round(avg_row[0], 2) if avg_row[0] is not None else None

    # 校准偏差: |confidence - outcome_score| 均值
    cal_q = """SELECT AVG(ABS(d.confidence - r.outcome_score))
               FROM decisions d JOIN reviews r ON r.decision_id = d.id"""
    if args.domain:
        cal_q += " WHERE d.domain = ?"
    cal_row = conn.execute(cal_q, params).fetchone()
    calibration_gap = round(cal_row[0], 2) if cal_row[0] is not None else None

    # Top tags
    tag_q = f"SELECT tags FROM decisions {domain_filter}"
    tag_counts = {}
    for row in conn.execute(tag_q, params):
        if row["tags"]:
            for t in row["tags"].split(","):
                t = t.strip()
                if t:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
    top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    # 超14天未关闭
    stale_cutoff = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%S")
    stale_q = "SELECT id, title, created_at FROM decisions WHERE status = 'open' AND created_at < ?"
    stale_params = [stale_cutoff]
    if args.domain:
        stale_q += " AND domain = ?"
        stale_params.append(args.domain)
    stale = [row_to_dict(r) for r in conn.execute(stale_q, stale_params)]

    conn.close()

    result = {
        "total": total,
        "by_status": by_status,
        "reviewed_count": reviewed_count,
        "avg_outcome_score": avg_outcome,
        "calibration_gap": calibration_gap,
        "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
        "stale_open_decisions": stale,
    }
    if by_domain:
        result["by_domain"] = by_domain

    out(result)


# ── memory: KV记忆CRUD ──────────────────────────────────────

def cmd_memory(args):
    conn = init_db()
    action = args.action

    if action == "set":
        if not args.key or not args.value:
            out({"error": "用法: memory set <key> <value> [--category X]"})
            conn.close()
            return
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        conn.execute(
            """INSERT OR REPLACE INTO memory_kv (key, value, category, updated_at)
               VALUES (?, ?, ?, ?)""",
            (args.key, args.value, args.category or "general", now)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM memory_kv WHERE key = ?",
                           (args.key,)).fetchone()
        conn.close()
        out({"status": "saved", "memory": row_to_dict(row)})

    elif action == "get":
        if not args.key:
            out({"error": "用法: memory get <key>"})
            conn.close()
            return
        row = conn.execute("SELECT * FROM memory_kv WHERE key = ?",
                           (args.key,)).fetchone()
        conn.close()
        if row:
            out(row_to_dict(row))
        else:
            out({"error": f"key '{args.key}' 不存在"})

    elif action == "list":
        if args.category:
            rows = conn.execute(
                "SELECT * FROM memory_kv WHERE category = ? ORDER BY updated_at DESC",
                (args.category,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memory_kv ORDER BY category, updated_at DESC"
            ).fetchall()
        conn.close()
        out({"count": len(rows), "memories": [row_to_dict(r) for r in rows]})

    elif action == "delete":
        if not args.key:
            out({"error": "用法: memory delete <key>"})
            conn.close()
            return
        conn.execute("DELETE FROM memory_kv WHERE key = ?", (args.key,))
        conn.commit()
        conn.close()
        out({"status": "deleted", "key": args.key})

    else:
        conn.close()
        out({"error": f"未知操作: {action}，支持: get/set/list/delete"})


# ── CLI入口 ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="JARVIS 决策日志")
    sub = parser.add_subparsers(dest="command")

    # log
    p_log = sub.add_parser("log", help="记录新决策")
    p_log.add_argument("--domain", required=True, choices=["work", "investment"])
    p_log.add_argument("--title", required=True)
    p_log.add_argument("--context", help="决策背景")
    p_log.add_argument("--options", help="可选方案")
    p_log.add_argument("--chosen", help="最终选择")
    p_log.add_argument("--rationale", help="决策理由")
    p_log.add_argument("--risk", help="风险备注")
    p_log.add_argument("--tags", help="标签（逗号分隔）")
    p_log.add_argument("--confidence", type=int, default=3,
                       choices=[1, 2, 3, 4, 5], help="信心度 1-5（默认3）")

    # list
    p_list = sub.add_parser("list", help="查询决策列表")
    p_list.add_argument("--domain", choices=["work", "investment"])
    p_list.add_argument("--status", dest="filter_status",
                        choices=["open", "closed", "abandoned"])
    p_list.add_argument("--tag", help="按标签过滤")
    p_list.add_argument("--days", type=int, help="最近N天")
    p_list.add_argument("--limit", type=int, default=20, help="返回条数（默认20）")

    # show
    p_show = sub.add_parser("show", help="查看决策详情")
    p_show.add_argument("--id", type=int, required=True, help="决策ID")

    # review
    p_review = sub.add_parser("review", help="添加复盘评价")
    p_review.add_argument("--id", type=int, required=True, help="决策ID")
    p_review.add_argument("--score", type=int, required=True,
                          choices=[1, 2, 3, 4, 5], help="结果评分 1-5")
    p_review.add_argument("--result", required=True, help="实际结果")
    p_review.add_argument("--lesson", help="经验教训")
    p_review.add_argument("--change", help="如果重来会怎么做")

    # stats
    p_stats = sub.add_parser("stats", help="统计分析")
    p_stats.add_argument("--domain", choices=["work", "investment"])

    # memory
    p_mem = sub.add_parser("memory", help="KV记忆管理")
    p_mem.add_argument("action", choices=["get", "set", "list", "delete"])
    p_mem.add_argument("key", nargs="?", help="记忆key")
    p_mem.add_argument("value", nargs="?", help="记忆value（set时需要）")
    p_mem.add_argument("--category", help="分类（默认general）")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    dispatch = {
        "log": cmd_log,
        "list": cmd_list,
        "show": cmd_show,
        "review": cmd_review,
        "stats": cmd_stats,
        "memory": cmd_memory,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
