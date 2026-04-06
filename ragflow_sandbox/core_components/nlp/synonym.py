import logging
import json
import os
import re

import nltk
from nltk.corpus import wordnet

# Optional: Disable NLTK download noise if already installed
try:
    wordnet.ensure_loaded()
except Exception:
    logging.warning("Fail to load wordnet.ensure_loaded(), nltk wordnet might be missing.")

class SynonymDealer:
    def __init__(self, use_redis=False):
        self.dictionary = None
        # Use relative path since we copied res to core_components/nlp/res
        path = os.path.join(os.path.dirname(__file__), "res", "synonym.json")
        try:
            with open(path, 'r', encoding="utf-8") as f:
                self.dictionary = json.load(f)
            self.dictionary = { (k.lower() if isinstance(k, str) else k): v for k, v in self.dictionary.items() }
        except Exception:
            logging.warning(f"Missing synonym.json at {path}")
            self.dictionary = {}

        if not len(self.dictionary.keys()):
            logging.warning("Fail to load local synonym dict.")

        # We keep this boolean for future extension if we want dynamic synonyms,
        # but the heavy strict-dependency on redis is removed.
        self.use_redis = use_redis

    def lookup(self, tk, topn=8):
        if not tk or not isinstance(tk, str):
            return []

        # 1) Check the custom dictionary first (both keys and tk are already lowercase)
        key = re.sub(r"[ \t]+", " ", tk.strip())
        res = self.dictionary.get(key, [])
        if isinstance(res, str):
            res = [res]
        if res:  # Found in dictionary -> return directly
            return res[:topn]

        # 2) If not found and tk is purely alphabetical -> fallback to WordNet
        if re.fullmatch(r"[a-z]+", tk):
            try:
                wn_set = {
                    re.sub("_", " ", syn.name().split(".")[0])
                    for syn in wordnet.synsets(tk)
                }
                wn_set.discard(tk)  # Remove the original token itself
                wn_res = [t for t in wn_set if t]
                return wn_res[:topn]
            except Exception:
                pass

        # 3) Nothing found
        return []

if __name__ == '__main__':
    dl = SynonymDealer()
    print("Synonym dictionary loaded with keys:", len(dl.dictionary))
