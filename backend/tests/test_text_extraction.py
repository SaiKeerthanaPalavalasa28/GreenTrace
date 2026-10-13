import pytest

from app.pipeline import text as text_mod
from app.pipeline.errors import OcrUnavailableError, PdfReadError
from app.pipeline.text import extract_text
from tests.helpers import ELECTRICITY_BILL, make_image_pdf, make_pdf, make_text_pdf


def test_text_layer_pdf_uses_pdfplumber():
    pdf = make_text_pdf([ELECTRICITY_BILL, ["Page two: payment slip", "Consumer No: 170012345678 and more text here"]])
    result = extract_text(pdf, ocr=lambda *a: pytest.fail("OCR must not run on a text PDF"))
    assert result.method == "pdfplumber"
    assert len(result.pages) == 2
    assert "Units Consumed (kWh): 12,500" in result.pages[0]
    prompt = result.as_prompt()
    assert prompt.startswith("=== PAGE 1 ===")
    assert "=== PAGE 2 ===" in prompt


def test_scanned_pdf_falls_back_to_ocr():
    pdf = make_image_pdf(ELECTRICITY_BILL)
    calls = []

    def fake_ocr(data, page_index, dpi):
        calls.append((page_index, dpi))
        return "\n".join(ELECTRICITY_BILL)

    result = extract_text(pdf, ocr=fake_ocr)
    assert calls == [(0, 300)]
    assert result.method == "ocr"
    assert "12,500" in result.pages[0]


def test_mixed_pdf_only_ocrs_pages_without_text():
    pdf = make_pdf([("text", ELECTRICITY_BILL), ("image", ["Scanned annexure page"])])
    calls = []
    result = extract_text(pdf, ocr=lambda data, i, dpi: calls.append(i) or "Scanned annexure page text")
    assert calls == [1]
    assert result.page_methods == ["pdfplumber", "ocr"]
    assert result.method == "mixed"


def test_scanned_pdf_without_tesseract_gives_readable_error(monkeypatch):
    import pytesseract

    def missing(*a, **k):
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(pytesseract, "image_to_string", missing)
    with pytest.raises(OcrUnavailableError, match="Tesseract is not installed"):
        extract_text(make_image_pdf(ELECTRICITY_BILL))


def test_ocr_renders_page_for_tesseract(monkeypatch):
    import pytesseract

    seen = {}

    def fake_tesseract(image, *a, **k):
        seen["size"] = image.size
        return "OCR TEXT " * 10

    monkeypatch.setattr(pytesseract, "image_to_string", fake_tesseract)
    assert text_mod.ocr_page(make_image_pdf(ELECTRICITY_BILL), 0, 150).startswith("OCR TEXT")
    # A4 at 150 dpi is about 1240 x 1754 px.
    assert abs(seen["size"][0] - 1240) < 5


def test_blank_scan_fails_clearly():
    with pytest.raises(PdfReadError, match="No readable text"):
        extract_text(make_image_pdf([]), ocr=lambda *a: "  \n ")


@pytest.mark.parametrize("data", [b"%PDF-1.4 garbage", b"not a pdf at all", b""])
def test_corrupt_pdf_fails_clearly(data):
    with pytest.raises(PdfReadError):
        extract_text(data)


def test_too_many_pages(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_pdf_pages", 2)
    with pytest.raises(PdfReadError, match="3 pages"):
        extract_text(make_text_pdf([ELECTRICITY_BILL] * 3))
