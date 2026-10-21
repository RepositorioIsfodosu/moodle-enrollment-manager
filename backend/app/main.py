import json
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.endpoints import audit, auth, moodle, users
from app.core.config import get_settings
from app.core.token_vault import VaultError, vault
from app.db.session import get_engine


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({"level": record.levelname, "message": record.getMessage()})


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.basicConfig(handlers=[handler], level=logging.INFO)
app = FastAPI(title="Moodle Enrollment Manager", version="0.3.0")


@app.get("/api/v1/health/live")
def live():
    return {"status": "ok"}


@app.get("/api/v1/health/ready")
def ready():
    checks = {}
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
            checks["postgresql"] = revision == "0003"
    except SQLAlchemyError:
        checks["postgresql"] = False
    try:
        with Redis.from_url(
            get_settings().redis_url.get_secret_value(),
            socket_connect_timeout=2,
            socket_timeout=2,
        ) as client:
            checks["redis"] = bool(client.ping())
    except RedisError:
        checks["redis"] = False
    try:
        vault()
        checks["token_encryption"] = True
    except VaultError:
        checks["token_encryption"] = False
    healthy = all(checks.values())
    return JSONResponse(
        {"status": "ready" if healthy else "unavailable", "checks": checks},
        status_code=200 if healthy else 503,
    )


app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(moodle.router, prefix="/api/v1")


@app.exception_handler(RequestValidationError)
async def invalid_input(request: Request, error: RequestValidationError):
    # Pydantic's default errors can echo submitted passwords/tokens.
    return JSONResponse(
        {
            "detail": [
                {"loc": list(item["loc"]), "type": item["type"], "msg": "Valor no válido"}
                for item in error.errors()
            ]
        },
        status_code=422,
    )


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, error: SQLAlchemyError):
    logging.getLogger(__name__).error("database_operation_failed")
    return JSONResponse(
        {"detail": "Servicio de datos temporalmente no disponible"}, status_code=503
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.exception_handler(VaultError)
async def encryption_error(request: Request, error: VaultError):
    return JSONResponse(
        {"detail": "Cifrado no disponible; verificar configuración y claves"}, status_code=503
    )
