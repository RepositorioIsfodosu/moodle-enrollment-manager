import math
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.token_vault import VaultError, decrypt_token
from app.integrations.moodle.client import EVALUATED_FUNCTIONS, MoodleClient, MoodleError
from app.integrations.moodle.urls import UnsafeURL
from app.models import MoodleConnection, MoodleConnectionCheck
from app.schemas.moodle import ConnectionView, Limits
from app.services.audit import audit
from app.services.moodle_gate import GateError, network_slot


def view(connection: MoodleConnection) -> ConnectionView:
    return ConnectionView(
        id=connection.id,
        name=connection.name,
        base_url=connection.base_url,
        service_url=connection.base_url + "/webservice/rest/server.php",
        token_configured=bool(connection.token_ciphertext),
        active=connection.active,
        description=connection.description,
        limits=Limits.model_validate(connection.limits),
        status=connection.status,
        configuration_version=connection.configuration_version,
        created_at=connection.created_at,
        last_verified_at=connection.last_verified_at,
        last_error_code=connection.last_error_code,
        site_metadata=connection.site_metadata,
        available_functions=connection.available_functions,
        missing_evaluated_functions=sorted(
            set(EVALUATED_FUNCTIONS) - set(connection.available_functions)
        ),
        latency_ms=connection.latency_ms,
    )


def check_connection(db: Session, connection_id, actor_id, client: MoodleClient):
    connection = db.scalar(
        select(MoodleConnection)
        .where(MoodleConnection.id == connection_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not connection:
        raise HTTPException(404, "Conexión no encontrada")
    if not connection.active:
        raise HTTPException(409, "La conexión está desactivada")
    limits = Limits.model_validate(connection.limits)
    now = datetime.now(UTC)
    if connection.next_probe_at and connection.next_probe_at > now:
        raise HTTPException(
            429,
            "Comprobación en curso o límite de frecuencia alcanzado",
            headers={
                "Retry-After": str(
                    max(1, math.ceil((connection.next_probe_at - now).total_seconds()))
                )
            },
        )
    try:
        token = decrypt_token(connection.token_ciphertext)
    except VaultError:
        audit(
            db, "moodle.probe_blocked", actor_id, connection_id, error_code="encryption_unavailable"
        )
        db.commit()
        raise
    version, base_url = connection.configuration_version, connection.base_url
    interval = max(limits.min_probe_interval_seconds, math.ceil(60 / limits.requests_per_minute))
    connection.next_probe_at = now + timedelta(seconds=4 * limits.timeout_seconds + 6 + interval)
    audit(db, "moodle.probe_started", actor_id, connection_id, configuration_version=version)
    db.commit()  # No database lock is held during the network request.
    status, code, latency, functions, metadata = "error", None, None, [], {}

    def guard():
        db.expire_all()
        current = db.get(MoodleConnection, connection_id, populate_existing=True)
        if not current or not current.active or current.configuration_version != version:
            raise GateError("configuration_changed")
        db.commit()

    try:
        with network_slot(db, connection, limits, guard):
            site, latency = client.site_info(base_url, token, limits.timeout_seconds)
        functions = sorted({item.name for item in site.functions})
        status = "verified" if set(EVALUATED_FUNCTIONS) <= set(functions) else "limited"
        metadata = {"sitename": site.sitename, "release": site.release, "version": site.version}
    except GateError as error:
        code = str(error)
    except UnsafeURL:
        code = "unsafe_destination"
    except MoodleError as error:
        code = error.code
    connection = db.scalar(
        select(MoodleConnection)
        .where(MoodleConnection.id == connection_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if connection.configuration_version != version or not connection.active:
        audit(db, "moodle.probe_discarded", actor_id, connection_id, configuration_version=version)
        db.commit()
        raise HTTPException(
            409, "La configuración cambió durante la comprobación; resultado descartado"
        )
    connection.status, connection.last_error_code = status, code
    connection.last_verified_at = datetime.now(UTC)
    connection.next_probe_at = datetime.now(UTC) + timedelta(seconds=interval)
    connection.latency_ms, connection.available_functions = latency, functions
    connection.site_metadata = metadata
    db.add(
        MoodleConnectionCheck(
            connection_id=connection_id,
            actor_id=actor_id,
            status=status,
            error_code=code,
            latency_ms=latency,
            available_functions=functions,
        )
    )
    audit(db, "moodle.probe_finished", actor_id, connection_id, status=status, error_code=code)
    result = view(connection)
    db.commit()
    return result
