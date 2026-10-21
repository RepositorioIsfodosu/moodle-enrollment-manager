import hashlib
import uuid
from collections import Counter

from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models import CsvContent, CsvFile, CsvImport, CsvOperation, ImportProfile
from app.schemas.csv import FileView, ImportView, Normalize, ProfileView
from app.services.audit import audit
from app.services.csv_parser import normalize, parse_csv, resolved_mapping
from app.services.import_access import own_resource


def file_view(row):
    return FileView(**{name: getattr(row, name) for name in FileView.model_fields})


def profile_view(row):
    return ProfileView(id=row.id, owner_id=row.owner_id, name=row.name, mapping=row.mapping)


def import_view(db, row):
    counts = dict(
        db.execute(
            select(CsvOperation.local_status, func.count())
            .where(CsvOperation.import_id == row.id)
            .group_by(CsvOperation.local_status)
        ).all()
    )
    return ImportView(
        id=row.id,
        file_id=row.file_id,
        mapping_snapshot=row.mapping_snapshot,
        operation_count=row.operation_count,
        counts=counts,
    )


def persist_file(db, actor, filename, content, encoding, delimiter):
    headers, rows, separator = parse_csv(content, encoding, delimiter, get_settings().csv_max_rows)
    file = CsvFile(
        uploaded_by=actor.id,
        original_name=filename,
        storage_key=str(uuid.uuid4()),
        sha256=hashlib.sha256(content).hexdigest(),
        byte_count=len(content),
        row_count=len(rows),
        headers=headers,
        preview=rows[:20],
        encoding=encoding,
        delimiter=separator,
    )
    db.add(file)
    db.flush()
    db.add(CsvContent(file_id=file.id, content=content))
    audit(db, "csv.uploaded", actor.id, file.id, rows=len(rows), bytes=len(content))
    result = file_view(file)
    db.commit()
    return result


def normalize_file(db, actor, file_id, data: Normalize):
    file = db.get(CsvFile, file_id)
    if not file:
        raise HTTPException(404, "Archivo no encontrado")
    own_resource(db, actor, file.uploaded_by)
    mapping = data.mapping
    if data.profile_id:
        profile = db.get(ImportProfile, data.profile_id)
        if not profile:
            raise HTTPException(404, "Perfil no encontrado")
        own_resource(db, actor, profile.owner_id)
        from app.schemas.csv import Mapping

        mapping = Mapping.model_validate(profile.mapping)
    content = db.get(CsvContent, file_id)
    if not content:
        raise HTTPException(409, "Archivo legado sin original almacenado; volver a cargar")
    _, rows, _ = parse_csv(
        content.content, file.encoding, file.delimiter, get_settings().csv_max_rows
    )
    mapping = resolved_mapping(mapping, file.headers)
    operations = normalize(rows, mapping, get_settings().csv_max_operations)
    entry = CsvImport(
        file_id=file.id,
        owner_id=actor.id,
        mapping_snapshot=mapping.model_dump(),
        operation_count=len(operations),
    )
    db.add(entry)
    db.flush()
    db.add_all(CsvOperation(import_id=entry.id, **operation) for operation in operations)
    audit(
        db,
        "csv.normalized",
        actor.id,
        entry.id,
        operations=len(operations),
        counts=dict(Counter(x["local_status"] for x in operations)),
    )
    db.flush()
    result = import_view(db, entry)
    db.commit()
    return result


def record_view(record, op):
    from app.services.csv_parser import MESSAGES

    code = record.error_code
    return {
        "id": record.id,
        "operation_id": op.id,
        "import_id": op.import_id,
        "source_row": op.source_row,
        "slot": op.slot,
        "payload": op.payload,
        "status": record.status,
        "error_code": code,
        "reason": MESSAGES.get(code, code),
        "checked_at": record.checked_at,
        "resolved_user_id": record.resolved_user_id,
        "resolved_course_id": record.resolved_course_id,
        "resolved_group_id": record.resolved_group_id,
        "approval_id": record.approval_id,
        "role_evidence_source": "administrator_attestation" if record.approval_id else None,
    }
