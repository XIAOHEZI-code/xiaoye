import re
import json

from . import rag_tokenizer
from .term_weight import TermWeightDealer
from .synonym import SynonymDealer


class QueryBuilder:
    """
    Translates natural language questions into Elasticsearch weighted queries (DSL)
    using Token weights (TF-IDF) and Synonym Expansion.
    """

    def __init__(self):
        self.tw = TermWeightDealer()
        self.syn = SynonymDealer()
        # Default fields to search in ES
        self.query_fields = ["content^2"]

    def sub_special_char(self, line):
        return re.sub(
            r"[ \t]+",
            " ",
            re.sub(r"[ :|\r\n\t,，。？?/`!！&^%%()\[\]{}<>]+", " ", line),
        ).strip()

    def build_es_query(self, txt, min_match=0.6):
        """
        Parses `txt`, attaches weights, adds synonyms, and returns
        a formatted boolean string or ES DSL dictionary.
        Returns: (query_string, list_of_keywords)
        """
        txt = self.sub_special_char(
            rag_tokenizer.tradi2simp(rag_tokenizer.strQ2B(txt.lower()))
        )
        keywords = []

        # 1. Split text into segments
        segments = self.tw.split(txt)[:256]

        query_parts = []

        for tt in segments:
            if not tt:
                continue
            keywords.append(tt)

            # 2. Get weights for sub-tokens
            twts = self.tw.weights([tt])
            syns = self.syn.lookup(tt)
            if syns and len(keywords) < 32:
                keywords.extend(syns)

            tms = []
            # 3. Build query part with weights and synonyms
            for tk, w in sorted(twts, key=lambda x: x[1] * -1):
                tk_clean = self.sub_special_char(tk)

                # fine-grained tokenization (e.g. 1cr18ni9ti -> 1 cr 18 ni 9 ti)
                sm = rag_tokenizer.fine_grained_tokenize(tk_clean).split()
                sm = [self.sub_special_char(m) for m in sm if len(m) > 1]

                if len(keywords) < 32:
                    keywords.extend(sm)

                tk_syns = self.syn.lookup(tk_clean)
                tk_syns = [self.sub_special_char(s) for s in tk_syns if s]
                if len(keywords) < 32:
                    keywords.extend(tk_syns)

                if " " in tk_clean or "\t" in tk_clean:
                    tk_clean_quoted = f'"{tk_clean}"'
                else:
                    tk_clean_quoted = tk_clean

                # Format synonyms for ES Query String Syntax
                if tk_syns:
                    tk_syns_str = " ".join(
                        [f'"{s}"' if " " in s else s for s in tk_syns]
                    )
                    tk_clean = f"({tk_clean_quoted} OR ({tk_syns_str})^0.2)"

                if sm:
                    sm_str = " ".join(sm)
                    _term = tk_clean if tk_syns else tk_clean_quoted
                    tk_clean = f'{_term} OR "{sm_str}" OR ("{sm_str}"~2)^0.5'

                if tk_clean.strip():
                    _term = tk_clean if (tk_syns or sm) else tk_clean_quoted
                    tms.append(f"({_term})^{w:.4f}")

            if tms:
                query_parts.append(" ".join(tms))

        final_query = " ".join(query_parts) if query_parts else txt

        # We can construct the actual ES DSL here, e.g., using query_string
        es_dsl = {
            "query_string": {
                "query": final_query,
                "fields": self.query_fields,
                "minimum_should_match": f"{int(min_match * 100)}%",
            }
        }

        return es_dsl, list(set(keywords))


if __name__ == "__main__":
    qb = QueryBuilder()
    question = "马氏体不锈钢的屈服强度是多少？"
    dsl, kwds = qb.build_es_query(question)
    print("ES DSL:", json.dumps(dsl, indent=2, ensure_ascii=False))
    print("Extracted Keywords:", kwds)
