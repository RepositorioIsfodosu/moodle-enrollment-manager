# Modelo inicial

UUID como claves de entidades; timestamps de creación con zona horaria y valores del servidor. Sesiones y procesos usan UTC; presentación prevista America/Santo_Domingo.

Tablas: users, roles, user_roles, moodle_connections, csv_files, csv_import_profiles, enrollment_jobs, job_files, enrollment_records, enrollment_attempts, job_events, audit_logs y system_settings. job_files permite varios CSV por trabajo. Las claves foráneas impiden referencias huérfanas; no hay borrados en cascada de historial.

La unicidad `(job_id, operation_key)` evita repetir operaciones normalizadas en el mismo trabajo sin prohibir otros trabajos. El algoritmo de normalización y su uso se implementarán en fase 4/5. Estados de trabajos y registros tienen restricciones CHECK. Índice compuesto para selección de registros por trabajo, estado y vencimiento de reserva. Intentos únicos por registro y número. No se ha implementado todavía la ejecución concurrente.

La migración 0001 crea el esquema; ejecutar `alembic upgrade head` desde backend. No ejecutar downgrade con datos sin copia previa; revierte tablas y destruye su contenido. Se debe generar una nueva migración ante cada evolución, no editar una revisión ya desplegada.

## Revisión 0002

Añade auth_sessions (UUID, user_id, token_hash único SHA-256, expires_at, created_at), con índices por usuario y caducidad. No almacena el token en claro. users exige correo normalizado; se aborta ante colisiones de correos existentes. Roles iniciales: administrador, operador, supervisor, consulta. No se crean contraseñas ni cuentas por migración. El esquema contiene ahora 14 tablas.

Cambios de rol/activación y bootstrap se serializan mediante advisory lock transaccional PostgreSQL para conservar un administrador activo incluso ante solicitudes concurrentes. Login y cambios de credenciales bloquean la fila de usuario para coordinar revocaciones. Las sesiones se borran al revocar; los eventos permanecen en audit_logs. El downgrade elimina sesiones (obliga a entrar de nuevo), pero conserva roles y auditoría para no destruir asignaciones.

## Revisión 0003

Añade a moodle_connections descripción, estado controlado (unverified/verified/limited/error/disabled), versión de configuración, marca de última comprobación, siguiente comprobación permitida, código de error, metadatos seleccionados, lista de funciones y latencia. Crea moodle_connection_checks con autor, timestamp UTC, estado, error y funciones observadas. Total: 15 tablas. No se convierten ciegamente valores antiguos de token_ciphertext: si no son descifrables, hay que reintroducir el token.

Una comprobación reserva su ventana bajo bloqueo de fila y libera la transacción antes de llamar por red. Al terminar compara configuration_version bajo otro bloqueo: si se editó/desactivó la conexión, descarta el resultado y lo audita. No se elimina historial al editar o desactivar. El downgrade elimina columnas e historial de comprobaciones; respaldar primero y no usarlo sobre datos valiosos como operación rutinaria.

## Fase 4: revisiones 0004 y 0005

0004 añade metadatos de CSV y propietario de perfiles; crea csv_contents (original BYTEA), csv_imports (snapshot de perfil), csv_operations (normalización), connection_grants, role_approvals, validation_runs, validation_records y validation_cache. Total: 23 tablas. No hay rutas arbitrarias de archivos; el original se respalda junto a PostgreSQL. Perfiles antiguos sin propietario sólo son accesibles por administrador; archivos antiguos sin contenido conservado requieren nueva carga.

Los registros normalizados no se sobrescriben al editar un perfil: cada normalización es una importación inmutable. source_row identifica el registro lógico CSV (encabezado=1), no una línea física en campos multilínea. La unicidad por importación/registro/slot protege su procedencia. No hay unicidad global que impida usar al mismo usuario en distintos procesos.

validation_records conserva resultado, motivo, IDs Moodle resueltos, revisión administrativa utilizada y fecha. La unicidad (run_id, operation_id) evita reservas duplicadas, y (run_id, resolved_key) evita identidades resueltas repetidas; los duplicados conservan la fila y no reservan otra clave resuelta. Los estados tienen CHECK. validation_runs conserva lease, propietario del lease, contador de recuperaciones y última publicación. El broker no es fuente de verdad.

0005 añade full_enrollment_visibility a las evidencias, predeterminado false incluso para las existentes. No se interpreta una lista de participantes filtrada como prueba de ausencia. La evidencia se vincula a curso, rol, versión de conexión y expiración. Se conserva al revocarla para mantener auditoría.

validation_cache guarda sólo campos necesarios por proceso, con límites de consulta; no guarda respuestas remotas completas ni claves de grupo. system_settings conserva el heartbeat UTC del coordinador de recuperación. Consultar csv-imports.md para las limitaciones de consistencia de las lecturas remotas.

## Fase 5: revisión 0006

enrollment_jobs incorpora lease_owner, lease_until indexado, next_run_at, dispatched_at y runtime JSON. enrollment_records incorpora FK opcional a validation_records para trazabilidad, error_code, retry_count, reconciliation_count, next_attempt_at y FK opcional a otro enrollment_record para reconciliaciones solicitadas desde reintentos. Los borradores anteriores conservan datos y resuelven la referencia por su validation_id y clave canónica.

No se añaden restricciones únicas globales de usuario/curso. La clave única sigue siendo (job_id, operation_key). Los intentos tienen numeración única por registro. Reservas usan FOR UPDATE SKIP LOCKED, fencing de lease y locks de sesión PostgreSQL por instalación y usuario/curso. system_settings conserva circuitos compartidos y heartbeats de coordinadores, sin tokens ni cuerpos de respuesta. Una observación tardía puede confirmar un registro original incierto sin borrar intentos ni reescribir el estado histórico final del trabajo.
