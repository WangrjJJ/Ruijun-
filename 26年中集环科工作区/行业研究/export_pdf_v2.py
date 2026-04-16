# -*- coding: utf-8 -*-
"""将行业研究报告（v2版：能力差距评估+战略建议使用Opus优化版）合并导出为PDF"""

import re
from pathlib import Path
from markdown_pdf import MarkdownPdf, Section

# 报告目录
BASE = Path(__file__).parent

# 按章节顺序排列——第6、7章使用v2版本
FILES = [
    "00_执行摘要.md",
    "01_公司基本面深度画像.md",
    "02_行业概况与市场规模.md",
    "03_竞争格局.md",
    "04_上下游产业链.md",
    "05_宏观政策与技术趋势.md",
    "06_能力差距评估_v2.md",
    "07_战略建议_v2.md",
]

OUTPUT = BASE / "中集环科行业研究报告_2026_v2.pdf"

def strip_frontmatter(text: str) -> str:
    """去除YAML frontmatter"""
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3:].lstrip("\n")
    return text

def main():
    pdf = MarkdownPdf(toc_level=2)

    for fname in FILES:
        fpath = BASE / fname
        if not fpath.exists():
            print(f"WARNING: {fname} not found, skipping")
            continue

        raw = fpath.read_text(encoding="utf-8")
        content = strip_frontmatter(raw)

        # 添加章节分页
        pdf.add_section(Section(content, toc=True))
        print(f"  Added: {fname} ({len(content):,} chars)")

    pdf.meta["title"] = "中集环科行业研究报告（v2 Opus优化版）"
    pdf.meta["author"] = "中集安瑞科环科技股份有限公司"
    pdf.meta["subject"] = "ISO罐式集装箱行业研究与战略建议 (2026-2029) — v2深度版"
    pdf.meta["keywords"] = "ISO罐箱, 中集环科, 行业研究, 战略建议, Opus优化"

    pdf.save(str(OUTPUT))
    print(f"\nPDF saved to: {OUTPUT}")

if __name__ == "__main__":
    main()
