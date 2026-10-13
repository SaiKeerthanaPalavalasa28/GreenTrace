"""Split a billing period into segments for pro-rating.

Convention: billing periods are inclusive of both dates (1-30 April = 30 days). A bill is
split at every calendar-month start inside it, so every segment lies in exactly one month
(and therefore one reporting year, since reporting years start on the 1st of a month), and
at any extra boundary passed in (e.g. the day an emission factor's validity changes).
Consumption is assumed uniform over the billing period, so each segment gets
days_in_segment / days_in_period of the quantity.
"""

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Segment:
    start: date
    end: date  # inclusive

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


class PeriodError(ValueError):
    pass


def period_days(start: date, end: date) -> int:
    return (end - start).days + 1


def _month_starts(start: date, end: date) -> list[date]:
    out = []
    d = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    while d <= end:
        out.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def split_period(start: date, end: date, extra_boundaries: list[date] = ()) -> list[Segment]:
    """extra_boundaries: dates on which a new segment must start."""
    if start is None or end is None:
        raise PeriodError("Billing period start and end are required")
    if end < start:
        raise PeriodError(f"Billing period end {end} is before start {start}")
    cuts = sorted({d for d in [*_month_starts(start, end), *extra_boundaries] if start < d <= end})
    segments, seg_start = [], start
    for cut in cuts:
        segments.append(Segment(seg_start, cut - timedelta(days=1)))
        seg_start = cut
    segments.append(Segment(seg_start, end))
    return segments


def reporting_year_label(d: date, fy_start_month: int) -> str:
    """'2025' for calendar-year reporting, 'FY2024-25' for e.g. April-March."""
    if fy_start_month == 1:
        return str(d.year)
    first = d.year if d.month >= fy_start_month else d.year - 1
    return f"FY{first}-{str(first + 1)[-2:]}"


def reporting_year_start(d: date, fy_start_month: int) -> date:
    return date(d.year if d.month >= fy_start_month else d.year - 1, fy_start_month, 1)
