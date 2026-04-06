import re
import uuid

class MarkdownChunker:
    """
    A smart chunker for Markdown documents, specially tuned for `marker-pdf` output.
    It preserves the header hierarchy as context for dense retrieval.
    """
    def __init__(self, chunk_size=800, overlap=100):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def extract_hierarchy(self, text):
        """
        Parses Markdown into chunks while retaining the current Header context.
        Example: If we are under # H1 -> ## H2, the chunk metadata will include "H1 > H2".
        """
        lines = text.split('\n')
        chunks = []
        current_headers = {}
        current_chunk = []
        current_length = 0
        
        # Regex to match markdown headers
        header_pattern = re.compile(r'^(#{1,6})\s+(.*)')
        
        def flush_chunk():
            if current_chunk:
                content = '\n'.join(current_chunk).strip()
                if content:
                    # Build header context string
                    context_path = " > ".join([current_headers[k] for k in sorted(current_headers.keys())])
                    
                    chunks.append({
                        "content": content,
                        "metadata": {
                            "chunk_id": str(uuid.uuid4()),
                            "context": context_path,
                            "type": "text"
                        }
                    })
                current_chunk.clear()
        
        for line in lines:
            header_match = header_pattern.match(line)
            if header_match:
                level = len(header_match.group(1))
                title = header_match.group(2).strip()
                
                # Update header hierarchy
                current_headers[level] = title
                # Remove any headers deeper than current level
                keys_to_remove = [k for k in current_headers.keys() if k > level]
                for k in keys_to_remove:
                    del current_headers[k]
                
                # Often a good idea to flush chunk on new headers if current length is substantial
                if current_length > self.chunk_size * 0.5:
                    flush_chunk()
                    current_length = 0
                    
            # Basic table detection (can be expanded)
            if line.strip().startswith('|') and len(line.split('|')) > 2:
                # To be improved: Collect table block
                pass
                
            current_chunk.append(line)
            current_length += len(line)
            
            if current_length >= self.chunk_size:
                flush_chunk()
                current_length = 0
                
        # Flush remaining
        flush_chunk()
        return chunks

if __name__ == '__main__':
    # Test
    sample_md = \"\"\"# 1cr18ni9ti 规范\n## 化学成分\n碳含量小于0.12%。\n## 机械性能\n屈服强度>=205MPa。\"\"\"
    chunker = MarkdownChunker()
    chunks = chunker.extract_hierarchy(sample_md)
    for c in chunks:
        print(f"Context: {c['metadata']['context']}")
        print(f"Content: {c['content']}")
        print("---")
