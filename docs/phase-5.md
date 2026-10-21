# Fase 5 — avance: borradores y estados

La Fase 5 está **en curso**. Esta entrega incorpora gestión persistente de borradores; no incorpora todavía un ejecutor de matrículas ni se considera terminada.

## Funcionalidad disponible

- Crear un borrador desde una validación completada de la versión vigente de conexión. Se exige propiedad o administración y acceso vigente al destino.
- Rechazar validaciones con registros inválidos o pendientes, sin omitirlos silenciosamente. Los duplicados ya identificados no generan otra operación.
- Conservar referencias a validación, archivos, filas, identificadores resueltos y configuración acotada. No se imponen restricciones globales entre trabajos distintos.
- Listar, consultar y paginar registros de trabajos. Operadores sólo ven sus propios trabajos dentro de conexiones autorizadas; administrador puede consultarlos. El acceso de supervisores a trabajos de terceros queda pendiente de definir e implementar.
- Cancelar borradores con bloqueo transaccional, fecha de finalización, evento y auditoría. Repetir la cancelación devuelve 409 y no duplica eventos.
- Máquina explícita de transiciones para todos los estados definidos. Las transiciones del ejecutor aún no se exponen como acciones disponibles.
- Inicio deshabilitado con respuesta 503 explícita. No se publica ninguna tarea de escritura Moodle.

Los registros de validación `existing` se copian como pendientes: una observación anterior no confirma el resultado de un trabajo futuro. Se conserva la referencia a la validación original para trazabilidad. No se copian tokens ni respuestas completas de Moodle a la configuración.

## Archivos

Creados en backend: app/api/v1/endpoints/jobs.py, app/schemas/jobs.py, app/services/job_states.py, tests/unit/test_job_states.py y tests/integration/test_jobs.py. Se modifica app/main.py para registrar el router. Documentación: README.md y este informe. No se necesitan nuevas tablas ni migraciones para este avance: utiliza los modelos existentes y revisión 0005.

## Verificación

Pruebas unitarias de cobertura de estados, rechazo de reinicio terminal, pausa/cancelación cooperativa y límites de configuración. Integración con PostgreSQL/Redis aislados y Moodle simulado: persistencia, auditoría, cancelación repetida, inicio bloqueado, permisos, listado paginado, versión obsoleta de conexión, rechazo de validaciones incompletas y consolidación de duplicados. No se ejecutan matrículas reales.

Resultado ejecutado: **168 pruebas aprobadas**, ninguna omitida en la ejecución con RUN_INTEGRATION=1. Ruff check y format --check correctos. Una advertencia de deprecación proviene de la integración Starlette/HTTPX de TestClient. Imagen Docker reconstruida y Compose iniciado con todos los servicios saludables; migración finaliza con código cero, readiness 200 con cuatro comprobaciones verdaderas y cinco rutas de trabajos presentes en OpenAPI.

Comandos desde backend, con servicios de prueba dedicados y DATABASE_URL apuntando a una base cuyo nombre termine en `_test`:

```bash
uv sync --frozen
uv run alembic upgrade head
RUN_INTEGRATION=1 uv run pytest -q
uv run ruff check app tests
uv run ruff format --check app tests
```

Inicio del sistema desde la raíz, también en PowerShell con Docker Desktop:

```powershell
docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml up --build -d
```

El despliegue y configuración de Windows siguen descritos en README.md y docs/deployment.md. El estado del entorno no implica que el producto esté listo para producción.

## Trabajo esencial pendiente dentro de Fase 5

Reservas y leases de ejecución, workers de matrícula, lotes y revalidación fresca de identidades/permisos, control integral de solicitudes por instalación, circuit breaker y backoff con jitter, ventanas horarias, pausas/reanudación, cancelación de procesos activos, reintentos selectivos, recuperación de workers y reconciliación por operación. También faltan pruebas de ambigüedad HTTP, escrituras interrumpidas y concurrencia del ejecutor. El cliente Moodle continúa siendo de sólo lectura. El frontend corresponde a Fase 6 y no se ha iniciado.

La llamada enrol_manual_enrol_users no proporciona confirmaciones individuales; el diseño del ejecutor deberá distinguir respuesta HTTP de evidencia de matrícula, conservar resultados inciertos y evitar reenvíos automáticos de operaciones ambiguas. No se puede afirmar ejecución exactamente una vez sobre un servicio externo que no recibe una clave idempotente propia de esta aplicación.
