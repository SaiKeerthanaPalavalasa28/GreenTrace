import re
import uuid
from datetime import timedelta

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select

from app import audit
from app.calc.prorate import reporting_year_label, reporting_year_start
from app.deps import CurrentUser, DbSession
from app.models import Organization, Report
from app.reports.service import generate_report, verify_report
from app.reports.snapshot import canonical_json
from app.schemas import ReportCreateIn, ReportDetailOut, ReportOut
from app.storage import Storage, get_storage

router = APIRouter(prefix="/reports", tags=["reports"])
Store = Annotated[Storage, Depends(get_storage)]


def _get(db, org_id, report_id) -> Report:
    r = db.get(Report, report_id)
    if r is None or r.org_id != org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    return r


@router.post("", response_model=ReportDetailOut, status_code=status.HTTP_201_CREATED)
def create_report(body: ReportCreateIn, user: CurrentUser, db: DbSession, storage: Store):
    """Freeze the current approved data for the period into a snapshot and render the PDF."""
    if body.period_start.day != 1 or (body.period_end + timedelta(days=1)).day != 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Reports cover whole months: start on the 1st, end on a month's last day")
    if body.period_end < body.period_start or (body.period_end - body.period_start).days > 366 * 5:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Period must be between one month and five years")
    org = db.get(Organization, user.org_id)
    label = body.label
    if not label:
        fy = org.fiscal_year_start_month
        start = reporting_year_start(body.period_start, fy)
        is_year = start == body.period_start and body.period_end == start.replace(year=start.year + 1) - timedelta(days=1)
        label = reporting_year_label(start, fy) if is_year else f"{body.period_start:%b %Y} to {body.period_end:%b %Y}"
    report = generate_report(db, storage, org=org, user=user, period_start=body.period_start,
                             period_end=body.period_end, label=label)
    db.commit()
    return _detail(report)


def _detail(r: Report) -> ReportDetailOut:
    return ReportDetailOut.model_validate({**ReportOut.model_validate(r).model_dump(), "summary": r.snapshot_json["summary"]})


@router.get("", response_model=list[ReportOut])
def list_reports(user: CurrentUser, db: DbSession):
    return db.scalars(select(Report).where(Report.org_id == user.org_id).order_by(Report.generated_at.desc())).all()


@router.get("/{report_id}", response_model=ReportDetailOut)
def get_report(report_id: uuid.UUID, user: CurrentUser, db: DbSession):
    return _detail(_get(db, user.org_id, report_id))


def _filename(r: Report, org: Organization, ext: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "-", f"{org.name}-{r.reporting_period_label}").strip("-")
    return f"GHG-report-{safe}-{str(r.id)[:8]}{'-DRAFT' if r.is_draft else ''}.{ext}"


@router.get("/{report_id}/download")
def download_report(report_id: uuid.UUID, user: CurrentUser, db: DbSession, storage: Store):
    r = _get(db, user.org_id, report_id)
    return Response(storage.read(r.file_path), media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{_filename(r, db.get(Organization, r.org_id), "pdf")}"'})


@router.get("/{report_id}/snapshot")
def download_snapshot(report_id: uuid.UUID, user: CurrentUser, db: DbSession):
    r = _get(db, user.org_id, report_id)
    return Response(canonical_json(r.snapshot_json), media_type="application/json", headers={
        "Content-Disposition": f'attachment; filename="{_filename(r, db.get(Organization, r.org_id), "json")}"'})


@router.post("/{report_id}/verify")
def verify(report_id: uuid.UUID, user: CurrentUser, db: DbSession, storage: Store):
    """Re-check stored files against their hashes and re-render the PDF from the snapshot."""
    r = _get(db, user.org_id, report_id)
    result = verify_report(r, storage)
    audit.record(db, actor=str(user.id), action="verify_report", entity="report", entity_id=r.id,
                 org_id=r.org_id, after=result)
    db.commit()
    return result
