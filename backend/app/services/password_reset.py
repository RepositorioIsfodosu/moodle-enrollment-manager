"""One-time password reset tokens and SMTP delivery without credential logging."""

import secrets
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from urllib.parse import urlencode, urlsplit, urlunsplit

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import token_digest
from app.models import PasswordResetToken, User
from app.services.audit import audit
from app.services.auth import revoke_sessions


def reset_delivery_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.smtp_host
        and settings.smtp_from
        and settings.password_reset_url
        and settings.smtp_username
        and settings.smtp_password
    )


def reset_url(token: str) -> str:
    base = get_settings().password_reset_url
    if not base:
        raise RuntimeError("Password reset URL not configured")
    parts = urlsplit(str(base))
    query = urlencode({"token": token})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def send_reset_email(recipient: str, token: str):
    settings = get_settings()
    if not reset_delivery_configured():
        raise RuntimeError("Password reset email is not configured")
    message = EmailMessage()
    message["Subject"] = "Restablece tu contraseña de Moodle Enrollment Manager"
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message.set_content(
        "Se solicitó restablecer tu contraseña. Usa este enlace una sola vez dentro de "
        f"{settings.password_reset_ttl_seconds // 60} minutos:\n\n{reset_url(token)}\n\n"
        "Si no solicitaste este cambio, ignora este mensaje."
    )
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as client:
            client.ehlo()
            if settings.smtp_starttls:
                client.starttls()
                client.ehlo()
            client.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            client.send_message(message)
    except (OSError, smtplib.SMTPException):
        raise RuntimeError("Password reset email delivery failed") from None


def create_and_send_reset(db: Session, email: str):
    """Returns silently for unknown/inactive identities to prevent account enumeration."""
    if not reset_delivery_configured():
        raise HTTPException(503, "Recuperación de contraseña no configurada")
    user = db.scalar(select(User).where(User.email == email).with_for_update())
    if not user or not user.active:
        audit(db, "auth.password_reset_requested", reason="unknown_or_inactive")
        db.commit()
        return
    now = datetime.now(UTC)
    db.execute(
        delete(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
    )
    raw_token = secrets.token_urlsafe(32)
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=token_digest(raw_token),
            expires_at=now + timedelta(seconds=get_settings().password_reset_ttl_seconds),
        )
    )
    audit(db, "auth.password_reset_requested", user.id, user.id)
    db.commit()
    try:
        send_reset_email(user.email, raw_token)
    except RuntimeError:
        # Do not leave a usable token if delivery is unknown or failed.
        db.execute(
            delete(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_digest(raw_token)
            )
        )
        audit(db, "auth.password_reset_delivery_failed", user.id, user.id)
        db.commit()
        raise HTTPException(503, "No se pudo enviar el correo de recuperación") from None


def consume_reset(db: Session, token: str, password_hash: str):
    now = datetime.now(UTC)
    item = db.scalar(
        select(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash == token_digest(token),
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .with_for_update()
    )
    if not item:
        raise HTTPException(400, "El enlace de recuperación no es válido o ha caducado")
    user = db.get(User, item.user_id, with_for_update=True)
    if not user or not user.active:
        raise HTTPException(400, "El enlace de recuperación no es válido o ha caducado")
    item.used_at = now
    user.password_hash = password_hash
    revoke_sessions(db, user.id)
    audit(db, "auth.password_reset_completed", user.id, user.id)
    db.commit()
