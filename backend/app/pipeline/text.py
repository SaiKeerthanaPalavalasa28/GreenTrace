"""PDF -> per-page text. pdfplumber first; pages without a usable text layer are OCR'd
(pypdfium2 renders the page, Tesseract reads it)."""

import io
import re
from collections.abc import Callable
from dataclasses import dataclass

import pdfplumber
from pdfminer.pdfparser import PDFSyntaxError

from app.config import get_settings
from app.pipeline.errors import OcrUnavailableError, PdfReadError

PAGE_MARKER = "=== PAGE {n} ==="


@dataclass
class PdfText:
    pages: list[str]  # index 0 = page 1
    page_methods: list[str]  # "pdfplumber" | "ocr", per page

    @property
    def method(self) -> str:
        methods = set(self.page_methods)
        return methods.pop() if len(methods) == 1 else "mixed"

    def as_prompt(self) -> str:
        return "\n\n".join(f"{PAGE_MARKER.format(n=i + 1)}\n{t}" for i, t in enumerate(self.pages))


def _meaningful_chars(text: str) -> int:
    return len(re.sub(r"\s", "", text))


def ocr_page(pdf_bytes: bytes, page_index: int, dpi: int) -> str:
    import pypdfium2
    import pytesseract

    settings = get_settings()
    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
    pdf = pypdfium2.PdfDocument(pdf_bytes)
    try:
        image = pdf[page_index].render(scale=dpi / 72).to_pil()
    finally:
        pdf.close()
    try:
        return pytesseract.image_to_string(image)
    except pytesseract.TesseractNotFoundError:
        raise OcrUnavailableError(
            "This bill has no text layer (it looks scanned) and OCR is not available on the server: "
            "Tesseract is not installed or not on PATH. Install it, then reprocess the bill."
        ) from None


def extract_text(pdf_bytes: bytes, ocr: Callable[[bytes, int, int], str] = ocr_page) -> PdfText:
    settings = get_settings()
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if len(pdf.pages) == 0:
                raise PdfReadError("The PDF has no pages.")
            if len(pdf.pages) > settings.max_pdf_pages:
                raise PdfReadError(
                    f"The PDF has {len(pdf.pages)} pages; bills over {settings.max_pdf_pages} pages are not supported."
                )
            pages = [page.extract_text() or "" for page in pdf.pages]
    except PdfReadError:
        raise
    except (PDFSyntaxError, ValueError, KeyError, TypeError) as e:
        raise PdfReadError(f"The file could not be read as a PDF ({type(e).__name__}). It may be corrupt.") from e
    except Exception as e:
        if "password" in str(e).lower() or "encrypt" in type(e).__name__.lower():
            raise PdfReadError("The PDF is password-protected. Upload an unlocked copy.") from e
        raise PdfReadError(f"The file could not be read as a PDF ({type(e).__name__}).") from e

    methods = []
    for i, text in enumerate(pages):
        if _meaningful_chars(text) >= settings.min_text_chars_per_page:
            methods.append("pdfplumber")
            continue
        pages[i] = ocr(pdf_bytes, i, settings.ocr_dpi)
        methods.append("ocr")

    if sum(_meaningful_chars(t) for t in pages) < settings.min_text_chars_per_page:
        raise PdfReadError("No readable text was found in the PDF, even with OCR.")
    return PdfText(pages, methods)
