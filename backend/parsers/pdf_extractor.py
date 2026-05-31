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
from typing import List, Optional

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
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    logger.warning("pytesseract not installed - OCR disabled")

try:
    from PIL import Image, ImageFilter, ImageOps
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("Pillow not installed - image OCR preprocessing disabled")

try:
    from pdf2image import convert_from_path
    PDF_OCR_AVAILABLE = TESSERACT_AVAILABLE
except ImportError:
    PDF_OCR_AVAILABLE = False
    logger.warning("pdf2image not installed - PDF OCR disabled")

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

    if use_ocr and PDF_OCR_AVAILABLE and len(text.strip()) < MIN_TEXT_LENGTH:
        ocr_text = _extract_with_ocr(path, max_pages, lang=_preferred_ocr_lang())
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
        try:
            texts: List[str] = []
            for page_index in range(min(max_pages, doc.page_count)):
                page = doc.load_page(page_index)
                page_text = page.get_text("text") or ""
                if page_text.strip():
                    texts.append(page_text)
            return "\n".join(texts).strip()
        finally:
            doc.close()
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
    if not PDF_OCR_AVAILABLE:
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
            prepared = _preprocess_for_ocr(image)
            try:
                text = pytesseract.image_to_string(
                    prepared,
                    lang=lang,
                    config="--oem 1 --psm 6",
                    timeout=_OCR_TIMEOUT_SECONDS,
                )
            except RuntimeError as err:
                logger.warning("Tesseract timeout/error on page %s: %s", i + 1, err)
                continue
            if text.strip():
                texts.append(text)
                logger.debug("OCR extracted %s chars from page %s", len(text), i + 1)

        return "\n".join(texts).strip()
    except Exception as err:
        logger.debug("OCR extraction failed: %s", err)
        return ""


def _preferred_ocr_lang(default: str = "rus+eng") -> str:
    if not TESSERACT_AVAILABLE:
        return default
    try:
        langs = set(pytesseract.get_languages(config=""))
    except Exception:
        return default
    if "uzb" in langs:
        return "rus+eng+uzb"
    if "uzb_cyrl" in langs:
        return "rus+eng+uzb_cyrl"
    return default


_OCR_MIN_WIDTH = int(os.getenv("OCR_MIN_WIDTH", "1500"))
_OCR_PSM_MODES = (6, 4, 11)
_OCR_TIMEOUT_SECONDS = int(os.getenv("OCR_TIMEOUT_SECONDS", "20"))


def _preprocess_for_ocr(image):
    if not PIL_AVAILABLE:
        return image
    img = ImageOps.grayscale(image)
    if img.width < _OCR_MIN_WIDTH:
        scale = max(2, (_OCR_MIN_WIDTH + img.width - 1) // img.width)
        img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    img = ImageOps.autocontrast(img, cutoff=2)
    img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=140, threshold=2))
    return img


def extract_text_from_image_path(path: str, lang: Optional[str] = None) -> str:
    if not TESSERACT_AVAILABLE or not PIL_AVAILABLE:
        return ""
    ocr_lang = lang or _preferred_ocr_lang()
    try:
        image = Image.open(path)
        prepared = _preprocess_for_ocr(image)
    except Exception as err:
        logger.debug("Image OCR open/preprocess failed for %s: %s", path, err)
        return ""

    best_text = ""
    for psm in _OCR_PSM_MODES:
        config = f"--oem 1 --psm {psm}"
        try:
            text = pytesseract.image_to_string(
                prepared,
                lang=ocr_lang,
                config=config,
                timeout=_OCR_TIMEOUT_SECONDS,
            ) or ""
        except RuntimeError as err:
            logger.warning("Tesseract timeout for %s psm=%s: %s", path, psm, err)
            continue
        except Exception as err:
            logger.debug("Image OCR psm=%s failed for %s: %s", psm, path, err)
            continue
        if len(text.strip()) > len(best_text.strip()):
            best_text = text
    return _strip_ocr_noise(best_text.strip())


def _strip_ocr_noise(text: str) -> str:
    """Drop OCR-output that's obviously garbage.

    Returns "" when alphanumeric ratio is below threshold (i.e. random punctuation
    soup from a blank/black page). Avoids feeding nonsense to regex/AI.
    """
    if not text:
        return ""
    total = len(text)
    if total < 10:
        return ""
    alnum = sum(1 for ch in text if ch.isalnum())
    ratio = alnum / total if total else 0
    if ratio < 0.20:
        logger.warning("OCR noise filtered: ratio=%.2f len=%d", ratio, total)
        return ""
    return text


def extract_text_from_image_bytes(image_bytes: bytes, lang: Optional[str] = None) -> str:
    if not image_bytes:
        return ""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".img") as tmp:
        tmp.write(image_bytes)
        tmp_path = tmp.name
    try:
        return extract_text_from_image_path(tmp_path, lang=lang)
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def render_image_to_base64(path: str) -> str:
    with open(path, "rb") as file:
        data = file.read()
    return base64.b64encode(data).decode("ascii")


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
    return list(iter_pdf_pages_png_base64(path=path, max_pages=max_pages, dpi=dpi))


def iter_pdf_pages_png_base64(path: str, max_pages: int = 2, dpi: int = 150):
    """
    Stream PDF pages one-by-one as base64 PNG to avoid holding all rendered pages in memory.
    """
    doc = fitz.open(path)
    try:
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        for page_index in range(min(max_pages, doc.page_count)):
            page = doc.load_page(page_index)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            png_bytes = pix.tobytes("png")
            yield base64.b64encode(png_bytes).decode("ascii")
    finally:
        doc.close()


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
