from celery import Celery

from app.core.config import get_settings

celery_app = Celery(
    "enrollment",
    broker=get_settings().redis_url.get_secret_value(),
    include=["app.tasks.validations", "app.tasks.enrollments"],
)
celery_app.conf.update(
    broker_connection_timeout=2,
    broker_transport_options={"socket_connect_timeout": 2, "socket_timeout": 2},
    beat_schedule={
        "validation-recovery": {"task": "validation.recover", "schedule": 15.0},
        "enrollment-recovery": {"task": "enrollment.recover", "schedule": 15.0},
    },
    task_routes={
        "enrollment.batch": {"queue": "enrollment"},
        "enrollment.recover": {"queue": "maintenance"},
        "validation.batch": {"queue": "validation"},
        "validation.recover": {"queue": "maintenance"},
    },
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
# PostgreSQL remains authoritative; Beat republishes lost dispatches.
