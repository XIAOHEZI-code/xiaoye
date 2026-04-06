import re
import jieba

# Initialize jieba
jieba.initialize()

def is_chinese(s: str) -> bool:
    if not s:
        return False
    return any('\u4e00' <= char <= '\u9fff' for char in s)

def is_number(s: str) -> bool:
    if not s:
        return False
    # Check if string is a number (integer or float)
    try:
        float(s)
        return True
    except ValueError:
        return False

def is_alphabet(s: str) -> bool:
    if not s:
        return False
    return s.isalpha()

def strQ2B(ustring: str) -> str:
    """Convert full-width characters to half-width characters."""
    rstring = ""
    for uchar in ustring:
        inside_code = ord(uchar)
        if inside_code == 12288:  # Full-width space
            inside_code = 32
        elif 65281 <= inside_code <= 65374:  # Full-width characters
            inside_code -= 65248
        rstring += chr(inside_code)
    return rstring

def tradi2simp(line: str) -> str:
    """Traditional to Simplified Chinese conversion. 
    A basic mock here if OpenCC is not available."""
    try:
        import opencc
        converter = opencc.OpenCC('t2s.json')
        return converter.convert(line)
    except ImportError:
        # If opencc is not installed, return as is (or use a lightweight dict)
        return line

def naive_qie(txt: str) -> list[str]:
    """Naive cutting without jieba (used as fallback or for very specific splitting)"""
    return list(txt)

class RagTokenizer:
    def __init__(self):
        pass

    def tokenize(self, line: str) -> str:
        """Standard tokenization for search."""
        if not line:
            return ""
        
        # 1. Full-width to half-width
        line = strQ2B(line)
        # 2. Traditional to simplified
        line = tradi2simp(line)
        # 3. Lowercase
        line = line.lower()
        
        # 4. Remove excessive whitespaces/newlines and split by jieba
        tokens = jieba.cut_for_search(line)
        
        # Join tokens with space
        return " ".join([t.strip() for t in tokens if t.strip()])

    def fine_grained_tokenize(self, tks: str) -> str:
        """
        Fine-grained tokenization for edge cases 
        (e.g. splitting '1cr18ni9ti' into '1 cr 18 ni 9 ti').
        """
        if not tks:
            return ""
        
        tokens = tks.split()
        fine_tokens = []
        for tk in tokens:
            if len(tk) <= 2:
                fine_tokens.append(tk)
                continue
            
            # If it's pure alphabet or digit, don't split further
            if tk.isalpha() or tk.isdigit():
                fine_tokens.append(tk)
                continue
                
            # If mixed (like model numbers 'sus304'), split numbers and letters
            parts = re.findall(r'[a-zA-Z]+|\d+|[\u4e00-\u9fff]+|[^a-zA-Z\d\u4e00-\u9fff\s]', tk)
            if len(parts) > 1:
                fine_tokens.extend(parts)
            else:
                fine_tokens.append(tk)
                
        return " ".join(fine_tokens)

# Singleton exports to match RAGFlow's Infinity extension API
tokenizer = RagTokenizer()
tokenize = tokenizer.tokenize
fine_grained_tokenize = tokenizer.fine_grained_tokenize
strQ2B_func = strQ2B
tradi2simp_func = tradi2simp
