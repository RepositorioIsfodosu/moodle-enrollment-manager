# Entrega técnica — Fase 2

## Resultado

Autenticación y administración de usuarios funcionales por API, con persistencia PostgreSQL y limitación compartida Redis. No hay interfaz gráfica todavía. Esta fase no realiza llamadas a Moodle ni matrículas.

## Archivos nuevos

- backend/app/core/security.py y permissions.py: Argon2id, hashes de tokens y matriz de permisos.
- backend/app/api/dependencies.py: sesión y autorización en servidor.
- backend/app/api/v1/endpoints/auth.py, users.py y audit.py: endpoints de sesión, usuarios, roles y auditoría.
- backend/app/schemas/auth.py: validación de solicitudes y respuestas sin contraseñas.
- backend/app/services/auth.py y audit.py: limitador atómico Redis, coordinación y eventos.
- backend/app/cli.py: primer administrador interactivo y purga de sesiones caducadas.
- backend/alembic/versions/0002_auth_sessions.py: sesiones, correo normalizado y roles iniciales.
- backend/tests/unit/test_security.py y tests/integration/test_auth.py: regresiones de seguridad y concurrencia.
- docs/authentication.md y este informe.

## Archivos actualizados

Modelos y configuración del backend, main.py, pyproject.toml, uv.lock y pruebas de salud; Dockerfile y Compose; env.example; CI; README y documentos de arquitectura, base de datos, despliegue, seguridad y manual. La migración 0001 permanece intacta. Argon2 y email-validator se justifican en architecture.md.

## Funcionalidades

Login con respuesta genérica para credenciales erróneas, token Bearer aleatorio, sesión revocable y caducidad absoluta. El token se guarda sólo como hash. Logout, logout-all y cambio de contraseña. Crear, listar, consultar, desactivar/reactivar, cambiar roles y restablecer contraseñas mediante administrador. Roles fijos administrador, operador, supervisor y consulta; permisos comprobados en servidor. Auditoría paginada con filtros para administrador/supervisor.

Cambio de roles, desactivación o contraseña revoca sesiones. El último administrador activo no puede desactivarse ni perder su rol; las pruebas concurrentes verifican esa garantía a través de la API. El primer administrador sólo se crea desde CLI si no existe otro activo. Ninguna cuenta productiva ni contraseña por defecto fue creada durante la entrega.

## Verificaciones ejecutadas

- **37 pruebas aprobadas:** 16 unitarias y 21 de integración, sin omisiones con RUN_INTEGRATION=1, PostgreSQL 16 y Redis 7 dedicados. Incluyen hash seguro, validaciones, permisos de los cuatro roles, login/logout, expiración, revocación, cambio/reset de contraseña, auditoría, paginación, errores sin secretos, fallo de Redis, rate limiting, cabeceras X-Forwarded-For, creación duplicada concurrente y protección concurrente del último administrador.
- Ruff check y format check correctos; instalación uv sync --frozen correcta.
- Migración 0002 aplicada, downgrade a 0001 en base de ensayo, reaplicación y segundo upgrade sin cambios. Alembic check no detecta diferencias.
- Construcción Docker correcta con verificación TLS y lockfile; Compose arranca db, redis, migración, API y worker. Health ready devuelve PostgreSQL/Redis verdaderos y worker responde pong.
- CLI create-admin ejecutado en terminal interactiva contra base dedicada de pruebas. Cuenta temporal retirada al terminar.
- Prueba HTTP adicional con Uvicorn real: login correcto, acceso administrativo, sesión válida después de detener el proceso y arrancar otro con PID distinto, logout y posterior 401. No forma parte del conteo de Pytest.

Se mantiene una advertencia de deprecación del transporte HTTPX de TestClient/Starlette heredada de fase 1; no provoca fallos. La CI está actualizada para base de pruebas dedicada, pero su resultado en GitHub requiere comprobarse después de subir el commit. Windows se documenta, no se ha probado en una máquina Windows.

## Cómo ejecutar

Desde la raíz: `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml up --build -d --wait --wait-timeout 120`. En Codex Cloud compilar antes con `DOCKER_CONFIG=/workspace/.docker-build python3 scripts/cloud-install.py` y usar `--no-build` en lugar de `--build`.

Primer administrador: `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml exec api python -m app.cli create-admin`. Solicita correo y contraseña sin mostrarla. Login y resto de endpoints en authentication.md y Swagger `/docs`.

Pruebas desde backend: `uv run pytest tests/unit -q`. Integración: configurar DATABASE_URL con base dedicada terminada en _test, REDIS_URL de pruebas, RUN_INTEGRATION=1, aplicar `uv run alembic upgrade head` y ejecutar `uv run pytest -q`. Las pruebas limpian claves auth:login del Redis de pruebas; no usar Redis de la aplicación. No se han ejecutado pruebas contra un Moodle real.

## Pendientes y siguiente fase

No se considera producto listo para producción. Falta frontend, integración y cifrado de tokens Moodle, SSRF, importaciones, motor de matrícula y reportes. Los permisos de esos módulos se declaran como contrato futuro; no implican endpoints ya implementados. No hay MFA, recuperación por correo ni purga programada automática. Se requiere TLS y revisión del proxy antes de acceso remoto; consultar security.md y deployment.md.

La siguiente fase es **Fase 3 — Conexiones Moodle**. No se ha iniciado; esperar instrucciones.
