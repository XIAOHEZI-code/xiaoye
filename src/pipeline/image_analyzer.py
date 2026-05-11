"""
冶金图像分析模块 — 支持上下文感知增强分析

V2 增强（2026-04-26）：
  - 新增 analyze_metallurgy_image_with_context(): 接收图注+上下文，提升 VL 分析质量
  - 借鉴 RAGFlow VisionFigureParser 的双 Prompt 策略
  - 新增结构描述模式，区分"可枚举数据"和"视觉描述"
"""

import json
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from src.core.config import settings
from typing import Optional

# 冶金图表分类体系 (Based on user input)
METALLURGY_CATEGORIES = [
    "基础热力学与物理化学图表", # e.g. 相图, 埃林汉姆图, 溶解度曲线
    "传输过程与数值模拟图",   # e.g. 流场/温度场/浓度场, 网格划分图
    "宏观过程控制与时序监测图", # e.g. 过程参数波动图, PFD/P&ID, 质量控制图
    "微观组织与多模态表征图谱"  # e.g. OM/SEM/TEM, 面分布/衍射图谱(XRD/EBSD)
]


class ImageEvaluationResult(BaseModel):
    """图像分析的结构化输出"""
    category: str = Field(description=f"Must be one of: {', '.join(METALLURGY_CATEGORIES)}")
    sub_category: str = Field(description="更具体的子分类，例如：相图、SEM、过程参数折线图等")
    description: str = Field(description="图表说明了什么冶金现象或工艺参数。提供不少于100字的详尽描述。")
    key_metrics: list[str] = Field(description="提取出的关键数值或材料型号列表", default_factory=list)


# =============================================================
#  基础分析（向后兼容）
# =============================================================

def analyze_metallurgy_image(image_base64: str) -> ImageEvaluationResult:
    """
    [旧接口 - 向后兼容] 基础的冶金图像分析，不使用上下文。

    Args:
        image_base64: 图片的 Base64 编码（JPEG/PNG）

    Returns:
        结构化的图像分析结果
    """
    return analyze_metallurgy_image_with_context(
        image_base64=image_base64,
        caption=None,
        context_above=None,
        context_below=None,
    )


# =============================================================
#  上下文感知分析（新接口） - 参考 RAGFlow VisionFigureParser
# =============================================================

def analyze_metallurgy_image_with_context(
    image_base64: str,
    caption: Optional[str] = None,
    context_above: Optional[str] = None,
    context_below: Optional[str] = None,
) -> ImageEvaluationResult:
    """
    上下文感知的冶金图像分析。

    参考 RAGFlow vision_llm_figure_describe_prompt_with_context：
    - 传入图注（caption）让 VL 模型知道图片的标题和角色
    - 传入上下文（context_above/context_below）辅助消歧
    - 区分两种分析模式：结构化数据 vs 视觉描述

    Args:
        image_base64: 图片的 Base64 编码
        caption: 图注文本（如 "图1: 淬火后马氏体组织"）
        context_above: 图片上方的文字上下文
        context_below: 图片下方的文字上下文

    Returns:
        结构化的图像分析结果
    """
    chat = ChatOpenAI(
        model="qwen3-vl-plus",
        api_key=settings.QWEN_API_KEY,
        base_url=settings.QWEN_BASE_URL,
        max_tokens=1000,
    )

    # 构建增强 Prompt（参考 RAGFlow 双模式设计）
    prompt_text = _build_context_aware_prompt(
        caption=caption,
        context_above=context_above,
        context_below=context_below,
    )

    msg = HumanMessage(
        content=[
            {"type": "text", "text": prompt_text},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
        ]
    )

    response = chat.invoke([msg])

    # 鲁棒的 JSON 解析
    try:
        content = response.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        data = json.loads(content)
        return ImageEvaluationResult(**data)
    except Exception as e:
        print(f"[image_analyzer] Failed to parse QWENV3 response: {e}")
        return ImageEvaluationResult(
            category="未分类",
            sub_category="未知",
            description=response.content[:200],
            key_metrics=[]
        )


def _build_context_aware_prompt(
    caption: Optional[str] = None,
    context_above: Optional[str] = None,
    context_below: Optional[str] = None,
) -> str:
    """构建带上下文的增强 Prompt。

    设计参考 RAGFlow vision_llm_figure_describe_prompt_with_context：
    - 如果图片包含可枚举数据（表格/柱状图/折线图）→ 结构化输出
    - 否则 → 按空间顺序描述
    - 上下文仅用于消歧，不引入新信息

    Returns:
        完整的 Prompt 文本
    """
    # 上下文部分
    context_parts = []
    if caption:
        context_parts.append(f"【图片图注】\n{caption}")
    if context_above:
        # 上文取最后 300 字符，避免过长
        context_parts.append(f"【上文参考】\n{context_above[-300:]}")
    if context_below:
        context_parts.append(f"【下文参考】\n{context_below[:300]}")

    context_section = "\n\n".join(context_parts)
    context_block = f"\n\n---\n以下信息来自论文上下文，请结合分析：\n{context_section}\n---\n" if context_parts else ""

    full_prompt = f"""
你是一个极其资深的冶金领域的材料专家。请分析这张图片/图表。

【决策规则】
- 如果图片包含可枚举数据单元（表格的行/列、柱状图的条、折线图的数据点、饼图扇区等）
  → 优先提取结构化数据，输出 Data Points
- 如果不含可枚举数据（如金相照片、SEM/TEM 图像、设备照片）
  → 按空间顺序描述视觉元素，转录所有可见文本

{context_block}

请严格按照 JSON 格式输出：
  'category': 严格属于以下枚举值之一：{METALLURGY_CATEGORIES}
  'sub_category': 更具体的细分类型（如：金相图、XRD图谱、连铸温度场、柱状图、折线图）
  'description': 不少于 100 字的详细领域分析。如有数据，列出关键数值和趋势。
  'key_metrics': 提取的关键数值、材料型号、工艺参数列表（数组格式）
    """
    return full_prompt.strip()
