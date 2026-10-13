import hashlib
import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.api.facilities import get_org_facility
from app.config import get_settings
from app.deps import CurrentUser, DbSession
from app.enums import BillStatus
from app.models import Bill, Extraction, Facility
from app.pipeline.pages import render_page
from app.pipeline.queue import JobQueue, get_queue
from app.calc.engine import kg_to_tonnes
from app.calc.service import current_extraction, current_records, recalculate
from app.deps import AdminUser
from app.models import EmissionRecord
from app.schemas import (
    BillDetailOut, BillListItem, BillOut, BillStatusOut, BillTraceOut, EmissionRecordOut, ExtractionOut,
    RecalculateOut, UploadOut, UploadResult,
)
from app.storage import Storage, get_storage


router = APIRouter(prefix="/bills", tags=["bills"])

Queue = Annotated[JobQueue, Depends(get_queue)]
Store = Annotated[Storage, Depends(get_storage)]

REPROCESSABLE = {BillStatus.failed, BillStatus.needs_review}


def get_org_bill(db: Session, org_id: uuid.UUID, bill_id: uuid.UUID) -> Bill:
    bill = db.get(Bill, bill_id)
    if bill is None or bill.org_id != org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found")
    return bill


@router.post("/upload", response_model=UploadOut)
def upload_bills(
    user: CurrentUser,
    db: DbSession,
    queue: Queue,
    storage: Store,
    facility_id: Annotated[uuid.UUID, Form()],
    files: Annotated[list[UploadFile], File()],
):
    """Upload PDFs for one facility. Each file gets its own outcome; one bad file never fails the batch."""
    settings = get_settings()
    facility = get_org_facility(db, user.org_id, facility_id)
    if len(files) > settings.max_files_per_upload:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"At most {settings.max_files_per_upload} files per upload")
    max_bytes = settings.max_upload_mb * 1024 * 1024

    results: list[UploadResult] = []
    queued: list[uuid.UUID] = []
    seen_in_batch: dict[str, str] = {}
    for f in files:
        name = (f.filename or "unnamed.pdf")[:300]
        data = f.file.read(max_bytes + 1)

        reason = None
        if not name.lower().endswith(".pdf"):
            reason = "Only PDF files are accepted"
        elif len(data) > max_bytes:
            reason = f"File is larger than {settings.max_upload_mb} MB"
        elif not data.startswith(b"%PDF-"):
            reason = "File is not a valid PDF"
        if reason:
            results.append(UploadResult(filename=name, outcome="rejected", reason=reason))
            continue

        digest = hashlib.sha256(data).hexdigest()
        if digest in seen_in_batch:
            results.append(UploadResult(filename=name, outcome="duplicate",
                                        reason=f"Same file as {seen_in_batch[digest]} in this upload"))
            continue
        existing = db.scalars(select(Bill).where(Bill.org_id == user.org_id, Bill.file_hash == digest)).first()
        if existing:
            results.append(UploadResult(
                filename=name, outcome="duplicate", bill_id=existing.id,
                reason=f"Already uploaded as {existing.original_filename} on {existing.uploaded_at:%Y-%m-%d}",
            ))
            continue
        seen_in_batch[digest] = name

        key = storage.save(user.org_id, digest, data)
        bill = Bill(
            org_id=user.org_id, facility_id=facility.id, original_filename=name, file_path=key,
            file_hash=digest, file_size=len(data), status=BillStatus.uploaded, uploaded_by=user.id,
        )
        db.add(bill)
        db.flush()
        audit.record(db, actor=str(user.id), action="upload", entity="bill", entity_id=bill.id,
                     org_id=user.org_id, after=audit.snapshot(bill))
        results.append(UploadResult(filename=name, outcome="queued", bill_id=bill.id))
        queued.append(bill.id)

    db.commit()  # bills must exist before workers pick them up
    for bill_id in queued:
        queue.enqueue(bill_id)
    return UploadOut(results=results)


@router.get("", response_model=list[BillListItem])
def list_bills(
    user: CurrentUser,
    db: DbSession,
    status_: Annotated[str | None, Query(alias="status")] = None,
    facility_id: uuid.UUID | None = None,
    utility_type: str | None = None,
    period_start: date | None = Query(None, description="only bills whose billing period overlaps this range"),
    period_end: date | None = None,
    limit: int = Query(500, le=2000),
):
    q = (
        select(Bill, Facility.name, Extraction)
        .join(Facility, Facility.id == Bill.facility_id)
        .outerjoin(Extraction, (Extraction.bill_id == Bill.id) & Extraction.is_current.is_(True))
        .where(Bill.org_id == user.org_id)
    )
    if status_:
        q = q.where(Bill.status.in_(status_.split(",")))
    if facility_id:
        q = q.where(Bill.facility_id == facility_id)
    if utility_type:
        q = q.where(Bill.utility_type == utility_type)
    if period_start and period_end:
        q = q.where(Extraction.billing_period_start <= period_end, Extraction.billing_period_end >= period_start)
    rows = db.execute(q.order_by(Bill.uploaded_at.desc()).limit(limit)).all()
    totals = dict(db.execute(
        select(Extraction.bill_id, func.sum(EmissionRecord.kgco2e))
        .join(EmissionRecord, EmissionRecord.extraction_id == Extraction.id)
        .where(Extraction.bill_id.in_([b.id for b, _, _ in rows]), EmissionRecord.is_current.is_(True))
        .group_by(Extraction.bill_id)
    ).all())
    out = []
    for bill, facility_name, e in rows:
        item = BillListItem.model_validate({**BillOut.model_validate(bill).model_dump(), "facility_name": facility_name})
        if e is not None:
            item.billing_period_start = e.billing_period_start
            item.billing_period_end = e.billing_period_end
            item.quantity = e.quantity
            item.unit = e.unit
            item.issue_count = len(e.validation_issues_json or [])
        if bill.id in totals:
            item.kgco2e = Decimal(totals[bill.id])
            item.tco2e = kg_to_tonnes(item.kgco2e)
        out.append(item)
    return out


@router.get("/status", response_model=list[BillStatusOut])
def bill_status(user: CurrentUser, db: DbSession, ids: str = Query(..., description="comma-separated bill ids")):
    """Cheap endpoint for the upload page to poll."""
    try:
        wanted = [uuid.UUID(i) for i in ids.split(",") if i][:200]
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "ids must be UUIDs")
    return db.scalars(select(Bill).where(Bill.org_id == user.org_id, Bill.id.in_(wanted))).all()


@router.post("/recalculate", response_model=RecalculateOut)
def recalculate_bills(admin: AdminUser, db: DbSession):
    """Recalculate every approved bill in the organization (e.g. after adding missing
    factors). Bills whose result doesn't change are left untouched."""
    stats = recalculate(db, actor=str(admin.id), reason="manual recalculation", org_id=admin.org_id)
    db.commit()
    return stats


def bill_detail(db: Session, bill: Bill) -> BillDetailOut:
    e = current_extraction(db, bill.id)
    return BillDetailOut(
        bill=BillOut.model_validate(bill),
        facility_name=db.get(Facility, bill.facility_id).name,
        extraction=ExtractionOut.model_validate(e) if e else None,
    )


@router.get("/{bill_id}", response_model=BillDetailOut)
def get_bill(bill_id: uuid.UUID, user: CurrentUser, db: DbSession):
    return bill_detail(db, get_org_bill(db, user.org_id, bill_id))


@router.get("/{bill_id}/pages/{page_number}")
def get_bill_page(bill_id: uuid.UUID, page_number: int, user: CurrentUser, db: DbSession, storage: Store,
                  highlight: bool = True):
    """PNG of one page; with highlight, the current extraction's source snippet is boxed."""
    bill = get_org_bill(db, user.org_id, bill_id)
    e = current_extraction(db, bill.id)
    snippet = e.raw_text_snippet if (highlight and e and e.page_number == page_number) else None
    try:
        page = render_page(storage.read(bill.file_path), page_number, snippet)
    except IndexError as err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(err))
    return Response(page.png, media_type="image/png", headers={
        "X-Page-Count": str(page.page_count),
        "X-Highlight": page.highlight,
        "Cache-Control": "private, no-store",
    })


@router.get("/{bill_id}/trace", response_model=BillTraceOut)
def get_bill_trace(bill_id: uuid.UUID, user: CurrentUser, db: DbSession):
    """Bill -> extraction -> factor -> formula -> result, plus earlier (superseded) results."""
    bill = get_org_bill(db, user.org_id, bill_id)
    e = current_extraction(db, bill.id)
    records = current_records(db, bill.id)
    total = sum((Decimal(r.kgco2e) for r in records), Decimal(0)) if records else None
    history = db.scalars(
        select(EmissionRecord).join(Extraction, Extraction.id == EmissionRecord.extraction_id)
        .where(Extraction.bill_id == bill.id, EmissionRecord.is_current.is_(False))
        .order_by(EmissionRecord.calculated_at.desc(), EmissionRecord.allocation_start)
    ).all()
    return BillTraceOut(
        bill=BillOut.model_validate(bill),
        facility_name=db.get(Facility, bill.facility_id).name,
        extraction=ExtractionOut.model_validate(e) if e else None,
        records=[EmissionRecordOut.model_validate(r) for r in records],
        total_kgco2e=total,
        total_tco2e=kg_to_tonnes(total) if total is not None else None,
        superseded_records=[EmissionRecordOut.model_validate(r) for r in history],
    )


@router.get("/{bill_id}/file")
def get_bill_file(bill_id: uuid.UUID, user: CurrentUser, db: DbSession, storage: Store):
    bill = get_org_bill(db, user.org_id, bill_id)
    safe_name = re.sub(r"[^A-Za-z0-9._ -]", "_", bill.original_filename)
    return Response(
        storage.read(bill.file_path),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{safe_name}"',
                 "X-Content-Type-Options": "nosniff"},
    )


@router.post("/{bill_id}/reprocess", response_model=BillOut)
def reprocess_bill(bill_id: uuid.UUID, user: CurrentUser, db: DbSession, queue: Queue):
    """Run extraction again (e.g. after configuring OCR or the API key). The previous
    extraction is kept for audit and marked not current."""
    bill = get_org_bill(db, user.org_id, bill_id)
    if bill.status not in REPROCESSABLE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Bills in status '{bill.status}' cannot be reprocessed")
    before = {"status": bill.status, "failure_reason": bill.failure_reason}
    bill.status = BillStatus.uploaded
    bill.failure_reason = None
    audit.record(db, actor=str(user.id), action="reprocess", entity="bill", entity_id=bill.id,
                 org_id=user.org_id, before=before, after={"status": bill.status})
    db.commit()
    queue.enqueue(bill.id)
    return bill
