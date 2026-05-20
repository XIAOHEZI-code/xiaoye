import sys
import os
import json

sys.path.append(os.path.abspath('.'))

from src.retrieval.semantic_search import SemanticSearchTool
from src.retrieval.hyde_searcher import HyDESearcher

def main():
    questions = [
        "调质处理对复合螺栓的疲劳性能有什么负面影响？",
        "304/45双金属复合螺栓是通过哪些制造工艺成型的？",
        "冷加工会导致不锈钢覆层晶界出现什么特殊结构？",
        "敏化现象是如何影响304不锈钢的耐腐蚀性的？",
        "碳化物颗粒在晶界的析出是由什么工艺或状态引起的？",
        "复合螺栓的芯材和包覆层分别是什么材料？",
        "经过热轧和拉拔之后，螺纹是通过什么工艺最终制成的？",
        "纤维状流线分布的形成机理是什么？",
        "为什么调质处理后材料的耐蚀性能会大幅度下降？",
        "箱式炉在调质处理中的作用是什么，具体的加热温度和时间是多少？"
    ]
    
    semantic_searcher = SemanticSearchTool()
    hyde_searcher = HyDESearcher()
    
    print("==================================================")
    print("      Standard ES vs KG-HyDE Retrieval Test       ")
    print("==================================================\n")
    
    for i, q in enumerate(questions, 1):
        print(f"【Q{i}】: {q}")
        
        # Standard Search
        std_results = semantic_searcher.search(q, top_k=2)
        std_docs = [f"{(res.chunk_id or res.doc_id)[:8]}... (Score: {res.score:.3f})" for res in std_results if res]
        
        # HyDE Search
        # To avoid cluttering stdout too much, we intercept prints inside HyDE if possible, 
        # or we just let it print.
        print(f"  [Running KG-HyDE...]")
        hyde_results = hyde_searcher.search(q, top_k=2)
        hyde_docs = [f"{(res.chunk_id or res.doc_id)[:8]}... (Score: {res.score:.3f})" for res in hyde_results if res]
        
        print(f"  -> [Standard ES Top 2 Chunks]: {std_docs}")
        print(f"  -> [ KG-HyDE Top 2 Chunks  ]: {hyde_docs}")
        print("-" * 50)

if __name__ == "__main__":
    main()
