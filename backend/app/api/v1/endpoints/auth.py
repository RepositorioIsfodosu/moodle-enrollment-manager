import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.dependencies import bearer, current_user
from app.core.config import get_settings
from app.core.permissions import permissions_for
from app.core.security import dummy_hash, hash_password, hasher, token_digest, verify_password
from app.db.session import get_session
from app.models import AuthSession, User
from app.schemas.auth import Login, Me, PasswordChange, TokenView
from app.services.audit import audit
from app.services.auth import login_limit, revoke_sessions, roles_for

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenView)
def login(data: Login, request: Request, response: Response, db: Session = Depends(get_session)):
    try:
        login_limit(request, str(data.email))
    except HTTPException as error:
        audit(
            db,
            "auth.login_blocked",
            reason="rate_limit" if error.status_code == 429 else "limiter_unavailable",
        )
        db.commit()
        raise
    user = db.scalar(select(User).where(User.email == str(data.email)).with_for_update())
    valid = verify_password(
        data.password.get_secret_value(), user.password_hash if user else dummy_hash()
    )
    if not user or not valid or not user.active:
        audit(db, "auth.login_failed", reason="invalid_credentials")
        db.commit()
        raise HTTPException(401, "Credenciales incorrectas", headers={"WWW-Authenticate": "Bearer"})
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(data.password.get_secret_value())
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(seconds=get_settings().session_ttl_seconds)
    db.add(AuthSession(user_id=user.id, token_hash=token_digest(token), expires_at=expires))
    audit(db, "auth.login", user.id, user.id)
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return TokenView(access_token=token, expires_at=expires)


@router.get("/me", response_model=Me)
def me(user: User = Depends(current_user), db: Session = Depends(get_session)):
    roles = roles_for(db, user.id)
    return Me(
        id=user.id,
        email=user.email,
        active=user.active,
        created_at=user.created_at,
        roles=roles,
        permissions=permissions_for(roles),
    )


@router.post("/logout", status_code=204)
def logout(
    user: User = Depends(current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_session),
):
    db.execute(
        delete(AuthSession).where(AuthSession.token_hash == token_digest(credentials.credentials))
    )
    audit(db, "auth.logout", user.id, user.id)
    db.commit()


@router.post("/logout-all", status_code=204)
def logout_all(user: User = Depends(current_user), db: Session = Depends(get_session)):
    db.refresh(user, with_for_update=True)
    revoke_sessions(db, user.id)
    audit(db, "auth.logout_all", user.id, user.id)
    db.commit()


@router.post("/change-password", status_code=204)
def change_password(
    data: PasswordChange,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    login_limit(request, user.email)
    db.refresh(user, with_for_update=True)
    if not user.active:
        raise HTTPException(401, "Sesión no válida")
    if not verify_password(data.current_password.get_secret_value(), user.password_hash):
        audit(db, "auth.password_change_failed", user.id, user.id)
        db.commit()
        raise HTTPException(400, "Contraseña actual incorrecta")
    user.password_hash = hash_password(data.new_password.get_secret_value())
    revoke_sessions(db, user.id)
    audit(db, "auth.password_changed", user.id, user.id)
    db.commit()
