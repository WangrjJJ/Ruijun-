# -*- coding: utf-8 -*-
"""将行业研究报告（v3行业战略版）合并导出为PDF
新结构：宏观中观视角，聚焦市场/材料/工艺/AI四大技术维度"""

import re
from pathlib import Path
from markdown_pdf import MarkdownPdf, Section

BASE = Path(__file__).parent

# v3 章节顺序：行业外部视角，从宏观到技术深度
FILES = [
    "00_执行摘要.md",
    "02_行业概况与市场规模.md",
    "03_竞争格局.md",
    "04_上下游产业链.md",
    "05_宏观政策与技术趋势.md",
    "06_材料技术与产品演进.md",
    "07_加工工艺与制造技术.md",
    "08_AI与组织变革.md",
    # 附录
    "08_高附加值化学品细分市场与ISO罐箱增量需求研究.md",
    "09_罐箱产业波特五力分析.md",
]

OUTPUT = BASE / "中集环科行业研究报告_2026_v4.pdf"

def strip_frontmatter(text):
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3:].lstrip("\n")
    return text

def main():
    pdf = MarkdownPdf()
    for fname in FILES:
        fpath = BASE / fname
        if not fpath.exists():
            print(f"  [SKIP] 文件不存在: {fname}")
            continue
        text = fpath.read_text(encoding="utf-8")
        text = strip_frontmatter(text)
        pdf.add_section(Section(text))
        print(f"  Added: {fname} ({len(text):,} chars)")

    pdf.save(OUTPUT)
    print(f"\nPDF saved to: {OUTPUT}")

if __name__ == "__main__":
    main()
