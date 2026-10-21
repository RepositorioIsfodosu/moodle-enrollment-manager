from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.core.token_vault import encrypt_token
from app.db.session import get_session
from app.integrations.moodle.client import MoodleClient
from app.models import MoodleConnection, MoodleConnectionCheck, User
from app.schemas.moodle import (
    CheckPage,
    ConnectionCreate,
    ConnectionPage,
    ConnectionUpdate,
    ConnectionView,
)
from app.services.audit import audit
from app.services.moodle_connections import check_connection, view

router = APIRouter(prefix="/moodle-connections", tags=["moodle-connections"])
manager = require_permission("connections:manage")


def moodle_client():
    return MoodleClient()


@router.post("", response_model=ConnectionView, status_code=201)
def create(
    data: ConnectionCreate, actor: User = Depends(manager), db: Session = Depends(get_session)
):
    connection = MoodleConnection(
        name=data.name,
        base_url=data.base_url,
        token_ciphertext=encrypt_token(data.token.get_secret_value()),
        description=data.description,
        limits=data.limits.model_dump(),
    )
    db.add(connection)
    db.flush()
    audit(db, "moodle.created", actor.id, connection.id)
    result = view(connection)
    db.commit()
    return result


@router.get("", response_model=ConnectionPage)
def listing(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    active: bool | None = None,
    actor: User = Depends(manager),
    db: Session = Depends(get_session),
):
    query = select(MoodleConnection)
    if active is not None:
        query = query.where(MoodleConnection.active == active)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(MoodleConnection.created_at.desc(), MoodleConnection.id)
        .offset(offset)
        .limit(limit)
    )
    return ConnectionPage(items=[view(c) for c in rows], total=total, offset=offset, limit=limit)


@router.get("/{connection_id}", response_model=ConnectionView)
def detail(connection_id: UUID, actor: User = Depends(manager), db: Session = Depends(get_session)):
    connection = db.get(MoodleConnection, connection_id)
    if not connection:
        raise HTTPException(404, "Conexión no encontrada")
    return view(connection)


@router.patch("/{connection_id}", response_model=ConnectionView)
def update(
    connection_id: UUID,
    data: ConnectionUpdate,
    actor: User = Depends(manager),
    db: Session = Depends(get_session),
):
    connection = db.scalar(
        select(MoodleConnection).where(MoodleConnection.id == connection_id).with_for_update()
    )
    if not connection:
        raise HTTPException(404, "Conexión no encontrada")
    if not data.model_fields_set:
        return view(connection)
    # Reuse complete validation so PATCH cannot bypass URL/token constraints.
    candidate = {
        "name": connection.name,
        "base_url": connection.base_url,
        "description": connection.description,
        "limits": connection.limits,
        "token": "unchanged",
    }
    candidate.update(data.model_dump(exclude_unset=True, exclude={"active"}))
    try:
        checked = ConnectionCreate.model_validate(candidate)
    except ValidationError:
        raise HTTPException(422, "Configuración de conexión no válida") from None
    if checked.base_url != connection.base_url and "token" not in data.model_fields_set:
        raise HTTPException(422, "Cambiar el destino requiere proporcionar un token nuevo")
    connection.name, connection.base_url = checked.name, checked.base_url
    connection.description, connection.limits = checked.description, checked.limits.model_dump()
    if "token" in data.model_fields_set:
        connection.token_ciphertext = encrypt_token(checked.token.get_secret_value())
    if "active" in data.model_fields_set:
        connection.active = data.active
    connection.configuration_version += 1
    connection.status = "unverified" if connection.active else "disabled"
    connection.available_functions, connection.site_metadata = [], {}
    connection.last_verified_at, connection.last_error_code, connection.latency_ms = (
        None,
        None,
        None,
    )
    audit(db, "moodle.updated", actor.id, connection.id, fields=sorted(data.model_fields_set))
    result = view(connection)
    db.commit()
    return result


@router.post("/{connection_id}/test", response_model=ConnectionView)
def test(
    connection_id: UUID,
    actor: User = Depends(manager),
    db: Session = Depends(get_session),
    client: MoodleClient = Depends(moodle_client),
):
    return check_connection(db, connection_id, actor.id, client)


@router.get("/{connection_id}/checks", response_model=CheckPage)
def checks(
    connection_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    actor: User = Depends(manager),
    db: Session = Depends(get_session),
):
    if not db.get(MoodleConnection, connection_id):
        raise HTTPException(404, "Conexión no encontrada")
    query = select(MoodleConnectionCheck).where(
        MoodleConnectionCheck.connection_id == connection_id
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = list(
        db.scalars(
            query.order_by(MoodleConnectionCheck.created_at.desc(), MoodleConnectionCheck.id)
            .offset(offset)
            .limit(limit)
        )
    )
    return CheckPage(items=rows, total=total, offset=offset, limit=limit)
