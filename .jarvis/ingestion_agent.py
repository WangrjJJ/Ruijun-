#!/usr/bin/env python3
"""
JARVIS Ingestion Agent — 文件摄入代理
扫描文件 → 文本提取 → 哈希去重 → 输出 ingestion_events.jsonl

用法:
  python3 ingestion_agent.py                    # 扫描所有已知源
  python3 ingestion_agent.py --file <path>       # 单文件摄入
  python3 ingestion_agent.py --dir <path>        # 扫描目录
  python3 ingestion_agent.py --scan              # 全量扫描（忽略去重）
  python3 ingestion_agent.py --stats             # 查看摄入统计
"""

import os
import sys
import json
import hashlib
import argparse
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

EVENTS_FILE = os.path.join(DATA_DIR, "ingestion_events.jsonl")
PROCESSED_FILE = os.path.join(DATA_DIR, "processed_files.json")

# ── 扫描路径配置 ──────────────────────────────────────────────────
# 默认扫描的目录及其标签
SCAN_PATHS = [
    {
        "path": r"C:\Users\01455310\Documents\Obsidian Vault\26年中集环科工作区",
        "label": "26年工作区",
        "recursive": True,
    },
    {
        "path": r"C:\Users\01455310\Desktop\26年工作文件\_inbox",
        "label": "收件箱",
        "recursive": True,
    },
    {
        "path": r"C:\Users\01455310\Desktop\26年工作文件\26年季度经营分析会",
        "label": "季度经营分析",
        "recursive": True,
    },
]

# 支持的文件扩展名及解析器映射
SUPPORTED_EXT = {
    ".md": "markdown",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".docx": "docx",
    ".pdf": "pdf",
    ".txt": "txt",
    ".csv": "csv",
}


def file_fingerprint(filepath: str) -> str:
    """基于 mtime + size 的哈希，用于去重"""
    try:
        stat = os.stat(filepath)
        raw = f"{stat.st_mtime:.6f}|{stat.st_size}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
    except OSError:
        return ""


def load_processed() -> dict:
    """加载已处理文件注册表: {fingerprint: {path, time, label}}"""
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_processed(registry: dict):
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


def extract_text_markdown(filepath: str) -> str:
    """提取 markdown 文件全文"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(filepath, "r", encoding="gbk") as f:
            return f.read()


def extract_text_pptx(filepath: str) -> str:
    """提取 PPTX 文本内容"""
    try:
        from pptx import Presentation
        prs = Presentation(filepath)
        parts = []
        for i, slide in enumerate(prs.slides, 1):
            slide_text = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        text = para.text.strip()
                        if text:
                            slide_text.append(text)
                if shape.has_table:
                    table = shape.table
                    for row in table.rows:
                        row_text = " | ".join(
                            cell.text.strip() for cell in row.cells
                        )
                        if row_text.strip():
                            slide_text.append(row_text)
            if slide_text:
                parts.append(f"## Slide {i}\n" + "\n".join(slide_text))
        return "\n\n".join(parts)
    except Exception as e:
        return f"[PPTX提取失败: {e}]"


def extract_text_xlsx(filepath: str) -> str:
    """提取 XLSX 文本"""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(filepath, data_only=True, read_only=True)
        parts = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if any(cell is not None for cell in row):
                    row_text = " | ".join(
                        str(cell) if cell is not None else "" for cell in row
                    )
                    rows.append(row_text)
                if i > 500:  # 限制每 sheet 行数
                    rows.append("... (truncated)")
                    break
            if rows:
                parts.append(f"## Sheet: {sheet_name}\n" + "\n".join(rows[:100]))
        wb.close()
        return "\n\n".join(parts)
    except Exception as e:
        return f"[XLSX提取失败: {e}]"


def extract_text_docx(filepath: str) -> str:
    """提取 DOCX 文本"""
    try:
        from docx import Document
        doc = Document(filepath)
        parts = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                parts.append(text)
        # 提取表格
        for i, table in enumerate(doc.tables):
            table_parts = []
            for row in table.rows:
                row_text = " | ".join(
                    cell.text.strip() for cell in row.cells
                )
                if row_text.strip():
                    table_parts.append(row_text)
            if table_parts:
                parts.append(f"\n[Table {i+1}]\n" + "\n".join(table_parts))
        return "\n\n".join(parts)
    except Exception as e:
        return f"[DOCX提取失败: {e}]"


def extract_text_pdf(filepath: str) -> str:
    """提取 PDF 文本（简易版，使用 PyPDF2）"""
    try:
        import PyPDF2
        text_parts = []
        with open(filepath, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for i, page in enumerate(reader.pages):
                text = page.extract_text()
                if text:
                    text_parts.append(text)
                if i > 50:
                    text_parts.append("... (truncated)")
                    break
        return "\n\n".join(text_parts)
    except ImportError:
        return "[PDF提取需要安装PyPDF2: pip install PyPDF2]"
    except Exception as e:
        return f"[PDF提取失败: {e}]"


def extract_text_plain(filepath: str) -> str:
    """提取纯文本文件"""
    for encoding in ["utf-8", "gbk", "gb2312", "latin-1"]:
        try:
            with open(filepath, "r", encoding=encoding) as f:
                return f.read()[:10000]
        except UnicodeDecodeError:
            continue
    return "[无法解码文件]"


EXTRACTORS = {
    ".md": extract_text_markdown,
    ".pptx": extract_text_pptx,
    ".xlsx": extract_text_xlsx,
    ".docx": extract_text_docx,
    ".pdf": extract_text_pdf,
    ".txt": extract_text_plain,
    ".csv": extract_text_plain,
}


def generate_summary(text: str, max_len: int = 200, file_type: str = "") -> str:
    """从提取文本生成简短摘要"""
    # 对 markdown 文件跳过 frontmatter
    content = text
    if file_type == "markdown" and text.startswith("---"):
        end = text.find("---", 3)
        if end > 0:
            content = text[end + 3:].strip()
    lines = [l.strip() for l in content.split("\n") if l.strip() and not l.startswith("[")]
    summary = " ".join(lines[:5])
    if len(summary) > max_len:
        summary = summary[:max_len] + "..."
    return summary


def extract_topics(text: str, max_topics: int = 5) -> list:
    """从文本中提取可能的关键话题词"""
    # 基于 frontmatter tags 和关键词出现频率的简易提取
    topics = []
    # 尝试提取 frontmatter tags
    if text.startswith("---"):
        end = text.find("---", 3)
        if end > 0:
            fm = text[3:end].strip()
            for line in fm.split("\n"):
                if line.startswith("tags:") or line.startswith("tags:"):
                    continue
                if "tags:" in fm:
                    tag_section = fm.split("tags:")[1].split("\n")[0]
                    for tag in tag_section.replace("[", "").replace("]", "").split(","):
                        t = tag.strip().strip("'").strip('"')
                        if t and len(t) > 1:
                            topics.append(t)
                    break
    return topics[:max_topics]


def ingest_file(filepath: str, label: str = "", force: bool = False) -> dict | None:
    """摄入单个文件，返回事件或 None（如果已处理）"""
    if not os.path.isfile(filepath):
        return None

    ext = Path(filepath).suffix.lower()
    if ext not in SUPPORTED_EXT:
        return None

    fp = file_fingerprint(filepath)
    if not fp:
        return None

    registry = load_processed()
    if not force and fp in registry:
        return None

    extractor = EXTRACTORS.get(ext)
    if not extractor:
        return None

    extracted = extractor(filepath)
    if not extracted or extracted.startswith("["):
        return None

    summary = generate_summary(extracted, file_type=SUPPORTED_EXT[ext])
    topics = extract_topics(extracted)

    event = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "fingerprint": fp,
        "source_path": filepath,
        "source_label": label,
        "file_type": SUPPORTED_EXT[ext],
        "file_name": os.path.basename(filepath),
        "summary": summary,
        "key_topics": topics,
        "extracted_length": len(extracted),
        "extracted_text": extracted,
    }

    # 写 JSONL
    with open(EVENTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    # 更新注册表
    registry[fp] = {
        "path": filepath,
        "label": label,
        "time": event["timestamp"],
        "file_name": event["file_name"],
    }
    save_processed(registry)

    return event


def scan_directory(dir_path: str, label: str = "", recursive: bool = True) -> list:
    """扫描目录下所有支持的文件，返回摄入事件列表"""
    if not os.path.isdir(dir_path):
        return []
    events = []
    pattern = "*" if not recursive else "**/*"
    for ext in SUPPORTED_EXT:
        for filepath in Path(dir_path).glob(f"{pattern}{ext}"):
            try:
                event = ingest_file(str(filepath), label)
                if event:
                    events.append(event)
            except Exception as e:
                print(f"  [WARN] {filepath}: {e}", file=sys.stderr)
    return events


def cmd_scan(args=None):
    """全量扫描所有已配置路径"""
    all_events = []
    for cfg in SCAN_PATHS:
        path = cfg["path"]
        if not os.path.exists(path):
            print(f"  [SKIP] 不存在: {path}", file=sys.stderr)
            continue
        print(f"[SCAN] {cfg['label']}: {path}", file=sys.stderr)
        events = scan_directory(path, cfg["label"], cfg.get("recursive", True))
        all_events.extend(events)
        print(f"  → {len(events)} 新文件", file=sys.stderr)
    return all_events


def cmd_file(filepath: str, label: str = "手动摄入", force: bool = False):
    """单文件摄入"""
    if not os.path.exists(filepath):
        print(f"文件不存在: {filepath}", file=sys.stderr)
        return None
    event = ingest_file(filepath, label, force=force)
    if event:
        print(f"[INGEST] {event['file_name']} → {event['summary'][:80]}", file=sys.stderr)
    else:
        print(f"[SKIP] 已处理或无变化: {filepath}", file=sys.stderr)
    return event


def cmd_stats():
    """摄入统计"""
    if not os.path.exists(EVENTS_FILE):
        print("暂无摄入事件")
        return

    events = []
    with open(EVENTS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                events.append(json.loads(line))

    registry = load_processed()
    print(f"摄入统计:")
    print(f"  总摄入事件: {len(events)}")
    print(f"  已处理文件数: {len(registry)}")

    # 按类型统计
    by_type = {}
    for e in events:
        t = e.get("file_type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
    print(f"  按文件类型: {by_type}")

    # 按来源统计
    by_label = {}
    for e in events:
        lbl = e.get("source_label", "unknown")
        by_label[lbl] = by_label.get(lbl, 0) + 1
    print(f"  按来源: {by_label}")

    # 最近24小时
    cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
    recent = [e for e in events if e["timestamp"] >= cutoff]
    print(f"  最近24小时: {len(recent)} 事件")
    for e in recent:
        print(f"    - [{e['file_type']}] {e['file_name']}: {e['summary'][:60]}")


def cmd_recent(hours: int = 24) -> list:
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


def main():
    parser = argparse.ArgumentParser(description="JARVIS 摄入代理")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--file", help="摄入单个文件")
    group.add_argument("--dir", help="扫描目录")
    group.add_argument("--scan", action="store_true", help="全量扫描所有已知路径")
    group.add_argument("--stats", action="store_true", help="显示摄入统计")
    group.add_argument("--recent", type=int, metavar="HOURS", help="获取最近N小时事件(JSON输出)")
    parser.add_argument("--force", action="store_true", help="强制重新摄入（忽略去重）")
    parser.add_argument("--label", default="", help="来源标签")
    args = parser.parse_args()

    if args.stats:
        cmd_stats()
    elif args.recent:
        events = cmd_recent(args.recent)
        print(json.dumps(events, ensure_ascii=False, indent=2))
    elif args.file:
        cmd_file(args.file, args.label or "手动摄入", args.force)
    elif args.dir:
        events = scan_directory(args.dir, args.label or os.path.basename(args.dir))
        print(f"摄入完成: {len(events)} 个新文件", file=sys.stderr)
        for e in events:
            print(f"  [{e['file_type']}] {e['file_name']}", file=sys.stderr)
    elif args.scan:
        events = cmd_scan()
        print(f"\n总计摄入: {len(events)} 个新文件", file=sys.stderr)
    else:
        # 默认：快速扫描（检查已知路径的新文件）
        print("快速扫描模式...", file=sys.stderr)
        events = cmd_scan()
        print(f"完成: {len(events)} 个新文件", file=sys.stderr)


if __name__ == "__main__":
    main()
