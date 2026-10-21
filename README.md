# Moodle Enrollment Manager

Aplicación para administrar matrículas masivas en Moodle. Estado: Fase 3 (conexiones Moodle). Permite iniciar sesión, administrar usuarios y configurar/probar conexiones Moodle mediante API; todavía no permite importar CSV ni matricular. No utilizar como sistema de producción.

## Inicio con Docker (Linux, macOS y Windows)

Requisitos: Git y Docker Engine con Compose v2; en Windows, Docker Desktop con WSL2 y contenedores Linux. Desde PowerShell en la raíz del repositorio:

```powershell
Copy-Item infrastructure/env.example infrastructure/.env
# Editar infrastructure/.env y sustituir POSTGRES_PASSWORD.
# Generar la clave local de cifrado sin mostrarla (alternativa con Python instalado: py -3 scripts/init-secrets.py).
docker run --rm -v "${PWD}:/workspace/moodle-enrollment-manager" -w /workspace/moodle-enrollment-manager python:3.12-slim python scripts/init-secrets.py
docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml up --build -d
docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml ps
Invoke-RestMethod http://localhost:8000/api/v1/health/ready
```

En Linux sustituir Copy-Item por `cp` y generar la clave con `python3 scripts/init-secrets.py` antes de Compose. La API escucha únicamente en loopback. Swagger se encuentra en `/docs`; no hay interfaz React todavía. El proceso migrate debe terminar con código cero; api debe estar healthy. Para detener sin borrar datos usar `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml down`. Nunca usar `down -v` con datos que deban conservarse.

## Desarrollo y pruebas

Python 3.12 y uv. Desde backend: `uv sync --frozen`; configurar DATABASE_URL (postgresql+psycopg) y REDIS_URL; ejecutar `uv run alembic upgrade head`, `uv run pytest`, `uv run ruff check .`. Para pruebas con servicios reales establecer RUN_INTEGRATION=1. Las pruebas unitarias no requieren servicios; las de integración se omiten explícitamente sin esa variable.

Arquitectura, decisiones y limitaciones en [docs/architecture.md](docs/architecture.md). Despliegue en [docs/deployment.md](docs/deployment.md). La siguiente fase es importación y validación CSV; requiere instrucción expresa antes de iniciarse.

## Primer administrador y autenticación

Después de migrar, desde PowerShell o terminal interactiva:

```powershell
docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml exec api python -m app.cli create-admin
```

El comando solicita correo y contraseña sin mostrarla. No existe una cuenta predeterminada; no introduzcas contraseñas como argumentos ni las guardes en Git. Sólo permite crear el administrador inicial si aún no existe uno activo. Sigue [autenticación y API](docs/authentication.md) para iniciar sesión y administrar usuarios. La interfaz visual se implementará en fase 6.

Informe: [Fase 2](docs/phase-2.md). Pruebas de integración sólo sobre una base dedicada cuyo nombre termine en `_test` y Redis de pruebas; no usar el broker de la aplicación.

## Conexiones Moodle

El administrador puede crear conexiones en `/api/v1/moodle-connections` y probarlas mediante POST `/{id}/test`. Se requiere URL HTTPS pública y token de un servicio con `core_webservice_get_site_info`. La prueba es sólo de lectura; no matricula. El token se cifra y nunca se devuelve; proteger la clave MOODLE_TOKEN_KEYS en .env y sus respaldos. Ver [configuración Moodle y contrato de API](docs/moodle-api.md) e [informe de Fase 3](docs/phase-3.md). No hay todavía formulario React para estas operaciones.
