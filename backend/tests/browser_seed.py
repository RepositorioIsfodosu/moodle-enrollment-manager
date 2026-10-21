"""Fixtures ONLY for an explicitly selected disposable browser-test database."""

import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cli import bootstrap_admin
from app.core.security import hash_password
from app.core.token_vault import encrypt_token
from app.db.session import get_engine
from app.models import (
    ConnectionGrant,
    CsvContent,
    CsvFile,
    CsvImport,
    CsvOperation,
    MoodleConnection,
    Role,
    User,
    UserRole,
    ValidationRecord,
    ValidationRun,
)
from app.schemas.auth import UserCreate
from app.schemas.csv import Mapping
from app.services.csv_parser import digest

PASSWORD = "browser-test-password-long"


def main():
    engine = get_engine()
    if os.getenv("RUN_BROWSER_TESTS") != "1" or not engine.url.database.endswith("_test"):
        raise RuntimeError("Requires RUN_BROWSER_TESTS=1 and disposable database ending in _test")
    suffix = uuid4().hex[:8]
    admin_email, operator_email = (
        f"ui-admin-{suffix}@example.com",
        f"ui-reader-{suffix}@example.com",
    )
    with Session(engine) as db:
        # A new disposable database is required; never add a hidden administrative account to a live DB.
        owner = bootstrap_admin(
            db, UserCreate(email=admin_email, password=PASSWORD, roles=["administrador"])
        )
        reader = User(email=operator_email, password_hash=hash_password(PASSWORD), active=True)
        db.add(reader)
        db.flush()
        role = db.scalar(select(Role).where(Role.name == "consulta"))
        db.add(UserRole(user_id=reader.id, role_id=role.id))
        connection = MoodleConnection(
            name="Moodle de ensayo UI",
            base_url="https://moodle.invalid",
            token_ciphertext=encrypt_token("test-only-never-a-real-moodle-token"),
            limits={},
        )
        db.add(connection)
        db.flush()
        db.add(ConnectionGrant(connection_id=connection.id, user_id=reader.id))
        content = b"username,course1,role1\nalice,BIO,5\n"
        file = CsvFile(
            uploaded_by=owner,
            original_name="fixture-only.csv",
            storage_key=str(uuid4()),
            sha256=sha256(content).hexdigest(),
            row_count=1,
            byte_count=len(content),
            encoding="utf-8-sig",
            delimiter=",",
            headers=["username", "course1", "role1"],
            preview=[{"username": "alice", "course1": "BIO", "role1": "5"}],
        )
        db.add(file)
        db.flush()
        db.add(CsvContent(file_id=file.id, content=content))
        entry = CsvImport(
            file_id=file.id,
            owner_id=owner,
            mapping_snapshot=Mapping().model_dump(),
            operation_count=1,
        )
        db.add(entry)
        db.flush()
        payload = {
            "user_field": "username",
            "user_identifier": "alice",
            "course_field": "shortname",
            "course_identifier": "BIO",
            "role_id": 5,
            "group_field": "name",
            "group_identifier": "",
            "metadata": {},
        }
        op = CsvOperation(
            import_id=entry.id,
            source_row=2,
            slot=1,
            operation_key=digest(payload),
            payload=payload,
            local_status="pending",
        )
        db.add(op)
        db.flush()
        run = ValidationRun(
            owner_id=owner,
            connection_id=connection.id,
            configuration_version=1,
            import_ids=[str(entry.id)],
            state="completed",
            finished_at=datetime.now(UTC),
        )
        db.add(run)
        db.flush()
        db.add(
            ValidationRecord(
                run_id=run.id,
                operation_id=op.id,
                sequence=0,
                status="valid",
                checked_at=datetime.now(UTC),
                resolved_user_id=10,
                resolved_course_id=101,
                resolved_key=digest([10, 101, 5, None]),
            )
        )
        db.commit()
        result = {
            "email": admin_email,
            "reader": operator_email,
            "password": PASSWORD,
            "connection_id": str(connection.id),
            "validation_id": str(run.id),
        }
    destination = Path(os.environ["E2E_SEED_PATH"])
    destination.write_text(json.dumps(result))
    destination.chmod(0o600)


if __name__ == "__main__":
    main()
