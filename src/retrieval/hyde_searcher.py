import json
from typing import List, Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from src.core.config import settings
from src.retrieval.graph_search import GraphLogicTool
from src.retrieval.semantic_search import SemanticSearchTool


class HyDESearcher:
    """
    KG-Anchored HyDE Pipeline.
    Step 1: Extract entities from the query.
    Step 2: Traverse KG for these entities to get precise context.
    Step 3: Generate a Hypothetical Document (HyDE) anchored in the KG context.
    Step 4: Use SemanticSearchTool to retrieve final chunks using the HyDE doc.
    """

    def __init__(self, fast_mode: bool = False):
        model_name = "qwen-turbo" if fast_mode else "qwen-max"
        self.llm = ChatOpenAI(
            model=model_name,
            api_key=settings.QWEN_API_KEY,
            base_url=settings.QWEN_BASE_URL,
        )
        self.json_llm = ChatOpenAI(
            model=model_name,
            api_key=settings.QWEN_API_KEY,
            base_url=settings.QWEN_BASE_URL,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        self.graph_tool = GraphLogicTool()
        self.semantic_tool = SemanticSearchTool()

    @classmethod
    def create_fast(cls) -> "HyDESearcher":
        """Factory returning a HyDESearcher configured for fast mode (qwen-turbo)."""
        return cls(fast_mode=True)

    def search(self, query: str, top_k: int = 5) -> List[Any]:
        # Step 1: Entity Extraction
        entities = self._extract_entities(query)
        print(f"[HyDESearcher] Extracted entities: {entities}")

        # Step 2: Graph Traversal
        kg_context = self._fetch_kg_context(entities)
        print(f"[HyDESearcher] KG Context length: {len(kg_context)}")

        # Step 3: Generate KG-Anchored HyDE
        hyde_doc = self._generate_hyde_doc(query, kg_context)
        print(f"[HyDESearcher] Generated HyDE doc:\n{hyde_doc[:200]}...")

        # Step 4: Semantic Search (incorporating the original query as well to prevent semantic drift)
        fused_query = f"{query}\n\n{hyde_doc}"
        return self.semantic_tool.search(fused_query, top_k=top_k)

    def _extract_entities(self, query: str) -> List[str]:
        prompt = f"""
        Extract the core metallurgy entities from the following query. 
        Return a JSON object with a key 'entities' containing a list of strings.
        Query: "{query}"
        """
        try:
            res = self.json_llm.invoke([HumanMessage(content=prompt)])
            data = json.loads(res.content)
            return data.get("entities", [])
        except Exception as e:
            print(f"[HyDESearcher] Entity extraction failed: {e}")
            return []

    def _fetch_kg_context(self, entities: List[str]) -> str:
        context_lines = []
        for entity in entities[:3]:  # Limit to 3 entities to avoid explosion
            rels = self.graph_tool.find_direct_relations(entity)
            for r in rels[:10]:  # Limit to 10 rels per entity
                mech = f", mechanism: {r['mechanism']}" if r.get("mechanism") else ""
                ctx = f", context: {r['context']}" if r.get("context") else ""
                context_lines.append(
                    f"{r['subject']} -[{r['relation']}]-> {r['object']}{mech}{ctx}"
                )

        return "\n".join(context_lines)

    def _generate_hyde_doc(self, query: str, kg_context: str) -> str:
        prompt = f"""
        You are a metallurgy expert. 
        Please generate a hypothetical document (an academic paragraph) that perfectly answers the user's query.
        Use the following Knowledge Graph context to ensure the document is factually anchored and uses the correct terminology.
        
        [KG Context]:
        {kg_context if kg_context else "No specific KG context found."}
        
        [User Query]:
        {query}
        
        Generate ONLY the hypothetical answer document, no pleasantries or meta-text.
        """
        try:
            res = self.llm.invoke([HumanMessage(content=prompt)])
            return res.content
        except Exception as e:
            print(f"[HyDESearcher] HyDE generation failed: {e}")
            return query
