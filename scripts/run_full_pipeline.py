import os
import sys
import argparse
from pathlib import Path
import uuid
import subprocess
# Ensure project root is in PYTHONPATH for relative imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.append(project_root)

# Ensure conda env variables are set when running via conda run

def ensure_es_running():
    # Check if Elasticsearch container is up
    try:
        result = subprocess.run(['docker', 'ps', '--filter', 'name=elasticsearch', '--format', '{{.Names}}'], capture_output=True, text=True, check=True)
        containers = result.stdout.strip().split('\n')
        if any('elasticsearch' in name for name in containers if name):
            print('✅ Elasticsearch container is running')
            return True
    except Exception as e:
        print(f'⚠️ Docker check failed: {e}')
    # Try to start via docker-compose
    print('🚀 Starting Elasticsearch via docker-compose...')
    subprocess.run(['docker', 'compose', 'up', '-d', 'elasticsearch'], check=False)
    # Wait a bit
    import time
    time.sleep(10)
    # Re‑check
    result = subprocess.run(['docker', 'ps', '--filter', 'name=elasticsearch', '--format', '{{.Names}}'], capture_output=True, text=True)
    if result.stdout.strip():
        print('✅ Elasticsearch started')
        return True
    print('❌ Failed to start Elasticsearch')
    return False

def extract_and_index(pdf_path: Path):
    from src.pipeline.pdf_parser import extract_pdf_with_marker, split_markdown_into_chunk_documents
    from src.retrieval.es_indexer import index_chunk_documents
    # Create output dir for images
    out_dir = Path('/tmp/marker_output_' + uuid.uuid4().hex[:6])
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f'🔎 Processing PDF: {pdf_path.name}')
    md_text, image_paths, out_meta = extract_pdf_with_marker(str(pdf_path), str(out_dir))
    print(f'🖼️ Extracted {len(image_paths)} images')
    # Move images to project media folder for persistence
    media_dir = Path('media') / pdf_path.stem
    media_dir.mkdir(parents=True, exist_ok=True)
    for img_path in image_paths:
        src = Path(img_path)
        dst = media_dir / src.name
        src.rename(dst)
    # Chunking
    chunks = split_markdown_into_chunk_documents(
        md_text=md_text,
        out_metadata=out_meta,
        doc_id=pdf_path.stem,
        source_pdf_id=pdf_path.name,
        chunk_size=500,
    )
    print(f'📦 Generated {len(chunks)} chunks')
    # Index into Elasticsearch
    indexed = index_chunk_documents(chunks)
    print(f'✅ Indexed {indexed} documents into Elasticsearch')
    return chunks

def sample_search(pdf_name: str):
    from src.retrieval.semantic_search import SemanticSearchTool
    tool = SemanticSearchTool()
    # Simple query to retrieve something from the newly indexed doc
    query = f"{pdf_name}"  # just use the filename as query term
    results = tool.search(query)
    print('🔎 Sample search results (top 3):')
    for i, doc in enumerate(results[:3], 1):
        print(f"--- Result {i} ---")
        print(f"Doc ID   : {doc.doc_id}")
        print(f"Page     : {doc.page_number}")
        print(f"Citation  : {doc.to_citation_str()}")
        snippet = doc.text_content[:200].replace('\n', ' ')
        print(f"Snippet  : {snippet}...")
        print('----------------')

def main():
    parser = argparse.ArgumentParser(description='Run full RAG pipeline for a single PDF')
    parser.add_argument('pdf_path', type=str, help='Path to the PDF file')
    args = parser.parse_args()
    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f'❌ PDF not found: {pdf_path}')
        sys.exit(1)
    if not ensure_es_running():
        print('❌ Elasticsearch not available, aborting')
        sys.exit(1)
    chunks = extract_and_index(pdf_path)
    sample_search(pdf_path.stem)

if __name__ == '__main__':
    main()
