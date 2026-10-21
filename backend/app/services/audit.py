from sqlalchemy.orm import Session

from app.models import AuditLog


def audit(db: Session, action: str, actor_id=None, entity_id=None, **context):
    # Only explicitly selected scalar metadata; never pass request bodies or credentials.
    db.add(
        AuditLog(
            action=action,
            actor_id=actor_id,
            entity_id=str(entity_id) if entity_id else None,
            safe_context=context,
        )
    )
