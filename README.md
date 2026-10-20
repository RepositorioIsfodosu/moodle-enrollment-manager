# Moodle Enrollment Manager

Aplicación para administrar matrículas masivas en Moodle. Estado: Fase 1 (fundamentos). No permite aún iniciar sesión, importar CSV ni matricular. No utilizar como sistema de producción.

## Inicio con Docker (Linux, macOS y Windows)

Requisitos: Git y Docker Engine con Compose v2; en Windows, Docker Desktop con WSL2 y contenedores Linux. Desde PowerShell en la raíz del repositorio:

```powershell
Copy-Item infrastructure/env.example infrastructure/.env
# Editar infrastructure/.env y sustituir POSTGRES_PASSWORD.
docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml up --build -d
docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml ps
Invoke-RestMethod http://localhost:8000/api/v1/health/ready
```

En Linux sustituir Copy-Item por `cp`. La API escucha únicamente en loopback. Swagger se encuentra en `/docs`; no hay interfaz React todavía. El proceso migrate debe terminar con código cero; api debe estar healthy. Para detener sin borrar datos usar `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml down`. Nunca usar `down -v` con datos que deban conservarse.

## Desarrollo y pruebas

Python 3.12 y uv. Desde backend: `uv sync --frozen`; configurar DATABASE_URL (postgresql+psycopg) y REDIS_URL; ejecutar `uv run alembic upgrade head`, `uv run pytest`, `uv run ruff check .`. Para pruebas con servicios reales establecer RUN_INTEGRATION=1. Las pruebas unitarias no requieren servicios; las de integración se omiten explícitamente sin esa variable.

Arquitectura, decisiones y limitaciones en [docs/architecture.md](docs/architecture.md). Despliegue en [docs/deployment.md](docs/deployment.md). La siguiente fase es autenticación y permisos; requiere instrucción expresa antes de iniciarse.
