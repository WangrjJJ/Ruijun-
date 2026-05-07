# -*- coding: utf-8 -*-
"""将行业研究报告（v4 行业战略版）合并导出为 PDF
v4 关键升级：
1. 章节编号统一（一~九章）
2. 第五章名称对齐（宏观政策与技术趋势）
3. 新增第九章 1-3年战略路径（行业通用 + 中集异质性）
4. frontmatter 统一 version: 4.0
"""

import re
from pathlib import Path
from markdown_pdf import MarkdownPdf, Section

BASE = Path(__file__).parent

# v4 章节顺序：一至九章 + 两份附录
FILES = [
    "00_执行摘要.md",                                    # 第一章
    "02_行业概况与市场规模.md",                          # 第二章
    "03_竞争格局.md",                                    # 第三章
    "04_上下游产业链.md",                                # 第四章
    "05_宏观政策与技术趋势.md",                          # 第五章
    "06_材料技术与产品演进.md",                          # 第六章
    "07_加工工艺与制造技术.md",                          # 第七章
    "08_AI与组织变革.md",                                # 第八章
    "09_行业战略路径.md",                                # 第九章（v4 新增）
    # 附录
    "08_高附加值化学品细分市场与ISO罐箱增量需求研究.md", # 附录 A
    "09_罐箱产业波特五力分析.md",                        # 附录 B
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
