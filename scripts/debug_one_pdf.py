import sys
from pathlib import Path
from unittest.mock import patch
import uuid

# Mock OpenAI embeddings to avoid external calls
embed_doc_patch = patch('langchain_openai.OpenAIEmbeddings.embed_documents', return_value=[[0.1]*1024])
embed_query_patch = patch('langchain_openai.OpenAIEmbeddings.embed_query', return_value=[0.1]*1024)

with embed_doc_patch, embed_query_patch:
    from src.pipeline.pdf_parser import extract_pdf_with_marker, split_markdown_into_chunk_documents
    from src.core.config import settings

    # Directory with PDFs
    pdf_dir = Path('/home/xiaohezi/Downloads/冶金科技竞赛')
    pdf_files = sorted(pdf_dir.rglob('*.pdf'))
    if not pdf_files:
        print('⚠️ No PDF files found in the directory')
        sys.exit(0)

    pdf_path = pdf_files[0]
    print(f'🔎 Processing first PDF: {pdf_path.name}')
    out_dir = '/tmp/marker_images_test'
    if not Path(out_dir).exists():
        Path(out_dir).mkdir(parents=True)
    md_text, image_paths, out_meta = extract_pdf_with_marker(str(pdf_path), out_dir)
    print(f'🖼️  Extracted {len(image_paths)} images')
    if image_paths:
        from PIL import Image
        try:
            img = Image.open(image_paths[0])
            print(f'   First image: {image_paths[0]} (size: {img.size[0]}x{img.size[1]})')
        except Exception as e:
            print(f'   Failed to open first image: {e}')
    else:
        print('   No images found')
    print(f'📄 Markdown length: {len(md_text)} characters')
    chunks = split_markdown_into_chunk_documents(
        md_text=md_text,
        out_metadata=out_meta,
        doc_id=pdf_path.stem,
        source_pdf_id=pdf_path.name,
        chunk_size=500,
    )
    print(f'📦 Generated {len(chunks)} chunks')
    # Show first few chunks with metadata
    for i, ch in enumerate(chunks[:3], 1):
        print(f'--- Chunk {i} ---')
        print(f'Doc ID   : {ch.doc_id}')
        print(f'Page     : {ch.page_number}')
        print(f'BBox     : {ch.bbox}')
        snippet = ch.text_content[:200].replace('\n', ' ')
        print(f'Snippet  : {snippet}...')
        print('----------------')
