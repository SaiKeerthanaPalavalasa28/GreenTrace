"""Process one bill end to end: PDF text -> LLM extraction -> validation -> extraction row.

process_bill never raises. Whatever goes wrong with one bill is recorded on that bill
(status "failed" + a readable reason) so the rest of the batch carries on.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.calc.quantity import effective_quantity
from app.calc.service import calculate_bill
from app.config import get_settings
from app.enums import BillStatus
from app.models import Bill, Extraction, FacilityAccount
from app.pipeline.errors import PipelineError
from app.pipeline.llm import Extractor, extract_structured
from app.pipeline.schema import LLMExtraction
from app.pipeline.text import extract_text
from app.pipeline.validate import Fields, HistoryPoint, ValidationContext, validate
from app.storage import Storage

log = logging.getLogger(__name__)

SYSTEM_ACTOR = "system"
PROCESSABLE = {BillStatus.uploaded, BillStatus.processing}


def process_bill(
    bill_id: uuid.UUID,
    *,
    session_factory: Callable[[], Session],
    extractor: Extractor,
    storage: Storage,
    today: date | None = None,
) -> None:
    with session_factory() as db:
        bill = db.get(Bill, bill_id)
        if bill is None or bill.status not in PROCESSABLE:
            return
        bill.status = BillStatus.processing
        bill.failure_reason = None
        db.commit()
        file_path = bill.file_path

    try:
        pdf_text = extract_text(storage.read(file_path))
        result = extract_structured(extractor, pdf_text.as_prompt())
        with session_factory() as db:
            _store_extraction(db, bill_id, result.data, result.model_used, pdf_text.pages,
                              pdf_text.method, today or date.today())
            db.commit()
    except PipelineError as e:
        _fail(session_factory, bill_id, str(e))
    except Exception:
        ref = uuid.uuid4().hex[:8]
        log.exception("Unexpected error processing bill %s (ref %s)", bill_id, ref)
        _fail(session_factory, bill_id, f"Unexpected error while processing this bill (reference {ref}). Try reprocessing.")


def _fail(session_factory, bill_id: uuid.UUID, reason: str) -> None:
    try:
        with session_factory() as db:
            bill = db.get(Bill, bill_id)
            if bill is None:
                return
            before = {"status": bill.status}
            bill.status = BillStatus.failed
            bill.failure_reason = reason
            audit.record(db, actor=SYSTEM_ACTOR, action="processing_failed", entity="bill", entity_id=bill.id,
                         org_id=bill.org_id, before=before, after={"status": bill.status, "reason": reason})
            db.commit()
    except Exception:
        log.exception("Could not mark bill %s as failed", bill_id)


def build_context(db: Session, bill: Bill, x: Fields, today: date) -> ValidationContext:
    s = get_settings()
    ctx = ValidationContext(
        today=today,
        confidence_threshold=s.review_confidence_threshold,
        max_period_days=s.max_billing_period_days,
        outlier_ratio=s.outlier_ratio,
        outlier_min_history=s.outlier_min_history,
        facility_id=bill.facility_id,
    )
    utility = x.utility_type if x.utility_type != "unknown" else None

    if x.account_number and utility:
        mapping = db.scalars(select(FacilityAccount).where(
            FacilityAccount.org_id == bill.org_id,
            FacilityAccount.utility_type == utility,
            FacilityAccount.account_number == x.account_number,
        )).first()
        ctx.mapped_facility_id = mapping.facility_id if mapping else None

    if utility:
        # Current extractions of other non-rejected bills for the same facility and utility.
        rows = db.execute(
            select(Bill.id, Bill.status, Extraction)
            .join(Extraction, Extraction.bill_id == Bill.id)
            .where(
                Bill.facility_id == bill.facility_id,
                Bill.id != bill.id,
                Bill.utility_type == utility,
                Bill.status.not_in([BillStatus.rejected, BillStatus.failed]),
                Extraction.is_current.is_(True),
            )
        ).all()
        start, end = x.billing_period_start, x.billing_period_end
        for other_id, status, e in rows:
            if start and end and e.billing_period_start and e.billing_period_end:
                if e.billing_period_start <= end and start <= e.billing_period_end:
                    ctx.overlapping_bill_ids.append(other_id)
            if status == BillStatus.approved and e.unit and e.billing_period_start and e.billing_period_end:
                q = effective_quantity(e.quantity, e.meter_previous, e.meter_current, e.meter_multiplier)
                if q.value:
                    days = (e.billing_period_end - e.billing_period_start).days + 1
                    ctx.history.append(HistoryPoint(q.value, e.unit, days))
    return ctx


def _store_extraction(db: Session, bill_id: uuid.UUID, x: LLMExtraction, model_used: str,
                      pages: list[str], text_method: str, today: date) -> Extraction:
    bill = db.get(Bill, bill_id)
    ctx = build_context(db, bill, Fields.from_llm(x), today)
    result = validate(x, pages, ctx)

    for old in db.scalars(select(Extraction).where(Extraction.bill_id == bill.id, Extraction.is_current.is_(True))):
        old.is_current = False

    mr = x.meter_readings
    extraction = Extraction(
        bill_id=bill.id,
        provider_name=x.provider_name,
        account_number=x.account_number,
        billing_period_start=x.billing_period_start,
        billing_period_end=x.billing_period_end,
        # Quantity exactly as printed (null if only meter readings were printed; the
        # calculation derives it from them). Unit in canonical form when recognized; the
        # label as printed stays visible in the source snippet.
        quantity=x.quantity,
        unit=result.canonical_unit or x.unit,
        meter_previous=mr.previous,
        meter_current=mr.current,
        meter_multiplier=mr.multiplier,
        read_type=x.read_type,
        multiple_meters=x.multiple_meters_or_line_items,
        notes=x.notes,
        raw_text_snippet=x.source_snippet,
        page_number=x.page_number,
        confidence=x.confidence,
        text_method=text_method,
        model_used=model_used,
        validation_issues_json=[i.to_dict() for i in result.issues],
    )
    db.add(extraction)
    if x.utility_type != "unknown":
        bill.utility_type = x.utility_type

    before = {"status": bill.status}
    if result.passed:
        # All rules passed and confidence is above the threshold: auto-approved, and
        # recorded as such so reports can show it was not reviewed by a person.
        bill.status = BillStatus.approved
        action = "auto_approve"
    else:
        bill.status = BillStatus.needs_review
        action = "needs_review"
    db.flush()
    audit.record(db, actor=SYSTEM_ACTOR, action=action, entity="bill", entity_id=bill.id, org_id=bill.org_id,
                 before=before, after={"status": bill.status, "extraction_id": extraction.id,
                                       "issues": [i.code for i in result.issues],
                                       "llm_output": x.model_dump(mode="json")})
    if bill.status == BillStatus.approved:
        calculate_bill(db, bill, actor=SYSTEM_ACTOR, reason="auto-approved")
    return extraction
