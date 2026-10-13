"""Static charts for the PDF report (matplotlib, Agg backend). Same palette and rules as the
dashboard: Scope 1 = slot 1 blue, Scope 2 = slot 2 orange, thin bars, hairline grid, one axis.
Output is deterministic (no timestamps or software metadata), so reports reproduce byte-for-byte."""

import io
from decimal import Decimal

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SCOPE_COLOR = {1: "#2a78d6", 2: "#eb6834"}
INK_MUTED = "#898781"
INK_SECONDARY = "#52514e"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

plt.rcParams.update({
    "font.family": "DejaVu Sans",  # bundled with matplotlib: identical on every machine
    "font.size": 8,
    "svg.hashsalt": "greentrace",
    "path.simplify": False,
})


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, metadata={"Software": None}, facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def _style(ax):
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=INK_MUTED, length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def monthly_chart(monthly: list[dict]) -> bytes:
    labels = [f"{MONTHS[int(m['month'][5:]) - 1]} {m['month'][2:4]}" for m in monthly]
    s1 = [float(Decimal(m["scope1_kg"]) / 1000) for m in monthly]  # geometry only; values are in the tables
    s2 = [float(Decimal(m["scope2_kg"]) / 1000) for m in monthly]
    fig, ax = plt.subplots(figsize=(7.0, 2.6))
    x = range(len(labels))
    width = min(0.55, 6 / max(len(labels), 1))
    ax.bar(x, s1, width, color=SCOPE_COLOR[1], edgecolor="white", linewidth=1, label="Scope 1")
    ax.bar(x, s2, width, bottom=s1, color=SCOPE_COLOR[2], edgecolor="white", linewidth=1, label="Scope 2")
    ax.set_xticks(list(x), labels, rotation=0 if len(labels) <= 12 else 90)
    ax.set_ylabel("tCO$_2$e", color=INK_SECONDARY)
    _style(ax)
    ax.legend(loc="upper left", bbox_to_anchor=(0, 1.15), ncol=2, frameon=False, labelcolor=INK_SECONDARY,
              handlelength=1, handleheight=1)
    fig.tight_layout()
    return _png(fig)


def facility_chart(by_facility: list[dict]) -> bytes:
    """Horizontal stacked bars by facility (scales to any number of facilities, unlike a donut)."""
    rows = list(reversed(by_facility))  # largest at the top
    names = [r["facility"] for r in rows]
    s1 = [float(Decimal(r["scope1_kg"]) / 1000) for r in rows]
    s2 = [float(Decimal(r["scope2_kg"]) / 1000) for r in rows]
    fig, ax = plt.subplots(figsize=(7.0, 0.45 * len(rows) + 0.9))
    y = range(len(rows))
    ax.barh(y, s1, 0.55, color=SCOPE_COLOR[1], edgecolor="white", linewidth=1, label="Scope 1")
    ax.barh(y, s2, 0.55, left=s1, color=SCOPE_COLOR[2], edgecolor="white", linewidth=1, label="Scope 2")
    ax.set_yticks(list(y), names)
    ax.set_xlabel("tCO$_2$e", color=INK_SECONDARY)
    ax.spines[["top", "right", "bottom"]].set_visible(False)
    ax.spines["left"].set_color(AXIS)
    ax.tick_params(colors=INK_MUTED, length=0)
    ax.tick_params(axis="y", colors=INK_SECONDARY)
    ax.xaxis.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.legend(loc="lower right", bbox_to_anchor=(1, 1.0), ncol=2, frameon=False, labelcolor=INK_SECONDARY,
              handlelength=1, handleheight=1)
    fig.tight_layout()
    return _png(fig)
