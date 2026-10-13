"""Test helpers: generate real PDFs (text-layer and image-only) and a scriptable fake LLM."""

import io
import json
from collections.abc import Callable

from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

ELECTRICITY_BILL = [
    "Maharashtra State Electricity Distribution Co. Ltd",
    "Consumer No: 170012345678",
    "Billing Period: 01-04-2024 to 30-04-2024",
    "Previous Reading: 45210   Current Reading: 57710   MF: 1",
    "Units Consumed (kWh): 12,500",
    "Amount Payable: Rs 1,12,345.00",
]


def make_pdf(pages: list[tuple[str, list[str]]]) -> bytes:
    """pages: ("text", lines) for a normal page, ("image", lines) for a scanned page with no text layer."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for kind, lines in pages:
        if kind == "text":
            y = 800
            for line in lines:
                c.drawString(50, y, line)
                y -= 18
        else:
            img = Image.new("RGB", (1240, 1754), "white")
            draw = ImageDraw.Draw(img)
            for i, line in enumerate(lines):
                draw.text((80, 100 + i * 40), line, fill="black")
            c.drawImage(ImageReader(img), 0, 0, width=A4[0], height=A4[1])
        c.showPage()
    c.save()
    return buf.getvalue()


def make_text_pdf(pages: list[list[str]]) -> bytes:
    return make_pdf([("text", lines) for lines in pages])


def make_image_pdf(lines: list[str]) -> bytes:
    return make_pdf([("image", lines)])


def llm_json(**overrides) -> dict:
    """A valid model response for ELECTRICITY_BILL; override fields per test."""
    data = {
        "utility_type": "electricity",
        "provider_name": "Maharashtra State Electricity Distribution Co. Ltd",
        "account_number": "170012345678",
        "billing_period_start": "2024-04-01",
        "billing_period_end": "2024-04-30",
        "quantity": "12500",
        "unit": "kWh",
        "meter_readings": {"previous": "45210", "current": "57710", "multiplier": "1"},
        "read_type": "actual",
        "multiple_meters_or_line_items": False,
        "page_number": 1,
        "source_snippet": "Units Consumed (kWh): 12,500",
        "confidence": 0.97,
        "notes": None,
    }
    data.update(overrides)
    return data


def _dumps(d: dict) -> str:
    # Quantities as JSON numbers, like a real model would send (json writes 0.1 as "0.1").
    def num(v):
        if not isinstance(v, str):
            return v
        return int(v) if v.isdigit() else float(v)

    out = dict(d)
    if isinstance(out.get("quantity"), str):
        out["quantity"] = num(out["quantity"])
    if isinstance(out.get("meter_readings"), dict):
        out["meter_readings"] = {k: num(v) for k, v in out["meter_readings"].items()}
    return json.dumps(out)


class FakeExtractor:
    """Returns scripted responses. Each item is a dict (serialized), a raw string, an
    exception (raised), or a callable(document_text) -> any of those."""

    model_name = "fake-model"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, str | None]] = []

    def extract(self, document_text: str, correction: str | None = None) -> str:
        self.calls.append((document_text, correction))
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Callable) and not isinstance(r, type):
            r = r(document_text)
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, str) else _dumps(r)
