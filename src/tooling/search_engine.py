# 渐进式工具披露引擎 (Progressive Tool Disclosure Engine)
# 单一职责：管理工具的延迟加载注册表，并提供搜索/精确选取能力，
#           使 LLM 在初始 Prompt 中只看到工具名，按需拉取完整 Schema。
# 设计参考：Claude Code `ToolSearchTool` (restored-src/src/tools/ToolSearchTool/)

import re
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field


@dataclass
class ToolMetadata:
    """每个可搜索工具的元数据描述符"""
    name: str                          # 工具的 LangChain 注册名
    description: str                   # 工具的完整 docstring/描述
    category: str                      # 所属分组：text / graph / calculation / analysis
    search_hint: str = ""              # 额外搜索线索（补充名字中没有的关键词）
    should_defer: bool = True          # 是否延迟加载（True = 初始只给名字不给 Schema）
    always_load: bool = False          # 是否永不延迟（核心工具始终暴露）


class ToolSearchEngine:
    """
    工具搜索引擎 — 借鉴 Claude Code 的 ToolSearchTool 设计。

    核心机制：
    1. 所有工具注册时携带 ToolMetadata
    2. 标记 should_defer=True 的工具初始不暴露 Schema，只告诉 LLM 工具名
    3. LLM 需要时通过 search_available_tools 主动拉取
    4. 支持两种查询：
       - "select:工具名" 精确选取
       - "关键词1 关键词2" 模糊搜索
    """

    def __init__(self):
        self._registry: Dict[str, ToolMetadata] = {}
        self._tool_callables: Dict[str, Callable] = {}

    def register(self, tool_callable: Callable, metadata: ToolMetadata):
        """注册一个工具及其元数据。

        Args:
            tool_callable: LangChain @tool 装饰的可调用对象
            metadata: 工具的搜索元数据
        """
        self._registry[metadata.name] = metadata
        self._tool_callables[metadata.name] = tool_callable

    def get_deferred_tool_names(self) -> List[str]:
        """返回所有被延迟加载的工具名列表（用于塞入初始 Prompt）。

        Returns:
            只包含名字的字符串列表
        """
        return [
            m.name for m in self._registry.values()
            if m.should_defer and not m.always_load
        ]

    def get_always_loaded_tools(self) -> List[Callable]:
        """返回始终暴露的核心工具（always_load=True 或 should_defer=False）。

        Returns:
            LangChain Tool 可调用对象列表
        """
        return [
            self._tool_callables[name]
            for name, meta in self._registry.items()
            if meta.always_load or not meta.should_defer
        ]

    def get_tool_callable(self, name: str) -> Optional[Callable]:
        """根据名字获取工具的可调用对象。

        Args:
            name: 工具注册名

        Returns:
            LangChain Tool 对象，不存在则返回 None
        """
        return self._tool_callables.get(name)

    def search(self, query: str, max_results: int = 5) -> List[Dict]:
        """搜索匹配的工具并返回其完整描述。

        支持两种查询模式：
        - "select:工具名1,工具名2" — 精确选取
        - "自然语言关键词" — 模糊搜索

        Args:
            query: 搜索查询
            max_results: 最大返回数

        Returns:
            匹配工具的元数据字典列表
        """
        # 模式 1：精确选取 "select:tool1,tool2"
        select_match = re.match(r'^select:(.+)$', query, re.IGNORECASE)
        if select_match:
            requested = [n.strip() for n in select_match.group(1).split(',') if n.strip()]
            results = []
            for name in requested:
                # 模糊匹配：不区分大小写
                matched = self._find_by_name(name)
                if matched:
                    results.append(self._to_schema_dict(matched))
            return results

        # 模式 2：关键词搜索
        return self._keyword_search(query, max_results)

    def _find_by_name(self, name: str) -> Optional[ToolMetadata]:
        """按名字查找工具（不区分大小写）。

        Args:
            name: 工具名

        Returns:
            ToolMetadata 或 None
        """
        name_lower = name.lower()
        for tool_name, meta in self._registry.items():
            if tool_name.lower() == name_lower:
                return meta
        return None

    def _keyword_search(self, query: str, max_results: int) -> List[Dict]:
        """对注册表进行关键词评分搜索。

        评分规则（借鉴 Claude Code ToolSearchTool）：
        - 工具名拆词精确匹配：+10 分
        - 工具名子串包含：+5 分
        - search_hint 匹配：+4 分
        - description 词边界匹配：+2 分
        - category 匹配：+3 分

        Args:
            query: 搜索关键词
            max_results: 最大返回数

        Returns:
            按评分降序排列的匹配结果
        """
        query_lower = query.lower().strip()
        terms = [t for t in query_lower.split() if t]

        if not terms:
            return []

        # 分离 "+" 前缀的强制要求项
        required_terms = [t[1:] for t in terms if t.startswith('+') and len(t) > 1]
        optional_terms = [t for t in terms if not t.startswith('+')]
        scoring_terms = required_terms + optional_terms if required_terms else terms

        scored = []
        for name, meta in self._registry.items():
            # 预过滤：如果有强制项，先检查是否全部命中
            if required_terms:
                name_lower = name.lower()
                desc_lower = meta.description.lower()
                hint_lower = meta.search_hint.lower()
                all_match = all(
                    t in name_lower or t in desc_lower or t in hint_lower
                    for t in required_terms
                )
                if not all_match:
                    continue

            score = self._score_tool(meta, scoring_terms)
            if score > 0:
                scored.append((meta, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [self._to_schema_dict(meta) for meta, _ in scored[:max_results]]

    def _score_tool(self, meta: ToolMetadata, terms: List[str]) -> int:
        """对单个工具计算关键词匹配分数。

        Args:
            meta: 工具元数据
            terms: 搜索词项

        Returns:
            匹配得分
        """
        score = 0
        name_parts = self._parse_tool_name(meta.name)
        desc_lower = meta.description.lower()
        hint_lower = meta.search_hint.lower()
        cat_lower = meta.category.lower()

        for term in terms:
            # 工具名拆词精确匹配
            if term in name_parts:
                score += 10
            elif any(term in part for part in name_parts):
                score += 5

            # search_hint 匹配
            if hint_lower and re.search(r'\b' + re.escape(term) + r'\b', hint_lower):
                score += 4

            # category 匹配
            if term in cat_lower:
                score += 3

            # description 词边界匹配
            if re.search(r'\b' + re.escape(term) + r'\b', desc_lower):
                score += 2

        return score

    @staticmethod
    def _parse_tool_name(name: str) -> List[str]:
        """将工具名拆解为可搜索的词项。

        处理 snake_case 和 CamelCase 两种风格。

        Args:
            name: 工具名

        Returns:
            拆解后的小写词项列表
        """
        # snake_case 拆分
        parts = name.replace('_', ' ')
        # CamelCase 拆分
        parts = re.sub(r'([a-z])([A-Z])', r'\1 \2', parts)
        return [p.lower() for p in parts.split() if p]

    def _to_schema_dict(self, meta: ToolMetadata) -> Dict:
        """将工具元数据转为 LLM 可消费的 Schema 字典。

        Args:
            meta: 工具元数据

        Returns:
            包含名称、描述、分类和参数 Schema 的字典
        """
        tool = self._tool_callables.get(meta.name)
        schema = {}
        if tool and hasattr(tool, 'args_schema') and tool.args_schema:
            try:
                schema = tool.args_schema.schema()
            except Exception:
                schema = {}

        return {
            "name": meta.name,
            "description": meta.description,
            "category": meta.category,
            "parameters": schema
        }


# === 全局单例 ===
_engine_instance: Optional[ToolSearchEngine] = None

def get_tool_search_engine() -> ToolSearchEngine:
    """获取全局 ToolSearchEngine 单例。

    Returns:
        ToolSearchEngine 实例
    """
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = ToolSearchEngine()
    return _engine_instance
