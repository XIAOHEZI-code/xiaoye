import json
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from src.core.config import settings

# 冶金图表分类体系 (Based on user input)
METALLURGY_CATEGORIES = [
    "基础热力学与物理化学图表", # e.g. 相图, 埃林汉姆图, 溶解度曲线
    "传输过程与数值模拟图",   # e.g. 流场/温度场/浓度场, 网格划分图
    "宏观过程控制与时序监测图", # e.g. 过程参数波动图, PFD/P&ID, 质量控制图
    "微观组织与多模态表征图谱"  # e.g. OM/SEM/TEM, 面分布/衍射图谱(XRD/EBSD)
]

class ImageEvaluationResult(BaseModel):
    category: str = Field(description=f"Must be one of: {', '.join(METALLURGY_CATEGORIES)}")
    sub_category: str = Field(description="更具体的子分类，例如：相图、SEM、过程参数折线图等")
    description: str = Field(description="图表说明了什么冶金现象或工艺参数。提供不少于100字的详尽描述。")
    key_metrics: list[str] = Field(description="提取出的关键数值或材料型号列表", default_factory=list)

def analyze_metallurgy_image(image_base64: str) -> ImageEvaluationResult:
    """
    Calls QWEN-VL-Max via OpenAI compatible generic interface to evaluate the metallurgy image.
    """
    chat = ChatOpenAI(
        model="qwen-vl-max",
        api_key=settings.QWEN_API_KEY,
        base_url=settings.QWEN_BASE_URL,
        max_tokens=1000,
    )
    
    prompt_text = f"""
    你是一个极其资深的冶金领域的材料专家。请分析这张图片/图表，然后严格按照 JSON 格式输出分析结果。
    请确保 'category' 字段严格属于以下枚举值之一：
    {METALLURGY_CATEGORIES}
    
    'sub_category' 描述具体的细分类型（如：金相图，XRD图谱，连铸温度场等）。
    'description' 进行 > 100字的详细领域解析。
    'key_metrics' 提取关键的数值、型号、工艺参数等。
    """

    msg = HumanMessage(
        content=[
            {"type": "text", "text": prompt_text},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
        ]
    )
    
    # We use Langchain's structured output capability if the model supports it, 
    # but QWEN VL over API may just return JSON blocks. 
    # We enforce JSON mode generally:
    response = chat.invoke([msg])
    
    # Simple parse assuming the model is instructed to return JSON
    # In production, we'd use robust json parsing logic or LC's JsonOutputParser
    try:
        content = response.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        data = json.loads(content)
        return ImageEvaluationResult(**data)
    except Exception as e:
        print(f"Failed to parse QWENV3 response: {e}")
        return ImageEvaluationResult(
            category="未分类", 
            sub_category="未知", 
            description=response.content[:200], # fallback
            key_metrics=[]
        )
