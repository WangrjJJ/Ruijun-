# -*- coding: utf-8 -*-
"""将行业研究报告（v5 三轨战略版）合并导出为 PDF
v5 关键升级：
1. 战略框架从"四个杠杆论"修正为"守份额+改毛利+相关多元化"三轨并行论
2. 第八章数字化战略：从"行业 IoT 平台"修正为"OBD2 数据基础设施"
3. 第二章新增"周期 vs 结构"辨析，识别需求中枢结构性下移
4. 第六章材料战略：从"6 种材料全面布局"收敛为"PFA+铝合金两点突破"
5. 第九章战略路径完全重写：3+2+1 相关多元化组合
6. 执行摘要重写：纳入第一性诊断和修正战略
"""

import re
from pathlib import Path
from markdown_pdf import MarkdownPdf, Section

BASE = Path(__file__).parent

# v5 章节顺序：一至九章 + 两份附录
FILES = [
    "00_执行摘要.md",                                    # 第一章（v5 重写）
    "02_行业概况与市场规模.md",                          # 第二章（v5 微调：周期 vs 结构）
    "03_竞争格局.md",                                    # 第三章（v5 沿用）
    "04_上下游产业链.md",                                # 第四章（v5 沿用）
    "05_宏观政策与技术趋势.md",                          # 第五章（v5 沿用）
    "06_材料技术与产品演进.md",                          # 第六章（v5 微调：两点突破）
    "07_加工工艺与制造技术.md",                          # 第七章（v5 沿用）
    "08_AI与组织变革.md",                                # 第八章（v5 重大修订：OBD2 定位）
    "09_行业战略路径.md",                                # 第九章（v5 完全重写：三轨战略）
    # 附录
    "08_高附加值化学品细分市场与ISO罐箱增量需求研究.md", # 附录 A
    "09_罐箱产业波特五力分析.md",                        # 附录 B
]

OUTPUT = BASE / "中集环科行业研究报告_2026_v5.pdf"

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
