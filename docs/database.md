# Modelo inicial

UUID como claves de entidades; timestamps de creación con zona horaria y valores del servidor. Sesiones y procesos usan UTC; presentación prevista America/Santo_Domingo.

Tablas: users, roles, user_roles, moodle_connections, csv_files, csv_import_profiles, enrollment_jobs, job_files, enrollment_records, enrollment_attempts, job_events, audit_logs y system_settings. job_files permite varios CSV por trabajo. Las claves foráneas impiden referencias huérfanas; no hay borrados en cascada de historial.

La unicidad `(job_id, operation_key)` evita repetir operaciones normalizadas en el mismo trabajo sin prohibir otros trabajos. El algoritmo de normalización y su uso se implementarán en fase 4/5. Estados de trabajos y registros tienen restricciones CHECK. Índice compuesto para selección de registros por trabajo, estado y vencimiento de reserva. Intentos únicos por registro y número. No se ha implementado todavía la ejecución concurrente.

La migración 0001 crea el esquema; ejecutar `alembic upgrade head` desde backend. No ejecutar downgrade con datos sin copia previa; revierte tablas y destruye su contenido. Se debe generar una nueva migración ante cada evolución, no editar una revisión ya desplegada.
