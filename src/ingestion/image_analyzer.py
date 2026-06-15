"""
冶金图像分析模块 — 两阶段 VLM 管线（V3）

V3 增强（2026-06-15）：
  - 新增两阶段 VLM 分析管线：Stage 1 快速预分类 + Stage 2 深度分析
  - Stage 1: qwen3.6-flash 做图像类型判断和关注点生成（"让大模型给大模型写测试"）
  - Stage 2: qwen3.7-plus 按预分析指引做详细领域分析
  - 替代 storage_router 中的关键词分类逻辑，实现 VLM 驱动的图像路由

V2 增强（2026-04-26）：
  - 新增 analyze_metallurgy_image_with_context(): 接收图注+上下文，提升 VL 分析质量
  - 借鉴 RAGFlow VisionFigureParser 的双 Prompt 策略
  - 新增结构描述模式，区分"可枚举数据"和"视觉描述"
"""

import json
import logging
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from src.core.config import settings
from typing import Optional

logger = logging.getLogger("xiaoye.ingestion.image_analyzer")

# 冶金图表分类体系 (Based on user input)
METALLURGY_CATEGORIES = [
    "基础热力学与物理化学图表",  # e.g. 相图, 埃林汉姆图, 溶解度曲线
    "传输过程与数值模拟图",  # e.g. 流场/温度场/浓度场, 网格划分图
    "宏观过程控制与时序监测图",  # e.g. 过程参数波动图, PFD/P&ID, 质量控制图
    "微观组织与多模态表征图谱",  # e.g. OM/SEM/TEM, 面分布/衍射图谱(XRD/EBSD)
]


class ImageEvaluationResult(BaseModel):
    """图像分析的结构化输出"""

    category: str = Field(
        description=f"Must be one of: {', '.join(METALLURGY_CATEGORIES)}"
    )
    sub_category: str = Field(
        description="更具体的子分类，例如：相图、SEM、过程参数折线图等"
    )
    description: str = Field(
        description="图表说明了什么冶金现象或工艺参数。提供不少于100字的详尽描述。"
    )
    key_metrics: list[str] = Field(
        description="提取出的关键数值或材料型号列表", default_factory=list
    )


class ImagePreAnalysis(BaseModel):
    """Stage 1 输出：图像预分类——让大模型决定图像类型和关注重点"""

    image_type: str = Field(
        description="图像类型，如：原电池示意图、SEM图像、TEM图像、金相组织图、工艺曲线、相图、设备结构图等"
    )
    domain_category: str = Field(
        description="领域分类，如：电化学、冶金组织、热力学、力学性能、工艺控制、材料表征、设备结构等"
    )
    focus_points: list[str] = Field(
        description="3-5个具体关注点，提示深度分析应该看什么。越具体越好，如：'观察阳极表面腐蚀形貌'而非'观察形貌'"
    )
    suggested_questions: list[str] = Field(
        description="2-3个建议深度分析回答的专业问题"
    )


# =============================================================
#  共享工具函数
# =============================================================


def _parse_vlm_json(response_content: str, additional_content: str = "") -> dict:
    """鲁棒的 VLM JSON 解析，处理多种 VLM 响应格式（含 Qwen3.x 思考模式）。

    支持的格式：
    - 纯 JSON: {"key": "value"}
    - Qwen3.x XML 包裹: <thinking>...</thinking><answer>{"key": "value"}</answer>
    - ```json 包裹: ```json\n{"key": "value"}\n```
    - ``` 包裹: ```\n{"key": "value"}\n```
    - 文本+JSON: 这是一个图表。{"key": "value"}
    - JSON+文本: {"key": "value"} 以上是分析结果。

    Args:
        response_content: response.content 文本（可能为空字符串）
        additional_content: 额外内容，如 Qwen3.x 的 reasoning_content
    """
    if not response_content and not additional_content:
        raise ValueError("Empty VLM response, cannot parse JSON")

    # Combine both content sources
    combined = (response_content or "") + (additional_content or "")
    content = combined.strip()

    if not content:
        raise ValueError("Empty combined VLM content, cannot parse JSON")

    # 1. Extract from Qwen3.x XML tags: <answer>, <response>, <output>, <json>
    for tag in ("answer", "response", "output", "json"):
        if f"<{tag}>" in content and f"</{tag}>" in content:
            content = content.split(f"<{tag}>")[1].split(f"</{tag}>")[0].strip()
            break

    # 2. Extract from ```json markers
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()

    # 3. Try direct parse first (fast path for clean JSON)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 4. Extract JSON object from surrounding text (find first { to last })
    brace_start = content.find('{')
    brace_end = content.rfind('}')
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        json_candidate = content[brace_start:brace_end + 1]
        try:
            return json.loads(json_candidate)
        except json.JSONDecodeError:
            pass

    # 5. Last resort with better error context
    raise ValueError(
        f"Cannot parse JSON from VLM response. "
        f"Content preview (first 300 chars): {content[:300]}"
    )


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
    from src.core.config import settings as _settings
    chat = ChatOpenAI(
        model=_settings.VLM_MODEL,
        api_key=_settings.QWEN_API_KEY,
        base_url=_settings.QWEN_BASE_URL,
        max_tokens=1000,
        model_kwargs={"extra_body": {"enable_thinking": False}},
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
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
            },
        ]
    )

    response = chat.invoke([msg])

    # Extract reasoning from Qwen3.x thinking mode (stored in additional_kwargs)
    reasoning = ""
    if hasattr(response, 'additional_kwargs') and response.additional_kwargs:
        reasoning = response.additional_kwargs.get('reasoning_content', '')

    # 鲁棒的 JSON 解析（使用共享解析器）
    try:
        data = _parse_vlm_json(response.content, additional_content=reasoning)
        return ImageEvaluationResult(**data)
    except Exception as e:
        logger.error(
            f"Failed to parse VLM response: {e}. "
            f"Raw content preview: {str(response.content)[:200]}"
        )
        return ImageEvaluationResult(
            category="未分类",
            sub_category="未知",
            description=response.content[:200] if response.content else "VLM returned no content",
            key_metrics=[],
        )


def _build_context_block(
    caption: Optional[str] = None,
    context_above: Optional[str] = None,
    context_below: Optional[str] = None,
) -> str:
    """构建上下文块，供深度分析 Prompt 使用。"""
    parts = []
    if caption:
        parts.append(f"【图片图注】\n{caption}")
    if context_above:
        parts.append(f"【上文参考】\n{context_above[-300:]}")
    if context_below:
        parts.append(f"【下文参考】\n{context_below[:300]}")
    if not parts:
        return ""
    return "\n\n---\n以下信息来自论文上下文，请结合分析：\n" + "\n\n".join(parts) + "\n---\n"


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
    context_block = _build_context_block(caption, context_above, context_below)

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


# =============================================================
#  V3 两阶段 VLM 管线 — "让大模型给大模型写测试"
# =============================================================


def _build_pre_analysis_prompt() -> str:
    """构建 Stage 1 预分析 Prompt — 快速分类 + 关注点生成。

    设计理念：让大模型代替人做图像路由判断。
    不要求详细分析，只要求输出结构化的分类和关注点。
    """
    return """
你是一个冶金图像预分析专家。请快速判断这张图片的类型，并指出需要重点关注哪些方面。

【重要】不要做详细分析。你只需要：
1. 判断图像类型
2. 指出应该关注什么（为后续深度分析提供指引）

请严格按照以下 JSON 格式输出：
{
  "image_type": "图像类型（如：原电池示意图、SEM图像、金相组织图、工艺曲线、XRD图谱、相图、设备结构图等）",
  "domain_category": "领域分类（电化学、冶金组织、热力学、力学性能、工艺控制、材料表征、设备结构等）",
  "focus_points": ["具体关注点1", "具体关注点2", ...]（3-5个要点，越具体越好，避免笼统描述。示例：应为'观察马氏体针的长度和分布密度'，而非'观察组织形貌'）",
  "suggested_questions": ["建议深度分析回答的问题1", "问题2", ...]（2-3个专业领域问题）
}
""".strip()


def pre_analyze_image(
    image_base64: str,
    caption: Optional[str] = None,
) -> ImagePreAnalysis:
    """Stage 1: 快速图像预分类 — 用便宜模型判断图像类型和关注重点。

    这是管线的第一步。输出用于：
    - 指导 Stage 2 深度分析
    - 图像分类入库（替代 storage_router 中的关键词匹配）
    - 知识库检索增强

    Args:
        image_base64: 图片的 Base64 编码（JPEG/PNG）
        caption: 可选的图注文本

    Returns:
        结构化的预分析结果（image_type, domain_category, focus_points, suggested_questions）
    """
    from src.core.config import settings as _settings

    chat = ChatOpenAI(
        model=_settings.VLM_PRE_ANALYZER_MODEL,
        api_key=_settings.QWEN_API_KEY,
        base_url=_settings.QWEN_BASE_URL,
        max_tokens=600,
        model_kwargs={"extra_body": {"enable_thinking": False}},
    )

    prompt_text = _build_pre_analysis_prompt()
    if caption:
        prompt_text = prompt_text + f"\n\n【图注参考】\n{caption}"

    msg = HumanMessage(
        content=[
            {"type": "text", "text": prompt_text},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
            },
        ]
    )

    response = chat.invoke([msg])

    # Extract reasoning from Qwen3.x thinking mode (stored in additional_kwargs)
    reasoning = ""
    if hasattr(response, 'additional_kwargs') and response.additional_kwargs:
        reasoning = response.additional_kwargs.get('reasoning_content', '')

    try:
        data = _parse_vlm_json(response.content, additional_content=reasoning)
        return ImagePreAnalysis(**data)
    except Exception as e:
        logger.error(
            f"Failed to parse pre-analysis response: {e}. "
            f"Raw content preview: {str(response.content)[:200]}"
        )
        # Fallback: 返回默认预分析，不阻断管线
        return ImagePreAnalysis(
            image_type="未知图像",
            domain_category="未分类",
            focus_points=["图像内容分析"],
            suggested_questions=["这张图片表达了什么信息？"],
        )


_PROMPT_INJECTION_CUES = [
    "ignore", "忽略", "override", "覆盖", "system", "系统",
    "forget", "忘记", "disregard", "无视",
    "you are", "你是", "new instruction", "新指令",
]


def _sanitize_pre_analysis(pre: ImagePreAnalysis) -> ImagePreAnalysis:
    """Sanitize Stage 1 output to prevent prompt injection into Stage 2.
    
    Filters out focus_points and suggested_questions that contain 
    instruction-like patterns. Returns a clean copy.
    """
    safe_focus = [
        fp for fp in pre.focus_points
        if not any(cue in fp.lower() for cue in _PROMPT_INJECTION_CUES)
    ]
    safe_questions = [
        q for q in pre.suggested_questions
        if not any(cue in q.lower() for cue in _PROMPT_INJECTION_CUES)
    ]
    # 如果所有内容都被过滤，保留一个安全的默认项
    if not safe_focus:
        safe_focus = ["根据图像内容进行领域分析"]
    if not safe_questions:
        safe_questions = ["这张图片表达了什么信息？"]
    
    return ImagePreAnalysis(
        image_type=pre.image_type,
        domain_category=pre.domain_category,
        focus_points=safe_focus,
        suggested_questions=safe_questions,
    )


def analyze_with_focus(
    image_base64: str,
    pre_analysis: ImagePreAnalysis,
    caption: Optional[str] = None,
    context_above: Optional[str] = None,
    context_below: Optional[str] = None,
) -> ImageEvaluationResult:
    """Stage 2: 深度分析 — 按预分析指引进行详细的冶金图像分析。

    管线的第二步。使用更强的模型，在 Stage 1 关注点指导下做深度分析。

    Args:
        image_base64: 图片的 Base64 编码
        pre_analysis: Stage 1 的预分析结果（image_type, focus_points, suggested_questions）
        caption: 可选的图注文本
        context_above: 图片上方的文字上下文
        context_below: 图片下方的文字上下文

    Returns:
        结构化的图像评估结果（category, sub_category, description, key_metrics）
    """
    from src.core.config import settings as _settings

    chat = ChatOpenAI(
        model=_settings.VLM_DEEP_ANALYZER_MODEL,
        api_key=_settings.QWEN_API_KEY,
        base_url=_settings.QWEN_BASE_URL,
        max_tokens=1500,
        model_kwargs={"extra_body": {"enable_thinking": False}},
    )

    # Sanitize pre-analysis to prevent prompt injection
    pre_analysis = _sanitize_pre_analysis(pre_analysis)

    # 构建带预分析指引的深度分析 Prompt
    focus_list = "\n".join(
        f"  {i+1}. {fp}" for i, fp in enumerate(pre_analysis.focus_points)
    )
    questions_list = "\n".join(
        f"  {i+1}. {q}" for i, q in enumerate(pre_analysis.suggested_questions)
    )

    # 上下文部分
    context_block = _build_context_block(caption, context_above, context_below)

    full_prompt = f"""
你是一个极其资深的冶金材料专家。请根据以下预分析指引，深度分析这张图片/图表。

【预分析指引 — 由快速 VLM 生成】
- 图片类型：{pre_analysis.image_type}
- 领域分类：{pre_analysis.domain_category}
- 重点关注：
{focus_list}
- 建议回答的问题：
{questions_list}

【分析决策规则】
- 如果图片包含可枚举数据单元（表格的行/列、柱状图的条、折线图的数据点、饼图扇区等）
  → 优先提取结构化数据，输出 Data Points
- 如果不含可枚举数据（如金相照片、SEM/TEM 图像、设备照片）
  → 按空间顺序描述视觉元素，转录所有可见文本
- 请特别关注预分析指引中指出的具体要点

{context_block}

请严格按照 JSON 格式输出：
  'category': 严格属于以下枚举值之一：{METALLURGY_CATEGORIES}
  'sub_category': 更具体的细分类型（如：金相图、XRD图谱、连铸温度场、柱状图、折线图）
  'description': 不少于 100 字的详细领域分析。如有可枚举数据，列出关键数值和趋势。务必回答预分析指引中的建议问题。
  'key_metrics': 提取的关键数值、材料型号、工艺参数列表（数组格式）
""".strip()

    msg = HumanMessage(
        content=[
            {"type": "text", "text": full_prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
            },
        ]
    )

    response = chat.invoke([msg])

    # Extract reasoning from Qwen3.x thinking mode (stored in additional_kwargs)
    reasoning = ""
    if hasattr(response, 'additional_kwargs') and response.additional_kwargs:
        reasoning = response.additional_kwargs.get('reasoning_content', '')

    try:
        data = _parse_vlm_json(response.content, additional_content=reasoning)
        return ImageEvaluationResult(**data)
    except Exception as e:
        logger.error(
            f"Failed to parse deep analysis response: {e}. "
            f"Raw content preview: {str(response.content)[:200]}"
        )
        return ImageEvaluationResult(
            category="未分类",
            sub_category="未知",
            description=response.content[:200] if response.content else "VLM returned no content",
            key_metrics=[],
        )


def two_stage_analyze(
    image_base64: str,
    caption: Optional[str] = None,
    context_above: Optional[str] = None,
    context_below: Optional[str] = None,
) -> tuple[ImagePreAnalysis, ImageEvaluationResult]:
    """两阶段 VLM 图像分析管线：预分类 → 深度分析。

    Stage 1: qwen3.6-flash 快速判断图像类型和关注重点
    Stage 2: qwen3.7-plus 按预分析指引做深度领域分析

    这是推荐的主入口。替代旧的 analyze_metallurgy_image()。

    Args:
        image_base64: 图片的 Base64 编码
        caption: 可选的图注文本
        context_above: 图片上方的文字上下文
        context_below: 图片下方的文字上下文

    Returns:
        (pre_analysis, deep_result) 元组
        - pre_analysis: ImagePreAnalysis（预分类结果，可用于检索增强）
        - deep_result: ImageEvaluationResult（深度分析结果，与传统接口兼容）
    """
    from src.core.config import settings as _settings

    logger.info(
        "Starting two-stage VLM analysis: "
        f"Stage1={_settings.VLM_PRE_ANALYZER_MODEL}, "
        f"Stage2={_settings.VLM_DEEP_ANALYZER_MODEL}"
    )

    # Stage 1: 快速预分类
    pre = pre_analyze_image(image_base64, caption)
    logger.info(
        "Stage 1 complete: type=%s, domain=%s, focus_points=%d",
        pre.image_type, pre.domain_category, len(pre.focus_points),
    )

    # 检测 Stage 1 是否回退到默认值
    if pre.image_type == "未知图像" and pre.domain_category == "未分类":
        logger.warning(
            "Stage 1 fell back to defaults (VLM parse failed); "
            "skipping Stage 2 to avoid wasting tokens"
        )
        fallback_result = ImageEvaluationResult(
            category="未分类",
            sub_category="未知",
            description=f"预分析失败，无法进行深度分析。图片可访问但未识别类型。",
            key_metrics=[],
        )
        return pre, fallback_result

    # Stage 2: 指引深度分析
    result = analyze_with_focus(image_base64, pre, caption, context_above, context_below)
    logger.info(
        "Stage 2 complete: category=%s, sub_category=%s, metrics=%d",
        result.category, result.sub_category, len(result.key_metrics),
    )

    return pre, result
