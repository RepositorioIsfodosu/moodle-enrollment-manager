"""Explicit PostgreSQL runtime privileges; execute only through a trusted migration identity."""

import re

import psycopg
from psycopg import sql
from sqlalchemy.exc import SQLAlchemyError

from app.models import Base
from app.services.audit import audit

READ = ("SELECT",)
APPEND = ("SELECT", "INSERT")
MUTATE = ("SELECT", "INSERT", "UPDATE")
GRANTS = {
    "users": MUTATE,
    "roles": READ,
    "user_roles": ("SELECT", "INSERT", "DELETE"),
    "moodle_connections": MUTATE,
    "csv_import_profiles": MUTATE,
    "csv_files": APPEND,
    "csv_contents": APPEND,
    "csv_imports": APPEND,
    "csv_operations": APPEND,
    "job_files": APPEND,
    "enrollment_jobs": MUTATE,
    "enrollment_records": MUTATE,
    "enrollment_attempts": MUTATE,
    "job_events": APPEND,
    "audit_logs": APPEND,
    "system_settings": MUTATE,
    "auth_sessions": ("SELECT", "INSERT", "DELETE"),
    "password_reset_tokens": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "moodle_connection_checks": APPEND,
    "connection_grants": ("SELECT", "INSERT", "DELETE"),
    "role_approvals": MUTATE,
    "validation_runs": MUTATE,
    "validation_records": MUTATE,
    "validation_cache": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "alembic_version": READ,
}


class DatabaseRoleError(ValueError):
    pass


def valid_identifier(name):
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", name):
        raise DatabaseRoleError(
            "Usar identificador PostgreSQL de 1–48 letras minúsculas, números o guiones bajos"
        )


def configure_runtime_role(db, role="mem_runtime", *, password=None, schema="public"):
    """Create (with password) or refresh a safe existing role. Commit all or roll back all."""
    valid_identifier(role)
    valid_identifier(schema)
    if password is not None and (
        not 20 <= len(password) <= 128 or any(ord(c) < 32 for c in password)
    ):
        raise DatabaseRoleError("La contraseña requiere 20–128 caracteres sin controles")
    if set(Base.metadata.tables) != set(GRANTS) - {"alembic_version"}:
        raise DatabaseRoleError(
            "Revisar permisos explícitos para los modelos actuales antes de continuar"
        )
    try:
        conn = db.connection().connection.driver_connection
        with conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(732194028)")
            cursor.execute(
                "SELECT oid,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolinherit,rolcanlogin FROM pg_roles WHERE rolname=%s",
                (role,),
            )
            info = cursor.fetchone()
            if password is not None:
                if info:
                    raise DatabaseRoleError(
                        "El rol ya existe; no se modificó su contraseña. Usar grant-runtime-role para permisos"
                    )
                # Send a SCRAM verifier, never the plaintext password, in PostgreSQL DDL.
                verifier = conn.pgconn.encrypt_password(
                    password.encode(), role.encode(), b"scram-sha-256"
                ).decode()
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD {}"
                    ).format(sql.Identifier(role), sql.Literal(verifier))
                )
                cursor.execute(
                    "SELECT oid,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolinherit,rolcanlogin FROM pg_roles WHERE rolname=%s",
                    (role,),
                )
                info = cursor.fetchone()
            if not info or any(info[1:7]) or not info[7]:
                raise DatabaseRoleError(
                    "El rol debe existir con LOGIN y sin atributos administrativos ni INHERIT"
                )
            oid = info[0]
            cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_auth_members WHERE member=%s)", (oid,))
            if cursor.fetchone()[0]:
                raise DatabaseRoleError("El rol no debe pertenecer a otros roles")
            cursor.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_database WHERE datdba=%s) OR EXISTS(SELECT 1 FROM pg_namespace WHERE nspowner=%s) OR EXISTS(SELECT 1 FROM pg_class WHERE relowner=%s)",
                (oid, oid, oid),
            )
            if cursor.fetchone()[0]:
                raise DatabaseRoleError(
                    "El rol no debe ser propietario de bases, esquemas ni objetos"
                )
            cursor.execute("SELECT has_schema_privilege(%s,%s,'CREATE')", (role, schema))
            if cursor.fetchone()[0]:
                raise DatabaseRoleError(
                    "Retirar CREATE heredado de PUBLIC o concesiones externas antes de continuar"
                )
            cursor.execute("SELECT current_database()")
            database = cursor.fetchone()[0]
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(database), sql.Identifier(role)
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(role)
                )
            )
            for table, privileges in GRANTS.items():
                target = sql.Identifier(schema, table)
                cursor.execute(
                    sql.SQL("REVOKE ALL PRIVILEGES ON TABLE {} FROM {}").format(
                        target, sql.Identifier(role)
                    )
                )
                cursor.execute(
                    sql.SQL("GRANT {} ON TABLE {} TO {}").format(
                        sql.SQL(",").join(map(sql.SQL, privileges)), target, sql.Identifier(role)
                    )
                )
                # PUBLIC grants must not silently bypass the restricted privilege matrix.
                for privilege in {
                    "INSERT",
                    "UPDATE",
                    "DELETE",
                    "TRUNCATE",
                    "REFERENCES",
                    "TRIGGER",
                } - set(privileges):
                    cursor.execute(
                        "SELECT has_table_privilege(%s,%s,%s)",
                        (role, f'"{schema}"."{table}"', privilege),
                    )
                    if cursor.fetchone()[0]:
                        raise DatabaseRoleError(
                            "Hay privilegios efectivos externos incompatibles; revisar PUBLIC y concesiones del rol"
                        )
        audit(
            db,
            "database.runtime_role_created"
            if password is not None
            else "database.runtime_grants_refreshed",
            role=role,
            schema=schema,
        )
        db.commit()
    except DatabaseRoleError:
        db.rollback()
        raise
    except (psycopg.Error, SQLAlchemyError):
        db.rollback()
        raise DatabaseRoleError(
            "No se confirmó la configuración. Verificar identidad migradora, esquema y estado del rol antes de reintentar"
        ) from None


def validate_runtime_target(owner_url, runtime_url, role):
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import ArgumentError

    valid_identifier(role)
    try:
        owner, runtime = make_url(str(owner_url)), make_url(str(runtime_url))
    except (ArgumentError, ValueError):
        raise DatabaseRoleError("URL de runtime no válida; no se muestran credenciales") from None
    allowed_options = {
        "sslmode",
        "sslrootcert",
        "sslcert",
        "sslkey",
        "sslpassword",
        "sslcrl",
        "sslcrldir",
        "sslsni",
        "ssl_min_protocol_version",
        "ssl_max_protocol_version",
        "channel_binding",
        "application_name",
        "connect_timeout",
    }
    for url in (owner, runtime):
        if any(
            key not in allowed_options or not isinstance(value, str)
            for key, value in url.query.items()
        ):
            raise DatabaseRoleError("La URL contiene opciones de conexión no admitidas o repetidas")
    if (
        runtime.drivername != "postgresql+psycopg"
        or not runtime.password
        or runtime.username != role
        or owner.username == role
        or ((owner.host or "").lower(), owner.port or 5432, owner.database)
        != ((runtime.host or "").lower(), runtime.port or 5432, runtime.database)
    ):
        raise DatabaseRoleError(
            "Runtime requiere otro usuario, la misma base/host/puerto y el rol configurado"
        )
    return runtime
