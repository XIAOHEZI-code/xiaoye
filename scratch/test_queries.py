from src.retrieval.semantic_search import SemanticSearchTool

searcher = SemanticSearchTool()

queries = [
    '304/45钢复合螺栓 拉伸试验 数据',
    '304/45钢复合螺栓 抗拉强度',
    '304/45钢复合螺栓 578 593',
    '304/45钢复合螺栓 拉伸疲劳'
]

for q in queries:
    print(f"=== Query: '{q}' ===")
    results = searcher.search(q, top_k=5)
    for idx, r in enumerate(results):
        text = r.text_content
        contains_578 = "578" in text
        print(f"  Result {idx+1}: Page {r.page_number} | Contains 578: {contains_578}")
        if contains_578:
            print(f"    Text snippet: {text[:200]}")
    print("-" * 50)
