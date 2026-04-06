import os
from marker.convert import convert_single_pdf
from marker.models import load_all_models
from typing import Tuple, List

# To avoid loading models multiple times during Celery worker lifetime
_MARKER_MODELS = None

def get_marker_models():
    global _MARKER_MODELS
    if _MARKER_MODELS is None:
        print("Loading Marker Models (GPU)...")
        _MARKER_MODELS = load_all_models()
    return _MARKER_MODELS

def extract_pdf_with_marker(filepath: str, out_dir: str) -> Tuple[str, List[str]]:
    """
    Given a local PDF filepath, uses marker to convert it into Markdown and extracts images.
    Returns:
        (full_markdown_text, list_of_image_filepaths)
    """
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    models = get_marker_models()
    
    # We pass the filepath and models. Marker returns the full text and a dict of images
    full_text, images, out_metadata = convert_single_pdf(filepath, models, max_pages=None)

    image_paths = []
    # Marker returns images as dictionary mapping filename -> PIL Image
    if images:
        for img_name, img_obj in images.items():
            img_path = os.path.join(out_dir, img_name)
            img_obj.save(img_path)
            image_paths.append(img_path)

    # Save the markdown as well for debug
    md_path = os.path.join(out_dir, "document.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(full_text)

    return full_text, image_paths

def split_markdown_into_chunks(md_text: str, chunk_size: int = 1000) -> List[str]:
    """
    Very basic naive splitter.
    In real production, you'd use LangChain's MarkdownHeaderTextSplitter or RecursiveCharacterTextSplitter.
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=100,
        separators=["\n## ", "\n### ", "\n\n", "\n", " ", ""]
    )
    return splitter.split_text(md_text)
