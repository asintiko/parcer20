"""
PDF extraction utilities with OCR cascade support.

Supports multiple extraction methods with fallback:
1. PyMuPDF (fast, for text-layer PDFs)
2. pdfplumber (better extraction for complex layouts)
3. OCR via Tesseract (for scanned documents)
"""
import base64
import logging
import os
import tempfile
from typing import List

logger = logging.getLogger(__name__)

# Primary dependency - always available
try:
    import fitz  # PyMuPDF
except ImportError as exc:
    raise ImportError("PyMuPDF is required for PDF extraction") from exc

# Optional dependencies with graceful degradation
try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    logger.warning("pdfplumber not installed - OCR cascade limited")

try:
    from pdf2image import convert_from_path, convert_from_bytes
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    logger.warning("pdf2image/pytesseract not installed - OCR disabled")


def extract_text_from_pdf(path: str, max_pages: int = 2, use_ocr: bool = True) -> str:
    """
    Extract text from PDF using cascade approach with multiple fallback methods.

    Cascade order:
    1. PyMuPDF (fastest, works with text-layer PDFs)
    2. pdfplumber (better for complex layouts)
    3. OCR via Tesseract (for scanned documents)

    Args:
        path: Path to PDF file
        max_pages: Maximum pages to process (default: 2)
        use_ocr: Enable OCR fallback for scanned documents (default: True)

    Returns:
        Extracted text or empty string if extraction failed
    """
    # Step 1: Try PyMuPDF (fastest method)
    text = _extract_with_pymupdf(path, max_pages)
    if text and len(text.strip()) >= 50:
        logger.info(f"PDF text extracted via PyMuPDF: {len(text)} chars")
        return text

    # Step 2: Try pdfplumber (better for complex layouts)
    if PDFPLUMBER_AVAILABLE:
        text = _extract_with_pdfplumber(path, max_pages)
        if text and len(text.strip()) >= 50:
            logger.info(f"PDF text extracted via pdfplumber: {len(text)} chars")
            return text

    # Step 3: OCR fallback for scanned documents
    if use_ocr and OCR_AVAILABLE:
        text = _extract_with_ocr(path, max_pages, lang='rus+eng')
        if text and len(text.strip()) >= 30:
            logger.info(f"PDF text extracted via OCR: {len(text)} chars")
            return text

    # Return whatever we have (may be empty)
    logger.warning(f"Failed to extract meaningful text from PDF: {path}")
    return text or ""


def _extract_with_pymupdf(path: str, max_pages: int) -> str:
    """
    Extract text using PyMuPDF (fitz) - fastest method.

    Works well with:
    - Text-layer PDFs (documents with selectable text)
    - Simple layouts

    Args:
        path: Path to PDF file
        max_pages: Maximum pages to process

    Returns:
        Extracted text or empty string
    """
    try:
        doc = fitz.open(path)
        texts: List[str] = []
        for page_index in range(min(max_pages, doc.page_count)):
            page = doc.load_page(page_index)
            page_text = page.get_text("text") or ""
            if page_text.strip():
                texts.append(page_text)
        doc.close()
        return "\n".join(texts).strip()
    except Exception as e:
        logger.error(f"PyMuPDF extraction failed: {e}")
        return ""


def _extract_with_pdfplumber(path: str, max_pages: int) -> str:
    """
    Extract text using pdfplumber - better for complex layouts.

    Works well with:
    - Complex table layouts
    - Multi-column documents
    - Forms with structured data

    Args:
        path: Path to PDF file
        max_pages: Maximum pages to process

    Returns:
        Extracted text or empty string
    """
    try:
        texts: List[str] = []
        with pdfplumber.open(path) as pdf:
            for page_index in range(min(max_pages, len(pdf.pages))):
                page_text = pdf.pages[page_index].extract_text()
                if page_text and page_text.strip():
                    texts.append(page_text)
        return "\n".join(texts).strip()
    except Exception as e:
        logger.error(f"pdfplumber extraction failed: {e}")
        return ""


def _extract_with_ocr(path: str, max_pages: int, lang: str = 'rus+eng', dpi: int = 300) -> str:
    """
    Extract text using OCR (Optical Character Recognition) via Tesseract.

    Works well with:
    - Scanned documents
    - Images embedded in PDFs
    - Documents without text layer

    Args:
        path: Path to PDF file
        max_pages: Maximum pages to process
        lang: Tesseract language code (default: 'rus+eng' for Russian and English)
        dpi: DPI for image conversion (default: 300 for good quality)

    Returns:
        Extracted text or empty string
    """
    try:
        # Convert PDF pages to images
        images = convert_from_path(
            path,
            dpi=dpi,
            first_page=1,
            last_page=max_pages
        )

        texts: List[str] = []
        for i, image in enumerate(images):
            # Apply OCR to each image
            text = pytesseract.image_to_string(image, lang=lang)
            if text.strip():
                texts.append(text)
                logger.debug(f"OCR extracted {len(text)} chars from page {i+1}")

        return "\n".join(texts).strip()
    except Exception as e:
        logger.error(f"OCR extraction failed: {e}")
        return ""


def extract_text_from_pdf_bytes(pdf_bytes: bytes, max_pages: int = 2, use_ocr: bool = True) -> str:
    """
    Extract text from PDF bytes (for Celery worker and API uploads).

    Saves bytes to temporary file, extracts text, then deletes file.

    Args:
        pdf_bytes: PDF file content as bytes
        max_pages: Maximum pages to process (default: 2)
        use_ocr: Enable OCR fallback (default: True)

    Returns:
        Extracted text or empty string
    """
    # Create temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        # Extract text using cascade
        return extract_text_from_pdf(tmp_path, max_pages, use_ocr)
    finally:
        # Clean up temporary file
        try:
            os.unlink(tmp_path)
        except Exception as e:
            logger.warning(f"Failed to delete temp file {tmp_path}: {e}")


def render_pdf_pages_to_png_base64(path: str, max_pages: int = 2, dpi: int = 150) -> List[str]:
    """
    Render first `max_pages` pages of PDF to PNG and return base64 strings (no prefix).

    Used for Vision API fallback when text extraction fails.

    Args:
        path: Path to PDF file
        max_pages: Maximum pages to render (default: 2)
        dpi: DPI for rendering (default: 150, lower quality for API efficiency)

    Returns:
        List of base64-encoded PNG images (without data URI prefix)
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
