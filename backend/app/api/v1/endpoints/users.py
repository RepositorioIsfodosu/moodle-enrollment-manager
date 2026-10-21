from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.core.permissions import ROLE_PERMISSIONS
from app.core.security import hash_password
from app.db.session import get_session
from app.models import Role, User, UserRole
from app.schemas.auth import PasswordReset, RoleView, UserCreate, UserPage, UserUpdate, UserView
from app.services.audit import audit
from app.services.auth import revoke_sessions, roles_for

router = APIRouter(tags=["users"])
admin = require_permission("users:manage")


def view(db, user):
    return UserView(
        id=user.id,
        email=user.email,
        active=user.active,
        created_at=user.created_at,
        roles=roles_for(db, user.id),
    )


def assign_roles(db, user, names):
    roles = list(db.scalars(select(Role).where(Role.name.in_(set(names)))))
    if len(roles) != len(set(names)):
        raise HTTPException(409, "Roles no inicializados; verificar migraciones")
    db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    db.add_all(UserRole(user_id=user.id, role_id=role.id) for role in roles)
    db.flush()


@router.get("/roles", response_model=list[RoleView])
def roles(actor: User = Depends(admin)):
    return [
        RoleView(name=name, permissions=sorted(permissions))
        for name, permissions in ROLE_PERMISSIONS.items()
    ]


@router.get("/users", response_model=UserPage)
def users(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    search: str | None = Query(None, max_length=100),
    active: bool | None = None,
    actor: User = Depends(admin),
    db: Session = Depends(get_session),
):
    query = select(User)
    if search:
        query = query.where(User.email.contains(search.lower(), autoescape=True))
    if active is not None:
        query = query.where(User.active == active)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(User.created_at.desc(), User.id).offset(offset).limit(limit))
    return UserPage(
        items=[view(db, user) for user in rows], total=total, offset=offset, limit=limit
    )


@router.post("/users", response_model=UserView, status_code=201)
def create_user(data: UserCreate, actor: User = Depends(admin), db: Session = Depends(get_session)):
    if db.scalar(select(User.id).where(User.email == str(data.email))):
        raise HTTPException(409, "El usuario ya existe")
    user = User(
        email=str(data.email), password_hash=hash_password(data.password.get_secret_value())
    )
    db.add(user)
    db.flush()
    assign_roles(db, user, data.roles)
    audit(db, "users.created", actor.id, user.id, roles=sorted(set(data.roles)))
    result = view(db, user)
    db.commit()
    return result


@router.get("/users/{user_id}", response_model=UserView)
def get_user(user_id: UUID, actor: User = Depends(admin), db: Session = Depends(get_session)):
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if not user:
        raise HTTPException(404, "Usuario no encontrado")
    return view(db, user)


@router.patch("/users/{user_id}", response_model=UserView)
def update_user(
    user_id: UUID,
    data: UserUpdate,
    actor: User = Depends(admin),
    db: Session = Depends(get_session),
):
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if not user:
        raise HTTPException(404, "Usuario no encontrado")
    old_roles = roles_for(db, user.id)
    if (
        user.active
        and "administrador" in old_roles
        and (data.active is False or (data.roles is not None and "administrador" not in data.roles))
    ):
        other = db.scalar(
            select(User.id)
            .join(UserRole)
            .join(Role)
            .where(User.active.is_(True), User.id != user.id, Role.name == "administrador")
        )
        if not other:
            raise HTTPException(409, "Debe conservarse al menos un administrador activo")
    if data.active is not None:
        user.active = data.active
    if data.roles is not None:
        assign_roles(db, user, data.roles)
    if data.model_fields_set:
        revoke_sessions(db, user.id)
        audit(
            db,
            "users.updated",
            actor.id,
            user.id,
            fields=sorted(data.model_fields_set),
            active=user.active,
            roles=roles_for(db, user.id),
        )
    db.flush()
    result = view(db, user)
    db.commit()
    return result


@router.post("/users/{user_id}/reset-password", status_code=204)
def reset_password(
    user_id: UUID,
    data: PasswordReset,
    actor: User = Depends(admin),
    db: Session = Depends(get_session),
):
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if not user:
        raise HTTPException(404, "Usuario no encontrado")
    user.password_hash = hash_password(data.new_password.get_secret_value())
    revoke_sessions(db, user.id)
    audit(db, "users.password_reset", actor.id, user.id)
    db.commit()
