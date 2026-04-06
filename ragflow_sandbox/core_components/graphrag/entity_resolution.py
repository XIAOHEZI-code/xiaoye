import re
import editdistance

def is_english(s):
    try:
        s.encode(encoding='utf-8').decode('ascii')
    except UnicodeDecodeError:
        return False
    else:
        return True

class EntityResolutionDealer:
    """
    Utility to compute which entities in a Knowledge Graph (Neo4j) should be merged.
    Filters candidate pairs locally, and provides prompt templating for LLM confirmation.
    """
    def __init__(self):
        self.resolution_prompt_template = \"\"\"
You are an expert in Knowledge Graph construction.
When determining whether two {entity_type}s are the same, you should only focus on critical properties and overlook noisy factors.

{questions}

Use domain knowledge of {entity_type}s to help understand the text and answer the questions in the format: 
For Question i, Yes, {entity_type} A and {entity_type} B are the same {entity_type}. / No, {entity_type} A and {entity_type} B are different {entity_type}s.
\"\"\"

    def _has_digit_in_2gram_diff(self, a, b):
        def to_2gram_set(s):
            return {s[i:i+2] for i in range(len(s) - 1)}

        set_a = to_2gram_set(a)
        set_b = to_2gram_set(b)
        diff = set_a ^ set_b

        return any(any(c.isdigit() for c in pair) for pair in diff)

    def is_similarity(self, a: str, b: str) -> bool:
        """
        Fast local check to see if two entity strings are similar enough to be candidates for LLM resolution.
        Prevents merging entities that differ by critical digits (e.g. 1Cr18Ni9Ti vs 1Cr19Ni9Ti)
        """
        # If the slight difference involves digits, DO NOT merge. Very critical for metallurgy grades.
        if self._has_digit_in_2gram_diff(a, b):
            return False

        if is_english(a) and is_english(b):
            if editdistance.eval(a, b) <= min(len(a), len(b)) // 2:
                return True
            return False

        a_set, b_set = set(a), set(b)
        max_l = max(len(a_set), len(b_set))
        if max_l < 4:
            return len(a_set & b_set) > 1

        return len(a_set & b_set)*1./max_l >= 0.8

    def build_llm_prompt(self, entity_type: str, candidate_pairs: list[tuple[str, str]]) -> str:
        """
        Builds the prompt to throw to an LLM (from Xiaoye's Evaluator LLM pool)
        to confirm merging.
        """
        questions = []
        for index, candidate in enumerate(candidate_pairs):
            questions.append(
                f'Question {index + 1}: name of {entity_type} A is '{candidate[0]}', name of {entity_type} B is '{candidate[1]}''
            )
            
        return self.resolution_prompt_template.format(
            entity_type=entity_type,
            questions="\\n".join(questions)
        )

if __name__ == '__main__':
    er = EntityResolutionDealer()
    
    # Should be False due to digit difference mapping 18 vs 19
    print(er.is_similarity("1Cr18Ni9Ti", "1Cr19Ni9Ti")) 
    
    # Might be True, candidates for LLM
    print(er.is_similarity("马氏体不锈钢", "马氏体钢")) 
