"""Opt-in local load, no real Moodle transport and no rate/capacity claim."""

import json
import math
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import median
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import EnrollmentJob
from app.services.enrollment_engine import run_batch
from app.services.validation_engine import run_batch as validate
from tests.integration.test_enrollment_engine import due
from tests.integration.test_imports import FakeMoodle, approve, imported, validation
from tests.integration.test_imports import environment as environment  # noqa: PLC0414

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1" or os.getenv("RUN_LOAD_TESTS") != "1",
    reason="Opt-in simulated load with dedicated services only",
)


class LoadMoodle(FakeMoodle):
    def __init__(self):
        super().__init__()
        self.enrolled = {}
        self.writes = []

    def read_call(self, base, token, timeout, function, params):
        if function == "core_enrol_get_enrolled_users":
            self.calls.append((function, params))
            options = {
                params[k]: params[k.replace("[name]", "[value]")]
                for k in params
                if k.endswith("[name]")
            }
            start = int(options["limitfrom"])
            return sorted(self.enrolled.values(), key=lambda r: r["id"])[
                start : start + int(options["limitnumber"])
            ], 1
        return super().read_call(base, token, timeout, function, params)

    def write_call(self, base, token, timeout, function, params):
        assert token == "csv-simulator-token" and function == "enrol_manual_enrol_users"
        uid = int(params["enrolments[0][userid]"])
        assert uid not in self.enrolled, "Duplicate write in simulated Moodle"
        self.writes.append(uid)
        self.enrolled[uid] = {"id": uid, "roles": [{"roleid": 5}], "groups": []}
        return None, 1


def test_controlled_simulated_load(environment, monkeypatch):
    def deny_real_client(*args, **kwargs):
        raise AssertionError("Real Moodle transport forbidden in load tests")

    monkeypatch.setattr("app.services.validation_engine.MoodleClient", deny_real_client)
    monkeypatch.setattr(get_settings(), "enrollment_writes_enabled", True)  # Test process only.
    monkeypatch.setattr("app.api.v1.endpoints.jobs.dispatch", lambda _: None)
    rows = int(os.getenv("LOAD_ROWS", "1000"))
    assert 100 <= rows <= 2000, "Bounded local test only (100–2000 operations)"
    c, h, connection, engine, _ = environment
    started = time.perf_counter()
    body = b"username,course1,role1\n" + b"".join(f"u{i},BIO,5\n".encode() for i in range(rows))
    _, entry = imported(c, h, body=body)
    approve(c, h, connection)
    run = validation(c, h, connection, [entry])
    fake = LoadMoodle()
    while validate(UUID(run), client=fake, pace=False, engine=engine):
        pass
    validation_seconds = time.perf_counter() - started
    created = c.post(
        "/api/v1/enrollment-jobs",
        headers=h,
        json={
            "name": "Controlled simulated load",
            "validation_id": run,
            "configuration": {"batch_size": 25, "pause_seconds": 1},
        },
    )
    assert created.status_code == 201, created.text
    job = created.json()["id"]
    assert c.post(f"/api/v1/enrollment-jobs/{job}/start", headers=h).status_code == 202
    batches = []
    begun = time.perf_counter()
    for _ in range(math.ceil(rows / 25)):
        due(engine, job)
        tick = time.perf_counter()
        run_batch(job, client=fake, pace=False, engine=engine)
        batches.append(time.perf_counter() - tick)
    processing_seconds = time.perf_counter() - begun
    result = c.get(f"/api/v1/enrollment-jobs/{job}", headers=h).json()
    assert result["state"] == "completed" and result["counts"] == {"confirmed": rows}
    assert len(set(fake.writes)) == len(fake.writes) == rows
    # Duplicate deliveries cannot send another simulated write.
    assert run_batch(job, client=fake, pace=False, engine=engine) is False
    assert len(fake.writes) == rows

    def read_once(i):
        tick = time.perf_counter()
        path = "/api/v1/dashboard" if i % 2 else "/api/v1/reports?limit=10"
        response = c.get(path, headers=h)
        assert response.status_code == 200, response.text
        return time.perf_counter() - tick

    with ThreadPoolExecutor(max_workers=4) as pool:
        latencies = list(pool.map(read_once, range(40)))
    export_seconds = {}
    for format in ["csv", "xlsx", "pdf"]:
        tick = time.perf_counter()
        exported = c.get(
            "/api/v1/reports/export", headers=h, params={"job_id": job, "format": format}
        )
        assert exported.status_code == 200, exported.text
        assert len(exported.content) > 100
        export_seconds[format] = round(time.perf_counter() - tick, 4)
    with Session(engine) as db:
        assert db.get(EnrollmentJob, UUID(job)).state == "completed"
    metrics = {
        "mode": "local_simulator_pace_false_no_network",
        "operations": rows,
        "validation_seconds": round(validation_seconds, 4),
        "processing_seconds": round(processing_seconds, 4),
        "batches": len(batches),
        "batch_median_seconds": round(median(batches), 4),
        "batch_max_seconds": round(max(batches), 4),
        "simulated_writes": len(fake.writes),
        "simulated_read_calls": len(fake.calls),
        "api_requests": len(latencies),
        "api_concurrency": 4,
        "api_median_seconds": round(median(latencies), 4),
        "api_p95_seconds": round(sorted(latencies)[math.ceil(len(latencies) * 0.95) - 1], 4),
        "export_seconds": export_seconds,
        "warning": "Not Moodle capacity, network latency or production throughput; pacing disabled only in test.",
    }
    destination = Path(
        os.getenv("LOAD_RESULT_PATH", str(Path(tempfile.gettempdir()) / "mem-controlled-load.json"))
    )
    destination.write_text(json.dumps(metrics, indent=2) + "\n")
