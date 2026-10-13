import uuid
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, status

from app.dashboard import Filters, reporting_years, summarize
from app.deps import CurrentUser, DbSession
from app.enums import UtilityType
from app.models import Organization

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/periods")
def periods(user: CurrentUser, db: DbSession):
    """Reporting years to offer in the period picker (org's fiscal-year convention), newest first.
    The default is the latest year that has data."""
    org = db.get(Organization, user.org_id)
    years = reporting_years(db, org, date.today())
    default = next((y for y in years if y["has_data"]), years[0])
    return {"fiscal_year_start_month": org.fiscal_year_start_month, "years": years, "default": default["label"]}


@router.get("")
def dashboard(
    user: CurrentUser,
    db: DbSession,
    period_start: date,
    period_end: date,
    facility_id: uuid.UUID | None = None,
    utility_type: UtilityType | None = None,
):
    """Totals, monthly trend and breakdowns for approved bills. Periods are whole months,
    because emission records are allocated per month."""
    if period_start.day != 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "period_start must be the first day of a month")
    if (period_end + timedelta(days=1)).day != 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "period_end must be the last day of a month")
    if period_end < period_start or (period_end - period_start).days > 366 * 5:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Period must be between one month and five years")
    return summarize(db, Filters(user.org_id, period_start, period_end, facility_id,
                                 utility_type.value if utility_type else None))
