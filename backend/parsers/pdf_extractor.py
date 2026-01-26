"""
PDF extraction utilities using PyMuPDF.
"""
import base64
from typing import List

try:
    import fitz  # PyMuPDF
except ImportError as exc:  # pragma: no cover - runtime dependency
    raise ImportError("PyMuPDF is required for PDF extraction") from exc


def extract_text_from_pdf(path: str, max_pages: int = 2) -> str:
    """
    Extract text from the first `max_pages` of a PDF.
    """
    doc = fitz.open(path)
    try:
        texts: List[str] = []
        for page_index in range(min(max_pages, doc.page_count)):
            page = doc.load_page(page_index)
            texts.append(page.get_text("text") or "")
        return "\n".join(texts).strip()
    finally:
        doc.close()


def render_pdf_pages_to_png_base64(path: str, max_pages: int = 2, dpi: int = 150) -> List[str]:
    """
    Render first `max_pages` pages of PDF to PNG and return base64 strings (no prefix).
    """
    doc = fitz.open(path)
    images: List[str] = []
    try:
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        for page_index in range(min(max_pages, doc.page_count)):
            page = doc.load_page(page_index)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            png_bytes = pix.tobytes("png")
            images.append(base64.b64encode(png_bytes).decode("ascii"))
    finally:
        doc.close()
    return images
