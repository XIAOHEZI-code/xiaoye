import sys
import os
import asyncio

sys.path.append(os.path.abspath("."))
from src.retrieval.hyde_searcher import HyDESearcher
from src.tooling.definitions import semantic_searcher

async def main():
    hyde = HyDESearcher()
    
    queries = [
        "影响转炉终点碳含量的关键因素",
        "稀土元素在轴承钢中的作用机理",
        "连铸结晶器漏钢的主要原因"
    ]
    
    for i, q in enumerate(queries):
        print(f"\n{'='*50}")
        print(f"Test {i+1}: {q}")
        print(f"{'='*50}")
        
        print("\n--- [NO HyDE] Semantic Search ---")
        try:
            res_normal = semantic_searcher.search(q, top_k=3)
            print(str(res_normal)[:500] + "...")
        except Exception as e:
            print(f"Error: {e}")
            
        print("\n--- [WITH HyDE] HyDE Search ---")
        try:
            res_hyde = hyde.search(q, top_k=3)
            print(str(res_hyde)[:500] + "...")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
