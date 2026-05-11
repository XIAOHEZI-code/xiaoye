"""
图表提取与图注关联模块 — 吸收自 RAGFlow _extract_table_figure() 的设计思想

单一职责：
  1. 解析 Marker-PDF 输出的 Markdown，提取 ![alt](path) 图片引用
  2. 通过启发式规则将图注（"图"/"Fig"/"表"/"Table" 开头的邻近行）关联到图片
  3. 提取图片前后的文字上下文（供 Qwen-VL 增强分析用）
  4. 输出结构化的 FigureInfo 列表

与 RAGFlow 的区别：
  - RAGFlow 在 box 级别做图表提取（依赖 layout_type=figure/table）
  - 我们从 Markdown 级别提取（兼容 Marker-PDF 的输出格式）
  - RAGFlow 用欧氏距离匹配图注；我们用行级邻近匹配
"""

import re
import os
from dataclasses import dataclass, field
from typing import Optional


# 图注匹配模式（中英文，兼容 "表1" / "Fig.1" 等格式）
CAPTION_PATTERNS = [
    re.compile(r'^(图|图\s*|Figure|FIG\.?|Fig\.?)\s*[\d\.\-]+'),   # 图注
    re.compile(r'^(表|表\s*|Table|TABLE)\s*[\d\.\-]+'),           # 表注
    re.compile(r'^(Fig\.|Figure|FIG)\.?\s*\d+'),                  # 英文图注
]

# 图片引用匹配模式：![alt](path) 或 ![](path)
IMAGE_REF_PATTERN = re.compile(r'!\[(.*?)\]\((.+?)\)')


@dataclass
class FigureInfo:
    """单张图片的结构化信息，包含图注和上下文"""
    image_path: str                          # 图片文件路径
    image_filename: str = ""                 # 图片文件名（纯文件名）
    alt_text: str = ""                       # Markdown 中的 alt 文本
    caption: str = ""                        # 关联的图注文本（如 "图1: 淬火后马氏体组织"）
    caption_type: str = ""                   # "figure" / "table" / None
    context_above: str = ""                  # 图片上方的文字（前 N 段）
    context_below: str = ""                  # 图片下方的文字（后 N 段）
    page_number: int = -1                    # 页码（从元数据推断）
    line_index: int = -1                     # 在 Markdown 中的行号


def is_caption_line(line: str) -> bool:
    """判断一行是否是图注/表注行。

    启发式规则（参考 RAGFlow TableStructureRecognizer.is_caption）：
    - 以 "图"/"Fig"/"表"/"Table" 开头 + 数字编号
    - 或整行只是数字编号（辅助图注）

    Args:
        line: 待判断的文本行

    Returns:
        是否为图注行
    """
    stripped = line.strip()
    if not stripped:
        return False

    for pattern in CAPTION_PATTERNS:
        if pattern.match(stripped):
            return True

    return False


def extract_figures_from_markdown(
    md_text: str,
    image_dir: str = "",
) -> list[FigureInfo]:
    """从 Marker-PDF 输出的 Markdown 文本中提取所有图片及其图注、上下文。

    处理流程（参考 RAGFlow _extract_table_figure）：
    1. 逐行扫描 Markdown，找到 ![alt](path) 图片引用
    2. 对每个图片引用：
       a. 查找图片后面的图注行（is_caption_line）
       b. 提取图片上方的文字上下文（前 3-6 行）
       c. 提取图片下方的文字上下文（后 1-3 行）
    3. 将图片路径从相对路径转为绝对路径

    Args:
        md_text: Marker-PDF 输出的完整 Markdown 文本
        image_dir: 图片文件所在的目录（用于拼接绝对路径）

    Returns:
        FigureInfo 列表，按在文档中出现的顺序排列
    """
    lines = md_text.split('\n')
    figures = []

    for i, line in enumerate(lines):
        m = IMAGE_REF_PATTERN.search(line)
        if not m:
            continue

        alt_text = m.group(1).strip()
        img_rel_path = m.group(2).strip()

        # 拼接绝对路径
        if image_dir and not os.path.isabs(img_rel_path):
            img_path = os.path.join(image_dir, os.path.basename(img_rel_path))
        else:
            img_path = img_rel_path

        # 提取图注：从图片行往后找最近的图注行
        caption = ""
        caption_type = ""
        for j in range(i + 1, min(i + 5, len(lines))):
            if is_caption_line(lines[j]):
                caption = lines[j].strip()
                if re.match(r'^(图|Figure|Fig)', caption, re.IGNORECASE):
                    caption_type = "figure"
                elif re.match(r'^(表|Table)', caption, re.IGNORECASE):
                    caption_type = "table"
                else:
                    caption_type = "figure"  # 默认为 figure
                break
            # 如果遇到另一个图片引用或空行太多，停止搜索
            if IMAGE_REF_PATTERN.search(lines[j]):
                break
            if not lines[j].strip():
                continue

        # 如果没找到图注，尝试从图片前的行提取（某些格式图注在图片上方）
        if not caption:
            for j in range(i - 1, max(i - 3, -1), -1):
                if is_caption_line(lines[j]):
                    caption = lines[j].strip()
                    if re.match(r'^(图|Figure|Fig)', caption, re.IGNORECASE):
                        caption_type = "figure"
                    elif re.match(r'^(表|Table)', caption, re.IGNORECASE):
                        caption_type = "table"
                    break
                if lines[j].strip():
                    break

        # 提取上下文：图片前 6 行（但不包括前一个图片引用之前的内容）
        above_start = max(0, i - 6)
        # 往前回溯，跳过前一个图片引用
        for k in range(i - 1, above_start - 1, -1):
            if IMAGE_REF_PATTERN.search(lines[k]):
                above_start = k + 1
                break
        context_above = '\n'.join(
            lines[above_start:i]
        ).strip()

        # 提取上下文：图片后 3 行（跳过图注行本身）
        below_end = min(len(lines), i + 4)
        context_below_lines = []
        for k in range(i + 1, below_end):
            if is_caption_line(lines[k]):
                continue  # 跳过图注行
            context_below_lines.append(lines[k])
        context_below = '\n'.join(context_below_lines).strip()

        figure = FigureInfo(
            image_path=img_path,
            image_filename=os.path.basename(img_path),
            alt_text=alt_text,
            caption=caption,
            caption_type=caption_type,
            context_above=context_above,
            context_below=context_below,
            line_index=i,
        )
        figures.append(figure)

    return figures


def build_vision_prompt(
    figure: FigureInfo,
    base_prompt: str = "",
) -> str:
    """构建用于 Qwen-VL 的增强 Prompt。

    参考 RAGFlow vision_llm_figure_describe_prompt_with_context：
    将图注和上下文注入到 Prompt 中，辅助 VL 模型理解图片的领域角色。

    Args:
        figure: 图片信息
        base_prompt: 基础 Prompt 模板（如冶金分析的 system prompt）

    Returns:
        增强后的完整 Prompt
    """
    parts = []
    if base_prompt:
        parts.append(base_prompt)

    if figure.caption:
        parts.append(f"\n【图片图注】\n{figure.caption}")

    if figure.context_above:
        # 取上文最后 200 字符作为参考（避免上下文过长）
        above = figure.context_above[-200:]
        parts.append(f"\n【上文参考】\n{above}")

    if figure.context_below:
        below = figure.context_below[:200]
        parts.append(f"\n【下文参考】\n{below}")

    return '\n'.join(parts)


def is_figure_item(figure: FigureInfo) -> bool:
    """判断图片是否是"图表"（而非装饰性图片）。

    启发式规则：
    - 有图注 → 大概率是图表
    - alt_text 包含关键词 → 可能是图表
    - 无图注 + 无上下文 → 可能是装饰图

    Args:
        figure: 图片信息

    Returns:
        是否为需要分析的有意义图表
    """
    if figure.caption:
        return True
    if figure.alt_text and any(kw in figure.alt_text.lower()
                               for kw in ['图', '表', 'fig', 'chart', 'graph', 'photo', 'sem', 'tem']):
        return True
    return False
