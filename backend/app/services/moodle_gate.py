"""One paced request at a time per canonical installation, including probes and validation."""

import secrets
import time
from contextlib import contextmanager
from datetime import UTC, datetime

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select

from app.core.config import get_settings
from app.models import MoodleConnection, SystemSetting
from app.schemas.moodle import Limits
from app.services.csv_parser import digest

LEASE_SECONDS = 600


class GateError(Exception):
    pass


@contextmanager
def network_slot(db, connection, limits, guard, pace=True):
    if not pace:
        yield
        return
    circuit = db.get(SystemSetting, "moodle:circuit:" + digest(connection.base_url))
    if circuit and datetime.fromisoformat(circuit.value["until"]) > datetime.now(UTC):
        raise GateError("installation_circuit_open")
    # Multiple named connections to the same URL share the most conservative configured rate.
    rates = [
        Limits.model_validate(c.limits).requests_per_minute
        for c in db.scalars(
            select(MoodleConnection).where(
                MoodleConnection.base_url == connection.base_url,
                MoodleConnection.active.is_(True),
            )
        )
    ]
    rate = min(rates or [limits.requests_per_minute])
    interval = max(1, (60000 + rate - 1) // rate)
    prefix = "moodle:validation:" + digest(connection.base_url)
    lock_key, slot_key, owner = prefix + ":lock", prefix + ":slot", secrets.token_hex(16)
    try:
        with Redis.from_url(
            get_settings().redis_url.get_secret_value(),
            socket_timeout=2,
            socket_connect_timeout=2,
        ) as redis:
            while not redis.set(lock_key, owner, nx=True, px=LEASE_SECONDS * 1000):
                guard()
                time.sleep(0.5)
            try:
                while not redis.set(slot_key, "slot", nx=True, px=interval):
                    guard()
                    time.sleep(0.5)
                guard()
                circuit = db.get(
                    SystemSetting,
                    "moodle:circuit:" + digest(connection.base_url),
                    populate_existing=True,
                )
                if circuit and datetime.fromisoformat(circuit.value["until"]) > datetime.now(UTC):
                    raise GateError("installation_circuit_open")
                yield
            finally:
                redis.eval(
                    "if redis.call('GET',KEYS[1]) == ARGV[1] then return redis.call('DEL',KEYS[1]) else return 0 end",
                    1,
                    lock_key,
                    owner,
                )
    except RedisError:
        raise GateError("rate_limiter_unavailable") from None
