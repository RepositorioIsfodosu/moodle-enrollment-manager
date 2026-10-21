from typing import Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import require_permission
from app.core.config import get_settings
from app.db.session import get_session
from app.models import CsvContent, CsvFile, CsvImport, CsvOperation, ImportProfile, User
from app.schemas.csv import FileView, ImportView, Normalize, Page, ProfileCreate, ProfileView
from app.services.audit import audit
from app.services.import_access import is_admin, own_resource
from app.services.imports import file_view, import_view, normalize_file, persist_file, profile_view

router = APIRouter(tags=["csv-imports"])
writer, reader = require_permission("imports:write"), require_permission("imports:read")


def page(db, query, offset, limit, transform):
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.offset(offset).limit(limit))
    return Page(
        items=[transform(row).model_dump() for row in rows], total=total, offset=offset, limit=limit
    )


@router.post("/csv-files", response_model=FileView, status_code=201)
async def upload(
    request: Request,
    filename: str = Query(min_length=1, max_length=255),
    encoding: Literal["utf-8", "cp1252", "latin-1"] = "utf-8",
    delimiter: Literal["auto", ",", ";", "\t", "|"] = "auto",
    actor: User = Depends(writer),
    db: Session = Depends(get_session),
):
    if (
        not filename.lower().endswith(".csv")
        or any(c in filename for c in "/\\\r\n")
        or any(ord(c) < 32 for c in filename)
    ):
        raise HTTPException(422, "Nombre CSV no válido")
    if request.headers.get("content-type", "").split(";")[0] not in (
        "text/csv",
        "application/octet-stream",
    ):
        raise HTTPException(
            415, "Enviar bytes CSV con Content-Type text/csv o application/octet-stream"
        )
    maximum = get_settings().csv_max_bytes
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > maximum:
            raise HTTPException(413, "Tamaño máximo de archivo excedido")
        content.extend(chunk)
    return await run_in_threadpool(
        persist_file, db, actor, filename, bytes(content), encoding, delimiter
    )


@router.get("/csv-files", response_model=Page)
def files(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    actor: User = Depends(reader),
    db: Session = Depends(get_session),
):
    query = select(CsvFile)
    if not is_admin(db, actor.id):
        query = query.where(CsvFile.uploaded_by == actor.id)
    return page(db, query.order_by(CsvFile.created_at.desc(), CsvFile.id), offset, limit, file_view)


@router.get("/csv-files/{file_id}", response_model=FileView)
def detail(file_id: UUID, actor: User = Depends(reader), db: Session = Depends(get_session)):
    row = db.get(CsvFile, file_id)
    if not row:
        raise HTTPException(404, "Archivo no encontrado")
    own_resource(db, actor, row.uploaded_by)
    return file_view(row)


@router.get("/csv-files/{file_id}/original")
def original(file_id: UUID, actor: User = Depends(reader), db: Session = Depends(get_session)):
    row = db.get(CsvFile, file_id)
    if not row:
        raise HTTPException(404, "Archivo no encontrado")
    own_resource(db, actor, row.uploaded_by)
    content = db.get(CsvContent, file_id)
    if not content:
        raise HTTPException(409, "Original no disponible")
    audit(db, "csv.downloaded", actor.id, file_id)
    db.commit()
    return Response(
        content.content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(row.original_name, safe="")
        },
    )


@router.post("/csv-files/{file_id}/normalize", response_model=ImportView, status_code=201)
def normalize(
    file_id: UUID,
    data: Normalize,
    actor: User = Depends(writer),
    db: Session = Depends(get_session),
):
    return normalize_file(db, actor, file_id, data)


@router.post("/import-profiles", response_model=ProfileView, status_code=201)
def create_profile(
    data: ProfileCreate, actor: User = Depends(writer), db: Session = Depends(get_session)
):
    row = ImportProfile(name=data.name, mapping=data.mapping.model_dump(), owner_id=actor.id)
    db.add(row)
    db.flush()
    audit(db, "csv.profile_created", actor.id, row.id)
    result = profile_view(row)
    db.commit()
    return result


@router.get("/import-profiles", response_model=Page)
def profiles(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    actor: User = Depends(reader),
    db: Session = Depends(get_session),
):
    query = select(ImportProfile)
    if not is_admin(db, actor.id):
        query = query.where(ImportProfile.owner_id == actor.id)
    return page(
        db,
        query.order_by(ImportProfile.created_at.desc(), ImportProfile.id),
        offset,
        limit,
        profile_view,
    )


@router.put("/import-profiles/{profile_id}", response_model=ProfileView)
def update_profile(
    profile_id: UUID,
    data: ProfileCreate,
    actor: User = Depends(writer),
    db: Session = Depends(get_session),
):
    row = db.scalar(select(ImportProfile).where(ImportProfile.id == profile_id).with_for_update())
    if not row:
        raise HTTPException(404, "Perfil no encontrado")
    own_resource(db, actor, row.owner_id)
    row.name, row.mapping = data.name, data.mapping.model_dump()
    audit(db, "csv.profile_updated", actor.id, row.id)
    result = profile_view(row)
    db.commit()
    return result


@router.get("/csv-imports/{import_id}", response_model=ImportView)
def imported(import_id: UUID, actor: User = Depends(reader), db: Session = Depends(get_session)):
    row = db.get(CsvImport, import_id)
    if not row:
        raise HTTPException(404, "Importación no encontrada")
    own_resource(db, actor, row.owner_id)
    return import_view(db, row)


@router.get("/csv-imports/{import_id}/operations", response_model=Page)
def operations(
    import_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: Literal["pending", "invalid", "duplicate"] | None = None,
    actor: User = Depends(reader),
    db: Session = Depends(get_session),
):
    row = db.get(CsvImport, import_id)
    if not row:
        raise HTTPException(404, "Importación no encontrada")
    own_resource(db, actor, row.owner_id)
    query = select(CsvOperation).where(CsvOperation.import_id == import_id)
    if status:
        query = query.where(CsvOperation.local_status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    from app.services.csv_parser import MESSAGES

    rows = db.scalars(
        query.order_by(CsvOperation.source_row, CsvOperation.slot).offset(offset).limit(limit)
    )
    return Page(
        items=[
            {
                "id": op.id,
                "source_row": op.source_row,
                "slot": op.slot,
                "payload": op.payload,
                "status": op.local_status,
                "error_code": op.error_code,
                "reason": MESSAGES.get(op.error_code, op.error_code),
            }
            for op in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )
