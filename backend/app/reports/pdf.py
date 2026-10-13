"""Render the inspector report from a snapshot (and nothing else). Deterministic: the same
snapshot and library versions produce byte-identical PDFs (ReportLab invariant mode, fixed
chart metadata), which is how a stored report is verified."""

import io
from decimal import ROUND_HALF_EVEN, Decimal

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from xml.sax.saxutils import escape

from app.reports.charts import facility_chart, monthly_chart

INK = colors.HexColor("#0b0b0b")
INK2 = colors.HexColor("#52514e")
MUTED = colors.HexColor("#898781")
RULE = colors.HexColor("#e1e0d9")
BRAND = colors.HexColor("#065f46")
WARN_BG = colors.HexColor("#fffbeb")
WARN = colors.HexColor("#b45309")
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]
UTILITY = {"electricity": "Electricity", "natural_gas": "Natural gas"}

_base = getSampleStyleSheet()
S = {
    "title": ParagraphStyle("title", parent=_base["Title"], fontName="Helvetica-Bold", fontSize=24, leading=30,
                            alignment=TA_LEFT, textColor=INK, spaceAfter=6),
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=INK, spaceBefore=4, spaceAfter=8),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=INK, spaceBefore=10, spaceAfter=4),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9, leading=13, textColor=INK, spaceAfter=5),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=7.5, leading=10, textColor=INK2),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=7.5, leading=9.5, textColor=INK),
    "cellr": ParagraphStyle("cellr", fontName="Helvetica", fontSize=7.5, leading=9.5, textColor=INK, alignment=2),
    "big": ParagraphStyle("big", fontName="Helvetica-Bold", fontSize=26, leading=30, textColor=INK),
    "label": ParagraphStyle("label", fontName="Helvetica", fontSize=8.5, leading=11, textColor=INK2),
}
CO2E = "tCO<sub>2</sub>e"


def _t(kg: str | Decimal) -> str:
    """kg (exact) -> tonnes, 3 dp, thousands separators."""
    return f"{(Decimal(kg) / 1000).quantize(Decimal('0.001'), rounding=ROUND_HALF_EVEN):,}"


def _kg3(kg: str | Decimal) -> str:
    return f"{Decimal(kg).quantize(Decimal('0.001'), rounding=ROUND_HALF_EVEN):,}"


def _num(v: str) -> str:
    d = Decimal(v)
    s = f"{d.normalize():,f}" if d != d.to_integral_value() else f"{d.to_integral_value():,}"
    return s


def _value(v):
    """Correction values are stored as strings; show numbers without storage padding."""
    if v is None:
        return None
    try:
        return _num(v)
    except (ArithmeticError, ValueError):
        return v


def _month(ym: str) -> str:
    return f"{MONTHS[int(ym[5:]) - 1][:3]} {ym[:4]}"


def _p(text: str, style="cell") -> Paragraph:
    return Paragraph(text, S[style])


def _e(v) -> str:
    return escape(str(v)) if v is not None else "—"


def _table(rows, widths, header_rows=1, right_cols=(), zebra=True, total_row=False):
    t = Table(rows, colWidths=widths, repeatRows=header_rows)
    style = [
        ("FONTNAME", (0, 0), (-1, header_rows - 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("TEXTCOLOR", (0, 0), (-1, header_rows - 1), INK2),
        ("LINEBELOW", (0, header_rows - 1), (-1, header_rows - 1), 0.6, INK2),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    for c in right_cols:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    if zebra:
        for i in range(header_rows, len(rows)):
            if (i - header_rows) % 2 == 1:
                style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f7f7f5")))
    if total_row:
        style += [("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("LINEABOVE", (0, -1), (-1, -1), 0.6, INK2),
                  ("BACKGROUND", (0, -1), (-1, -1), colors.white)]
    t.setStyle(TableStyle(style))
    return t


def _image(png: bytes, width: float) -> Image:
    img = Image(io.BytesIO(png))
    ratio = img.imageHeight / img.imageWidth
    img.drawWidth, img.drawHeight = width, width * ratio
    return img


class _NumberedCanvas(rl_canvas.Canvas):
    """Two-pass canvas so the footer can say 'page X of Y'."""

    def __init__(self, *args, footer=None, draft=False, **kwargs):
        super().__init__(*args, **kwargs)
        self._pages, self._footer, self._draft = [], footer, draft

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self._decorate(total)
            super().showPage()
        super().save()

    def _decorate(self, total):
        w, h = A4
        self.saveState()
        if self._draft:
            self.setFillColor(colors.Color(0.85, 0.47, 0.03, alpha=0.10))
            self.setFont("Helvetica-Bold", 90)
            self.translate(w / 2, h / 2)
            self.rotate(45)
            self.drawCentredString(0, -30, "DRAFT")
            self.rotate(-45)
            self.translate(-w / 2, -h / 2)
        self.setStrokeColor(RULE)
        self.setLineWidth(0.5)
        self.line(18 * mm, 14 * mm, w - 18 * mm, 14 * mm)
        self.setFont("Helvetica", 7)
        self.setFillColor(MUTED)
        self.drawString(18 * mm, 10 * mm, self._footer)
        self.drawRightString(w - 18 * mm, 10 * mm, f"Page {self._pageNumber} of {total}")
        self.restoreState()


def render_pdf(snapshot: dict) -> bytes:
    org, period, summary = snapshot["organization"], snapshot["period"], snapshot["summary"]
    draft = summary["is_draft"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=20 * mm,
        title=f"GHG emissions report - {org['name']} - {period['label']}", author="GreenTrace",
        subject=f"Report {snapshot['report_id']}", creator="GreenTrace", invariant=1,
    )
    width = A4[0] - 36 * mm
    story = []
    story += _cover(snapshot, draft)
    story += _summary(snapshot, width)
    story += _breakdowns(snapshot, width)
    story += _methodology(snapshot, width)
    story += _appendix(snapshot, width)

    footer = f"{org['name']} · GHG emissions {period['label']} · Report {snapshot['report_id']}" + (" · DRAFT" if draft else "")
    doc.build(story, canvasmaker=lambda *a, **k: _NumberedCanvas(*a, footer=footer, draft=draft, **k))
    return buf.getvalue()


# ---------------------------------------------------------------- sections

def _cover(snap, draft):
    org, period, summary = snap["organization"], snap["period"], snap["summary"]
    status = (
        '<font color="#b45309"><b>DRAFT</b></font> - '
        f'{summary["bills_excluded"]} bill(s) that may belong to this period are not included (see Appendix C).'
        if draft else '<font color="#065f46"><b>COMPLETE</b></font> - every bill for the period is approved and calculated.'
    )
    rows = [
        ["Organization", _p(_e(org["name"]), "body")],
        ["Reporting period", _p(f"{_e(period['label'])} ({period['start']} to {period['end']})", "body")],
        ["Reporting framework", _p(_e(org["reporting_framework"]), "body")],
        ["Status", _p(status, "body")],
        ["Generated", _p(f"{snap['generated_at'][:19].replace('T', ' ')} UTC by {_e(snap['generated_by']['email'])}", "body")],
        ["Report ID", _p(f"<font face='Courier'>{snap['report_id']}</font>", "body")],
        ["Calculation engine", _p(f"GreenTrace engine v{_e(snap['engine_version'])}, snapshot schema v{snap['schema_version']}", "body")],
    ]
    t = Table(rows, colWidths=[42 * mm, None])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica"), ("FONTSIZE", (0, 0), (0, -1), 9), ("TEXTCOLOR", (0, 0), (0, -1), INK2),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return [
        Spacer(1, 40 * mm),
        Paragraph("GREENHOUSE GAS EMISSIONS REPORT", ParagraphStyle("k", fontName="Helvetica-Bold", fontSize=9, textColor=BRAND, spaceAfter=8)),
        Paragraph(_e(org["name"]), S["title"]),
        Paragraph(f"Scope 1 and Scope 2 emissions from purchased electricity and natural gas, {_e(period['label'])}", S["body"]),
        Spacer(1, 14 * mm),
        t,
        Spacer(1, 18 * mm),
        Paragraph(
            "Every figure in this report traces to a source bill: Appendix A lists each bill with its quantity, "
            "emission factor and result, and Appendix B every manual correction. A JSON snapshot of all data "
            "used is stored with the report so it can be reproduced exactly.", S["small"]),
        PageBreak(),
    ]


def _summary(snap, width):
    s = snap["summary"]
    total = Decimal(s["total_kg"])

    def share(kg):
        return f"{(Decimal(kg) * 100 / total).quantize(Decimal('0.1'))}%" if total else "—"

    head = Table([
        [_p("Total emissions", "label"), _p("Scope 1", "label"), _p("Scope 2 (location-based)", "label")],
        [_p(f"{_t(s['total_kg'])}", "big"), _p(f"{_t(s['scope1_kg'])}", "big"), _p(f"{_t(s['scope2_kg'])}", "big")],
        [_p(CO2E, "label"), _p(f"{CO2E} · {share(s['scope1_kg'])}", "label"), _p(f"{CO2E} · {share(s['scope2_kg'])}", "label")],
    ], colWidths=[width / 3] * 3)
    head.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 1)]))

    story = [Paragraph("Executive summary", S["h1"]), head, Spacer(1, 6 * mm)]
    rounded_sum = Decimal(_t(s["scope1_kg"]).replace(",", "")) + Decimal(_t(s["scope2_kg"]).replace(",", ""))
    notes = [
        f"{s['bills_included']} utility bills are included: {s['bills_human_reviewed']} approved by a reviewer and "
        f"{s['bills_included'] - s['bills_human_reviewed']} approved automatically because every validation rule passed.",
    ]
    if rounded_sum != Decimal(_t(s["total_kg"]).replace(",", "")):
        notes.append("Each figure is rounded to 0.001 t from exact values; Scope 1 + Scope 2 may differ from the total by 0.001 t.")
    if Decimal(s["co2_only_kg"]):
        notes.append(f"{_t(s['co2_only_kg'])} {CO2E} of the total uses grid emission factors that cover CO<sub>2</sub> only "
                     "(Central Electricity Authority, India); CH<sub>4</sub> and N<sub>2</sub>O from grid electricity are not "
                     "included in those figures.")
    for n in notes:
        story.append(Paragraph(n, S["body"]))
    if s["is_draft"]:
        box = Table([[Paragraph(
            f"<b>Draft - totals are incomplete.</b> {s['bills_excluded']} bill(s) that may fall in this period are not "
            "included because they are awaiting review, still processing, failed extraction, or could not be calculated. "
            "They are listed in Appendix C. Do not submit this report until it is regenerated as complete.", S["body"])]],
            colWidths=[width])
        box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), WARN_BG), ("BOX", (0, 0), (-1, -1), 0.8, WARN),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                                 ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story += [Spacer(1, 3 * mm), box]
    return story


def _breakdowns(snap, width):
    s = snap["summary"]
    story = [Spacer(1, 6 * mm), Paragraph("Emissions by month", S["h2"])]
    if s["bills_included"]:
        story.append(_image(monthly_chart(s["monthly"]), width))
    rows = [["Month", f"Scope 1 ({CO2E})", f"Scope 2 ({CO2E})", f"Total ({CO2E})"]]
    rows = [[_p(c, "cell") if i == 0 else _p(c, "cellr") for i, c in enumerate(rows[0])]]
    for m in s["monthly"]:
        rows.append([_month(m["month"]), _t(m["scope1_kg"]), _t(m["scope2_kg"]), _t(m["total_kg"])])
    rows.append(["Total", _t(s["scope1_kg"]), _t(s["scope2_kg"]), _t(s["total_kg"])])
    story.append(KeepTogether([_table(rows, [width * 0.31, width * 0.23, width * 0.23, width * 0.23], right_cols=(1, 2, 3), total_row=True)]))

    story += [PageBreak(), Paragraph("Emissions by facility", S["h2"])]
    if s["by_facility"]:
        story.append(_image(facility_chart(s["by_facility"]), width))
    region = {}
    for r in snap["records"]:
        region[r["facility"]] = r["facility_region"]
    rows = [[_p("Facility", "cell"), _p("Grid region", "cell"), _p(f"Scope 1 ({CO2E})", "cellr"),
             _p(f"Scope 2 ({CO2E})", "cellr"), _p(f"Total ({CO2E})", "cellr"), _p("Share", "cellr")]]
    total = Decimal(s["total_kg"])
    for f in s["by_facility"]:
        share = f"{(Decimal(f['total_kg']) * 100 / total).quantize(Decimal('0.1'))}%" if total else "—"
        rows.append([_p(_e(f["facility"])), region.get(f["facility"], ""), _t(f["scope1_kg"]), _t(f["scope2_kg"]), _t(f["total_kg"]), share])
    rows.append(["Total", "", _t(s["scope1_kg"]), _t(s["scope2_kg"]), _t(s["total_kg"]), "100.0%" if total else "—"])
    story.append(_table(rows, [width * 0.30, width * 0.12, width * 0.15, width * 0.15, width * 0.15, width * 0.13],
                        right_cols=(2, 3, 4, 5), total_row=True))
    return story


def _methodology(snap, width):
    fy = snap["organization"]["fiscal_year_start_month"]
    story = [PageBreak(), Paragraph("Methodology", S["h1"])]
    paras = [
        ("Standard and boundary",
         "Emissions are reported following the GHG Protocol Corporate Standard and its Scope 2 Guidance. The boundary "
         "covers the facilities listed in this report. <b>Scope 1</b>: direct emissions from natural gas burned on site "
         "(stationary combustion). <b>Scope 2</b>: indirect emissions from purchased grid electricity, reported "
         "<b>location-based</b> using grid-average emission factors. Market-based Scope 2 and Scope 3 (including "
         "transmission and distribution losses and well-to-tank emissions) are not included."),
        ("Activity data",
         "Consumption is taken from utility bills. Text is read from each PDF (with OCR for scanned bills) and a language "
         "model extracts the printed values - quantity, unit, billing period, account - without performing any "
         "calculation. Deterministic validation rules then check every extraction (unit, period length, positive "
         "quantity, the quoted source text appearing on the cited page, consistency with meter readings, unusual "
         "consumption against the facility's history, duplicate periods). Any failed rule or low model confidence sends "
         "the bill to a human reviewer; only approved bills are included. Corrections made by reviewers are listed in "
         "Appendix B. When only meter readings are printed, consumption = (current - previous) x multiplier."),
        ("Calculation",
         "kgCO<sub>2</sub>e = quantity x (days allocated / days in billing period) x unit conversion x emission factor. "
         "Billing periods are inclusive of both dates. A bill spanning more than one calendar month - or a reporting-year "
         f"boundary (reporting years start in {MONTHS[fy - 1]}) or a change of emission factor - is split by day count, "
         "assuming uniform consumption, and each part uses the factor valid for its dates. Unit conversions use exact "
         "definitions (1 kWh = 3.6 MJ; 1 therm = 100,000 Btu(IT); 1 ft<sup>3</sup> = 0.028316846592 m<sup>3</sup>); volume "
         "is never converted to energy without a published factor in that unit. Calculations use exact decimal "
         "arithmetic; each line is rounded to 0.000001 kg and totals are summed before rounding to 0.001 t."),
        ("Emission factors",
         "Factors are stored as versioned data with their source, publication, validity period and region; a bill whose "
         "dates are not covered by a factor is not calculated rather than assigned a factor from another period. Where a "
         "source lists CO<sub>2</sub>, CH<sub>4</sub> and N<sub>2</sub>O separately they are combined with IPCC AR5 100-year "
         "global warming potentials (CH<sub>4</sub> 28, N<sub>2</sub>O 265). The factors used in this report:"),
    ]
    for title, text in paras:
        story += [Paragraph(title, S["h2"]), Paragraph(text, S["body"])]

    rows = [[_p(h) for h in ["Factor (version)", "Applies to", "Value", "Basis", "Valid", "Source"]]]
    for f in snap["factors"]:
        rows.append([
            _p(f"{_e(f['key'])} (v{f['version']}){'<br/><i>organization-specific</i>' if f['owner'] == 'organization' else ''}"),
            _p(f"{UTILITY.get(f['utility_type'], f['utility_type'])}, {_e(f['region'])}, scope {f['scope']}"),
            _p(f"{_num(f['kgco2e_per_unit'])} kg/{_e(f['unit'])}", "cellr"),
            _p(_e(f["ghg_basis"]).replace("CO2e", "CO<sub>2</sub>e").replace("CO2", "CO<sub>2</sub>")),
            _p(f"{f['valid_from']} to {f['valid_to'] or 'open'}"),
            _p(f"{_e(f['source_name'])} ({f['publication_year']})<br/><font color='#52514e'>{_e(f['source_url'])}</font>"),
        ])
    if len(rows) == 1:
        rows.append([_p("No factors used (no approved bills in the period)."), "", "", "", "", ""])
    story.append(_table(rows, [width * 0.20, width * 0.15, width * 0.12, width * 0.07, width * 0.14, width * 0.32], right_cols=(2,)))
    story += [
        Paragraph("Limitations", S["h2"]),
        Paragraph("Pro-rating assumes consumption is uniform across each billing period. Estimated meter readings, where "
                  "accepted by a reviewer, are reported as billed. Grid factors are published with a lag and reflect the "
                  "grid average for their stated year.", S["body"]),
    ]
    return story


def _appendix(snap, width):
    story = [PageBreak(), Paragraph("Appendix A - Line items", S["h1"]),
             Paragraph("Each row is the part of one bill allocated to one month. kgCO<sub>2</sub>e is shown to 0.001 kg; "
                       "totals are summed from the exact values.", S["small"]), Spacer(1, 3 * mm)]
    factors = {f["id"]: f for f in snap["factors"]}
    rows = [[_p(h) if i < 3 else _p(h, "cellr") for i, h in enumerate(
        ["Allocated period (share of bill)", "Quantity", "Emission factor", "kgCO<sub>2</sub>e"])]]
    group_rows, current_bill = [], None
    for r in snap["records"]:
        if r["bill_id"] != current_bill:
            current_bill = r["bill_id"]
            approval = f"reviewed by {_e(r['reviewed_by'])}" if r["approval"] == "human" else "auto-approved (all checks passed)"
            group_rows.append(len(rows))
            rows.append([_p(
                f"<b>{_e(r['file_name'])}</b> &nbsp;page {r['page_number'] or '?'} &nbsp;·&nbsp; {_e(r['facility'])} &nbsp;·&nbsp; "
                f"{UTILITY.get(r['utility_type'], '')} &nbsp;·&nbsp; billing period {r['billing_period'][0]} to "
                f"{r['billing_period'][1]} &nbsp;·&nbsp; <font color='#52514e'>{approval}</font>"), "", "", ""])
        f = factors[r["factor_id"]]
        rows.append([
            _p(f"{r['allocation'][0]} to {r['allocation'][1]} ({r['allocation_fraction']} days)"),
            _p(f"{_num(r['bill_quantity'])} {_e(r['bill_unit'])} &rarr; {_num(r['normalized_quantity'])} {_e(r['normalized_unit'])}"),
            _p(f"{_e(f['key'])} v{f['version']}: {_num(f['kgco2e_per_unit'])} kg {_e(f['ghg_basis'])}/{_e(f['unit'])}"),
            _p(_kg3(r["kgco2e"]), "cellr"),
        ])
    rows.append([_p("<b>Total</b>"), "", "", _p(f"<b>{_kg3(snap['summary']['total_kg'])}</b>", "cellr")])
    t = _table(rows, [width * 0.27, width * 0.26, width * 0.33, width * 0.14], right_cols=(3,), zebra=False, total_row=True)
    t.setStyle(TableStyle(
        [("SPAN", (0, i), (-1, i)) for i in group_rows]
        + [("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f2f2ef")) for i in group_rows]
        + [("TOPPADDING", (0, i), (-1, i), 4) for i in group_rows]
    ))
    story.append(t)

    story += [PageBreak(), Paragraph("Appendix B - Manual corrections", S["h1"])]
    corr = [[_p(h) for h in ["Bill", "Field", "Value read from bill", "Corrected value", "Reviewer", "Approved at (UTC)"]]]
    seen = set()
    for r in snap["records"]:
        if r["bill_id"] in seen or not r["corrections"]:
            continue
        seen.add(r["bill_id"])
        for field, ch in sorted(r["corrections"].items()):
            corr.append([_p(_e(r["file_name"])), _p(_e(field.replace("_", " "))), _p(_e(_value(ch.get("before")))),
                         _p(_e(_value(ch.get("after")))), _p(_e(r["reviewed_by"])), _p(_e((r["reviewed_at"] or "")[:19].replace("T", " ")))])
    if len(corr) == 1:
        story.append(Paragraph("No values were corrected by reviewers for the bills in this report.", S["body"]))
    else:
        story.append(_table(corr, [width * 0.24, width * 0.13, width * 0.16, width * 0.16, width * 0.17, width * 0.14]))

    story += [Spacer(1, 6 * mm), Paragraph("Appendix C - Bills not included", S["h1"])]
    ex = snap["excluded_bills"]
    if not ex:
        story.append(Paragraph("None: every bill that may belong to this period is approved and calculated.", S["body"]))
    else:
        rows = [[_p(h) for h in ["Bill", "Facility", "Billing period", "Reason"]]]
        for b in ex:
            per = f"{b['billing_period'][0]} to {b['billing_period'][1]}" if b["billing_period"] else "not known"
            rows.append([_p(_e(b["file_name"])), _p(_e(b["facility"])), _p(per), _p(_e(b["reason"]))])
        story.append(_table(rows, [width * 0.36, width * 0.15, width * 0.17, width * 0.32]))
    story += [Spacer(1, 8 * mm), Paragraph(
        f"Snapshot: the data behind this report is stored as JSON with report {snap['report_id']}. Regenerating the PDF "
        "from that snapshot reproduces this document exactly.", S["small"])]
    return story
