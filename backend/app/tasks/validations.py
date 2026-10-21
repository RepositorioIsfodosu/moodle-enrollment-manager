import logging
from datetime import UTC, datetime, timedelta

from kombu.exceptions import OperationalError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import session as database
from app.models import SystemSetting, ValidationRun
from app.services.validation_engine import run_batch
from app.workers.celery_app import celery_app


@celery_app.task(name="validation.batch", acks_late=True, reject_on_worker_lost=True)
def validate_batch(run_id):
    try:
        more = run_batch(run_id)
        if more:
            enqueue(run_id)
    except Exception:  # noqa: BLE001 - task boundary must redact exceptions and preserve failed status.
        logging.getLogger(__name__).error("validation_worker_failed")
        raise RuntimeError("validation_worker_failed") from None


def enqueue(run_id):
    with Session(database.get_engine()) as db:
        run = db.scalar(select(ValidationRun).where(ValidationRun.id == run_id).with_for_update())
        if not run or run.state not in ("queued", "running"):
            return
        run.dispatched_at = datetime.now(UTC)
        db.commit()
    try:
        validate_batch.apply_async(args=[str(run_id)], retry=False)
    except OperationalError:
        logging.getLogger(__name__).warning("validation_dispatch_deferred")


@celery_app.task(name="validation.recover")
def recover():
    now = datetime.now(UTC)
    with Session(database.get_engine()) as db:
        ids = list(
            db.scalars(
                select(ValidationRun.id)
                .where(
                    or_(
                        ValidationRun.state == "queued",
                        (ValidationRun.state == "running") & (ValidationRun.lease_until < now),
                    ),
                    or_(
                        ValidationRun.dispatched_at.is_(None),
                        ValidationRun.dispatched_at < now - timedelta(seconds=60),
                    ),
                )
                .order_by(ValidationRun.created_at)
                .limit(100)
            )
        )
        marker = db.get(SystemSetting, "validation_recovery")
        value = {"at": datetime.now(UTC).isoformat()}
        if marker:
            marker.value = value
        else:
            db.add(SystemSetting(key="validation_recovery", value=value))
        db.commit()
    for run_id in ids:
        enqueue(run_id)
