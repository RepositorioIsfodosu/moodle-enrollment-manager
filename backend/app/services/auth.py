from datetime import UTC, datetime

from fastapi import HTTPException, Request
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import token_digest
from app.models import AuthSession, Role, UserRole

# One atomic fixed-window counter, shared by all API processes.
LIMIT_SCRIPT = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return {n, redis.call('TTL', KEYS[1])}
"""


def login_limit(request: Request, email: str):
    settings = get_settings()
    ip = request.client.host if request.client else "unknown"
    try:
        with Redis.from_url(
            settings.redis_url.get_secret_value(), socket_connect_timeout=2, socket_timeout=2
        ) as client:
            for kind, value, limit in (
                ("ip", ip, settings.login_ip_limit),
                ("account", email, settings.login_account_limit),
            ):
                key = "auth:login:" + kind + ":" + token_digest(value)
                count, ttl = client.eval(LIMIT_SCRIPT, 1, key, settings.login_window_seconds)
                if count > limit:
                    raise HTTPException(
                        429,
                        "Demasiados intentos; inténtalo más tarde",
                        headers={"Retry-After": str(max(ttl, 1))},
                    )
    except RedisError:
        raise HTTPException(503, "Autenticación temporalmente no disponible") from None


def roles_for(db: Session, user_id) -> list[str]:
    return list(
        db.scalars(
            select(Role.name).join(UserRole).where(UserRole.user_id == user_id).order_by(Role.name)
        )
    )


def revoke_sessions(db: Session, user_id):
    db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))


def administration_lock(db: Session):
    # Serialize role/activation changes and bootstrap to protect the last active admin.
    db.execute(text("SELECT pg_advisory_xact_lock(732194027)"))


def purge_expired_sessions(db: Session) -> int:
    result = db.execute(delete(AuthSession).where(AuthSession.expires_at <= datetime.now(UTC)))
    return result.rowcount
