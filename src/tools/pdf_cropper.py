import fitz  # PyMuPDF
import base64
import os

def crop_pdf_to_base64_png(pdf_path: str, page_number: int, relative_bbox: dict) -> str:
    """
    Crops a section of a PDF page defined by relative ratios (0.0 to 1.0) 
    and returns it as a Base64 encoded PNG String.
    
    relative_bbox should contain: x0, y0, x1, y1
    Example: { "x0": 0.1, "y0": 0.2, "x1": 0.5, "y1": 0.6 }
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"Source PDF missing at {pdf_path}")
        
    doc = fitz.open(pdf_path)
    
    # 1-indexed UI pageNumber to 0-indexed PyMuPDF pageNumber
    page_idx = page_number - 1
    if page_idx < 0 or page_idx >= len(doc):
        raise ValueError(f"Page number {page_number} is out of bounds [1, {len(doc)}]")
        
    page = doc.load_page(page_idx)
    page_width = page.rect.width
    page_height = page.rect.height
    
    # Map relative proportions -> physical points
    x0 = relative_bbox.get("x0", 0) * page_width
    y0 = relative_bbox.get("y0", 0) * page_height
    x1 = relative_bbox.get("x1", 1) * page_width
    y1 = relative_bbox.get("y1", 1) * page_height
    
    # Create the Fitz Rect
    crop_rect = fitz.Rect(x0, y0, x1, y1)
    
    # Extract the pixmap with a higher zoom matrix for better OCR/VLM clarity
    zoom = 2.0  # scale up density
    mat = fitz.Matrix(zoom, zoom)
    
    pix = page.get_pixmap(matrix=mat, clip=crop_rect, alpha=False)
    
    # Convert pixels straight to Base64 skipping filesystem latency!
    img_bytes = pix.tobytes("png")
    base64_encoded = base64.b64encode(img_bytes).decode("utf-8")
    
    doc.close()
    
    return base64_encoded
