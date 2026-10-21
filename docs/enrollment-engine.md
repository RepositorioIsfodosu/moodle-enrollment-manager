# Motor de matriculación

## Autorización y arranque

La variable ENROLLMENT_WRITES_ENABLED es false por defecto en API y workers. El inicio/reanudación responde 503 mientras esté deshabilitada. Crear borradores, consultar, validar y cancelar sigue disponible. Para una aceptación autorizada, usar un Moodle de ensayo, configurar sus servicios y permisos, habilitar la variable en infrastructure/.env y recrear servicios. No se ha ejecutado esta aceptación con un Moodle real.

Desde PowerShell, Linux o macOS, en la raíz:

```powershell
docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml up --build -d --wait --wait-timeout 120
docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml ps
```

Se ejecutan API, PostgreSQL, Redis, worker de validación, enrollment-worker, maintenance y un único Beat. La migración 0006 debe finalizar antes. No sustituir PostgreSQL por Redis como fuente de resultados.

## Flujo API

1. Cargar, normalizar y validar CSV según csv-imports.md. Corregir inválidos/pendientes antes de crear el trabajo.
2. POST /api/v1/enrollment-jobs con name, validation_id y configuration opcional. El destino y propietario se derivan de la validación autorizada.
3. POST /api/v1/enrollment-jobs/{id}/start inicia explícitamente. Requiere jobs:write, propiedad o administración, concesión vigente, usuario activo y conexión sin cambios.
4. Consultar GET /api/v1/enrollment-jobs/{id}; ofrece counts, progress_percent, fechas y runtime con última actividad del worker y latencia medida cuando exista. Puede hacerse polling cada cinco segundos; no condiciona la ejecución. 100% incluye errores/inciertos y no significa éxito de todas las matrículas.
5. Consultar records, attempts y events paginados, con offset y limit (máximo 200).
6. POST pause/resume/cancel permite control cooperativo. La cancelación conserva resultados confirmados, inciertos y fallidos y marca como skipped lo que no se envió. Una solicitud enviada puede terminar después de pedir la cancelación.
7. POST retry con record_ids seleccionados, hasta 200: sólo errores transitorios fallidos y resultados inciertos de trabajos terminados. Crea un borrador distinto; requiere otro start. Los inciertos permanecen en modo de reconciliación, sin reenviar. Una observación positiva también resuelve la incertidumbre del registro original, con eventos y conservación de intentos. El estado final histórico del trabajo original no se reescribe.

Los trabajos terminales no se reinician implícitamente. La configuración puede reutilizarse al crear otro borrador desde la validación original, siempre que siga vigente. Si cambió la conexión, realizar una nueva validación.

## Parámetros de trabajo

| Campo | Predeterminado | Rango / significado |
| --- | --- | --- |
| batch_size | 5 | 1–50 operaciones por tarea |
| pause_seconds | 10 | 1–3600, espera mínima entre lotes |
| timeout_seconds | 30 | 5–120; se aplica además el menor timeout de la conexión (máximo 60) |
| max_concurrency | 1 | Un ejecutor por trabajo; varias instalaciones/trabajos pueden usar otros workers |
| max_retries | 3 | 0–5 reintentos automáticos de lecturas/preflight transitorios |
| retry_base_seconds | 30 | 1–3600; backoff exponencial con jitter para errores transitorios previos al envío |
| allowed_hours_utc | 0..23 | Lista no vacía de horas UTC; fuera de ventana no se inician escrituras |
| latency_threshold_ms | 10000 | 100–120000, umbral para aumentar la pausa |
| error_threshold | 3 | 1–20 errores consecutivos para suspender automáticamente |
| circuit_cooldown_seconds | 300 | 30–3600, enfriamiento antes de reanudación explícita |

En limits de la conexión: requests_per_minute 1–120, predeterminado 10, y max_concurrency 1–4 trabajos simultáneos, predeterminado 1. Las conexiones con la misma URL canónica comparten el mínimo de sus límites activos. El semáforo de trabajos usa advisory locks de PostgreSQL; el gate de solicitudes mantiene una única solicitud HTTP en vuelo por instalación y espacia sus inicios, incluso con varios trabajos. Validaciones y pruebas de conexión comparten ese gate y respetan el circuito abierto. Aumentar max_concurrency no elimina el límite de solicitudes.

Para ejecutar varios trabajos en paralelo se pueden escalar enrollment-worker hasta el límite autorizado. Un trabajo sigue siendo secuencial; no se ejecuta el mismo registro desde dos workers. La contención genera espera persistida, no reenvíos inmediatos en bucle. Los valores iniciales son conservadores, no una garantía de capacidad.

La adaptación aumenta la pausa ante latencia de escritura superior al umbral y la reduce gradualmente después de respuestas más rápidas. No consulta ni inventa CPU, memoria o usuarios concurrentes de Moodle. La pausa efectiva y latencia quedan en runtime. Los errores persistentes abren un circuito guardado en PostgreSQL y dejan el trabajo pausado. El contador agregado por instalación se conserva entre trabajos; limits.error_threshold (3) y limits.circuit_cooldown_seconds (300) definen la política administrativa, con el umbral más conservador y el mayor enfriamiento entre conexiones activas del mismo destino. Cada trabajo puede suspenderse antes mediante su propio umbral. Al terminar el enfriamiento se necesita resume; nuevas tareas del mismo destino también respetan el circuito.

## Reservas y resultados

Cada tarea reclama un lease de trabajo de 600 segundos y reserva registros mediante bloqueo transaccional y SKIP LOCKED. Renueva la actividad al comprobar permisos y antes de solicitudes. Un lock adicional por instalación/usuario/curso protege operaciones que coinciden entre trabajos, incluso con grupos o roles distintos. La exclusión de matrícula se aplica durante la ejecución; no se impone una unicidad global que prohíba repetir legítimamente un usuario en otro trabajo.

El motor vuelve a resolver usuario, curso, grupo, estado de suspensión y evidencia de rol/visibilidad. Usa consultas agrupadas y caché nueva por lote, sin reutilizar la caché histórica de la validación. Un cambio de identidad resuelta se bloquea. Los límites de escaneo de participantes siguen vigentes: no encontrar un usuario en una consulta incompleta no prueba ausencia.

Antes de escribir, confirma funciones disponibles y evidencia administrativa vigente y guarda un intento write_intent con registro uncertain. La API oficial devuelve null; sólo una lectura positiva del rol activo y grupo solicitado permite confirmed. Una matrícula que ya estaba presente queda existing y no se vuelve a enviar. Agregar grupo exige observar primero el rol activo. Si la aplicación sabe que no llegó a despachar una solicitud (por ejemplo, pausa mientras esperaba el gate), conserva not_dispatched y devuelve el registro a pending. Una caída en el intervalo de intención/envío se conserva como incierta.

No hay reintentos de escritura automáticos tras timeout, error remoto, respuesta inesperada o caída en el intervalo ambiguo. Se realizan hasta tres comprobaciones automáticas de reconciliación, separadas por retry_base_seconds. Si no hay prueba suficiente, se conserva uncertain y el trabajo puede finalizar completed_with_errors. Otros trabajos que requieran escribir sobre ese mismo usuario/curso se bloquean mientras exista una incertidumbre no resuelta. Se requiere investigar Moodle y después solicitar otra reconciliación; el sistema no decide que una lista vacía justifica reenviar un intento incierto.

No se promete ejecución exactamente una vez frente a un servicio externo sin clave idempotente propia ni se atribuye causalidad a una observación posterior: confirmed significa que se observó el estado solicitado. Los intentos originales y sus errores se conservan.

## Recuperación

Beat solicita recuperación cada 15 segundos. maintenance vuelve a publicar trabajos pendientes cuya publicación falta o lleva más de 60 segundos, siempre que estén listos por fecha. Los leases activos no se roban. Tras 600 segundos sin renovación, una reserva sin intención de escritura vuelve a pending; un intento incierto sólo se reconcilia. Si muere un proceso, PostgreSQL libera sus advisory locks al cerrar la conexión. Un proceso vivo bloqueado puede conservarlos: inspeccionar antes de terminarlo, sin asumir que la solicitud remota se deshizo.

Al cerrar el navegador no cambia ningún estado del trabajo. Redis puede perder un mensaje y PostgreSQL permite recuperarlo. Reiniciar Redis no debe usarse como mecanismo para reintentar matrículas. Si se deshabilitan escrituras, los nuevos lotes se pausan y las cancelaciones aún se pueden completar sin llamadas Moodle.

Ante cambios de conexión o revocación de permisos se detienen nuevas operaciones. Un error inesperado queda registrado sin datos técnicos sensibles; los intentos ambiguos se conservan para investigar. El resultado puede requerir revisión manual del administrador de Moodle.

## Supervisión

Readiness verifica migración 0006, Redis, cifrado y heartbeats recientes de ambos coordinadores. No sustituye la salud de cada worker ni certifica disponibilidad de Moodle. Revisar ps, logs y el ping de enrollment-worker:

```powershell
docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml exec enrollment-worker celery -A app.workers.celery_app:celery_app inspect ping
```

Respaldar PostgreSQL y claves antes de actualizar. No ejecutar down -v con datos que deban conservarse. Fechas y ventanas se almacenan en UTC; la presentación en America/Santo_Domingo corresponde a la interfaz administrativa.
