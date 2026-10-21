# Entrega técnica — Fase 4

## Implementación

Carga CSV por stream acotado, conservación del original en PostgreSQL, SHA-256, historial, encabezados, vista previa, delimitador y codificación explícita. Perfiles reutilizables y mapeo de columnas propias o courseN/roleN/groupN. La normalización genera varias operaciones por fila cuando corresponde, conserva registros inválidos y detecta duplicados sin borrar la evidencia de origen. Una nueva normalización conserva un snapshot del perfil.

Validación asíncrona por Celery: selección de hasta 20 importaciones, duplicados entre archivos y tras resolver aliases, usuarios/cursos/grupos existentes o no visibles, matrículas activas con rol/grupo solicitado, estados de suspensión y evidencia administrativa de rol y visibilidad. Resultados valid/invalid/duplicate/existing/pending, motivos y progreso en PostgreSQL. No se crean entidades ni se escribe en Moodle.

Administrador controla conexiones y revisiones; operadores sólo sus archivos y conexiones concedidas. Supervisor/consulta requieren alcance explícito para ver validaciones de un destino, sin acceso al original. Revocación, desactivación y cambios de conexión se comprueban durante el proceso. Los resultados anteriores se mantienen.

## Decisiones importantes

La API Moodle 4.5 revisada no ofrece un catálogo estándar de roles asignables. Además, get_enrolled_users puede devolver listas filtradas por grupos/permisos. Se implementó evidencia administrativa explícita, con referencia, versión de conexión y caducidad de hasta siete días. full_enrollment_visibility es false por defecto: no se infiere ausencia de una matrícula a partir de una lista vacía sin esa evidencia. groups_authorized confirma por separado permisos de grupos. El resultado indica administrator_attestation, sin fingir verificación API de esos permisos.

Las consultas de usuarios se agrupan de 50 en 50, cursos por ID usan field=ids, y los demás identificadores se consultan una vez por valor/proceso. Participantes se paginan con onlyactive=1 y límite de escaneo. La caché se conserva por validación para continuar entre tareas o reinicios; es una evidencia de lectura que puede quedar obsoleta, no una garantía de ejecución futura. Las respuestas se filtran antes de guardar, sin claves de grupos ni datos remotos innecesarios.

Worker de validación, worker de mantenimiento y Celery Beat separados: un proceso largo no impide recuperar publicaciones perdidas. Redis coordina intervalos y exclusión de solicitudes de validación por URL canónica; PostgreSQL conserva estado, publicación, leases y resultados. Las tareas comprueban su lease al guardar. Los leases abandonados vencen a los 600 segundos, con tres recuperaciones máximas. Errores permanentes quedan failed; no hay reintentos Moodle ilimitados. Cancelación cooperativa sin borrar historial.

El frontend, incluida selección múltiple visual/arrastrar y soltar, corresponde a fase 6. Esta fase ofrece la API funcional, no pantallas estáticas. La carga usa bytes CSV en el cuerpo, no multipart; no se añadió dependencia para ello.

## Archivos creados

- app/api/v1/endpoints/imports.py y validations.py: archivos, perfiles, normalización, resultados, autorizaciones y evidencias.
- app/services/csv_parser.py, imports.py e import_access.py: parsing, normalización y alcance.
- app/services/validation_engine.py: consultas, caché, checkpoints, exclusión y recuperación de leases.
- app/tasks/validations.py: tareas, publicación y barrido periódico.
- app/integrations/moodle/read_models.py y app/schemas/csv.py: validación de datos externos y de API.
- alembic/versions/0004_csv_import_and_validation.py y 0005_enrollment_visibility_evidence.py: estructuras y requisito explícito de visibilidad.
- tests/unit/test_csv_parser.py y tests/integration/test_imports.py.
- docs/csv-imports.md y este informe.

Rutas app/alembic/tests anteriores están bajo backend/. Se actualizaron modelos, configuración, permisos, cliente Moodle de lectura, main.py, configuración Celery, versión/lockfile, Compose y ejemplos de variables, pruebas de regresión, README y documentación de arquitectura, base de datos, Moodle, autenticación, seguridad, despliegue y uso. Migraciones 0001–0003 permanecen intactas.

## Verificación ejecutada

- **150 pruebas aprobadas**, sin omisiones con RUN_INTEGRATION=1, PostgreSQL 16 y Redis 7 dedicados. Se mantienen las regresiones anteriores.
- Nuevas pruebas: BOM/codificaciones/delimitadores, quoted/multilínea, encabezados y límites, mapeo y metadatos, roles y campos faltantes, múltiples cursos, originales, snapshots de perfiles, privacidad de archivos, concesiones/revocación, duplicados crudos/resueltos, consultas agrupadas, suspensión no divulgada, grupos, matrículas activas, evidencia y caducidad, capacidades, paginación incompleta, checkpoints de más de un lote, caché persistida, cancelación, edición de conexión, concurrencia, rate limiting real Redis, publicaciones perdidas, límite de recuperación y errores sanitizados.
- Prueba adicional con procesos reales FastAPI/Uvicorn, Celery, Redis, PostgreSQL, mantenimiento y Beat: carga/normalización y validación completadas; se retiró deliberadamente una publicación de la cola de pruebas y Beat la recuperó desde PostgreSQL. Se cerró el cliente HTTP y otro cliente consultó el resultado. Los registros de esa prueba eran inválidos localmente y no se llamó a Moodle. Este smoke test no se cuenta como prueba Pytest.
- Migraciones 0004/0005 aplicadas; reversión a 0003 en base dedicada, reaplicación y segundo upgrade sin cambios. Alembic check sin diferencias. No se revirtieron datos de la aplicación para probar migraciones.
- Ruff check/format e instalación uv sync --frozen correctos. Imagen Docker construida con TLS y lockfile, sin dependencias nuevas. Arranque Compose con migración terminada en cero y verificación de salud/actividad de recuperación.

Se mantiene una advertencia de deprecación de TestClient/Starlette. Windows está documentado, pero no probado en una máquina Windows. No se afirma que la CI GitHub haya pasado sin comprobar su ejecución. Las pruebas de carga completas pertenecen a fase 8.

## Ejecución

Desde la raíz: `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml up --build -d --wait --wait-timeout 120`. En Cloud compilar antes con `DOCKER_CONFIG=/workspace/.docker-build python3 scripts/cloud-install.py` y usar --no-build. Ejecutar todos los servicios, incluidos maintenance y beat. Readiness comprueba revisión 0005, Redis, cifrado y actividad reciente del coordinador; revisar también salud del worker de validación.

Primer administrador: comando interactivo del README; no hay credenciales predeterminadas. Carga: POST /api/v1/csv-files con cuerpo de bytes CSV. Normalización: POST /api/v1/csv-files/{id}/normalize. Crear validación: POST /api/v1/validations. Consultar /{id} y /{id}/records; cancelar con /{id}/cancel. Ejemplos y campos en csv-imports.md.

Pruebas desde backend: `uv run pytest tests/unit -q`; integración sólo con DATABASE_URL a una base terminada en _test y Redis dedicados, REDIS_URL, RUN_INTEGRATION=1, después de `uv run alembic upgrade head`. Ejecutar `uv run pytest -q`. No usar el broker de la aplicación: la suite crea datos/esquemas temporales y limpia sus claves de prueba.

## Límites y siguiente fase

No se ha configurado un Moodle real ni se han ejecutado matrículas. La integración remota se prueba con simuladores y contratos oficiales revisados. Se necesita un Moodle de ensayo y un administrador que configure usuario técnico, funciones, capacidades y evidencias reales antes de validar esa instalación. No pegar tokens en chat.

completed significa análisis terminado, no matrícula confirmada; puede haber pending incluso con 100 % de progreso. valid no garantiza que las condiciones sigan vigentes al ejecutar. No hay endpoint de matrícula ni cambios remotos. El motor futuro debe revalidar y reconciliar con autorización explícita, sin confiar sólo en este snapshot. Siguen pendientes frontend, reportes, retención completa y preparación productiva.

Siguiente fase: **Fase 5 — Motor de matriculación por lotes**. No se inicia automáticamente.
