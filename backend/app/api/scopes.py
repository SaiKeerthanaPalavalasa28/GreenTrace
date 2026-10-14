import hashlib
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Path, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app import scope_analysis as sa
from app.config import get_settings
from app.deps import AdminUser, CurrentUser, DbSession
from app.models import Organization, ScopeDocument
from app.scope_summary import build_report, build_summary, report_pdf
from app.storage import Storage, get_storage

router = APIRouter(prefix="/scopes", tags=["scopes"])
Store = Annotated[Storage, Depends(get_storage)]
ScopeNo = Annotated[int, Path(ge=1, le=3)]


def _doc_out(d: ScopeDocument) -> dict:
    return {"id": str(d.id), "scope": d.scope, "filename": d.original_filename, "page_count": d.page_count,
            "items": d.items, "flags": d.flags, "risk": sa.risk_of(d.flags), "total_kg_co2e": d.total_kg_co2e,
            "uploaded_at": d.uploaded_at.isoformat(), "uploaded_by": str(d.uploaded_by)}


def _get_doc(db: Session, org_id: uuid.UUID, doc_id: uuid.UUID) -> ScopeDocument:
    d = db.get(ScopeDocument, doc_id)
    if d is None or d.org_id != org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return d


def org_budget_kg(org: Organization, scope: int) -> float | None:
    t = getattr(org, f"scope{scope}_budget_t")
    return None if t is None else t * 1000.0


@router.get("/summary")
def summary(user: CurrentUser, db: DbSession):
    return build_summary(db, db.get(Organization, user.org_id))


@router.get("/report")
def report(user: CurrentUser, db: DbSession):
    return build_report(db, db.get(Organization, user.org_id))


@router.get("/report.pdf")
def report_download(user: CurrentUser, db: DbSession):
    org = db.get(Organization, user.org_id)
    return Response(report_pdf(build_report(db, org)), media_type="application/pdf",
                    headers={"Content-Disposition": "attachment; filename=greentrace-report.pdf"})


class BudgetsIn(BaseModel):
    scope1_budget_t: float | None = Field(None, ge=0, le=1e9)
    scope2_budget_t: float | None = Field(None, ge=0, le=1e9)
    scope3_budget_t: float | None = Field(None, ge=0, le=1e9)


@router.put("/budgets")
def set_budgets(body: BudgetsIn, admin: AdminUser, db: DbSession):
    """Tonnes CO2e allowed per scope for the reporting year. Null clears a budget."""
    org = db.get(Organization, admin.org_id)
    before = audit.snapshot(org)
    for k, v in body.model_dump().items():
        setattr(org, k, v)
    audit.record(db, actor=str(admin.id), action="set_budgets", entity="organization", entity_id=org.id,
                 org_id=org.id, before=before, after=audit.snapshot(org))
    db.commit()
    return build_summary(db, org)


@router.get("/categories")
def categories(user: CurrentUser):
    return {str(s): sa.categories_for(s) for s in (1, 2, 3)}


@router.get("/{scope}/documents")
def list_documents(scope: ScopeNo, user: CurrentUser, db: DbSession):
    docs = db.scalars(select(ScopeDocument).where(ScopeDocument.org_id == user.org_id, ScopeDocument.scope == scope)
                      .order_by(ScopeDocument.uploaded_at.desc())).all()
    return [_doc_out(d) for d in docs]


@router.post("/{scope}/documents", status_code=status.HTTP_201_CREATED)
def upload_documents(scope: ScopeNo, admin: AdminUser, db: DbSession, storage: Store,
                     files: Annotated[list[UploadFile], File()]):
    """One outcome per file; a bad file never fails the others."""
    settings = get_settings()
    if len(files) > settings.max_files_per_upload:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"At most {settings.max_files_per_upload} files per upload")
    org = db.get(Organization, admin.org_id)
    max_bytes = settings.max_upload_mb * 1024 * 1024
    budget = org_budget_kg(org, scope)
    results: list[dict] = []
    seen: set[str] = set()
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
        digest = hashlib.sha256(data).hexdigest()
        if reason is None:
            dup = digest in seen or db.scalars(select(ScopeDocument).where(
                ScopeDocument.org_id == org.id, ScopeDocument.file_hash == digest)).first()
            if dup:
                reason = "This exact file was already uploaded"
        if reason:
            results.append({"filename": name, "outcome": "rejected", "reason": reason})
            continue
        history = [{"total_kg_co2e": d.total_kg_co2e, "items": d.items} for d in db.scalars(select(ScopeDocument).where(
            ScopeDocument.org_id == org.id, ScopeDocument.scope == scope)).all()]
        try:
            res = sa.analyse(data, scope, org.default_region, history, budget)
        except Exception:  # corrupt / encrypted PDFs raise assorted library errors
            results.append({"filename": name, "outcome": "rejected",
                            "reason": "The PDF could not be read (corrupt or password-protected)"})
            continue
        seen.add(digest)
        doc = ScopeDocument(org_id=org.id, scope=scope, original_filename=name,
                            file_path=storage.save_file(f"scope/{org.id}/{digest}.pdf", data), file_hash=digest,
                            page_count=res["page_count"], items=res["items"], flags=res["flags"],
                            total_kg_co2e=res["total_kg_co2e"], uploaded_by=admin.id)
        db.add(doc)
        db.flush()
        audit.record(db, actor=str(admin.id), action="upload", entity="scope_document", entity_id=doc.id,
                     org_id=org.id, after={"scope": scope, "filename": name, "total_kg_co2e": doc.total_kg_co2e})
        results.append({"filename": name, "outcome": "ok", "document": _doc_out(doc)})
    db.commit()
    return {"results": results, "summary": build_summary(db, org)}


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: uuid.UUID, user: CurrentUser, db: DbSession, storage: Store):
    d = _get_doc(db, user.org_id, doc_id)
    return Response(storage.read(d.file_path), media_type="application/pdf",
                    headers={"Content-Disposition": "inline"})


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(doc_id: uuid.UUID, admin: AdminUser, db: DbSession):
    d = _get_doc(db, admin.org_id, doc_id)
    audit.record(db, actor=str(admin.id), action="delete", entity="scope_document", entity_id=d.id, org_id=admin.org_id,
                 before={"scope": d.scope, "filename": d.original_filename, "total_kg_co2e": d.total_kg_co2e})
    db.delete(d)
    db.commit()


class ItemPatch(BaseModel):
    quantity: float | None = Field(None, gt=0, le=1e12)
    category: str | None = None


def _retotal(d: ScopeDocument, admin, db: Session, before_total: float, action: str) -> dict:
    d.total_kg_co2e = sum(i["kg_co2e"] for i in d.items)
    if not any(f["code"] == "manually_edited" for f in d.flags):
        d.flags = [*d.flags, sa.flag("manually_edited", "low", "An admin edited this document's extracted values.")]
    audit.record(db, actor=str(admin.id), action=action, entity="scope_document", entity_id=d.id, org_id=admin.org_id,
                 before={"total_kg_co2e": before_total}, after={"total_kg_co2e": d.total_kg_co2e})
    db.commit()
    return _doc_out(d)


@router.patch("/documents/{doc_id}/items/{index}")
def edit_item(doc_id: uuid.UUID, index: int, body: ItemPatch, admin: AdminUser, db: DbSession):
    d = _get_doc(db, admin.org_id, doc_id)
    if not 0 <= index < len(d.items):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    item = dict(d.items[index])
    if body.category is not None:
        cat = sa.CAT_BY_KEY.get(body.category)
        if cat is None or cat.scope != d.scope:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown category for Scope {d.scope}")
        item["category"] = body.category
    if body.quantity is not None:
        item["quantity"] = body.quantity
    org = db.get(Organization, admin.org_id)
    try:
        item = sa.recompute_item(item, org.default_region)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    item["edited"] = True
    before = d.total_kg_co2e
    items = list(d.items)
    items[index] = item
    d.items = items  # reassign so SQLAlchemy sees the JSON change
    return _retotal(d, admin, db, before, "edit_item")


@router.delete("/documents/{doc_id}/items/{index}")
def delete_item(doc_id: uuid.UUID, index: int, admin: AdminUser, db: DbSession):
    d = _get_doc(db, admin.org_id, doc_id)
    if not 0 <= index < len(d.items):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    before = d.total_kg_co2e
    d.items = [i for n, i in enumerate(d.items) if n != index]
    return _retotal(d, admin, db, before, "delete_item")
