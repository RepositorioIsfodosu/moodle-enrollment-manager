# Moodle Enrollment Manager

Aplicación para administrar matrículas masivas en Moodle. Estado: versión 0.8.0, verificación local de Fase 8; aceptación y calibración en Moodle real pendientes. Interfaz administrativa con reportes CSV/XLSX/PDF y motor verificado con simuladores. Permite iniciar sesión, gestionar conexiones, cargar CSV, validar y ejecutar trabajos asíncronos con recuperación y reconciliación. Las escrituras están deshabilitadas por defecto; no se ha ejecutado una aceptación contra Moodle real. No utilizar como sistema de producción.

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

En Linux sustituir Copy-Item por `cp` y generar la clave con `python3 scripts/init-secrets.py` antes de Compose. La API escucha únicamente en loopback. Swagger se encuentra en `/docs`; la interfaz web escucha en el puerto local 8080. El proceso migrate debe terminar con código cero; api debe estar healthy. Para detener sin borrar datos usar `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml down`. Nunca usar `down -v` con datos que deban conservarse.

## Desarrollo y pruebas

Python 3.12 y uv. Desde backend: `uv sync --frozen`; configurar DATABASE_URL (postgresql+psycopg), REDIS_URL y MOODLE_TOKEN_KEYS; ejecutar `uv run alembic upgrade head`, `uv run pytest`, `uv run ruff check .`. Para pruebas con servicios reales establecer RUN_INTEGRATION=1. Las pruebas unitarias no requieren servicios; las de integración se omiten explícitamente sin esa variable.

Arquitectura, decisiones y limitaciones en [docs/architecture.md](docs/architecture.md). Despliegue en [docs/deployment.md](docs/deployment.md). El alcance y la verificación local de Fase 8 se detallan en [docs/phase-8.md](docs/phase-8.md). Desarrollo y pruebas de navegador en [docs/frontend.md](docs/frontend.md). Para cerrar Fase 8 falta la [aceptación autorizada en Moodle de ensayo](docs/acceptance.md).

## Primer administrador y autenticación

Después de migrar, desde PowerShell o terminal interactiva:

```powershell
docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml exec api python -m app.cli create-admin
```

El comando solicita correo y contraseña sin mostrarla. No existe una cuenta predeterminada; no introduzcas contraseñas como argumentos ni las guardes en Git. Sólo permite crear el administrador inicial si aún no existe uno activo. Sigue [autenticación y API](docs/authentication.md) para iniciar sesión y administrar usuarios. La interfaz visual permite iniciar sesión con esa cuenta.

Informe: [Fase 2](docs/phase-2.md). Pruebas de integración sólo sobre una base dedicada cuyo nombre termine en `_test` y Redis de pruebas; no usar el broker de la aplicación.

## Conexiones Moodle

El administrador puede crear conexiones en `/api/v1/moodle-connections` y probarlas mediante POST `/{id}/test`. Se requiere URL HTTPS pública y token de un servicio con `core_webservice_get_site_info`. La prueba es sólo de lectura; no matricula. El token se cifra y nunca se devuelve; proteger la clave MOODLE_TOKEN_KEYS en .env y sus respaldos. Ver [configuración Moodle y contrato de API](docs/moodle-api.md) e [informe de Fase 3](docs/phase-3.md). La sección Conexiones Moodle permite estas operaciones.

## Importación y validación CSV

Consultar [formatos, perfiles y API CSV](docs/csv-imports.md) y el [informe de Fase 4](docs/phase-4.md). El archivo original se conserva en PostgreSQL; una fila puede generar varias operaciones. La validación usa una cola Celery independiente del navegador, con progreso persistido y recuperación coordinada por Celery Beat y un worker de mantenimiento. Compose inicia ambos servicios.

No confundir validación completada con matrícula realizada: los estados son valid, invalid, duplicate, existing y pending. Rol asignable y visibilidad completa de matrículas requieren revisión administrativa explícita con caducidad, porque la API estándar de Moodle 4.5 no ofrece las pruebas necesarias en todos los contextos. No se crean usuarios, cursos, grupos ni matrículas.

## Trabajos y motor de matrícula — Fase 5

`POST /api/v1/enrollment-jobs` crea un borrador desde una validación completada y vigente; recibe `name`, `validation_id` y opcionalmente `configuration`. Rechaza operaciones inválidas o pendientes, consolida duplicados y conserva archivos y validación de origen. Los resultados de validación se vuelven a comprobar al ejecutar.

Consultar lista/detalle con `GET /api/v1/enrollment-jobs` y `GET /api/v1/enrollment-jobs/{id}`; registros, intentos y eventos paginados en `/{id}/records`, `/{id}/attempts` y `/{id}/events`. Las acciones POST son `/{id}/start`, `/{id}/pause`, `/{id}/resume`, `/{id}/cancel` y `/{id}/retry`. Un reintento selectivo crea otro borrador trazable; los resultados inciertos sólo se vuelven a consultar y no se reenvían automáticamente.

Celery procesa hasta batch_size operaciones por tarea y espera entre lotes. Cada escritura Moodle contiene una operación para acotar la incertidumbre; las consultas de usuarios se agrupan por lote. PostgreSQL conserva estado, reservas, intentos y tiempos; Redis coordina las solicitudes. Cerrar el navegador no detiene el trabajo. Pausar o cancelar no deshace una solicitud enviada.

Para pruebas de aceptación autorizadas, configurar primero un Moodle de ensayo y sus funciones/permisos, conceder acceso al operador y registrar las evidencias administrativas de rol/visibilidad. Después habilitar `ENROLLMENT_WRITES_ENABLED=true` en infrastructure/.env y recrear los servicios con Compose. Cada trabajo requiere un inicio explícito. No habilitar escrituras contra producción antes de validar recuperación y calibrar límites con el responsable de Moodle.

Consultar [la guía del motor](docs/enrollment-engine.md) para configuración, controles y recuperación. La interfaz React permite gestionar estos trabajos. Reportes permite filtrar y exportar resultados a CSV, XLSX y PDF; consultar [guía de reportes](docs/reports.md).

## Operación y calidad

[Despliegue endurecido, respaldo y recuperación](docs/operations.md), [revisión de seguridad](docs/security-review.md) y [carga simulada reproducible](docs/load-testing.md). El overlay productivo requiere gateway HTTPS configurado y activa cookies Secure; no abre puertos públicos ni constituye un despliegue productivo. CI configura backend, frontend, navegador y auditorías; su ejecución remota se verifica en GitHub Actions. Las pruebas de carga reales sobre Moodle no se ejecutan automáticamente.
