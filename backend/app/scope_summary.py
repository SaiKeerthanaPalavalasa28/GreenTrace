"""Combines every scope document of an organization into the dashboard numbers, the zone
(green / moderate / danger), improvement suggestions and the final report."""

import io
from xml.sax.saxutils import escape as esc
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Organization, ScopeDocument
from app.scope_analysis import CAT_BY_KEY, risk_of

MODERATE_FROM = 70.0  # % of the budget used
DANGER_FROM = 90.0
SCOPE_NAMES = {1: "Scope 1 - direct emissions", 2: "Scope 2 - purchased energy", 3: "Scope 3 - value chain"}


def zone_for(pct: float | None) -> str:
    if pct is None:
        return "unset"
    if pct >= DANGER_FROM:
        return "danger"
    if pct >= MODERATE_FROM:
        return "moderate"
    return "green"


def _budget_kg(org: Organization, scope: int) -> float | None:
    t = getattr(org, f"scope{scope}_budget_t")
    return None if t is None else t * 1000.0


def build_summary(db: Session, org: Organization) -> dict:
    docs = db.scalars(select(ScopeDocument).where(ScopeDocument.org_id == org.id)).all()
    scopes, breakdown = [], {}
    for s in (1, 2, 3):
        mine = [d for d in docs if d.scope == s]
        used = sum(d.total_kg_co2e for d in mine)
        budget = _budget_kg(org, s)
        pct = None if not budget else used / budget * 100
        for d in mine:
            for it in d.items:
                breakdown[(s, it["category"])] = breakdown.get((s, it["category"]), 0.0) + it["kg_co2e"]
        scopes.append({
            "scope": s, "name": SCOPE_NAMES[s], "documents": len(mine),
            "flagged_documents": sum(1 for d in mine if d.flags),
            "high_risk_documents": sum(1 for d in mine if risk_of(d.flags) == "high"),
            "used_t": used / 1000, "budget_t": None if budget is None else budget / 1000,
            "remaining_t": None if budget is None else (budget - used) / 1000,
            "percent_used": pct, "zone": zone_for(pct),
        })
    used_total = sum(x["used_t"] for x in scopes)
    set_budgets = [x["budget_t"] for x in scopes if x["budget_t"] is not None]
    budget_total = sum(set_budgets) if set_budgets else None
    # Combined %: only scopes that have a budget are compared, so an unset scope can't dilute it.
    used_budgeted = sum(x["used_t"] for x in scopes if x["budget_t"] is not None)
    pct_total = None if not budget_total else used_budgeted / budget_total * 100
    return {
        "organization": org.name,
        "generated_at": datetime.now(UTC).isoformat(),
        "thresholds": {"moderate_from": MODERATE_FROM, "danger_from": DANGER_FROM},
        "scopes": scopes,
        "total": {
            "used_t": used_total, "budget_t": budget_total,
            "remaining_t": None if budget_total is None else budget_total - used_budgeted,
            "percent_used": pct_total, "zone": zone_for(pct_total),
            "documents": len(docs), "flagged_documents": sum(1 for d in docs if d.flags),
        },
        "breakdown": sorted(
            ({"scope": s, "category": c, "label": CAT_BY_KEY[c].label, "t": kg / 1000} for (s, c), kg in breakdown.items()),
            key=lambda r: -r["t"]),
    }


# Practical, category-specific advice. Shown when a category is a meaningful share of its scope.
TIPS = {
    "diesel": "Diesel is a major source. Replace diesel generators with grid/solar + battery backup, service them regularly and track fuel per operating hour.",
    "petrol": "Petrol use is significant. Move the owned fleet to EVs or hybrids and consolidate trips with route planning.",
    "fuel_oil": "Fuel oil is high-carbon. Switch boilers/furnaces to natural gas, biomass or electric heat pumps and tune burners.",
    "lpg": "LPG use stands out. Consider electric or induction alternatives and check for leaks and combustion efficiency.",
    "natural_gas": "Natural gas is a main driver. Insulate and recover waste heat, tune boilers, and evaluate heat pumps for space and process heat.",
    "coal": "Coal is the most carbon-intensive fuel here. Prioritise switching to gas, biomass or electrification.",
    "refrigerant": "Refrigerant leakage has a huge warming impact per kg. Run leak checks, repair promptly and move to low-GWP refrigerants (e.g. R-32 or natural refrigerants).",
    "electricity": "Purchased electricity dominates. Buy renewable power (PPA / green tariff), install rooftop solar, switch to LED and efficient HVAC, and shift load away from peak hours.",
    "heat_steam": "Purchased heat/steam is significant. Recover heat on site and ask the supplier about a lower-carbon source.",
    "air_travel": "Air travel is a major share. Replace short trips with video calls or rail, pool trips, and set a flight-reduction target.",
    "rail_travel": "Rail is already low-carbon; keep encouraging it over flying and road for business trips.",
    "bus_travel": "Bus travel is moderate. Encourage shared transport and electric buses for staff shuttles.",
    "road_travel": "Cars/taxis/commuting stand out. Offer EV or carpool schemes, transit passes and hybrid-work days.",
    "hotel": "Hotel stays add up. Prefer certified green hotels and cut trip frequency.",
    "freight": "Freight is a large share. Consolidate shipments, favour rail or sea over road/air, and ask logistics partners for emissions data.",
    "waste_landfill": "Landfill waste is significant. Segregate at source, divert organic waste to composting and recycle more.",
    "waste_recycled": "Recycling volumes are large - good. Keep reducing waste at source as the next step.",
    "water": "Water supply has a footprint. Fix leaks, install low-flow fittings and reuse treated water.",
    "paper": "Paper purchasing is notable. Go digital, print double-sided and buy recycled paper.",
    "plastic": "Plastics/packaging stand out. Cut single-use packaging and specify recycled content.",
    "steel": "Purchased metals are a large share. Ask for recycled-content or low-carbon steel/aluminium and reduce material waste.",
    "cement": "Cement/concrete is carbon heavy. Use blended cements (fly ash/slag) and optimise designs to use less.",
}


def build_suggestions(summary: dict, flagged: list[dict]) -> list[dict]:
    out: list[dict] = []
    for sc in summary["scopes"]:
        s = sc["scope"]
        if sc["documents"] == 0:
            out.append({"scope": s, "priority": "high", "title": f"Add evidence for Scope {s}",
                        "detail": f"No documents have been uploaded for {SCOPE_NAMES[s]}, so the report is incomplete."})
            continue
        if sc["budget_t"] is None:
            out.append({"scope": s, "priority": "medium", "title": f"Set a Scope {s} budget",
                        "detail": "Without an emission budget the remaining allowance and the green/orange/red status cannot be calculated."})
        elif sc["zone"] == "danger":
            over = sc["used_t"] - sc["budget_t"]
            msg = (f"Scope {s} has exceeded its budget by {over:,.2f} t CO2e." if over > 0
                   else f"Scope {s} has used {sc['percent_used']:.0f}% of its budget.")
            out.append({"scope": s, "priority": "high", "title": f"Scope {s} is in the danger zone",
                        "detail": msg + " Act on the top sources below now, and consider raising the reduction target."})
        elif sc["zone"] == "moderate":
            out.append({"scope": s, "priority": "medium", "title": f"Scope {s} is approaching its limit",
                        "detail": f"{sc['percent_used']:.0f}% of the budget is used. Plan reductions before it reaches {DANGER_FROM:.0f}%."})
        rows = [b for b in summary["breakdown"] if b["scope"] == s]
        scope_total = sum(b["t"] for b in rows)
        for b in rows[:3]:
            share = b["t"] / scope_total if scope_total else 0
            if share >= 0.25 and b["category"] in TIPS:
                out.append({"scope": s, "priority": "high" if sc["zone"] == "danger" else "medium",
                            "title": f"{b['label']} is {share:.0%} of Scope {s}", "detail": TIPS[b["category"]]})
    if flagged:
        high = sum(1 for d in flagged if d["risk"] == "high")
        out.append({"scope": None, "priority": "high" if high else "medium",
                    "title": f"Review {len(flagged)} flagged document(s)",
                    "detail": f"{high} are high risk. Verify or correct the source documents before using these figures externally."})
    if summary["total"]["zone"] == "green" and not flagged:
        out.append({"scope": None, "priority": "low", "title": "On track",
                    "detail": "All scopes are within budget with no flagged documents. Keep uploading monthly evidence to stay audit-ready."})
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda x: order[x["priority"]])


def flagged_documents(db: Session, org: Organization) -> list[dict]:
    docs = db.scalars(select(ScopeDocument).where(ScopeDocument.org_id == org.id).order_by(ScopeDocument.uploaded_at.desc())).all()
    return [{"id": str(d.id), "scope": d.scope, "filename": d.original_filename, "risk": risk_of(d.flags),
             "flags": d.flags} for d in docs if d.flags]


def build_report(db: Session, org: Organization) -> dict:
    summary = build_summary(db, org)
    flagged = flagged_documents(db, org)
    t = summary["total"]
    if t["percent_used"] is None:
        headline = f"{t['used_t']:,.2f} t CO2e recorded so far. Set per-scope budgets to see how much allowance is left."
    else:
        headline = (f"{t['used_t']:,.2f} t CO2e used of {t['budget_t']:,.2f} t budget "
                    f"({t['percent_used']:.0f}%), {t['remaining_t']:,.2f} t remaining - status {t['zone'].upper()}.")
    return {"summary": summary, "headline": headline, "flagged": flagged,
            "suggestions": build_suggestions(summary, flagged)}


def report_pdf(report: dict) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    sm = report["summary"]
    zone_color = {"green": "#1f7549", "moderate": "#e08a00", "danger": "#c62828", "unset": "#79776c"}

    fig, ax = plt.subplots(figsize=(6.4, 2.8), dpi=150)
    names = [f"Scope {s['scope']}" for s in sm["scopes"]]
    ax.bar(names, [s["used_t"] for s in sm["scopes"]], color=[zone_color[s["zone"]] for s in sm["scopes"]], label="Used (t CO2e)")
    budgets = [s["budget_t"] or 0 for s in sm["scopes"]]
    ax.plot(names, budgets, "k_", markersize=40, markeredgewidth=2, label="Budget")
    ax.set_ylabel("t CO2e")
    ax.legend(frameon=False)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)

    ss = getSampleStyleSheet()
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"GreenTrace emissions report - {sm['organization']}")
    story = [Paragraph("GreenTrace - Emissions Report", ss["Title"]),
             Paragraph(f"{esc(sm['organization'])} &middot; generated {sm['generated_at'][:16].replace('T', ' ')} UTC", ss["Normal"]),
             Spacer(1, 6 * mm), Paragraph(esc(report["headline"]), ss["Heading3"]), Spacer(1, 3 * mm)]
    rows = [["Scope", "Documents", "Used (t)", "Budget (t)", "Remaining (t)", "% used", "Status"]]
    fmt = lambda v: "-" if v is None else f"{v:,.2f}"  # noqa: E731
    for s in sm["scopes"] + [{**sm["total"], "scope": "Total"}]:
        rows.append([f"Scope {s['scope']}" if s["scope"] != "Total" else "Total", s["documents"], fmt(s["used_t"]), fmt(s["budget_t"]),
                     fmt(s["remaining_t"]), "-" if s["percent_used"] is None else f"{s['percent_used']:.0f}%", s["zone"].upper()])
    tbl = Table(rows, hAlign="LEFT")
    style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#134a30")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
             ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbc9bd")), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
             ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]
    for i, s in enumerate(sm["scopes"] + [sm["total"]], start=1):
        style.append(("TEXTCOLOR", (6, i), (6, i), colors.HexColor(zone_color[s["zone"]])))
    tbl.setStyle(TableStyle(style))
    story += [tbl, Spacer(1, 5 * mm), Image(buf, width=150 * mm, height=65 * mm), Spacer(1, 4 * mm),
              Paragraph("Where the emissions come from", ss["Heading2"])]
    top = [["Scope", "Source", "t CO2e"]] + [[f"Scope {b['scope']}", b["label"], f"{b['t']:,.2f}"] for b in sm["breakdown"][:12]]
    t2 = Table(top, hAlign="LEFT")
    t2.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbc9bd")), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef7f1"))]))
    story += [t2, Spacer(1, 4 * mm), Paragraph("Flagged documents", ss["Heading2"])]
    if report["flagged"]:
        for d in report["flagged"]:
            story.append(Paragraph(f"<b>Scope {d['scope']} - {esc(d['filename'])}</b> (risk: {d['risk']})", ss["Normal"]))
            for f in d["flags"]:
                story.append(Paragraph(f"&bull; [{f['severity']}] {esc(f['message'])}", ss["BodyText"]))
    else:
        story.append(Paragraph("No documents were flagged.", ss["Normal"]))
    story += [Spacer(1, 4 * mm), Paragraph("Suggestions to improve", ss["Heading2"])]
    for sug in report["suggestions"]:
        story.append(Paragraph(f"<b>{esc(sug['title'])}</b> ({sug['priority']} priority)<br/>{esc(sug['detail'])}", ss["BodyText"]))
        story.append(Spacer(1, 1.5 * mm))
    story += [Spacer(1, 4 * mm), Paragraph(
        "Emissions are computed from the uploaded documents with indicative emission factors; verify factors and flagged "
        "items before using these figures in external reporting.", ss["Italic"])]
    doc.build(story)
    return out.getvalue()
