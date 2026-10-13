"""Render a bill page as PNG for the review screen, with the extraction's source snippet
highlighted when it can be located in the PDF's text layer."""

import io
import re
from dataclasses import dataclass

import pdfplumber
import pypdfium2
from PIL import Image, ImageDraw


@dataclass
class RenderedPage:
    png: bytes
    page_count: int
    highlight: str  # "found" | "not_found" | "no_text_layer" | "none"


def _snippet_pattern(snippet: str) -> str | None:
    words = snippet.split()
    if not words:
        return None
    # Tolerate any whitespace / line breaks between words, as text extraction does.
    return r"\s+".join(re.escape(w) for w in words)


def _find_boxes(pdf_bytes: bytes, page_index: int, snippet: str) -> tuple[list[tuple], str]:
    pattern = _snippet_pattern(snippet)
    if pattern is None:
        return [], "none"
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[page_index]
        if not (page.extract_text() or "").strip():
            return [], "no_text_layer"
        matches = page.search(pattern, regex=True, case=False, return_chars=True)
        if not matches:
            # Long snippets often wrap oddly; fall back to its longest line.
            longest = max(snippet.splitlines(), key=len, default="")
            p2 = _snippet_pattern(longest)
            matches = page.search(p2, regex=True, case=False, return_chars=True) if p2 and p2 != pattern else []
        boxes = []
        for m in matches:
            # One box per text line so wrapped snippets highlight correctly.
            lines: dict[int, list] = {}
            for c in m.get("chars", []):
                lines.setdefault(round(c["top"]), []).append(c)
            if not lines:
                boxes.append((m["x0"], m["top"], m["x1"], m["bottom"]))
            for chars in lines.values():
                boxes.append((min(c["x0"] for c in chars), min(c["top"] for c in chars),
                              max(c["x1"] for c in chars), max(c["bottom"] for c in chars)))
        return boxes, "found" if boxes else "not_found"


def render_page(pdf_bytes: bytes, page_number: int, snippet: str | None = None, dpi: int = 110) -> RenderedPage:
    pdf = pypdfium2.PdfDocument(pdf_bytes)
    try:
        count = len(pdf)
        if not 1 <= page_number <= count:
            raise IndexError(f"Page {page_number} does not exist (the bill has {count})")
        image = pdf[page_number - 1].render(scale=dpi / 72).to_pil().convert("RGB")
    finally:
        pdf.close()

    status = "none"
    if snippet:
        boxes, status = _find_boxes(pdf_bytes, page_number - 1, snippet)
        if boxes:
            scale, pad = dpi / 72, 3
            overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            for x0, top, x1, bottom in boxes:
                rect = (x0 * scale - pad, top * scale - pad, x1 * scale + pad, bottom * scale + pad)
                draw.rectangle(rect, fill=(250, 204, 21, 90), outline=(202, 138, 4, 255), width=2)
            image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")

    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return RenderedPage(buf.getvalue(), count, status)
