from src.retrieval.semantic_search import SemanticSearchTool

searcher = SemanticSearchTool()
results = searcher.search('304/45钢复合螺栓 拉伸疲劳试验 数据', top_k=3)

for idx, r in enumerate(results):
    print(f"Result {idx+1}: Page {r.page_number}")
    print(f"Content: {r.text_content}")
    print("-" * 50)
