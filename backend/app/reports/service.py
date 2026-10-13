import hashlib
import uuid
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app import audit
from app.models import Organization, Report, User
from app.reports.pdf import render_pdf
from app.reports.snapshot import build_snapshot, snapshot_sha256
from app.storage import Storage


def generate_report(db: Session, storage: Storage, *, org: Organization, user: User, period_start: date,
                    period_end: date, label: str) -> Report:
    """Freeze the data as a snapshot, render the PDF from it, store both. Does not commit."""
    report_id = uuid.uuid4()
    now = datetime.now(UTC)
    snapshot = build_snapshot(db, org=org, user=user, report_id=report_id, period_start=period_start,
                              period_end=period_end, label=label, now=now)
    pdf = render_pdf(snapshot)
    pdf_sha = hashlib.sha256(pdf).hexdigest()
    key = storage.save_file(f"reports/{org.id}/{report_id}.pdf", pdf)
    report = Report(
        id=report_id, org_id=org.id, period_start=period_start, period_end=period_end,
        reporting_period_label=label, status="final" if not snapshot["summary"]["is_draft"] else "draft",
        is_draft=snapshot["summary"]["is_draft"], generated_by=user.id, generated_at=now, file_path=key,
        snapshot_json=snapshot, snapshot_sha256=snapshot_sha256(snapshot), pdf_sha256=pdf_sha,
    )
    db.add(report)
    db.flush()
    audit.record(db, actor=str(user.id), action="generate_report", entity="report", entity_id=report.id,
                 org_id=org.id, after={"period": [period_start.isoformat(), period_end.isoformat()], "label": label,
                                       "is_draft": report.is_draft, "pdf_sha256": pdf_sha,
                                       "snapshot_sha256": report.snapshot_sha256,
                                       "total_kg": snapshot["summary"]["total_kg"]})
    return report


def verify_report(report: Report, storage: Storage) -> dict:
    """Check the stored files against their recorded hashes, and re-render the PDF from the
    stored snapshot to confirm it reproduces exactly."""
    stored_pdf = storage.read(report.file_path)
    stored_ok = hashlib.sha256(stored_pdf).hexdigest() == report.pdf_sha256
    snapshot_ok = snapshot_sha256(report.snapshot_json) == report.snapshot_sha256
    rerendered = hashlib.sha256(render_pdf(report.snapshot_json)).hexdigest()
    return {
        "pdf_matches_recorded_hash": stored_ok,
        "snapshot_matches_recorded_hash": snapshot_ok,
        "rerender_matches": rerendered == report.pdf_sha256,
        "pdf_sha256": report.pdf_sha256,
        "snapshot_sha256": report.snapshot_sha256,
        "rerendered_sha256": rerendered,
    }
