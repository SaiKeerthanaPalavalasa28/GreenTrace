"""Reads an uploaded PDF for one GHG scope: finds quantities, converts them to kg CO2e with
indicative emission factors, and flags anything that looks suspicious.

This is deliberately plain code (no AI): the same file always gives the same numbers and flags.
Factors are INDICATIVE averages (DEFRA / IPCC / CEA order of magnitude) so the dashboard works out
of the box; replace them with your verified factors before external reporting.
"""

import io
import re
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime

import pdfplumber

# ------------------------------------------------------------------ factor catalogue
GRID_KG_PER_KWH = {"IN": 0.71, "UK": 0.207, "GB": 0.207, "US": 0.37, "EU": 0.25}
GRID_DEFAULT = 0.45
REFRIGERANT_KG = [(r"r-?410a", 2088), (r"r-?134a", 1430), (r"r-?404a", 3922), (r"r-?407c", 1774),
                  (r"r-?32\b", 675), (r"r-?22\b", 1810)]


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    scope: int
    keywords: str  # regex matched against the lowercase line
    factors: dict  # family -> kg CO2e per native unit of that family
    source: str


CATEGORIES: list[Category] = [
    # Scope 1: direct emissions
    Category("diesel", "Diesel", 1, r"diesel|hsd|genset|generator", {"l": 2.68}, "IPCC/DEFRA"),
    Category("petrol", "Petrol / gasoline", 1, r"petrol|gasoline", {"l": 2.31}, "IPCC/DEFRA"),
    Category("fuel_oil", "Furnace / fuel oil", 1, r"furnace oil|fuel oil|\bfo\b|\bldo\b", {"l": 3.18}, "DEFRA"),
    Category("lpg", "LPG", 1, r"\blpg\b|propane", {"l": 1.56, "kg": 2.98}, "DEFRA"),
    Category("natural_gas", "Natural gas", 1, r"natural gas|\bpng\b|\bcng\b|\blng\b|\bgas\b", {"kwh": 0.184, "m3": 2.04}, "DEFRA"),
    Category("coal", "Coal", 1, r"\bcoal\b|coke", {"kg": 2.42}, "IPCC"),
    Category("refrigerant", "Refrigerant leakage", 1, r"refrigerant|\br-?\d{2,3}[a-z]?\b|\bhfc\b", {"kg": 1500.0}, "IPCC AR5 GWP"),
    # Scope 2: purchased energy
    Category("heat_steam", "Purchased steam / heat / cooling", 2, r"steam|district|chilled|cooling|\bheat", {"kwh": 0.2}, "DEFRA"),
    Category("electricity", "Purchased electricity", 2, r"electric|\bgrid\b|\bpower\b|mains|units? consumed", {"kwh": GRID_DEFAULT}, "Grid average"),
    # Scope 3: value chain
    Category("air_travel", "Air travel", 3, r"flight|air ?travel|airline|airfare|\bair\b", {"km": 0.15}, "DEFRA"),
    Category("rail_travel", "Rail travel", 3, r"\brail|train|metro", {"km": 0.035}, "DEFRA"),
    Category("bus_travel", "Bus / coach", 3, r"\bbus\b|coach", {"km": 0.10}, "DEFRA"),
    Category("road_travel", "Taxi / car / commuting", 3, r"taxi|\bcab\b|\bcar\b|uber|rental|commut|vehicle|mileage|employee travel|business travel", {"km": 0.17}, "DEFRA"),
    Category("hotel", "Hotel stays", 3, r"hotel|lodging|accommodation|\bstay", {"nights": 15.0}, "DEFRA"),
    Category("freight", "Freight / logistics", 3, r"freight|shipping|shipment|logistic|haulage|transport|cargo", {"tkm": 0.10}, "DEFRA"),
    Category("waste_recycled", "Waste: recycled / composted", 3, r"recycl|compost", {"kg": 0.02}, "DEFRA"),
    Category("waste_landfill", "Waste: landfill / general", 3, r"waste|landfill|garbage|trash|disposal", {"kg": 0.45}, "DEFRA"),
    Category("water", "Water supply", 3, r"water", {"m3": 0.34}, "DEFRA"),
    Category("paper", "Purchased paper", 3, r"paper|cardboard|carton", {"kg": 1.0}, "DEFRA"),
    Category("plastic", "Purchased plastics", 3, r"plastic|polymer|packaging", {"kg": 3.1}, "DEFRA"),
    Category("steel", "Purchased steel / metals", 3, r"steel|iron|aluminium|aluminum|metal", {"kg": 2.0}, "worldsteel/DEFRA"),
    Category("cement", "Purchased cement / concrete", 3, r"cement|concrete", {"kg": 0.9}, "ICE database"),
]
CAT_BY_KEY = {c.key: c for c in CATEGORIES}

# unit token (lowercase) -> (family, multiplier to the family's native unit)
UNITS = {
    "kwh": ("kwh", 1), "mwh": ("kwh", 1000), "gwh": ("kwh", 1e6),
    "therm": ("kwh", 29.3071), "therms": ("kwh", 29.3071), "mmbtu": ("kwh", 293.071), "gj": ("kwh", 277.778),
    "l": ("l", 1), "ltr": ("l", 1), "ltrs": ("l", 1), "litre": ("l", 1), "litres": ("l", 1),
    "liter": ("l", 1), "liters": ("l", 1), "kl": ("l", 1000),
    "m3": ("m3", 1), "m³": ("m3", 1), "cum": ("m3", 1), "scm": ("m3", 1),
    "kg": ("kg", 1), "kgs": ("kg", 1), "tonne": ("kg", 1000), "tonnes": ("kg", 1000),
    "ton": ("kg", 1000), "tons": ("kg", 1000), "mt": ("kg", 1000),
    "km": ("km", 1), "kms": ("km", 1), "mile": ("km", 1.609), "miles": ("km", 1.609), "pkm": ("km", 1),
    "tkm": ("tkm", 1), "t-km": ("tkm", 1), "tonne-km": ("tkm", 1),
    "night": ("nights", 1), "nights": ("nights", 1),
}
UNIT_RE = "|".join(sorted((re.escape(u) for u in UNITS), key=len, reverse=True))
# sign (directly attached) + number (1,234.5 / 12,34,567 / 12.5) + optional space + unit
QTY_RE = re.compile(
    rf"(?<![\w.])([-−–(]?)(\d{{1,3}}(?:,\d{{2,3}})+(?:\.\d+)?|\d+(?:\.\d+)?)\)?\s?({UNIT_RE})(?![A-Za-z0-9])",
    re.I,
)
# unit first, the way bills print it: "Units Consumed (kWh) 14,250" / "Gas Quantity (MMBTU): 650.000"
QTY_UNIT_FIRST_RE = re.compile(
    rf"\(\s*({UNIT_RE})\s*\)\s*[:=\-]?\s*([-\u2212\u2013]?)(\d{{1,3}}(?:,\d{{2,3}})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\d.]*[A-Za-z%])",
    re.I,
)
READING_RE = re.compile(r"\b(previous|prev|opening|last|current|present|closing)\b.*\breading|\breading\b.*\b(previous|prev|opening|current|present|closing)\b", re.I)
PREV_RE = re.compile(r"\b(previous|prev|opening|last)\b", re.I)
MF_RE = re.compile(r"multipl\w*\s*factor|\bmf\b|\bmultiplier\b|\bcurrent transformer\b|\bCTPT\b", re.I)
NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?")
TOTAL_RE = re.compile(r"\b(grand\s+)?total\b|\bsub-?total\b", re.I)
DATE_RES = [
    re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](20\d{2})\b"),
    re.compile(r"\b(20\d{2})[/\-.](\d{1,2})[/\-.](\d{1,2})\b"),
    re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?:\d{1,2},?\s+)?(20\d{2})\b", re.I),
]
# Plausibility ceilings for ONE line item (native units). Anything above is almost surely a typo.
CEILING = {"kwh": 5e7, "l": 2e6, "m3": 5e6, "kg": 5e7, "km": 5e6, "tkm": 5e8, "nights": 1e5}
EDITORS = re.compile(r"photoshop|gimp|canva|ilovepdf|smallpdf|sejda|pdfescape|pdf24|inkscape|pdf ?editor|pdfsam", re.I)
MIN_TEXT_CHARS = 10


def quantity_matches(line: str):
    """(negative, value, unit text, matched text) for every 'number unit' or '(unit) number' in a line."""
    out = []
    for m in QTY_RE.finditer(line):
        out.append((m.group(1) in ("-", "\u2212", "\u2013"), float(m.group(2).replace(",", "")), m.group(3), m.group(0).strip()))
    for m in QTY_UNIT_FIRST_RE.finditer(line):
        out.append((bool(m.group(2)), float(m.group(3).replace(",", "")), m.group(1), m.group(0).strip()))
    return out


def categories_for(scope: int) -> list[dict]:
    return [{"key": c.key, "label": c.label, "families": [f for f, v in c.factors.items() if v]}
            for c in CATEGORIES if c.scope == scope]


def grid_factor(region: str | None) -> float:
    r = (region or "").upper()
    for prefix, f in GRID_KG_PER_KWH.items():
        if r.startswith(prefix):
            return f
    return GRID_DEFAULT


def factor_for(cat: Category, family: str, line: str, region: str | None) -> float | None:
    if cat.key == "electricity" and family == "kwh":
        return grid_factor(region)
    if cat.key == "refrigerant" and family == "kg":
        low = line.lower()
        for pat, f in REFRIGERANT_KG:
            if re.search(pat, low):
                return float(f)
    f = cat.factors.get(family)
    return float(f) if f else None


def flag(code: str, severity: str, message: str, line: str | None = None) -> dict:
    return {"code": code, "severity": severity, "message": message, "line": (line or "")[:200] or None}


def classify(line: str, scope: int, family: str) -> tuple[Category | None, Category | None]:
    """(category for this scope, category of ANOTHER scope when only that one fits)."""
    low = line.lower()
    for c in CATEGORIES:
        if c.scope == scope and re.search(c.keywords, low):
            return c, None
    for c in CATEGORIES:
        if c.scope != scope and re.search(c.keywords, low):
            return None, c
    # A bare "Energy used: 5,000 kWh" in the Scope 2 tab is purchased electricity.
    if family == "kwh":
        return (CAT_BY_KEY["electricity"], None) if scope == 2 else (None, CAT_BY_KEY["electricity"])
    return None, None


def read_pdf(data: bytes) -> dict:
    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        meta = dict(pdf.metadata or {})
        n = len(pdf.pages)
        for p in pdf.pages[:60]:
            pages.append(p.extract_text() or "")
    return {"pages": pages, "page_count": n, "meta": meta}


def _pdf_date(raw) -> datetime | None:
    m = re.match(r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?", str(raw or ""))
    if not m:
        return None
    parts = [int(g) if g else d for g, d in zip(m.groups(), (0, 1, 1, 0, 0, 0))]
    try:
        return datetime(*parts, tzinfo=UTC)
    except ValueError:
        return None


def analyse(data: bytes, scope: int, region: str | None, history: list[dict],
            budget_kg: float | None, now: datetime | None = None) -> dict:
    """history = the org's earlier documents for this scope: [{"total_kg_co2e":..,"items":[..]}]."""
    now = now or datetime.now(UTC)
    doc = read_pdf(data)
    flags: list[dict] = []
    text = "\n".join(doc["pages"])
    items: list[dict] = []
    control_totals: list[dict] = []
    unclassified: list[str] = []
    wrong_scope: list[tuple[str, Category]] = []
    readings: dict = {}
    multiplier = 1.0

    if len(re.sub(r"\s", "", text)) < MIN_TEXT_CHARS:
        flags.append(flag("unreadable", "high", "No readable text found (a scanned image or empty PDF). "
                          "Nothing could be counted - upload a text-based PDF."))
    else:
        seen: set[tuple] = set()
        for page_no, page_text in enumerate(doc["pages"], start=1):
            for line in page_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                is_total = bool(TOTAL_RE.search(line))
                if MF_RE.search(line) and not quantity_matches(line):
                    nums = NUMBER_RE.findall(line)
                    if nums:
                        mf = float(nums[-1].replace(",", ""))
                        if 0 < mf <= 10000:
                            multiplier = mf
                    continue
                reading = bool(READING_RE.search(line))
                for neg, value, unit_txt, matched in quantity_matches(line):
                    unit = unit_txt.lower()
                    family, mult = UNITS[unit]
                    if reading:
                        readings.setdefault("prev" if PREV_RE.search(line) else "cur", (value, unit_txt, family, mult, line))
                        continue
                    cat, other = classify(line, scope, family)
                    entry = {"line": line[:200], "page": page_no, "quantity": value, "unit": unit_txt,
                             "family": family, "native_qty": value * mult}
                    if is_total:
                        control_totals.append({**entry, "category": cat.key if cat else None, "other": other.key if other else None})
                        continue
                    if neg:
                        flags.append(flag("negative_value", "high", f"Negative quantity ({matched}) - "
                                          "credits are not counted automatically; verify the document.", line))
                        continue
                    if value == 0:
                        flags.append(flag("zero_value", "low", "A quantity of zero was reported.", line))
                        continue
                    if cat is None:
                        if other is not None:
                            wrong_scope.append((line, other))
                        else:
                            unclassified.append(line)
                        continue
                    factor = factor_for(cat, family, line, region)
                    if factor is None:
                        unclassified.append(line)
                        continue
                    key = (cat.key, value, family, line)
                    if key in seen:
                        flags.append(flag("duplicate_line", "medium", "The same line appears more than once - "
                                          "possible double counting.", line))
                    seen.add(key)
                    ceiling = CEILING.get(family)
                    if ceiling and entry["native_qty"] > ceiling:
                        flags.append(flag("implausible_size", "high", f"{value:,.0f} {unit_txt} on one line is "
                                          "implausibly large - likely a typo or extra zeros.", line))
                    items.append({**entry, "category": cat.key, "label": cat.label, "factor": factor,
                                  "factor_source": cat.source, "kg_co2e": entry["native_qty"] * factor, "edited": False})

        # Meter readings: consumption = (current - previous) x multiplier. If the bill also states the
        # consumption, the two must agree.
        derived = None
        if "prev" in readings and "cur" in readings and readings["cur"][0] > readings["prev"][0]:
            _, unit_txt, family, mult, rline = readings["cur"]
            derived = {"line": f"{rline} (previous {readings['prev'][0]:,.0f}, multiplier {multiplier:g})"[:200], "page": 1,
                       "quantity": (readings["cur"][0] - readings["prev"][0]) * multiplier, "unit": unit_txt,
                       "family": family, "native_qty": (readings["cur"][0] - readings["prev"][0]) * multiplier * mult}
            dcat, dother = classify(rline, scope, family)
            derived["cat"], derived["other"] = dcat, dother
        stated = [i for i in items if derived and i["family"] == derived["family"]]
        if derived and stated:
            total_stated = sum(i["native_qty"] for i in stated)
            if abs(total_stated - derived["native_qty"]) / max(derived["native_qty"], 1e-9) > 0.02:
                flags.append(flag("reading_mismatch", "high", f"Stated consumption ({total_stated:,.0f}) does not match the meter "
                                  f"readings x multiplier ({derived['native_qty']:,.0f}).", derived["line"]))
        elif derived and not items:
            if derived["cat"]:
                factor = factor_for(derived["cat"], derived["family"], derived["line"], region)
                if factor:
                    items.append({k: v for k, v in derived.items() if k not in ("cat", "other")} | {
                        "category": derived["cat"].key, "label": derived["cat"].label, "factor": factor,
                        "factor_source": derived["cat"].source, "kg_co2e": derived["native_qty"] * factor, "edited": False})
            elif derived["other"]:
                wrong_scope.append((derived["line"], derived["other"]))

        # A document that only states totals: use them rather than reporting nothing.
        if not items and control_totals:
            for ct in control_totals:
                cat = CAT_BY_KEY.get(ct["category"] or "")
                factor = factor_for(cat, ct["family"], ct["line"], region) if cat else None
                if cat and factor:
                    items.append({k: v for k, v in ct.items() if k != "other"} | {
                        "label": cat.label, "factor": factor, "factor_source": cat.source,
                        "kg_co2e": ct["native_qty"] * factor, "edited": False})
                elif ct.get("other"):
                    wrong_scope.append((ct["line"], CAT_BY_KEY[ct["other"]]))
            control_totals = []

        if not items and not wrong_scope:
            flags.append(flag("no_activity_data", "high", f"No Scope {scope} activity data (kWh, litres, km, kg ...) "
                              "could be recognised in this document."))
        if wrong_scope:
            where = sorted({f"Scope {c.scope} ({c.label})" for _, c in wrong_scope})
            flags.append(flag("wrong_scope", "medium" if items else "high", f"This looks like {' / '.join(where)} data, "
                              f"not Scope {scope} - upload it on that tab. {len(wrong_scope)} line(s) were not counted here.",
                              wrong_scope[0][0]))
        if unclassified:
            flags.append(flag("unclassified", "low", f"{len(unclassified)} quantity line(s) could not be matched to an "
                              "emission category and were not counted.", unclassified[0]))

        # A stated total must equal the sum of its lines.
        for ct in control_totals:
            same = [i for i in items if i["family"] == ct["family"] and (ct["category"] in (None, i["category"]))]
            if same and ct["native_qty"] > 0:
                s = sum(i["native_qty"] for i in same)
                if abs(s - ct["native_qty"]) / ct["native_qty"] > 0.02:
                    flags.append(flag("total_mismatch", "high", f"Stated total {ct['quantity']:,.2f} {ct['unit']} does not "
                                      f"match the sum of the lines ({s / UNITS[ct['unit'].lower()][1]:,.2f}).", ct["line"]))

        if len(items) >= 4 and all(i["quantity"] >= 1000 and i["quantity"] % 100 == 0 for i in items):
            flags.append(flag("round_numbers", "low", "Every quantity is a round number - may be estimated rather than measured."))

        years = []
        for rx in DATE_RES:
            for m in rx.finditer(text):
                y = next((int(x) for x in m.groups() if x and len(x) == 4 and x.startswith("20")), None)
                if y:
                    years.append(y)
        if not years:
            flags.append(flag("no_date", "low", "No date or reporting period found in the document."))
        else:
            if max(years) > now.year:
                flags.append(flag("future_date", "medium", f"The document mentions a future year ({max(years)})."))
            if max(years) < now.year - 3:
                flags.append(flag("stale_document", "low", f"The newest date in this document is {max(years)} - very old evidence."))

    meta = doc["meta"]
    producer = " ".join(str(meta.get(k, "")) for k in ("Producer", "Creator"))
    if EDITORS.search(producer):
        flags.append(flag("edited_pdf", "medium", f"The PDF was produced or edited with an editing tool ({producer.strip()[:60]})."))
    created, modified = _pdf_date(meta.get("CreationDate")), _pdf_date(meta.get("ModDate"))
    if created and modified and (modified - created).days >= 1:
        flags.append(flag("modified_after_creation", "medium",
                          f"The PDF was modified {(modified - created).days} day(s) after it was created."))

    total = sum(i["kg_co2e"] for i in items)

    prior = [h["total_kg_co2e"] for h in history if h["total_kg_co2e"] > 0]
    if len(prior) >= 3 and total > 3 * statistics.median(prior):
        flags.append(flag("spike_vs_history", "medium", f"This document's emissions ({total / 1000:,.2f} t) are more than "
                          f"3x the usual for Scope {scope} (median {statistics.median(prior) / 1000:,.2f} t)."))
    for i in items:
        qs = [h_i["native_qty"] for h in history for h_i in h["items"] if h_i.get("category") == i["category"]]
        if len(qs) >= 3 and i["native_qty"] > 5 * statistics.median(qs):
            flags.append(flag("outlier_line", "medium", f"{i['label']}: {i['quantity']:,.0f} {i['unit']} is over 5x the "
                              "usual quantity for this category.", i["line"]))
    if budget_kg and total > 0.5 * budget_kg:
        flags.append(flag("dominates_budget", "medium", f"This single document is {total / budget_kg:.0%} of the "
                          f"Scope {scope} budget - verify it."))

    return {"items": items, "flags": _dedupe(flags), "total_kg_co2e": total, "page_count": doc["page_count"]}


def _dedupe(flags: list[dict]) -> list[dict]:
    out, seen = [], set()
    for f in flags:
        k = (f["code"], f["line"])
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}


def risk_of(flags: list[dict]) -> str:
    if not flags:
        return "clear"
    return max((f["severity"] for f in flags), key=lambda s: SEVERITY_RANK[s])


def recompute_item(item: dict, region: str | None) -> dict:
    cat = CAT_BY_KEY[item["category"]]
    _, mult = UNITS[item["unit"].lower()]
    factor = factor_for(cat, item["family"], item.get("line", ""), region)
    if factor is None:
        raise ValueError(f"{cat.label} cannot be measured in {item['unit']}")
    item.update(label=cat.label, factor_source=cat.source, native_qty=item["quantity"] * mult,
                factor=factor, kg_co2e=item["quantity"] * mult * factor)
    return item
