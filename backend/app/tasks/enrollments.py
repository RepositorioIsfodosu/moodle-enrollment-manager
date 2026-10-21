import logging
from datetime import UTC, datetime, timedelta

from kombu.exceptions import OperationalError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import session as database
from app.models import EnrollmentJob, SystemSetting
from app.services.enrollment_engine import run_batch
from app.workers.celery_app import celery_app


@celery_app.task(name="enrollment.batch", acks_late=True, reject_on_worker_lost=True)
def execute(job_id):
    try:
        if run_batch(job_id):
            enqueue(job_id)
    except Exception:  # noqa: BLE001 - task boundary must not reveal secrets.
        logging.getLogger(__name__).error("enrollment_worker_failed")
        raise RuntimeError("enrollment_worker_failed") from None


def enqueue(job_id):
    with Session(database.get_engine()) as db:
        job = db.scalar(select(EnrollmentJob).where(EnrollmentJob.id == job_id).with_for_update())
        if not job or job.state not in {"queued", "running", "pausing", "cancelling"}:
            return
        job.dispatched_at = datetime.now(UTC)
        delay = (
            max(0, (job.next_run_at - datetime.now(UTC)).total_seconds()) if job.next_run_at else 0
        )
        if job.state in {"pausing", "cancelling"}:
            delay = 0
        db.commit()
    try:
        execute.apply_async(args=[str(job_id)], countdown=delay, retry=False)
    except OperationalError:
        logging.getLogger(__name__).warning("enrollment_dispatch_deferred")


@celery_app.task(name="enrollment.recover")
def recover():
    current = datetime.now(UTC)
    with Session(database.get_engine()) as db:
        ids = list(
            db.scalars(
                select(EnrollmentJob.id)
                .where(
                    EnrollmentJob.state.in_(["queued", "running", "pausing", "cancelling"]),
                    or_(EnrollmentJob.lease_until.is_(None), EnrollmentJob.lease_until < current),
                    or_(
                        EnrollmentJob.dispatched_at.is_(None),
                        EnrollmentJob.dispatched_at < current - timedelta(seconds=60),
                    ),
                    or_(
                        EnrollmentJob.state.in_(["pausing", "cancelling"]),
                        EnrollmentJob.next_run_at.is_(None),
                        EnrollmentJob.next_run_at <= current,
                    ),
                )
                .order_by(EnrollmentJob.created_at)
                .limit(100)
            )
        )
        marker = db.get(SystemSetting, "enrollment_recovery")
        value = {"at": current.isoformat()}
        if marker:
            marker.value = value
        else:
            db.add(SystemSetting(key="enrollment_recovery", value=value))
        db.commit()
    for job_id in ids:
        enqueue(job_id)
