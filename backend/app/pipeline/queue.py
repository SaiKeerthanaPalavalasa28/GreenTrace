"""Background processing. A bounded thread pool keeps uploads non-blocking while limiting
concurrent LLM calls. Bills are durable in the database, so anything interrupted by a
restart is re-queued at startup (see requeue_unfinished)."""

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.enums import BillStatus
from app.models import Bill
from app.pipeline.llm import get_extractor
from app.pipeline.runner import process_bill
from app.storage import get_storage

log = logging.getLogger(__name__)


class JobQueue:
    def __init__(self, workers: int):
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="bill")

    def enqueue(self, bill_id: uuid.UUID) -> None:
        self._pool.submit(self._run, bill_id)

    @staticmethod
    def _run(bill_id: uuid.UUID) -> None:
        process_bill(bill_id, session_factory=SessionLocal, extractor=get_extractor(), storage=get_storage())

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


_queue: JobQueue | None = None


def get_queue() -> JobQueue:
    global _queue
    if _queue is None:
        _queue = JobQueue(get_settings().extraction_workers)
    return _queue


def requeue_unfinished() -> int:
    with SessionLocal() as db:
        ids = db.scalars(select(Bill.id).where(Bill.status.in_([BillStatus.uploaded, BillStatus.processing]))).all()
        for bill in db.scalars(select(Bill).where(Bill.id.in_(ids))):
            bill.status = BillStatus.uploaded
        db.commit()
    for bill_id in ids:
        get_queue().enqueue(bill_id)
    if ids:
        log.info("Re-queued %d unfinished bills", len(ids))
    return len(ids)
