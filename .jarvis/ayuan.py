#!/usr/bin/env python3
"""
阿原 — 价值观宪法的镜子

阿原不是 Jarvis 2.0。
Jarvis 是军师（方案、量化、优化），阿原是镜子（反问、陪伴、让你自己看见）。

锚点优先级：《我的宪法》 > 当前情绪 > 外部数据

用法：
  ayuan.py reflect --event "..." [--feeling] [--body] [--save]
  ayuan.py mirror  [--days 30]
  ayuan.py constitution
  ayuan.py checkin
"""

import os
import sys
import sqlite3
import argparse
import textwrap
from datetime import datetime, timedelta
from collections import Counter

import yaml

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR     = os.path.join(SCRIPT_DIR, "data")
DB_PATH      = os.path.join(DATA_DIR, "jarvis.db")
PROMPTS_PATH = os.path.join(SCRIPT_DIR, "ayuan_prompts.yaml")

VAULT_ROOT   = os.path.dirname(SCRIPT_DIR)
CONSTITUTION = os.path.join(VAULT_ROOT, "阿原", "价值观宪法", "我的宪法.md")
FRAMEWORK    = os.path.join(VAULT_ROOT, "阿原", "价值观宪法", "00_写作框架.md")


# ── 工具 ────────────────────────────────────────────────────

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_prompts():
    with open(PROMPTS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def match_trigger(prompts_doc, text):
    """在文本中匹配第一个命中的 trigger，未命中返回 '默认'。"""
    text = text or ""
    for entry in prompts_doc["triggers"]:
        for kw in entry.get("keywords", []):
            if kw and kw in text:
                return entry
    for entry in prompts_doc["triggers"]:
        if entry["name"] == "默认":
            return entry
    return prompts_doc["triggers"][-1]


def print_header(title):
    bar = "─" * 2
    print(f"\n{bar} {title} {bar}\n")


def wrap(text, indent="    "):
    return textwrap.fill(text, width=76, initial_indent=indent,
                         subsequent_indent=indent)


# ── reflect ─────────────────────────────────────────────────

def cmd_reflect(args):
    prompts_doc = load_prompts()
    scan_text = " ".join(filter(None, [args.event, args.feeling, args.body]))
    trigger = match_trigger(prompts_doc, scan_text)

    # 头部
    print_header("阿原 · reflect")
    print(f"    事件：{args.event}")
    if args.feeling:
        print(f"    情绪：{args.feeling}")
    if args.body:
        print(f"    身体：{args.body}")
    print(f"    触发：{trigger['name']}")
    anchor = trigger.get("anchors", {}) or {}
    if anchor.get("questions"):
        qs = "#".join(str(q) for q in anchor["questions"])
        print(f"    锚点：《我的宪法》{anchor.get('chapter','')} #{qs}")
    else:
        print(f"    锚点：《我的宪法》{anchor.get('chapter','全书')}")

    # 陪伴语
    if trigger.get("companion"):
        print_header("先停一下")
        print(wrap(trigger["companion"]))

    # 反问
    print_header("反问")
    for i, q in enumerate(trigger.get("prompts", []), 1):
        print(wrap(f"{i}. {q}"))

    # 尾部
    print()
    if args.save:
        conn = connect()
        # 确保表存在（若未初始化过 journal.py）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS life_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT NOT NULL, feeling TEXT DEFAULT '',
                body TEXT DEFAULT '', trigger TEXT DEFAULT '',
                anchor_ref TEXT DEFAULT '', reflection TEXT DEFAULT '',
                mode TEXT NOT NULL DEFAULT '收集',
                created_at TEXT NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
                updated_at TEXT NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
            );
        """)
        anchor_ref = ""
        if anchor.get("chapter"):
            qs = "#".join(str(q) for q in anchor.get("questions", []))
            anchor_ref = f"{anchor['chapter']}" + (f" #{qs}" if qs else "")
        cur = conn.execute(
            """INSERT INTO life_entries (event, feeling, body, trigger,
               anchor_ref, mode) VALUES (?, ?, ?, ?, ?, '反问')""",
            (args.event, args.feeling or "", args.body or "",
             trigger["name"], anchor_ref)
        )
        conn.commit()
        conn.close()
        print(f"    [已记录 life_entries #{cur.lastrowid}]\n")
    else:
        print("    （加 --save 把这次对话存进 life_entries）\n")


# ── mirror ──────────────────────────────────────────────────

def cmd_mirror(args):
    days = args.days or 30
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

    conn = connect()
    rows = conn.execute(
        """SELECT trigger, feeling, event, created_at FROM life_entries
           WHERE created_at >= ? ORDER BY created_at DESC""",
        (cutoff,)
    ).fetchall()
    conn.close()

    print_header(f"阿原 · mirror · 最近 {days} 天")

    if not rows:
        print("    暂无记录。先用 `ayuan.py reflect --event ... --save` 累积几条。\n")
        return

    print(f"    共 {len(rows)} 条片段\n")

    # 触发词分布
    trigger_counts = Counter(r["trigger"] for r in rows if r["trigger"])
    if trigger_counts:
        print("    触发词分布：")
        for t, c in trigger_counts.most_common():
            bar = "█" * c
            print(f"      {t:<8} {bar} {c}")
        print()

    # 情绪关键词
    feeling_counts = Counter()
    for r in rows:
        if r["feeling"]:
            for f in r["feeling"].replace("，", ",").split(","):
                f = f.strip()
                if f:
                    feeling_counts[f] += 1
    if feeling_counts:
        print("    情绪关键词 Top 5：")
        for f, c in feeling_counts.most_common(5):
            print(f"      {f:<8} × {c}")
        print()

    # 最近3条事件
    print("    最近 3 条事件：")
    for r in rows[:3]:
        date = r["created_at"][:10]
        event = r["event"][:60] + ("…" if len(r["event"]) > 60 else "")
        print(f"      [{date}] ({r['trigger'] or '-'}) {event}")
    print()

    # 镜子的反问
    print_header("镜子")
    top_trigger = trigger_counts.most_common(1)[0][0] if trigger_counts else None
    if top_trigger and trigger_counts[top_trigger] >= 3:
        print(wrap(f"「{top_trigger}」在 {days} 天里出现了 "
                   f"{trigger_counts[top_trigger]} 次。"))
        print(wrap("这是一个新模式，还是一个老模式？"))
        print(wrap("如果是老模式，它上一次出现是什么时候解决的？"))
    else:
        print(wrap("最近的片段分布还比较散。"))
        print(wrap("如果要在这些事里挑一件最值得坐下来再想想的，是哪一件？"))
    print()


# ── constitution ────────────────────────────────────────────

def cmd_constitution(args):
    print_header("《我的宪法》")

    if not os.path.exists(CONSTITUTION):
        print("    还没写。\n")
        print(wrap(f"框架在：{FRAMEWORK}"))
        print(wrap("按框架里「六章 · 三十问」先写糟糕的一稿。"))
        print(wrap("阿原上线是为了对齐这份文件——没有它，阿原只是另一个工具。"))
        print()
        return

    with open(CONSTITUTION, "r", encoding="utf-8") as f:
        content = f.read()

    # 字数粗估进度
    word_count = len(content.replace("\n", "").replace(" ", ""))
    # 如果只有 frontmatter，视为未开写
    if word_count < 200:
        print("    文件存在但几乎空白。")
        print(wrap(f"当前字数约 {word_count}。先写第一章的5个问题。"))
        print()
        return

    print(content)
    print()
    print(f"    [字数约 {word_count}]\n")


# ── checkin ─────────────────────────────────────────────────

def cmd_checkin(args):
    """周复盘：把最近7天的 life_entries 和宪法对照。"""
    days = 7
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

    conn = connect()
    rows = conn.execute(
        """SELECT event, feeling, trigger, anchor_ref, created_at
           FROM life_entries WHERE created_at >= ?
           ORDER BY created_at DESC""",
        (cutoff,)
    ).fetchall()
    # 同步拉 work/investment 最近决策，帮用户对照
    decisions = conn.execute(
        """SELECT domain, title, created_at FROM decisions
           WHERE created_at >= ? ORDER BY created_at DESC""",
        (cutoff,)
    ).fetchall()
    conn.close()

    constitution_exists = os.path.exists(CONSTITUTION)

    print_header(f"阿原 · checkin · 最近 {days} 天")

    if not constitution_exists:
        print(wrap("《我的宪法》还没写。周复盘的对照基准不存在——"))
        print(wrap("先花 2 小时写糟糕的一稿再回来。"))
        print()

    # 人生片段
    if rows:
        print(f"    生活片段 {len(rows)} 条：")
        for r in rows:
            date = r["created_at"][:10]
            print(f"      [{date}] ({r['trigger'] or '-'}) {r['event'][:50]}")
        print()
    else:
        print("    本周没有人生片段记录。\n")

    # 决策
    if decisions:
        print(f"    工作/投资决策 {len(decisions)} 条：")
        for d in decisions:
            date = d["created_at"][:10]
            print(f"      [{date}] ({d['domain']}) {d['title'][:50]}")
        print()

    # 反问（对照宪法）
    print_header("本周对照")
    questions = [
        "如果本周把时间放进 睡眠/工作/家庭/自我/无意义消耗 五格，差距最大的是哪一格？",
        "本周做过的事里，有哪件是你宪法里绝对不会做的？（哪怕只擦了边）",
        "有没有一件事你很想做但没做？是什么在阻止你？",
        "下周要不要只做一件「对齐宪法」的小事？是哪件？",
    ]
    for i, q in enumerate(questions, 1):
        print(wrap(f"{i}. {q}"))
    print()


# ── main ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="阿原 — 价值观宪法的镜子",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            示例:
              ayuan.py reflect --event "跟总经理谈了副总任命，心里憋屈"
              ayuan.py reflect --event "..." --feeling "不甘" --save
              ayuan.py mirror --days 30
              ayuan.py constitution
              ayuan.py checkin
        """)
    )
    sub = parser.add_subparsers(dest="command")

    p_reflect = sub.add_parser("reflect", help="记录+反问一件事")
    p_reflect.add_argument("--event", required=True, help="发生了什么")
    p_reflect.add_argument("--feeling", help="情绪关键词")
    p_reflect.add_argument("--body", help="身体感受")
    p_reflect.add_argument("--save", action="store_true",
                           help="写入 life_entries 表（默认只打印不保存）")

    p_mirror = sub.add_parser("mirror", help="最近N天的镜像汇总")
    p_mirror.add_argument("--days", type=int, default=30)

    sub.add_parser("constitution", help="读《我的宪法》")
    sub.add_parser("checkin", help="周复盘（对照宪法）")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    dispatch = {
        "reflect": cmd_reflect,
        "mirror": cmd_mirror,
        "constitution": cmd_constitution,
        "checkin": cmd_checkin,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
