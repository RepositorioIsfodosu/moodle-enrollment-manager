"""Local administration; passwords are read with getpass, never command arguments."""

import argparse
import os
from getpass import getpass

from pydantic import ValidationError
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.endpoints.users import assign_roles
from app.core.security import hash_password
from app.core.token_vault import VaultError, rotate_token
from app.db.session import get_engine
from app.models import MoodleConnection, Role, User, UserRole
from app.schemas.auth import UserCreate
from app.services.audit import audit
from app.services.auth import administration_lock, purge_expired_sessions


def bootstrap_admin(db: Session, data: UserCreate):
    administration_lock(db)
    if db.scalar(
        select(User.id)
        .join(UserRole)
        .join(Role)
        .where(User.active.is_(True), Role.name == "administrador")
    ):
        raise ValueError("Ya existe un administrador activo; utilizar la API autenticada")
    if db.scalar(select(User.id).where(User.email == str(data.email))):
        raise ValueError("El correo ya está registrado")
    user = User(
        email=str(data.email), password_hash=hash_password(data.password.get_secret_value())
    )
    db.add(user)
    db.flush()
    assign_roles(db, user, ["administrador"])
    audit(db, "users.bootstrap", user.id, user.id)
    db.commit()
    return user.id


def main():
    parser = argparse.ArgumentParser(description="Administración local segura")
    parser.add_argument(
        "command",
        choices=[
            "create-admin",
            "purge-sessions",
            "rotate-moodle-tokens",
            "purge-transient-data",
            "create-runtime-role",
            "grant-runtime-role",
        ],
    )
    parser.add_argument(
        "--days", type=int, default=30, help="Retención de caché terminal (7–3650 días)"
    )
    parser.add_argument(
        "--execute", action="store_true", help="Aplicar purga; por defecto sólo simula"
    )
    parser.add_argument("--role", default="mem_runtime", help="Rol PostgreSQL de runtime")
    parser.add_argument(
        "--check-runtime-url",
        action="store_true",
        help="Validar conexión separada de runtime antes de arrancar",
    )
    args = parser.parse_args()
    with Session(get_engine()) as db:
        if args.command in {"create-runtime-role", "grant-runtime-role"}:
            from app.services.database_roles import (
                DatabaseRoleError,
                configure_runtime_role,
                validate_runtime_target,
            )

            password = None
            if args.command == "create-runtime-role":
                password = getpass("Contraseña del nuevo rol PostgreSQL (20–128 caracteres): ")
                if password != getpass("Repetir contraseña: "):
                    raise SystemExit("Las contraseñas no coinciden")
            try:
                runtime = None
                if args.check_runtime_url:
                    runtime = validate_runtime_target(
                        get_engine().url, os.getenv("RUNTIME_DATABASE_URL", ""), args.role
                    )
                configure_runtime_role(db, args.role, password=password)
                if runtime:
                    engine = create_engine(
                        runtime, connect_args={"connect_timeout": 3}, hide_parameters=True
                    )
                    try:
                        with engine.connect() as connection:
                            identity = connection.execute(
                                text("SELECT current_user, current_schema()")
                            ).one()
                            if identity != (args.role, "public"):
                                raise DatabaseRoleError(
                                    "Identidad o esquema de runtime no coincide"
                                )
                    finally:
                        engine.dispose()
            except DatabaseRoleError as error:
                raise SystemExit(str(error)) from None
            except SQLAlchemyError:
                raise SystemExit(
                    "No se verificó la conexión de runtime; revisar sus credenciales sin mostrarlas"
                ) from None
            print("Permisos de runtime aplicados; no se muestran credenciales")
            return
        if args.command == "purge-transient-data":
            from app.services.maintenance import purge_transient

            try:
                result = purge_transient(db, days=args.days, execute=args.execute)
            except ValueError as error:
                raise SystemExit(str(error)) from None
            print(("Aplicado" if args.execute else "Simulación") + ": " + str(result))
            return
        if args.command == "rotate-moodle-tokens":
            count = 0
            try:
                for connection in db.scalars(
                    select(MoodleConnection).order_by(MoodleConnection.id).with_for_update()
                ):
                    connection.token_ciphertext = rotate_token(connection.token_ciphertext)
                    count += 1
                audit(db, "moodle.tokens_rotated", count=count)
                db.commit()
            except VaultError:
                db.rollback()
                raise SystemExit(
                    "Rotación cancelada; verificar claves. No se cambiaron tokens"
                ) from None
            print(f"Tokens recifrados: {count}")
            return
        if args.command == "purge-sessions":
            count = purge_expired_sessions(db)
            audit(db, "auth.sessions_purged", count=count)
            db.commit()
            print(f"Sesiones caducadas eliminadas: {count}")
            return
        email = input("Correo del primer administrador: ")
        password = getpass("Contraseña (12–128 caracteres): ")
        if password != getpass("Repetir contraseña: "):
            raise SystemExit("Las contraseñas no coinciden")
        try:
            data = UserCreate(email=email, password=password, roles=["administrador"])
            bootstrap_admin(db, data)
        except ValidationError:
            raise SystemExit("Correo o contraseña inválidos") from None
        except ValueError as error:
            raise SystemExit(str(error)) from None
        print("Administrador creado")


if __name__ == "__main__":
    main()
