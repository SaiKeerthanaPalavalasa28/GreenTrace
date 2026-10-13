import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app import review
from app.api.bills import bill_detail, get_org_bill
from app.deps import AdminUser, CurrentUser, DbSession
from app.enums import BillStatus
from app.models import Bill, Extraction, Facility
from app.pipeline.validate import BLOCKING_CODES
from app.schemas import (
    ApproveIn, BillDetailOut, RejectIn, ReopenIn, ReviewChangesIn, ReviewCounts, ReviewQueueItem,
)

router = APIRouter(tags=["review"])


def _http(e: review.ReviewError) -> HTTPException:
    detail = {"message": str(e), "issues": e.details} if e.details else str(e)
    return HTTPException(e.status, detail)


@router.get("/review", response_model=list[ReviewQueueItem])
def review_queue(user: CurrentUser, db: DbSession, facility_id: uuid.UUID | None = None):
    """Bills waiting for a person, oldest first."""
    q = (
        select(Bill, Facility.name, Extraction)
        .join(Facility, Facility.id == Bill.facility_id)
        .outerjoin(Extraction, (Extraction.bill_id == Bill.id) & Extraction.is_current.is_(True))
        .where(Bill.org_id == user.org_id, Bill.status == BillStatus.needs_review)
        .order_by(Bill.uploaded_at)
    )
    if facility_id:
        q = q.where(Bill.facility_id == facility_id)
    out = []
    for bill, facility_name, e in db.execute(q).all():
        codes = [i["code"] for i in (e.validation_issues_json or [])] if e else []
        out.append(ReviewQueueItem(
            bill_id=bill.id, extraction_id=e.id if e else None, original_filename=bill.original_filename,
            facility_name=facility_name, utility_type=bill.utility_type,
            billing_period_start=e.billing_period_start if e else None,
            billing_period_end=e.billing_period_end if e else None,
            quantity=e.quantity if e else None, unit=e.unit if e else None,
            confidence=e.confidence if e else None, issue_codes=codes,
            blocking_codes=[c for c in codes if c in BLOCKING_CODES], uploaded_at=bill.uploaded_at,
        ))
    return out


@router.get("/review/counts", response_model=ReviewCounts)
def review_counts(user: CurrentUser, db: DbSession):
    def count(*where):
        return db.scalar(select(func.count()).select_from(Bill).where(Bill.org_id == user.org_id, *where))

    return ReviewCounts(
        needs_review=count(Bill.status == BillStatus.needs_review),
        failed=count(Bill.status == BillStatus.failed),
        calculation_errors=count(Bill.status == BillStatus.approved, Bill.calculation_error.is_not(None)),
    )


@router.post("/extractions/{extraction_id}/correct", response_model=BillDetailOut)
def correct(extraction_id: uuid.UUID, body: ReviewChangesIn, user: CurrentUser, db: DbSession):
    """Save corrections without approving. The field rules run again."""
    try:
        bill, e = review.load_for_review(db, user.org_id, extraction_id, body.expected_updated_at)
        review.apply_corrections(db, bill, e, body.changes, user, body.reason)
    except review.ReviewError as err:
        db.rollback()
        raise _http(err)
    db.commit()
    return bill_detail(db, bill)


@router.post("/extractions/{extraction_id}/approve", response_model=BillDetailOut)
def approve(extraction_id: uuid.UUID, body: ApproveIn, user: CurrentUser, db: DbSession):
    """Apply any corrections and approve, atomically. Approval acknowledges the remaining
    warnings; blocking issues must be fixed first."""
    try:
        bill, e = review.load_for_review(db, user.org_id, extraction_id, body.expected_updated_at)
        if body.changes:
            review.apply_corrections(db, bill, e, body.changes, user, body.reason)
        review.approve(db, bill, e, user, remap_account=body.remap_account, note=body.note)
    except review.ReviewError as err:
        db.rollback()
        raise _http(err)
    db.commit()
    return bill_detail(db, bill)


@router.post("/extractions/{extraction_id}/reject", response_model=BillDetailOut)
def reject(extraction_id: uuid.UUID, body: RejectIn, user: CurrentUser, db: DbSession):
    """Exclude the bill from reporting (e.g. not a utility bill, duplicate, wrong organization)."""
    try:
        bill, e = review.load_for_review(db, user.org_id, extraction_id, body.expected_updated_at)
        review.reject(db, bill, e, user, body.reason)
    except review.ReviewError as err:
        db.rollback()
        raise _http(err)
    db.commit()
    return bill_detail(db, bill)


@router.post("/bills/{bill_id}/reopen", response_model=BillDetailOut)
def reopen(bill_id: uuid.UUID, body: ReopenIn, admin: AdminUser, db: DbSession):
    """Admin: send an approved or rejected bill back to the review queue."""
    bill = get_org_bill(db, admin.org_id, bill_id)
    try:
        review.reopen(db, bill, admin, body.reason)
    except review.ReviewError as err:
        db.rollback()
        raise _http(err)
    db.commit()
    return bill_detail(db, bill)
