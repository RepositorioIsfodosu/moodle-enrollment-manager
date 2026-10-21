from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import permissions_for
from app.core.security import token_digest
from app.db.session import get_session
from app.models import AuthSession, User
from app.services.audit import audit
from app.services.auth import administration_lock, roles_for

bearer = HTTPBearer(auto_error=False)


def require_same_origin(request: Request):
    try:
        origin = urlsplit(request.headers.get("origin", ""))
    except ValueError:
        raise HTTPException(403, "Origen no válido") from None
    if (
        request.headers.get("x-csrf-protection") != "1"
        or origin.scheme not in {"http", "https"}
        or origin.netloc != request.headers.get("host")
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise HTTPException(403, "Solicitud entre orígenes no permitida")


def current_user(
    request: Request,
    db: Session = Depends(get_session),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> User:
    denied = HTTPException(
        401, "Sesión no válida o caducada", headers={"WWW-Authenticate": "Bearer"}
    )
    token = credentials.credentials if credentials else request.cookies.get("mem_session", "")
    if not credentials and token and request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_same_origin(request)
    if len(token) != 43:
        raise denied
    login = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == token_digest(token),
            AuthSession.expires_at > datetime.now(UTC),
        )
    )
    user = db.get(User, login.user_id) if login else None
    if not user or not user.active:
        raise denied
    return user


def require_permission(permission: str):
    def dependency(
        request: Request,
        db: Session = Depends(get_session),
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ):
        if permission == "users:manage":
            administration_lock(db)
        user = current_user(request, db, credentials)
        if permission not in permissions_for(roles_for(db, user.id)):
            audit(db, "authorization.denied", user.id, permission=permission)
            db.commit()
            raise HTTPException(403, "Permisos insuficientes")
        return user

    return dependency
