from celery import Celery

from app.core.config import get_settings

celery_app = Celery("enrollment", broker=get_settings().redis_url.get_secret_value())
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
)
# No enrollment task exists until phase 5. Database records will remain authoritative.
