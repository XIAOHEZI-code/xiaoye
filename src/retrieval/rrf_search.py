from typing import List, Dict, Any

class ReciprocalRankFusionTool:
    """
    Implements Reciprocal Rank Fusion (RRF) to merge results from multiple search modalities.
    Typically used to fuse:
      1. BM25 Text Search
      2. Dense Vector Semantic Search
      3. Graph Traversal Results
      4. Image Metadata Search
    """
    def __init__(self, k_constant: int = 60):
        # k_constant is typically set to 60 as per standard RRF paper implementations
        self.k = k_constant

    def fuse(self, all_ranked_lists: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        Takes a list of search result lists.
        Each element in an inner list is a dictionary which MUST contain:
           - 'doc_id' (to merge identical chunks/documents)
           - 'content' or some representation
        
        Returns a single fused list sorted by RRF score.
        """
        rrf_scores: Dict[str, float] = {}
        merged_docs: Dict[str, Dict[str, Any]] = {}

        for rank_list in all_ranked_lists:
            # We assume the lists are already sorted descending by their specific subsystem's score
            for rank, item in enumerate(rank_list):
                # We need a unique identifier. Depending on granularity, chunk_id or doc_id.
                uid = item.get("chunk_id", item.get("doc_id", "unknown"))
                if not uid or uid == "unknown":
                    continue

                if uid not in rrf_scores:
                    rrf_scores[uid] = 0.0
                    merged_docs[uid] = item
                
                # RRF Formula: 1 / (k + rank+1)  [rank is 0-indexed]
                rrf_scores[uid] += 1.0 / (self.k + rank + 1)

        # Sort the dictionary based on the RRF score descending
        sorted_results = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

        final_list = []
        for uid, rrf_score in sorted_results:
            doc_item = merged_docs[uid].copy()
            doc_item["rrf_score"] = rrf_score
            final_list.append(doc_item)

        return final_list
