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
