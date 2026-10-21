# Entrega técnica — Fase 5

## Alcance implementado

Motor de trabajos persistidos, workers Celery independientes, ejecución gradual por lotes, controles cooperativos, límites compartidos por instalación, adaptación de pausa por latencia, circuit breaker persistido, reintentos transitorios acotados y reconciliación. Las escrituras se mantienen deshabilitadas por defecto; no se ha matriculado en un Moodle real.

API de creación/listado/consulta de trabajos, registros, intentos y eventos paginados, start, pause, resume, cancel y retry selectivo. El inicio exige acción explícita, usuario activo y autorizado, propiedad o administración, concesión y configuración vigente. Supervisor/consulta sólo leen destinos concedidos. Los estados terminales se conservan; retry crea otro borrador trazable, sin borrar resultados.

Una validación completada genera operaciones canónicas únicas por trabajo y conserva archivos y referencias. El motor no convierte sus snapshots en confirmaciones de ejecución: vuelve a resolver y comprobar antes de escribir. Los borradores del avance anterior siguen utilizables; la referencia a su registro de validación se resuelve de forma compatible.

## Fiabilidad y protección de Moodle

- Reservas transaccionales con FOR UPDATE SKIP LOCKED, lease renovable de 600 segundos y fencing al guardar.
- Advisory locks de sesión para slots de instalación y exclusión por usuario/curso entre trabajos; requieren PostgreSQL directo o pooling de sesión.
- Rate limiting agregado y exclusión de solicitudes compartidos entre conexiones con la misma URL, probes, validaciones y matrículas. Límites conservadores, sin promesas de capacidad.
- Hasta batch_size operaciones por tarea; una escritura por solicitud para limitar la ambigüedad. Consultas de usuarios/cursos agrupadas por lote y caché nueva, independiente de la validación histórica.
- Revisión de funciones, rol, visibilidad y autorización de grupo antes del envío. Cambios de identidad/configuración y revocaciones detienen nuevas operaciones.
- Persistencia de intención y resultado incierto antes de HTTP. La respuesta null oficial no confirma una matrícula; se observa el rol activo y grupo solicitado.
- Timeout/error remoto/caída en el intervalo ambiguo nunca provoca reenvío automático. Hasta tres comprobaciones de reconciliación; incertidumbre no resuelta se conserva y bloquea nuevas escrituras sobre el mismo usuario/curso.
- Los registros que se sabe que no fueron despachados se distinguen mediante not_dispatched. Pausa/cancelación no prometen deshacer solicitudes enviadas.
- Backoff exponencial con jitter y límite de reintentos para errores transitorios previos al envío. Fallos permanentes no son elegibles para retry automático ni selectivo.
- Circuito de instalación y contador agregado entre trabajos en PostgreSQL; suspensión y enfriamiento con reanudación explícita. Pausa adaptada a latencia medida y ventanas horarias UTC.
- Beat y maintenance recuperan despachos perdidos y leases vencidos. El navegador no interviene en la continuidad.

No se promete ejecución exactamente una vez frente a un servicio externo sin una clave idempotente propia. confirmed representa evidencia del estado solicitado, no atribución de causalidad a una llamada. Los intentos y errores originales se conservan, incluso después de una reconciliación tardía.

## Archivos creados

- backend/app/services/enrollment_engine.py: reserva, preflight, envío, reconciliación, carga, recuperación y finalización.
- backend/app/services/moodle_gate.py: gate compartido por los tres flujos y circuitos.
- backend/app/tasks/enrollments.py: ejecución, publicación diferida y recuperación por coordinador.
- backend/alembic/versions/0006_job_execution.py: leases, agenda, metadatos y trazabilidad de reconciliación.
- backend/tests/integration/test_enrollment_engine.py: escenarios del motor y Celery real con simulador Moodle.
- docs/enrollment-engine.md: manual operativo y configuración.

## Archivos modificados

- backend/app/api/v1/endpoints/jobs.py y schemas/jobs.py: acciones, permisos, progreso e intentos/eventos.
- backend/app/models/__init__.py: modelos de ejecución; core/config.py: flag seguro de habilitación.
- backend/app/integrations/moodle/client.py: whitelist de escritura separada y contrato de retorno null.
- backend/app/services/validation_engine.py y moodle_connections.py: uso del gate común.
- backend/app/schemas/moodle.py: concurrencia y política de circuito por instalación.
- backend/app/workers/celery_app.py: colas y recuperación; main.py: readiness 0006 y dos heartbeats.
- backend/tests/integration/test_database.py y tests/unit/test_moodle_security.py: readiness y contratos.
- backend/pyproject.toml y uv.lock: versión 0.5.0; no se agregan dependencias.
- infrastructure/compose.yaml y env.example: enrollment-worker separado y flag false.
- README y documentación de arquitectura, autenticación, CSV, datos, API Moodle, seguridad, usuario y despliegue.

## Verificación ejecutada

Los escenarios incluyen matrícula confirmada por lectura, matrícula existente sin reenvío, HTTP/null sin evidencia, timeout después de commit remoto, grupos, pausas antes/durante el envío, cancelación cooperativa, revocación/configuración obsoleta, evidencia caducada, reintentos acotados, circuito agregado entre trabajos, ventanas, latencia, concurrencia con uno/dos slots y interrupción simulada del ejecutor tras escritura. Un lote de 25 operaciones comprueba límites por tarea y consultas de usuarios agrupadas (10, 10 y 5), sin constituir una prueba de capacidad de Moodle.

Se ejecuta además un worker Celery real conectado a Redis de pruebas: se simula una publicación perdida, el coordinador la recupera y el trabajo termina sin polling HTTP. El simulador Moodle sólo existe en tests; no hay datos ficticios ni bypass SSRF en la aplicación.

Migración 0006: upgrade, downgrade a 0005 y reaplicación en PostgreSQL dedicado; Alembic check sin diferencias. No se revierten datos de la aplicación para ensayar migraciones.

Resultado final: **196 pruebas aprobadas**, ninguna omitida en la ejecución con RUN_INTEGRATION=1. Ruff check y format --check correctos. Una advertencia heredada procede de la integración Starlette/HTTPX de TestClient; no se agregó una dependencia para silenciarla.

Imagen Docker reconstruida con lockfile congelado. Compose inicia API, ambos workers de ejecución, mantenimiento, Beat, PostgreSQL y Redis; migrate finaliza con código cero. Readiness responde 200 con postgresql, redis, token_encryption, validation_recovery y enrollment_recovery verdaderos; OpenAPI expone versión 0.5.0 y diez rutas de trabajos. La configuración de ejecución real permanece false. Alembic check también se ejecuta en el contenedor de la aplicación sin detectar diferencias.

## Ejecución

Desde la raíz, con Docker Desktop/WSL2 en Windows o Docker Engine en Linux/macOS:

```powershell
docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml up --build -d --wait --wait-timeout 120
```

En Cloud, reconstruir primero con `DOCKER_CONFIG=/workspace/.docker-build python3 scripts/cloud-install.py` y arrancar Compose con --no-build. Se preservan claves y datos locales.

Desde backend, para desarrollo y pruebas:

```bash
uv sync --frozen
uv run alembic upgrade head
RUN_INTEGRATION=1 uv run pytest -q
uv run ruff check app tests alembic
uv run ruff format --check app tests alembic
```

Configurar DATABASE_URL y REDIS_URL para servicios de prueba aislados; la base de integración debe terminar en `_test`. En PowerShell configurar `$env:RUN_INTEGRATION="1"` antes de `uv run pytest -q`. Nunca ejecutar estas pruebas sobre la base/broker de la aplicación. El arranque se verifica en Linux; no se ha ejecutado Docker Desktop en Windows.

## Pendientes y siguiente fase

La aceptación y calibración contra Moodle de ensayo real requieren destino, token, permisos y autorización; no se han ejecutado. La validación de versiones/visibilidad sigue necesitando evidencia administrativa real. Estos ensayos y pruebas de carga controladas son requisitos previos a producción, no se sustituyen por el simulador.

La próxima fase es Fase 6, interfaz administrativa React/TypeScript. No se inicia automáticamente en esta entrega. Los reportes/exportaciones corresponden a Fase 7 y la revisión final de producción a Fase 8.
