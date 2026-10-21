"""Read-only validation with PostgreSQL checkpoints and connection-wide Redis pacing."""

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.token_vault import VaultError, decrypt_token
from app.db.session import get_engine
from app.integrations.moodle.client import MoodleClient, MoodleError
from app.integrations.moodle.read_models import (
    CourseInfo,
    GroupInfo,
    MemberInfo,
    UserInfo,
    filtered_list,
)
from app.integrations.moodle.urls import UnsafeURL
from app.models import (
    CsvOperation,
    MoodleConnection,
    RoleApproval,
    ValidationCache,
    ValidationRecord,
    ValidationRun,
)
from app.schemas.moodle import Limits
from app.services.audit import audit
from app.services.csv_parser import digest
from app.services.import_access import connection_access
from app.services.moodle_gate import GateError as ValidationFailure
from app.services.moodle_gate import network_slot

LEASE_SECONDS = 600


class Stopped(Exception):
    pass


class Engine:
    def __init__(self, db: Session, run: ValidationRun, owner: str, client=None, pace=True):
        self.db, self.run, self.owner = db, run, owner
        self.run_id = run.id
        self.client = client or MoodleClient()
        self.pace = pace
        self.connection = db.get(MoodleConnection, run.connection_id)
        self.limits = Limits.model_validate(self.connection.limits)
        self.token = decrypt_token(self.connection.token_ciphertext)

    def guard(self, commit=True):
        self.db.expire_all()
        run = self.db.scalar(
            select(ValidationRun)
            .where(ValidationRun.id == self.run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if run.state != "running" or run.lease_owner != self.owner:
            self.db.rollback()
            raise Stopped
        try:
            connection = connection_access(self.db, run.owner_id, run.connection_id)
        except HTTPException:
            raise ValidationFailure("access_revoked") from None
        if connection.configuration_version != run.configuration_version:
            raise ValidationFailure("configuration_changed")
        run.lease_until = datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)
        if commit:
            self.db.commit()

    def cached(self, key):
        row = self.db.get(ValidationCache, (self.run.id, digest(key)))
        return row.value if row else None

    def save(self, key, value):
        def contains_secret(item):
            if isinstance(item, str):
                return self.token in item
            if isinstance(item, dict):
                return any(contains_secret(k) or contains_secret(v) for k, v in item.items())
            if isinstance(item, list):
                return any(contains_secret(x) for x in item)
            return False

        if contains_secret(value):
            raise ValidationFailure("sensitive_response")
        self.guard(commit=False)
        row = self.db.get(ValidationCache, (self.run.id, digest(key)))
        if row:
            row.value = value
        else:
            self.db.add(ValidationCache(run_id=self.run.id, key=digest(key), value=value))
        self.db.commit()
        return value

    def request(self, function, params):
        self.guard()
        with self.network_slot():
            payload, _ = self.client.read_call(
                self.connection.base_url, self.token, self.limits.timeout_seconds, function, params
            )
        return payload

    def network_slot(self):
        return network_slot(self.db, self.connection, self.limits, self.guard, self.pace)

    def functions(self):
        cached = self.cached(["functions"])
        if cached is None:
            self.guard()
            with self.network_slot():
                site, _ = self.client.site_info(
                    self.connection.base_url, self.token, self.limits.timeout_seconds
                )
            cached = self.save(["functions"], {"names": [item.name for item in site.functions]})
        return set(cached["names"])

    def require(self, function):
        if function not in self.functions():
            raise MoodleError("function_unavailable")

    def users(self, operations):
        function = "core_user_get_users_by_field"
        self.require(function)
        for field in ("username", "email", "idnumber"):
            identifiers = sorted(
                {
                    op.payload["user_identifier"]
                    for op in operations
                    if op.payload["user_field"] == field
                    and self.cached(["user", field, op.payload["user_identifier"]]) is None
                }
            )
            for start in range(0, len(identifiers), 50):
                values = identifiers[start : start + 50]
                params = {
                    "field": field,
                    **{f"values[{i}]": value for i, value in enumerate(values)},
                }
                data = filtered_list(self.request(function, params), UserInfo, maximum=200)
                for value in values:
                    matches = [
                        row
                        for row in data
                        if row.get(field) is not None
                        and (str(row[field]).casefold() if field != "idnumber" else row[field])
                        == value
                    ]
                    self.save(
                        ["user", field, value],
                        {
                            "items": [
                                {"id": row["id"], "suspended": row["suspended"]} for row in matches
                            ]
                        },
                    )

    def courses(self, operations):
        ids = sorted(
            {
                op.payload["course_identifier"]
                for op in operations
                if op.payload["course_field"] == "id"
                and self.cached(["course", "id", op.payload["course_identifier"]]) is None
            }
        )
        if ids:
            self.require("core_course_get_courses_by_field")
            payload = self.request(
                "core_course_get_courses_by_field", {"field": "ids", "value": ",".join(ids)}
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("warnings"), list):
                raise MoodleError("invalid_response")
            rows = filtered_list(payload.get("courses"), CourseInfo, maximum=200)
            for value in ids:
                self.save(
                    ["course", "id", value],
                    {
                        "items": [x for x in rows if str(x["id"]) == value],
                        "warning": bool(payload["warnings"]),
                    },
                )
        for op in operations:
            field, value = op.payload["course_field"], op.payload["course_identifier"]
            if field == "id" or self.cached(["course", field, value]) is not None:
                continue
            self.require("core_course_get_courses_by_field")
            payload = self.request(
                "core_course_get_courses_by_field", {"field": field, "value": value}
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("warnings"), list):
                raise MoodleError("invalid_response")
            rows = filtered_list(payload.get("courses"), CourseInfo, maximum=100)
            self.save(
                ["course", field, value],
                {
                    "items": [x for x in rows if x.get(field) == value],
                    "warning": bool(payload["warnings"]),
                },
            )

    def groups(self, course_id):
        cached = self.cached(["groups", course_id])
        if cached is None:
            self.require("core_group_get_course_groups")
            rows = filtered_list(
                self.request("core_group_get_course_groups", {"courseid": str(course_id)}),
                GroupInfo,
                maximum=2000,
            )
            cached = self.save(["groups", course_id], {"items": rows})
        return cached["items"]

    def members(self, course_id, targets):
        key = ["members", course_id]
        cached = self.cached(key) or {"items": {}, "offset": 0, "complete": False}
        self.require("core_enrol_get_enrolled_users")
        while not cached["complete"] and not all(str(uid) in cached["items"] for uid in targets):
            if cached["offset"] >= get_settings().validation_max_pages * 100:
                break
            options = {
                "limitfrom": str(cached["offset"]),
                "limitnumber": "100",
                "sortby": "id",
                "sortdirection": "ASC",
                "onlyactive": "1",
            }
            params = {"courseid": str(course_id)}
            for i, (name, value) in enumerate(options.items()):
                params[f"options[{i}][name]"], params[f"options[{i}][value]"] = name, value
            rows = filtered_list(self.request("core_enrol_get_enrolled_users", params), MemberInfo)
            if any(str(row["id"]) in cached["items"] for row in rows):
                raise ValidationFailure("enrollment_scan_inconsistent")
            cached = {
                "items": cached["items"] | {str(x["id"]): x for x in rows},
                "offset": cached["offset"] + len(rows),
                "complete": len(rows) < 100,
            }
            self.save(key, cached)
        return cached

    def resolve(self, record, op):
        p = op.payload
        resolution = {}

        def result(status, code):
            return status, code, resolution

        users = self.cached(["user", p["user_field"], p["user_identifier"]])["items"]
        courses = self.cached(["course", p["course_field"], p["course_identifier"]])
        if len(users) != 1:
            return result("invalid", "ambiguous_user" if users else "user_not_found_or_not_visible")
        if courses.get("warning"):
            return result("pending", "course_lookup_warning")
        if len(courses["items"]) != 1:
            return result(
                "invalid",
                "ambiguous_course" if courses["items"] else "course_not_found_or_not_visible",
            )
        user, course = users[0], courses["items"][0]
        resolution.update(resolved_user_id=user["id"], resolved_course_id=course["id"])
        if user.get("suspended") is True:
            return result("invalid", "suspended_user")
        group_id = None
        if p["group_identifier"]:
            groups = [
                x
                for x in self.groups(course["id"])
                if str(x.get(p["group_field"], "")) == p["group_identifier"]
            ]
            if len(groups) != 1:
                return result("invalid", "ambiguous_group" if groups else "group_not_found")
            group_id = groups[0]["id"]
            resolution["resolved_group_id"] = group_id
        key = digest([user["id"], course["id"], p["role_id"], group_id])
        other = self.db.scalar(
            select(ValidationRecord.id).where(
                ValidationRecord.run_id == self.run.id,
                ValidationRecord.resolved_key == key,
                ValidationRecord.id != record.id,
            )
        )
        if other:
            return result("duplicate", "resolved_duplicate")
        resolution["resolved_key"] = key
        members = self.members(course["id"], [user["id"]])
        member = members["items"].get(str(user["id"]))
        if member:
            if member["roles"] is None or (group_id and member["groups"] is None):
                return result("pending", "enrollment_details_unavailable")
            if any(x["roleid"] == p["role_id"] for x in member["roles"]) and (
                not group_id or any(x["id"] == group_id for x in member["groups"] or [])
            ):
                return result("existing", None)
        elif not members["complete"]:
            return result("pending", "enrollment_scan_limit")
        if user.get("suspended") is None:
            return result("pending", "suspension_not_disclosed")
        if "enrol_manual_enrol_users" not in self.functions():
            return result("pending", "enrollment_function_unavailable")
        if group_id and "core_group_add_group_members" not in self.functions():
            return result("pending", "group_function_unavailable")
        approval = self.db.scalar(
            select(RoleApproval)
            .where(
                RoleApproval.connection_id == self.run.connection_id,
                RoleApproval.configuration_version == self.run.configuration_version,
                RoleApproval.course_id == course["id"],
                RoleApproval.role_id == p["role_id"],
                RoleApproval.active.is_(True),
                RoleApproval.expires_at > datetime.now(UTC),
            )
            .order_by(RoleApproval.created_at.desc())
            .limit(1)
        )
        if not approval:
            return result("pending", "role_assignability_unverified")
        if not approval.full_enrollment_visibility:
            return result("pending", "enrollment_visibility_unverified")
        if group_id and not approval.groups_authorized:
            return result("pending", "group_permission_unverified")
        resolution["approval_id"] = approval.id
        return result("valid", None)


def run_batch(run_id, client=None, pace=True, engine=None):
    owner = secrets.token_hex(16)
    with Session(engine or get_engine()) as db:
        run = db.scalar(select(ValidationRun).where(ValidationRun.id == run_id).with_for_update())
        now = datetime.now(UTC)
        if (
            not run
            or run.state not in ("queued", "running")
            or (run.lease_until and run.lease_until > now)
        ):
            return False
        if run.state == "running":
            run.recovery_count += 1
            if run.recovery_count > 3:
                run.state, run.error_code, run.finished_at = "failed", "recovery_limit", now
                audit(db, "validation.failed", run.owner_id, run.id, error_code="recovery_limit")
                db.commit()
                return False
        run.state, run.lease_owner = "running", owner
        run.lease_until = now + timedelta(seconds=LEASE_SECONDS)
        db.commit()
        try:
            worker = Engine(db, run, owner, client, pace)
            rows = list(
                db.scalars(
                    select(ValidationRecord)
                    .where(ValidationRecord.run_id == run.id, ValidationRecord.checked_at.is_(None))
                    .order_by(ValidationRecord.sequence)
                    .limit(50)
                )
            )
            operations = [db.get(CsvOperation, row.operation_id) for row in rows]
            if operations:
                worker.users(operations)
                worker.courses(operations)
            for row, op in zip(rows, operations, strict=True):
                worker.guard()
                try:
                    status, code, resolution = worker.resolve(row, op)
                except MoodleError as error:
                    status, code, resolution = "pending", error.code, {}
                # guard() expires objects: never write a result after losing lease/cancellation.
                worker.guard(commit=False)
                for field, value in resolution.items():
                    setattr(row, field, value)
                row.status, row.error_code, row.checked_at = status, code, datetime.now(UTC)
                db.commit()
            worker.guard(commit=False)
            remaining = db.scalar(
                select(func.count())
                .select_from(ValidationRecord)
                .where(ValidationRecord.run_id == run.id, ValidationRecord.checked_at.is_(None))
            )
            run.state = "queued" if remaining else "completed"
            run.lease_owner = run.lease_until = None
            if not remaining:
                run.finished_at = datetime.now(UTC)
                audit(db, "validation.completed", run.owner_id, run.id)
            db.commit()
            return bool(remaining)
        except Stopped:
            db.rollback()
            return False
        except (MoodleError, ValidationFailure, VaultError, UnsafeURL) as error:
            db.rollback()
            run = db.scalar(
                select(ValidationRun).where(ValidationRun.id == run_id).with_for_update()
            )
            if run.lease_owner == owner and run.state == "running":
                run.state = "failed"
                run.error_code = (
                    error.code
                    if isinstance(error, MoodleError)
                    else (
                        str(error)
                        if isinstance(error, ValidationFailure)
                        else "configuration_or_destination_unavailable"
                    )
                )
                run.lease_owner = run.lease_until = None
                run.finished_at = datetime.now(UTC)
                audit(db, "validation.failed", run.owner_id, run.id, error_code=run.error_code)
                db.commit()
            return False

        except Exception:  # noqa: BLE001 - persist unexpected failure under the current lease only.
            db.rollback()
            run = db.scalar(
                select(ValidationRun).where(ValidationRun.id == run_id).with_for_update()
            )
            if run and run.state == "running" and run.lease_owner == owner:
                run.state, run.error_code, run.finished_at = (
                    "failed",
                    "internal_error",
                    datetime.now(UTC),
                )
                run.lease_owner = run.lease_until = None
                audit(db, "validation.failed", run.owner_id, run.id, error_code="internal_error")
                db.commit()
            raise RuntimeError("validation_worker_failed") from None
