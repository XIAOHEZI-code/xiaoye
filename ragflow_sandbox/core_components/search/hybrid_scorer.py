import numpy as np
from collections import defaultdict
from sklearn.metrics.pairwise import cosine_similarity

from ..nlp.term_weight import TermWeightDealer

class HybridScorer:
    """
    Mixer algorithm to combine Lexical (BM25 or Token Similarity) 
    and Vector (Dense Cosine Similarity) scores.
    """
    def __init__(self):
        self.tw = TermWeightDealer()

    def token_similarity(self, atks: list[str], btkss: list[list[str]]) -> list[float]:
        """
        Calculates lexical token similarity between query (atks) and documents (btkss).
        Weights are calculated via TermWeightDealer (TF-IDF).
        """
        def to_dict(tks):
            if isinstance(tks, str):
                tks = tks.split()
            d = defaultdict(float)
            wts = self.tw.weights(tks, preprocess=False)
            for i, (t, c) in enumerate(wts):
                d[t] += c * 0.4
                if i + 1 < len(wts):
                    _t, _c = wts[i + 1]
                    d[t + _t] += max(c, _c) * 0.6
            return d

        def similarity(qtwt, dtwt):
            s = 1e-9
            for k, v in qtwt.items():
                if k in dtwt:
                    s += v
            q = 1e-9
            for k, v in qtwt.items():
                q += v
            return s / q

        a_dict = to_dict(atks)
        return [similarity(a_dict, to_dict(b_tks)) for b_tks in btkss]

    def hybrid_similarity(self, query_vec: list[float], doc_vecs: list[list[float]], 
                          query_tokens: list[str], doc_tokens_list: list[list[str]], 
                          vector_weight: float = 0.85, token_weight: float = 0.15):
        """
        Linear combination of dense vector cosine similarity and token lexical similarity.
        """
        if not doc_vecs:
            return np.array([]), [], []

        sims = cosine_similarity([query_vec], doc_vecs)[0]
        tksims = self.token_similarity(query_tokens, doc_tokens_list)
        
        if np.sum(sims) == 0:
            return np.array(tksims), tksims, sims

        combined_scores = (np.array(sims) * vector_weight) + (np.array(tksims) * token_weight)
        return combined_scores, tksims, sims

    @staticmethod
    def reciprocal_rank_fusion(lexical_results: list[dict], vector_results: list[dict], k=60):
        """
        Combines two ranked result lists using Reciprocal Rank Fusion (RRF).
        Typically used when scores are not easily linear-combinable (e.g. raw ES BM25 + raw FAISS Cosine)
        Expected format for result: {"doc_id": "123", "score": ...}
        """
        rrf_scores = defaultdict(float)

        def add_ranks(results):
            for rank, item in enumerate(sorted(results, key=lambda x: x.get('score', 0), reverse=True)):
                doc_id = item["doc_id"]
                rrf_scores[doc_id] += 1.0 / (k + rank + 1)
                
        add_ranks(lexical_results)
        add_ranks(vector_results)

        # Sort by RRF score descending
        return sorted([{"doc_id": doc_id, "rrf_score": score} for doc_id, score in rrf_scores.items()],
                      key=lambda x: x["rrf_score"], reverse=True)

if __name__ == "__main__":
    scorer = HybridScorer()
    q_vec = [0.1, 0.2, 0.3]
    d_vecs = [[0.1, 0.2, 0.3], [0.0, 0.0, 0.9]]
    q_toks = ["马氏体", "不锈钢"]
    d_toks = [["马氏体", "不锈钢", "硬度"], ["铁素体", "防锈"]]
    
    combined, t_sim, v_sim = scorer.hybrid_similarity(q_vec, d_vecs, q_toks, d_toks)
    print("Combined Scores:", combined)
