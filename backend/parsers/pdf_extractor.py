"""
PDF extraction utilities with OCR cascade support.

Supports multiple extraction methods with fallback:
1. pdfplumber (preferred for text-layer PDFs)
2. PyMuPDF (backup text extraction)
3. OCR via Tesseract (for scanned documents or sparse text)
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
    logger.warning("pdfplumber not installed - text extraction limited")

try:
    from pdf2image import convert_from_path
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    logger.warning("pdf2image/pytesseract not installed - OCR disabled")

MIN_TEXT_LENGTH = 80


def extract_text_from_pdf(path: str, max_pages: int = 2, use_ocr: bool = True) -> str:
    """
    Extract text from PDF using cascade approach with multiple fallback methods.

    Cascade:
    1. pdfplumber (preferred where text layer exists)
    2. PyMuPDF
    3. OCR via Tesseract if text is sparse or missing
    """
    text = ""

    if PDFPLUMBER_AVAILABLE:
        text = _extract_with_pdfplumber(path, max_pages)
        if text and len(text.strip()) >= MIN_TEXT_LENGTH:
            logger.info(f"PDF text extracted via pdfplumber: {len(text)} chars")
            return text

    if not text:
        text = _extract_with_pymupdf(path, max_pages)
        if text and len(text.strip()) >= MIN_TEXT_LENGTH:
            logger.info(f"PDF text extracted via PyMuPDF: {len(text)} chars")
            return text

    if use_ocr and OCR_AVAILABLE and len(text.strip()) < MIN_TEXT_LENGTH:
        ocr_text = _extract_with_ocr(path, max_pages, lang='rus+eng')
        if ocr_text:
            logger.info(f"PDF text extracted via OCR: {len(ocr_text)} chars")
            return ocr_text

    if text and text.strip():
        return text

    logger.warning(f"Failed to extract meaningful text from PDF: {path}")
    return ""


def _extract_with_pymupdf(path: str, max_pages: int) -> str:
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
    except Exception as err:
        logger.debug("PyMuPDF extraction failed: %s", err)
        return ""


def _extract_with_pdfplumber(path: str, max_pages: int) -> str:
    if not PDFPLUMBER_AVAILABLE:
        return ""
    try:
        texts: List[str] = []
        with pdfplumber.open(path) as pdf:
            for page_index in range(min(max_pages, len(pdf.pages))):
                page_text = pdf.pages[page_index].extract_text()
                if page_text and page_text.strip():
                    texts.append(page_text)
        return "\n".join(texts).strip()
    except Exception as err:
        logger.debug("pdfplumber extraction failed (%s); falling back", err)
        return ""


def _extract_with_ocr(path: str, max_pages: int, lang: str = 'rus+eng', dpi: int = 300) -> str:
    if not OCR_AVAILABLE:
        return ""
    try:
        images = convert_from_path(
            path,
            dpi=dpi,
            first_page=1,
            last_page=max_pages
        )

        texts: List[str] = []
        for i, image in enumerate(images):
            text = pytesseract.image_to_string(image, lang=lang)
            if text.strip():
                texts.append(text)
                logger.debug("OCR extracted %s chars from page %s", len(text), i + 1)

        return "\n".join(texts).strip()
    except Exception as err:
        logger.debug("OCR extraction failed: %s", err)
        return ""


def extract_text_from_pdf_bytes(pdf_bytes: bytes, max_pages: int = 2, use_ocr: bool = True) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        return extract_text_from_pdf(tmp_path, max_pages, use_ocr)
    finally:
        try:
            os.unlink(tmp_path)
        except Exception as err:
            logger.warning("Failed to delete temp file %s: %s", tmp_path, err)


def render_pdf_pages_to_png_base64(path: str, max_pages: int = 2, dpi: int = 150) -> List[str]:
    """
    Render first `max_pages` pages of a PDF to PNG and return base64-encoded strings.
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


def render_pdf_bytes_to_png_base64(pdf_bytes: bytes, max_pages: int = 2, dpi: int = 150) -> List[str]:
    """
    Convenience helper: render PDF bytes to PNG (base64) without exposing temp files to callers.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        return render_pdf_pages_to_png_base64(tmp_path, max_pages=max_pages, dpi=dpi)
    finally:
        try:
            os.unlink(tmp_path)
        except Exception as err:  # pragma: no cover - best effort cleanup
            logger.debug("Failed to cleanup temp PDF %s: %s", tmp_path, err)
