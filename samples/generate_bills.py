"""Generate the synthetic sample bills and their ground-truth manifest.

    backend/.venv/Scripts/python samples/generate_bills.py

All providers, addresses and account numbers are FICTIONAL. Bills imitate common layouts
(Indian DISCOM, Indian gas, UK supplier, US utility) without copying any real company's design.

manifest.json records, per bill: the values printed on it (what a perfect extraction returns)
and the expected kg CO2e, worked out by hand from the seeded emission factors - see the
`expected_working` strings. Integration tests compare the whole pipeline against it.
"""

import io
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

HERE = Path(__file__).resolve().parent
OUT = HERE / "bills"

BILLS = [
    {
        "file": "in-pune-electricity-2024-01.pdf", "org": "IN", "facility": "Pune Plant",
        "provider": "Sahyadri Power Distribution Ltd (fictional)", "account": "PN-4471-0098-2210",
        "address": "Plot 14, Chakan Industrial Area, Pune 410501",
        "period": ("2024-01-01", "2024-01-31"), "printed_period": "01-01-2024 to 31-01-2024",
        "meter": ("458210", "472460", "1"), "quantity": "14250", "unit": "kWh",
        "qty_line": ("Units Consumed (kWh)", "14,250"), "amount": "Rs 1,42,870.00",
        "expected_kg": "10359.750000",
        "expected_working": "14,250 kWh = 14.25 MWh x 727 kg CO2/MWh (CEA FY2023-24)",
        "style": "india",
    },
    {
        "file": "in-pune-electricity-2024-03-cross-fy.pdf", "org": "IN", "facility": "Pune Plant",
        "provider": "Sahyadri Power Distribution Ltd (fictional)", "account": "PN-4471-0098-2210",
        "address": "Plot 14, Chakan Industrial Area, Pune 410501",
        "period": ("2024-03-16", "2024-04-15"), "printed_period": "16-03-2024 to 15-04-2024",
        "meter": ("486710", "499110", "1"), "quantity": "12400", "unit": "kWh",
        "qty_line": ("Units Consumed (kWh)", "12,400"), "amount": "Rs 1,24,310.00",
        "expected_kg": "8912.800000",
        "expected_working": "31 days across the 1 April financial-year boundary: 16/31 x 12,400 = 6,400 kWh x 0.727 = "
                            "4,652.8 (FY2023-24) + 15/31 x 12,400 = 6,000 kWh x 0.710 = 4,260.0 (FY2024-25)",
        "style": "india",
    },
    {
        "file": "in-chennai-electricity-2024-02-meter-readings.pdf", "org": "IN", "facility": "Chennai Plant",
        "provider": "Coromandel Electricity Board (fictional)", "account": "CH-07-112-90341",
        "address": "SIDCO Estate, Irungattukottai, Chennai 602117",
        "period": ("2024-02-01", "2024-02-29"), "printed_period": "01/02/2024 - 29/02/2024",
        "meter": ("182450", "183410", "20"), "quantity": None, "unit": "kWh",
        "qty_line": None, "amount": "Rs 1,91,880.00",
        "expected_kg": "13958.400000",
        "expected_working": "No total printed: (183,410 - 182,450) x MF 20 = 19,200 kWh = 19.2 MWh x 727 (CEA FY2023-24)",
        "style": "india_meter_only",
    },
    {
        "file": "in-chennai-gas-2024-02-mmbtu.pdf", "org": "IN", "facility": "Chennai Plant",
        "provider": "Bay of Bengal Gas Transmission Ltd (fictional)", "account": "GTX-CHN-000418",
        "address": "SIDCO Estate, Irungattukottai, Chennai 602117",
        "period": ("2024-02-01", "2024-02-29"), "printed_period": "01-Feb-2024 to 29-Feb-2024",
        "meter": None, "quantity": "650", "unit": "MMBTU",
        "qty_line": ("Gas Quantity Supplied (MMBTU)", "650.000"), "amount": "Rs 47,25,500.00",
        "expected_kg": "38509.987019",
        "expected_working": "650 MMBtu x 0.00105505585262 TJ/MMBtu = 0.685786304203 TJ x 56,154.5 kg CO2e/TJ (IPCC 2006)",
        "style": "india_gas",
    },
    {
        "file": "in-pune-electricity-2024-02-scanned.pdf", "org": "IN", "facility": "Pune Plant",
        "provider": "Sahyadri Power Distribution Ltd (fictional)", "account": "PN-4471-0098-2210",
        "address": "Plot 14, Chakan Industrial Area, Pune 410501",
        "period": ("2024-02-01", "2024-02-29"), "printed_period": "01-02-2024 to 29-02-2024",
        "meter": ("472460", "485560", "1"), "quantity": "13100", "unit": "kWh",
        "qty_line": ("Units Consumed (kWh)", "13,100"), "amount": "Rs 1,31,450.00",
        "expected_kg": "9523.700000",
        "expected_working": "13,100 kWh = 13.1 MWh x 727 (CEA FY2023-24). Image-only PDF: needs OCR.",
        "style": "scanned",
    },
    {
        "file": "in-chennai-electricity-2023-12-two-pages.pdf", "org": "IN", "facility": "Chennai Plant",
        "provider": "Coromandel Electricity Board (fictional)", "account": "CH-07-112-90341",
        "address": "SIDCO Estate, Irungattukottai, Chennai 602117",
        "period": ("2023-12-01", "2023-12-31"), "printed_period": "01/12/2023 - 31/12/2023",
        "meter": ("181660", "182450", "20"), "quantity": "15800", "unit": "kWh",
        "qty_line": ("Net Energy Consumed (kWh)", "15,800"), "amount": "Rs 1,57,920.00",
        "expected_kg": "11486.600000",
        "expected_working": "15,800 kWh = 15.8 MWh x 727 (CEA FY2023-24); consumption is on page 2",
        "style": "two_pages",
    },
    {
        "file": "uk-london-electricity-2025-12-cross-year.pdf", "org": "UK", "facility": "London Office",
        "provider": "Thames Valley Energy (fictional)", "account": "TVE 8812 4471 09",
        "address": "21 Example Street, London EC1A 1AA",
        "period": ("2025-12-15", "2026-01-14"), "printed_period": "15 Dec 2025 - 14 Jan 2026",
        "meter": ("50120", "53220", "1"), "quantity": "3100", "unit": "kWh",
        "qty_line": ("Electricity used", "3,100 kWh"), "amount": "GBP 868.00",
        "expected_kg": "484.244000",
        "expected_working": "Crosses the calendar year: 17/31 x 3,100 = 1,700 kWh x 0.177 (DESNZ 2025) = 300.9 + "
                            "14/31 x 3,100 = 1,400 kWh x 0.13096 (DESNZ 2026) = 183.344",
        "style": "uk",
    },
    {
        "file": "uk-london-gas-2025-03.pdf", "org": "UK", "facility": "London Office",
        "provider": "Thames Valley Energy (fictional)", "account": "TVE 8812 5530 41",
        "address": "21 Example Street, London EC1A 1AA",
        "period": ("2025-03-01", "2025-03-31"), "printed_period": "01 Mar 2025 - 31 Mar 2025",
        "meter": None, "quantity": "18500", "unit": "kWh",
        "qty_line": ("Gas used", "18,500 kWh"), "amount": "GBP 1,387.50",
        "expected_kg": "3384.760000",
        "expected_working": "18,500 kWh (gross CV) x 0.18296 kg CO2e/kWh (DESNZ 2025 natural gas)",
        "style": "uk_gas",
    },
    {
        "file": "us-sf-electricity-2024-06.pdf", "org": "US", "facility": "San Francisco Lab",
        "provider": "Golden Gate Power & Light (fictional)", "account": "4410-228-917",
        "address": "500 Example Ave, San Francisco, CA 94107",
        "period": ("2024-06-01", "2024-06-30"), "printed_period": "06/01/2024 - 06/30/2024",
        "meter": None, "quantity": "42000", "unit": "kWh",
        "qty_line": ("Total Electricity Usage", "42,000 kWh"), "amount": "$11,340.00",
        "expected_kg": "8191.878202",
        "expected_working": "42,000 kWh = 42 MWh x 430.0 lb CO2e/MWh x 0.45359237 kg/lb (eGRID2023 CAMX)",
        "style": "us",
    },
    {
        "file": "us-sf-gas-2024-11-therms.pdf", "org": "US", "facility": "San Francisco Lab",
        "provider": "Golden Gate Power & Light (fictional)", "account": "4410-228-918",
        "address": "500 Example Ave, San Francisco, CA 94107",
        "period": ("2024-11-01", "2024-11-30"), "printed_period": "11/01/2024 - 11/30/2024",
        "meter": None, "quantity": "1200", "unit": "therms",
        "qty_line": ("Total Gas Usage", "1,200 Therms"), "amount": "$1,956.00",
        "expected_kg": "6373.740000",
        "expected_working": "1,200 therms = 120 MMBtu x 53.1145 kg CO2e/MMBtu (EPA Hub; parent region US)",
        "style": "us_gas",
    },
]

GREEN = colors.HexColor("#1f4e79")


def _header(c, b, w, h, title):
    c.setFillColor(GREEN)
    c.rect(0, h - 28 * mm, w, 28 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(18 * mm, h - 14 * mm, b["provider"])
    c.setFont("Helvetica", 9)
    c.drawString(18 * mm, h - 21 * mm, title)
    c.setFillColor(colors.black)


def _rows(c, x, y, rows, size=9, gap=5.5 * mm, bold_last=False):
    for i, (k, v) in enumerate(rows):
        c.setFont("Helvetica-Bold" if bold_last and i == len(rows) - 1 else "Helvetica", size)
        c.drawString(x, y, k)
        c.drawRightString(x + 160 * mm, y, v)
        y -= gap
    return y


def _consumption_rows(b):
    rows = []
    if b["meter"]:
        prev, cur, mf = b["meter"]
        unit = "kWh" if "gas" not in b["style"] else b["unit"]
        rows += [(f"Previous Reading ({unit})", prev), (f"Current Reading ({unit})", cur), ("Multiplying Factor (MF)", mf)]
    if b["qty_line"]:
        rows.append(b["qty_line"])  # (label, value as printed)
    return rows


def draw_bill(c, b, pagesize):
    w, h = pagesize
    style = b["style"]
    is_us = style.startswith("us")
    _header(c, b, w, h, "Tax invoice - electricity" if "gas" not in style else "Gas supply invoice")
    y = h - 40 * mm
    c.setFont("Helvetica", 9)
    for line in [f"Customer: GreenTrace Sample Co. ({b['facility']})", b["address"]]:
        c.drawString(18 * mm, y, line)
        y -= 5 * mm
    y -= 3 * mm
    acct_label = {"india": "Consumer No", "india_meter_only": "Service Connection No", "india_gas": "Customer ID",
                  "two_pages": "Service Connection No", "uk": "Account number", "uk_gas": "Account number",
                  "us": "Account Number", "us_gas": "Account Number", "scanned": "Consumer No"}[style]
    y = _rows(c, 18 * mm, y, [
        (acct_label, b["account"]),
        ("Billing Period" if not style.startswith("uk") else "Billing period", b["printed_period"]),
        ("Bill Date", "05-" + b["period"][1][5:7] + "-" + b["period"][1][:4] if not is_us else "Issued with statement"),
        ("Read Type", "Actual" if style != "uk" else "Actual (smart meter)"),
    ])
    y -= 4 * mm
    if style == "two_pages":
        c.setFont("Helvetica-Bold", 11)
        c.drawString(18 * mm, y, "Bill summary")
        y -= 7 * mm
        _rows(c, 18 * mm, y, [("Energy charges", b["amount"]), ("Total amount payable", b["amount"])], bold_last=True)
        c.setFont("Helvetica", 8)
        c.drawString(18 * mm, 20 * mm, "Consumption details are on page 2.")
        c.showPage()
        _header(c, b, w, h, "Consumption details")
        y = h - 40 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(18 * mm, y, "Consumption" if not is_us else "Usage summary")
    y -= 7 * mm
    y = _rows(c, 18 * mm, y, _consumption_rows(b))
    y -= 4 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(18 * mm, y, "Charges")
    y -= 7 * mm
    _rows(c, 18 * mm, y, [("Fixed charges", "included"), ("Energy charges", b["amount"]), ("Amount due", b["amount"])],
          bold_last=True)
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.grey)
    c.drawString(18 * mm, 12 * mm, "SAMPLE DOCUMENT - fictional supplier, generated for GreenTrace testing.")
    c.setFillColor(colors.black)
    c.showPage()


def text_pdf(b) -> bytes:
    buf = io.BytesIO()
    pagesize = LETTER if b["style"].startswith("us") else A4
    c = canvas.Canvas(buf, pagesize=pagesize, invariant=1)
    draw_bill(c, b, pagesize)
    c.save()
    return buf.getvalue()


def scanned_pdf(b) -> bytes:
    """Render the bill to an image, degrade it like a photocopy, and embed only the image."""
    import pypdfium2

    page = pypdfium2.PdfDocument(text_pdf({**b, "style": "india"}))[0]
    img = page.render(scale=150 / 72).to_pil().convert("L")
    rng = random.Random(7)
    img = img.rotate(0.6, resample=Image.BICUBIC, expand=False, fillcolor=255)
    noise = Image.effect_noise(img.size, 18).point(lambda v: 255 if v > 120 else 230)
    img = Image.composite(img, noise, img.point(lambda v: 255 if v < 200 else 0)).filter(ImageFilter.GaussianBlur(0.6))
    draw = ImageDraw.Draw(img)
    for _ in range(40):  # specks
        x, y = rng.randrange(img.width), rng.randrange(img.height)
        draw.ellipse((x, y, x + 2, y + 2), fill=150)
    jpeg = io.BytesIO()
    img.save(jpeg, format="JPEG", quality=70)  # JPEG is embedded as-is (DCT), keeping the file small
    jpeg.seek(0)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    c.drawImage(ImageReader(jpeg), 0, 0, width=A4[0], height=A4[1])
    c.showPage()
    c.save()
    return buf.getvalue()


def ground_truth(b, pdf: bytes) -> dict:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        pages = [p.extract_text() or "" for p in doc.pages]
    label = b["qty_line"][0] if b["qty_line"] else "Previous Reading"
    if b["style"] == "scanned":
        page_number, snippet = 1, " ".join(b["qty_line"])  # as printed; OCR output may differ slightly
    else:
        # The snippet is the exact line pdfplumber extracts, as a faithful model would quote it.
        page_number = next(i + 1 for i, t in enumerate(pages) if any(line.startswith(label) for line in t.splitlines()))
        lines = pages[page_number - 1].splitlines()
        if b["qty_line"]:
            snippet = next(line for line in lines if line.startswith(label))
        else:
            i = next(i for i, line in enumerate(lines) if line.startswith("Previous Reading"))
            snippet = "\n".join(lines[i:i + 3])
    prev, cur, mf = b["meter"] or (None, None, None)
    utility = "natural_gas" if "gas" in b["style"] else "electricity"
    return {
        "utility_type": utility,
        "provider_name": b["provider"],
        "account_number": b["account"],
        "billing_period_start": b["period"][0],
        "billing_period_end": b["period"][1],
        "quantity": b["quantity"],
        "unit": b["unit"],
        "meter_readings": {"previous": prev, "current": cur, "multiplier": mf},
        "read_type": "actual",
        "multiple_meters_or_line_items": False,
        "page_number": page_number,
        "source_snippet": snippet,
        "confidence": 0.97,
        "notes": None,
    }


def main():
    OUT.mkdir(exist_ok=True)
    manifest = []
    for b in BILLS:
        pdf = scanned_pdf(b) if b["style"] == "scanned" else text_pdf(b)
        (OUT / b["file"]).write_bytes(pdf)
        manifest.append({
            "file": f"bills/{b['file']}", "org": b["org"], "facility": b["facility"],
            "requires_ocr": b["style"] == "scanned",
            "expected_extraction": ground_truth(b, pdf),
            "expected_kgco2e": b["expected_kg"],
            "expected_working": b["expected_working"],
        })
        print(f"{b['file']:<52} {len(pdf):>7} bytes")
    (HERE / "manifest.json").write_text(json.dumps({
        "note": "Synthetic bills from fictional suppliers. expected_extraction = values printed on each bill; "
                "expected_kgco2e = hand-worked result using the seeded emission factors (see expected_working).",
        "organizations": {
            "IN": {"region_by_facility": {"Pune Plant": "IN", "Chennai Plant": "IN"}, "fiscal_year_start_month": 4, "framework": "BRSR"},
            "UK": {"region_by_facility": {"London Office": "UK"}, "fiscal_year_start_month": 1, "framework": "SECR"},
            "US": {"region_by_facility": {"San Francisco Lab": "US-CAMX"}, "fiscal_year_start_month": 1, "framework": "EPA"},
        },
        "bills": manifest,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"{len(manifest)} bills + manifest.json written")


if __name__ == "__main__":
    main()
