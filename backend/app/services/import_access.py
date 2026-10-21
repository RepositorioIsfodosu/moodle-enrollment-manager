from fastapi import HTTPException
from sqlalchemy import select

from app.core.permissions import permissions_for
from app.models import ConnectionGrant, MoodleConnection, User
from app.services.auth import roles_for


def is_admin(db, user_id):
    return "administrador" in roles_for(db, user_id)


def own_resource(db, user, owner_id):
    if user.id != owner_id and not is_admin(db, user.id):
        raise HTTPException(404, "Recurso no encontrado")


def connection_access(db, user_id, connection_id, writing=True):
    user = db.get(User, user_id)
    permissions = permissions_for(roles_for(db, user_id))
    if (
        not user
        or not user.active
        or ("imports:write" if writing else "jobs:read") not in permissions
    ):
        raise HTTPException(403, "Permisos insuficientes")
    connection = db.get(MoodleConnection, connection_id)
    grant = db.scalar(
        select(ConnectionGrant.user_id).where(
            ConnectionGrant.connection_id == connection_id, ConnectionGrant.user_id == user_id
        )
    )
    if not connection or (not is_admin(db, user_id) and grant is None):
        raise HTTPException(404, "Conexión no autorizada o inexistente")
    if writing and not connection.active:
        raise HTTPException(409, "La conexión está desactivada")
    return connection
