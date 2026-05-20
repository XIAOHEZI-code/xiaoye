import os
import json
from src.ingestion.pdf_parser import extract_pdf_with_marker, split_markdown_into_chunk_documents, process_figures

def test_pipeline():
    print("Testing PDF Parsing Pipeline...")
    pdf_path = "./test.pdf"
    out_dir = "./test_marker_output"
    
    # 1. Parse PDF
    md_text, image_paths, out_metadata = extract_pdf_with_marker(pdf_path, out_dir)
    print(f"Extracted {len(md_text)} chars of markdown, {len(image_paths)} images.")
    
    # 2. Chunk text
    text_chunks = split_markdown_into_chunk_documents(
        md_text, out_metadata, "test-doc-id", "test.pdf"
    )
    print(f"Generated {len(text_chunks)} text chunks.")
    
    # 3. Process figures
    figure_chunks = process_figures(
        md_text, image_paths, "test-doc-id", "test.pdf", analyze_with_vlm=False
    )
    print(f"Generated {len(figure_chunks)} figure chunks.")
    
    # 4. Save to JSON
    output_data = {
        "text_chunks": [c.to_dict() for c in text_chunks],
        "figure_chunks": [c.to_dict() for c in figure_chunks],
    }
    
    with open("test_chunks_output.json", "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print("Saved chunks to test_chunks_output.json")

if __name__ == "__main__":
    test_pipeline()
