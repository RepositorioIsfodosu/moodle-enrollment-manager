# PostgreSQL: migraciones y runtime separados — 0.8.1

La cuenta PostgreSQL inicial del Compose administra esquema/migraciones. El nuevo overlay compose.runtime-role.yaml asigna a API, workers y Beat otra credencial y añade db-permissions, un proceso previo de permisos. La separación se verificó en un proyecto Docker aislado; el entorno local de desarrollo no cambia de credencial automáticamente.

## Preparación

Realizar respaldo y conservar claves. Los siguientes comandos son para un despliegue controlado con PostgreSQL 16 del Compose, desde la raíz. En un entorno existente, pausar trabajos antes de recrear procesos. No borrar volúmenes ni ejecutar contra una base desconocida.

1. Construir las imágenes y arrancar db/redis con la configuración administrativa:

```powershell
docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml build
docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml up -d db redis
docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml run --rm migrate
```

En Codex Cloud usar scripts/cloud-install.py para la compilación con la CA/proxy existentes, como indica deployment.md.

2. Crear un usuario PostgreSQL nuevo mediante la identidad migradora, sin publicar su contraseña:

```powershell
docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml run --rm migrate python -m app.cli create-runtime-role --role mem_runtime
```

El comando solicita dos veces una contraseña de 20–128 caracteres sin controles. Obtenerla de un gestor de contraseñas; no usar valores de ejemplo ni argumentos de shell. Usa un verificador SCRAM-SHA-256 en el DDL; no transmite la contraseña en texto dentro de la sentencia CREATE ROLE. El rol no es un usuario ni un rol de la interfaz: no crea cuentas administrativas de la aplicación.

Se rechaza si ya existe, sin cambiar su contraseña. Para un rol creado previamente por este mecanismo usar grant-runtime-role; no modifica atributos administrativos ni elimina pertenencias/propiedades por sorpresa. La operación se audita con nombre de rol/esquema, sin contraseña ni verificador.

3. Crear un archivo privado fuera del repositorio con **la misma contraseña**:

```powershell
py -3 scripts/runtime-url.py C:\Secretos\mem-runtime.env --role mem_runtime --host db --database enrollment
```

En Linux usar python3 y, por ejemplo, /srv/mem-secrets/runtime.env con directorio ya creado y acceso restringido. Ajustar --database al POSTGRES_DB del despliegue y --role al rol creado. --host db es el nombre del servicio dentro de Compose; no usar localhost para conexiones desde contenedores. --port es 5432 por defecto.

El helper solicita la contraseña sin mostrarla y escribe RUNTIME_DB_USER y RUNTIME_DATABASE_URL codificando caracteres reservados. La URL **contiene una contraseña recuperable**, no está cifrada: permisos 0600 en sistemas que los aplican, ACL restringida en Windows y almacenamiento seguro. Rechaza sobrescritura y destinos dentro del checkout; elimina su archivo parcial si falla la escritura. No copiar su contenido a Git, logs, capturas o chat. Puede gestionarse con un mecanismo externo seguro en lugar del archivo, suministrando las mismas variables.

4. Arrancar con ambos archivos de entorno y el overlay de roles. Para producción HTTPS:

```powershell
docker compose --env-file infrastructure/.env --env-file C:\Secretos\mem-runtime.env -f infrastructure/compose.yaml -f infrastructure/compose.production.yaml -f infrastructure/compose.runtime-role.yaml up --build -d --wait --wait-timeout 120
```

En Linux sustituir la ruta del archivo privado. Para desarrollo HTTP, omitir únicamente compose.production.yaml. El overlay productivo activa cookies Secure y requiere gateway TLS/DNS/certificados reales; ver operations.md. En Cloud, tras compilar con el helper, sustituir --build por --no-build.

migrate conserva la identidad administrativa. db-permissions usa esa misma identidad, refresca permisos tras migrar, valida que la URL de runtime tenga el usuario esperado y la misma base, host y puerto, y comprueba autenticación y esquema public con esa conexión. API/workers/Beat esperan su salida cero y reciben sólo la URL reducida, sin la contraseña administrativa en su entorno. Se admiten parámetros explícitos de TLS, application_name y connect_timeout; se rechazan opciones de enrutamiento (host/hostaddr/dbname/service), cambios de search_path y parámetros repetidos para evitar que la consulta de URL redirija a otro destino. Esta receta no admite sockets Unix ni failover multihost. Se rechazan credenciales incorrectas o una URL del administrador; no se utiliza la cuenta administrativa como fallback.

## Permisos

El rol tiene LOGIN, NOINHERIT y ningún atributo de superusuario, creación de base/roles, replicación o bypass de RLS. No debe pertenecer a otros roles ni ser propietario de bases, esquemas u objetos. Se concede CONNECT y USAGE, sin CREATE sobre el esquema de aplicación.

| Tablas | Privilegios de runtime |
|---|---|
| roles, alembic_version | SELECT |
| audit_logs, job_events, csv_files, csv_contents, csv_imports, csv_operations, job_files, moodle_connection_checks | SELECT, INSERT |
| users, moodle_connections, csv_import_profiles, enrollment_jobs, enrollment_records, enrollment_attempts, system_settings, role_approvals, validation_runs, validation_records | SELECT, INSERT, UPDATE |
| user_roles, auth_sessions, connection_grants | SELECT, INSERT, DELETE |
| validation_cache | SELECT, INSERT, UPDATE, DELETE |

No se concede TRUNCATE, REFERENCES, TRIGGER ni propiedad. Auditoría, eventos e importaciones son inmutables para runtime; el propietario/migrador sigue siendo una identidad de confianza con capacidad administrativa. Esta separación no protege frente a un administrador de infraestructura ni cifra datos adicionales.

Se verifica que PUBLIC u otras concesiones efectivas no reintroduzcan los privilegios excluidos. Si un esquema antiguo concede CREATE a PUBLIC o auditoría modificable, el proceso falla; un administrador debe revisar esas concesiones, sin revocaciones globales automáticas. PostgreSQL puede conceder CONNECT/TEMP mediante PUBLIC: no se afirma que el usuario no pueda crear tablas temporales. Usar una base dedicada y revisar funciones SECURITY DEFINER y permisos externos al esquema de la aplicación.

La matriz es explícita: no se otorgan permisos automáticos a tablas futuras mediante ALTER DEFAULT PRIVILEGES. Todo modelo nuevo exige revisar la matriz y refrescar permisos después de migrar. db-permissions hace ese refresco al arrancar y falla si falta esa revisión. No hay nuevo esquema ni migración Alembic; la revisión continúa en 0006.

## Operación y recuperación

Para refrescar permisos sin cambiar contraseña: desde la identidad migradora ejecutar grant-runtime-role --role mem_runtime. Con --check-runtime-url requiere la variable RUNTIME_DATABASE_URL y verifica su conexión; el overlay la suministra. No ejecutar desde API/worker: esos procesos carecen deliberadamente de permisos para concederse privilegios.

Las concesiones y auditoría se ejecutan en una transacción. Si la conexión falla al confirmar, comprobar estado del rol antes de reintentar; un error de confirmación no demuestra que el servidor haya revertido. create-runtime-role nunca reemplaza una contraseña de un rol existente. La rotación de credenciales es un procedimiento administrativo separado, sincronizado con el secreto y los procesos; no automatizamos un cambio destructivo ni una recuperación de contraseña.

pg_dump custom sin owners/ACL no respalda roles del clúster ni sus contraseñas. Tras restaurar en un clúster nuevo, crear el rol de runtime con un secreto recuperado o nuevo y refrescar concesiones antes de arrancar la aplicación. Mantener escrituras Moodle deshabilitadas durante recuperación; seguir operations.md.

El propietario administrativo permanece en los servicios migrate/db-permissions y en el administrador del servidor Docker; no es una frontera frente a quien controla esos procesos. Para PostgreSQL gestionado externo se requiere adaptar la identidad migradora, red/TLS y el overlay a ese servicio; el overlay entregado corresponde al PostgreSQL del Compose, no asegura compatibilidad con todos los proveedores.

## Verificado

19 pruebas focalizadas: autenticación real PostgreSQL, pipeline API/validación/matrícula simulada/reportes, cambio de roles de aplicación, denegación de DDL y modificación de auditoría/originales, atributos y pertenencias peligrosas, ownership, concesiones inseguras de PUBLIC, tablas futuras sin acceso, validación de URL y archivo privado sin sobrescritura ni archivos parciales. Las 252 pruebas backend aprobaron, con una carga optativa omitida; no se repitió el benchmark de 1000 operaciones porque el motor no cambió.

Los siete recorridos Chromium ahora preparan fixtures con una identidad administrativa y ejecutan API/worker con un rol reducido efímero. El harness limpia rol y esquema aun si falla la preparación. Se necesita un PostgreSQL de pruebas con permisos administrativos para crear/eliminar esas identidades; nunca usar una base ni broker de aplicación.

En un proyecto Docker aislado se migró, provisionó el rol, arrancaron todos los servicios y se verificaron sesión HttpOnly por Nginx, readiness y CSV/XLSX/PDF. Se comprobó que la contraseña administrativa no estuviera en el entorno del API y que una contraseña de runtime incorrecta produjera error, sin fallback. No se crearon roles PostgreSQL ni cuentas de prueba en la base real de desarrollo.
