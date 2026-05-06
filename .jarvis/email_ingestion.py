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

# 邮件附件保存目录（桌面 _inbox 下，自动被摄入代理扫描）
ATTACHMENT_DIR = os.path.join(
    os.path.expanduser("~"),
    r"Desktop\26年工作文件\_inbox\邮件附件"
)
os.makedirs(ATTACHMENT_DIR, exist_ok=True)

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


def download_and_ingest_attachments(mail, save_dir: str) -> list:
    """下载邮件附件到指定目录，并调用摄入代理处理。
    返回附件信息列表。"""
    attachments_info = []
    if not mail.Attachments or mail.Attachments.Count == 0:
        return attachments_info

    for i in range(1, mail.Attachments.Count + 1):
        try:
            att = mail.Attachments.Item(i)
            original_name = att.FileName
            if not original_name:
                continue

            # 去重：加时间戳前缀
            import time as _time
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = f"{ts}_{original_name}"
            save_path = os.path.join(save_dir, safe_name)

            # 避免重复下载
            if os.path.exists(save_path):
                attachments_info.append({
                    "file_name": original_name,
                    "saved_as": safe_name,
                    "size_kb": os.path.getsize(save_path) // 1024,
                    "status": "already_saved",
                })
                continue

            att.SaveAsFile(save_path)
            size_kb = os.path.getsize(save_path) // 1024 if os.path.exists(save_path) else 0

            info = {
                "file_name": original_name,
                "saved_as": safe_name,
                "size_kb": size_kb,
                "status": "saved",
            }

            # 调用摄入代理处理附件
            try:
                ingestion_script = os.path.join(SCRIPT_DIR, "ingestion_agent.py")
                import subprocess
                r = subprocess.run(
                    [sys.executable, ingestion_script, "--file", save_path,
                     "--label", "邮件附件"],
                    capture_output=True, encoding="utf-8", errors="replace",
                    timeout=30,
                )
                if r.returncode == 0:
                    info["ingested"] = True
                else:
                    info["ingested"] = False
                    info["ingest_error"] = r.stderr[:200]
            except Exception as e:
                info["ingested"] = False
                info["ingest_error"] = str(e)[:200]

            attachments_info.append(info)

        except Exception as e:
            attachments_info.append({
                "file_name": getattr(mail.Attachments.Item(i), 'FileName', f'attachment_{i}'),
                "status": "failed",
                "error": str(e)[:200],
            })

    return attachments_info


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


def get_thread_key(subject: str) -> str:
    """提取线程匹配键：去掉 RE:/FW:/答复:/转发: 前缀，归一化空白"""
    if not subject:
        return ""
    import re
    # 去掉回复/转发前缀
    cleaned = re.sub(
        r'^(Re:|FW:|Fwd:|答复:|转发:|回复:)\s*', '',
        subject, flags=re.IGNORECASE
    )
    # 再去掉可能嵌套的多层前缀
    for _ in range(3):
        cleaned = re.sub(
            r'^(Re:|FW:|Fwd:|答复:|转发:|回复:)\s*', '',
            cleaned, flags=re.IGNORECASE
        )
    return cleaned.strip().lower()


def get_conversation_history(mail, folder, summary_only: bool = False) -> list:
    """获取同一会话线程的往期邮件（仅正文，不含附件）。
    使用清理后的主题做线程匹配，按时间升序，最多取 8 封。"""
    thread_messages = []
    try:
        subject = mail.Subject or ""
        thread_key = get_thread_key(subject)
        if len(thread_key) < 3:
            return thread_messages

        current_time = mail.ReceivedTime
        # 处理时区
        try:
            if hasattr(current_time, "tzinfo") and current_time.tzinfo is not None:
                current_time = current_time.replace(tzinfo=None)
        except Exception:
            pass

        messages = folder.Items
        messages.Sort("[ReceivedTime]", True)

        count = 0
        for msg in messages:
            try:
                # 只取比当前邮件早的
                msg_time = msg.ReceivedTime
                try:
                    if hasattr(msg_time, "tzinfo") and msg_time.tzinfo is not None:
                        msg_time = msg_time.replace(tzinfo=None)
                except Exception:
                    pass

                if msg_time >= current_time:
                    continue

                # 跳过自身
                if msg.EntryID == mail.EntryID:
                    continue

                # 主题线程匹配
                msg_subject = msg.Subject or ""
                if get_thread_key(msg_subject) != thread_key:
                    continue

                count += 1
                if count > 8:
                    break

                time_str = msg_time.strftime("%m-%d %H:%M") if hasattr(msg_time, "strftime") else "?"
                thread_msg = {
                    "sender": msg.SenderName or "?",
                    "time": time_str,
                    "subject": msg_subject,
                }

                # 提取正文（往期邮件不下载附件）
                if not summary_only:
                    body = extract_email_body(msg)
                    thread_msg["body_preview"] = body[:300] if body else ""
                else:
                    thread_msg["body_preview"] = ""

                thread_messages.append(thread_msg)
            except Exception:
                continue
    except Exception:
        pass

    # 按时间升序（最早的在前面）
    thread_messages.reverse()
    return thread_messages


def fetch_emails(days: int = 1, folder_name: str = "收件箱",
                 unread_only: bool = False, sender_filter: str = "",
                 summary_only: bool = False) -> list:
    """获取邮件列表"""
    namespace = connect_outlook()
    folder = get_folder(namespace, folder_name)
    messages = folder.Items
    messages.Sort("[ReceivedTime]", True)  # 最新在前

    # 使用带时区的 datetime 与 Outlook 保持一致
    from datetime import timezone as _tz
    try:
        # Python 3.11+
        cutoff = datetime.now(_tz.utc).astimezone() - timedelta(days=days)
    except Exception:
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

            # 统一转为 naive datetime 比较
            try:
                if hasattr(received_dt, "tzinfo") and received_dt.tzinfo is not None:
                    received_dt = received_dt.replace(tzinfo=None)
            except Exception:
                pass
            cutoff_naive = cutoff.replace(tzinfo=None) if hasattr(cutoff, "tzinfo") and cutoff.tzinfo is not None else cutoff

            if received_dt < cutoff_naive:
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

            # 获取对话历史（往期邮件正文，不含附件）
            thread_history = get_conversation_history(mail, folder, summary_only)

            # 下载并摄入附件（始终执行，不依赖 summary 模式）
            has_att = bool(mail.Attachments.Count) if mail.Attachments.Count else False
            attachments_info = []
            if has_att:
                attachments_info = download_and_ingest_attachments(mail, ATTACHMENT_DIR)
                ingested_count = sum(1 for a in attachments_info if a.get("ingested"))
                if ingested_count > 0:
                    print(f"  [ATTACH] {ingested_count}/{len(attachments_info)} attachments ingested from: {subject[:40]}",
                          file=sys.stderr)

            event = {
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "email_received": received_str,
                "fingerprint": fp,
                "folder": folder_name,
                "sender_name": sender_name,
                "sender_email": mail.SenderEmailAddress or "",
                "subject": subject,
                "priority": priority,
                "has_attachments": has_att,
                "attachments": attachments_info,
                "thread_history": thread_history,
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
            store = {k: v for k, v in e.items() if k not in ("body", "attachments", "thread_history")}
            store["body_preview"] = e["body"][:200] if e.get("body") else ""
            # 附件摘要（不含完整路径）
            if e.get("attachments"):
                store["attachments"] = [
                    {"file_name": a["file_name"], "size_kb": a.get("size_kb", 0),
                     "ingested": a.get("ingested", False)}
                    for a in e["attachments"]
                ]
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
            att_str = ""
            if e.get("attachments"):
                ingested = [a for a in e["attachments"] if a.get("ingested")]
                if ingested:
                    att_str = f" [附件: {len(ingested)}个已摄入]"
                elif e.get("has_attachments"):
                    att_str = f" [附件: {len(e['attachments'])}个]"
            print(f"  [{e['email_received'][:10]}] {e['sender_name']}: {e['subject']}{att_str}")
        print()

    if p1:
        print("=== P1 重要 ===")
        for e in p1[:10]:
            att_str = ""
            if e.get("attachments"):
                ingested = [a for a in e["attachments"] if a.get("ingested")]
                if ingested:
                    att_str = f" [附件: {len(ingested)}个已摄入]"
            print(f"  [{e['email_received'][:10]}] {e['sender_name']}: {e['subject']}{att_str}")
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
