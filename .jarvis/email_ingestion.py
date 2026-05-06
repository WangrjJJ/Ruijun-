#!/usr/bin/env python3
"""
JARVIS Email Ingestion — Outlook 邮件摄入
通过 win32com.client 连接 Outlook，提取收件箱/已发送邮件中的关键邮件。

用法:
  python3 email_ingestion.py                  # 获取今天邮件
  python3 email_ingestion.py --days 3          # 最近3天
  python3 email_ingestion.py --folder "收件箱"  # 指定文件夹
  python3 email_ingestion.py --unread-only     # 仅未读
  python3 email_ingestion.py --sender "季国祥"  # 按发件人过滤
  python3 email_ingestion.py --summary         # 仅摘要（不提取正文）
"""

import os
import sys
import json
import argparse
import hashlib
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

EMAIL_EVENTS_FILE = os.path.join(DATA_DIR, "email_events.jsonl")
EMAIL_PROCESSED_FILE = os.path.join(DATA_DIR, "email_processed.json")

# 关键联系人/关键词（用于优先级标记）
PRIORITY_SENDERS = [
    "季国祥", "ji guoxiang", "jiguoxiang",
    "方建平", "fang jianping",
    "杨殿伟", "包秋婧", "陈晓春",
]
PRIORITY_KEYWORDS = [
    "董事会", "汇报", "审批", "紧急", "商业计划",
    "KPI", "预算", "投资", "搬迁", "采购",
    "数字化", "QMS", "ERP", "方针", "绩效",
    "URGENT", "IMPORTANT", "FYI",
]


def connect_outlook():
    """建立 Outlook COM 连接"""
    try:
        import win32com.client
        outlook = win32com.client.Dispatch("Outlook.Application")
        namespace = outlook.GetNamespace("MAPI")
        return namespace
    except ImportError:
        print("错误: 需要安装 pywin32: pip install pywin32", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Outlook 连接失败: {e}", file=sys.stderr)
        print("请确认 Outlook 已打开并登录", file=sys.stderr)
        sys.exit(1)


def get_folder(namespace, folder_name: str = "收件箱"):
    """获取指定文件夹（支持中文名）"""
    # 首先尝试收件箱子文件夹
    inbox = namespace.GetDefaultFolder(6)  # 6 = olFolderInbox
    if folder_name == "收件箱":
        return inbox

    # 搜索子文件夹
    for folder in inbox.Folders:
        if folder.Name == folder_name:
            return folder

    # 尝试搜索所有文件夹
    for store in namespace.Stores:
        root = store.GetRootFolder()
        for folder in root.Folders:
            if folder.Name == folder_name:
                return folder

    # 默认返回收件箱
    print(f"未找到文件夹 '{folder_name}'，使用收件箱", file=sys.stderr)
    return inbox


def extract_email_body(mail) -> str:
    """提取邮件正文（优先纯文本，否则 HTML 转文本）"""
    try:
        if mail.BodyFormat == 1:  # olFormatPlain
            return mail.Body or ""
        else:
            # HTML 格式 — 简易去除标签
            import re
            body = mail.HTMLBody or ""
            # 去掉 HTML 标签
            body = re.sub(r'<style[^>]*>.*?</style>', '', body, flags=re.DOTALL | re.IGNORECASE)
            body = re.sub(r'<script[^>]*>.*?</script>', '', body, flags=re.DOTALL | re.IGNORECASE)
            body = re.sub(r'<[^>]+>', '\n', body)
            body = re.sub(r'&nbsp;', ' ', body)
            body = re.sub(r'&amp;', '&', body)
            body = re.sub(r'&lt;', '<', body)
            body = re.sub(r'&gt;', '>', body)
            body = re.sub(r'\n\s*\n', '\n\n', body)
            # 截取前 5000 字符
            lines = [l.strip() for l in body.split('\n') if l.strip()]
            return '\n'.join(lines[:100])
    except Exception as e:
        return f"[邮件正文提取失败: {e}]"


def get_email_fingerprint(mail) -> str:
    """基于邮件唯一标识的去重指纹"""
    try:
        raw = f"{mail.SenderEmailAddress}|{mail.Subject}|{mail.ReceivedTime}"
    except Exception:
        raw = f"{mail.EntryID}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def load_processed_emails() -> dict:
    if os.path.exists(EMAIL_PROCESSED_FILE):
        with open(EMAIL_PROCESSED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_processed_emails(registry: dict):
    with open(EMAIL_PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


def assess_priority(sender_name: str, subject: str, body: str) -> str:
    """评估邮件优先级: P0/P1/P2"""
    sender_lower = sender_name.lower()
    combined = f"{sender_lower} {subject} {body[:500]}".lower()

    # P0: 关键人物 + 紧急主题
    p0_senders = ["季国祥", "ji guoxiang", "jiguoxiang"]
    p0_keywords = ["紧急", "立即", "urgent", "审批", "董事会", "请尽快"]
    if any(s in combined for s in p0_senders) and any(k in combined for k in p0_keywords):
        return "P0"

    # P1: 关键人物 或 重要关键词
    if any(s in combined for s in PRIORITY_SENDERS):
        return "P1"
    if any(k in combined for k in PRIORITY_KEYWORDS):
        return "P1"

    return "P2"


def fetch_emails(days: int = 1, folder_name: str = "收件箱",
                 unread_only: bool = False, sender_filter: str = "",
                 summary_only: bool = False) -> list:
    """获取邮件列表"""
    namespace = connect_outlook()
    folder = get_folder(namespace, folder_name)
    messages = folder.Items
    messages.Sort("[ReceivedTime]", True)  # 最新在前

    cutoff = datetime.now() - timedelta(days=days)
    registry = load_processed_emails()
    events = []

    count = 0
    for mail in messages:
        try:
            received = mail.ReceivedTime
            if hasattr(received, "strftime"):
                received_str = received.strftime("%Y-%m-%dT%H:%M:%S")
                received_dt = received
            else:
                continue

            if received_dt < cutoff:
                break  # 已到截止时间，停止

            count += 1
            if count > 200:  # 最多处理200封
                break

            # 过滤
            if unread_only and not mail.Unread:
                continue
            if sender_filter:
                sender = (mail.SenderName or "").lower()
                if sender_filter.lower() not in sender:
                    continue

            fp = get_email_fingerprint(mail)
            if fp in registry:
                continue

            sender_name = mail.SenderName or "未知"
            subject = mail.Subject or "(无主题)"
            priority = assess_priority(sender_name, subject, "")
            body = "" if summary_only else extract_email_body(mail)

            event = {
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "email_received": received_str,
                "fingerprint": fp,
                "folder": folder_name,
                "sender_name": sender_name,
                "sender_email": mail.SenderEmailAddress or "",
                "subject": subject,
                "priority": priority,
                "has_attachments": bool(mail.Attachments.Count) if mail.Attachments.Count else False,
                "unread": bool(mail.Unread),
                "body_length": len(body),
                "body": body,
            }

            if not summary_only:
                event["body"] = body

            # 标记收件人
            try:
                event["to"] = mail.To or ""
            except Exception:
                event["to"] = ""

            events.append(event)

            # 更新注册表
            registry[fp] = {
                "subject": subject,
                "received": received_str,
                "time": event["timestamp"],
            }

        except Exception as e:
            print(f"  [WARN] 邮件处理异常: {e}", file=sys.stderr)
            continue

    save_processed_emails(registry)

    # 写入 JSONL
    for e in events:
        with open(EMAIL_EVENTS_FILE, "a", encoding="utf-8") as f:
            # 存储时移除 body（太大），改为 body_length
            store = {k: v for k, v in e.items() if k != "body"}
            store["body_preview"] = e["body"][:200] if e.get("body") else ""
            f.write(json.dumps(store, ensure_ascii=False) + "\n")

    return events


def cmd_summary(events: list):
    """打印邮件摘要"""
    if not events:
        print("无新邮件。")
        return

    p0 = [e for e in events if e["priority"] == "P0"]
    p1 = [e for e in events if e["priority"] == "P1"]
    p2 = [e for e in events if e["priority"] == "P2"]

    print(f"\n邮件摄入摘要: 共 {len(events)} 封新邮件")
    print(f"  P0 (紧急): {len(p0)}")
    print(f"  P1 (重要): {len(p1)}")
    print(f"  P2 (普通): {len(p2)}")
    print()

    if p0:
        print("=== P0 紧急 ===")
        for e in p0:
            print(f"  [{e['email_received'][:10]}] {e['sender_name']}: {e['subject']}")
        print()

    if p1:
        print("=== P1 重要 ===")
        for e in p1[:10]:
            print(f"  [{e['email_received'][:10]}] {e['sender_name']}: {e['subject']}")
        if len(p1) > 10:
            print(f"  ... 还有 {len(p1) - 10} 封")
        print()


def main():
    parser = argparse.ArgumentParser(description="JARVIS 邮件摄入")
    parser.add_argument("--days", type=int, default=1, help="获取最近N天的邮件（默认1）")
    parser.add_argument("--folder", default="收件箱", help="邮件文件夹（默认: 收件箱）")
    parser.add_argument("--unread-only", action="store_true", help="仅获取未读邮件")
    parser.add_argument("--sender", dest="sender_filter", default="",
                       help="按发件人过滤（支持部分匹配）")
    parser.add_argument("--summary", action="store_true", help="仅摘要模式（不提取正文）")
    parser.add_argument("--json", action="store_true", help="JSON格式输出")
    args = parser.parse_args()

    events = fetch_emails(
        days=args.days,
        folder_name=args.folder,
        unread_only=args.unread_only,
        sender_filter=args.sender_filter,
        summary_only=args.summary,
    )

    if args.json:
        print(json.dumps(events, ensure_ascii=False, indent=2))
    else:
        cmd_summary(events)

    print(f"\n摄入完成: {len(events)} 封邮件", file=sys.stderr)


if __name__ == "__main__":
    main()
