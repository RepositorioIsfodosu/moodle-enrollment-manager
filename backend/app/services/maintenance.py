"""Delete only expired sessions and old terminal-run caches, preserving history and CSV."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select

from app.models import AuthSession, ValidationCache, ValidationRun
from app.services.audit import audit


def purge_transient(db, *, days=30, execute=False):
    if not 7 <= days <= 3650:
        raise ValueError("La retención de caché debe estar entre 7 y 3650 días")
    now = datetime.now(UTC)
    runs = select(ValidationRun.id).where(
        ValidationRun.state.in_(["completed", "failed", "cancelled"]),
        ValidationRun.finished_at < now - timedelta(days=days),
    )
    predicates = [
        (AuthSession, AuthSession.expires_at <= now),
        (ValidationCache, ValidationCache.run_id.in_(runs)),
    ]
    result = {}
    for model, predicate in predicates:
        if execute:
            count = db.execute(delete(model).where(predicate)).rowcount
        else:
            count = db.scalar(select(func.count()).select_from(model).where(predicate))
        result[model.__tablename__] = count
    if execute:
        audit(db, "maintenance.transient_purged", cache_retention_days=days, **result)
        db.commit()
    return result
