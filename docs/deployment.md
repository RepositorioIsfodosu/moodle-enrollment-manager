# Instalación, operación y despliegue

Seguir README para Windows y Docker. Variables de Compose: POSTGRES_USER, POSTGRES_PASSWORD y POSTGRES_DB; backend recibe DATABASE_URL y REDIS_URL por red privada Docker. No publicar PostgreSQL ni Redis a Internet. Para contraseñas con caracteres reservados de URL configurar una URL correctamente codificada mediante una adaptación revisada del despliegue; el ejemplo local usa caracteres simples.

`/api/v1/health/live` indica que responde la API. `/api/v1/health/ready` comprueba PostgreSQL, revisión Alembic 0006 y Redis, devolviendo 503 al fallar. No representa disponibilidad de Moodle ni del worker. Verificar el worker mediante `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml exec worker celery -A app.workers.celery_app:celery_app inspect ping`. Existen tareas de validación CSV y matrícula en workers separados. Las escrituras están deshabilitadas por defecto. Consultar enrollment-engine.md para activación autorizada y recuperación.

## Copias de seguridad

Antes de migrar: `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml exec -T db pg_dump -U enrollment -d enrollment -Fc > backup.dump`. En Windows usar una terminal que preserve salida binaria o generar primero el archivo dentro del contenedor y copiarlo con docker cp. Guardar cifrado fuera del servidor, con acceso restringido. Probar restauraciones en base separada mediante pg_restore; no restaurar sobre producción sin plan de recuperación. Los volúmenes persisten al reiniciar.

## Diagnóstico

Consultar `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml logs api migrate worker`. Ante 503 revisar salud de db/redis y migración. Si falla una migración detener el despliegue e investigar; no borrar volúmenes como solución. Al cambiar contraseña de un PostgreSQL ya inicializado, cambiar también el rol en la base: las variables de la imagen no rotan la contraseña existente.

## Producción pendiente

La Fase 6 incorpora frontend, importación, validación y motor. Antes de producción faltan la aceptación real, calibración, retención completa y revisión integral. Mantener escrituras deshabilitadas hasta contar con un Moodle de ensayo autorizado.

## Codex Cloud

Usar el checkout existente, sin crear worktrees. La compilación puede necesitar el proxy inyectado y su CA: `DOCKER_CONFIG=/workspace/.docker-build python3 scripts/cloud-install.py`. El helper resuelve el hostname del proxy y monta la CA sólo durante la compilación mediante BuildKit; no desactiva TLS ni copia secretos a las capas. Después ejecutar Compose con `up --no-build -d --wait --wait-timeout 120`. No se presupone que los procesos sobrevivan a una nueva tarea.

El script crea infrastructure/.env sólo si no existe, con contraseña aleatoria local. No cambia contraseñas de volúmenes PostgreSQL existentes. `.venv`, cachés y archivos .env son salidas locales ignoradas y no se suben al repositorio.

## Actualización de Fase 1 a Fase 2

Respaldar la base, actualizar el checkout e imagen, y ejecutar Compose. El servicio migrate aplica 0002 antes de arrancar API/worker. La revisión normaliza los correos a minúsculas; si detecta colisiones aborta para que un administrador resuelva los datos, sin fusionar cuentas. Añade auth_sessions y los cuatro roles, sin crear usuarios. Repetir upgrade es seguro. No ejecutar pruebas automatizadas contra la base de la aplicación.

Crear el primer administrador con el comando interactivo del README. Para purgar sesiones caducadas: `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml exec api python -m app.cli purge-sessions`. No borra auditoría. Hacerlo periódicamente desde el planificador operativo; no hay servicio de limpieza automática aún.

Configurar en infrastructure/.env SESSION_TTL_SECONDS (300–86400, predeterminado 28800), LOGIN_IP_LIMIT (1–1000, predeterminado 30), LOGIN_ACCOUNT_LIMIT (1–100, predeterminado 10) y LOGIN_WINDOW_SECONDS (10–3600, predeterminado 300). Reiniciar API para aplicar cambios. El límite es una ventana fija compartida en Redis por IP de conexión y por correo normalizado; cuenta también accesos correctos y cambios de contraseña. Redis inaccesible bloquea nuevos logins con 503; las sesiones existentes siguen consultándose en PostgreSQL.

El contenedor API usa --no-proxy-headers: ignora X-Forwarded-For. Detrás de un proxy inverso el límite por IP será compartido por los clientes de ese proxy; se mantiene el límite por cuenta. Antes de exponerlo, configurar y probar una cadena de proxies de confianza que sobrescriba las cabeceras y conserve el rate limiting. No habilitar confianza indiscriminada en cabeceras del cliente. TLS obligatorio fuera del desarrollo local; CORS sigue cerrado y no se aceptan sesiones por cookie.

## Actualización a Fase 3

Respaldar datos y configuración. Ejecutar `python3 scripts/init-secrets.py` (Windows con Python: `py -3 scripts/init-secrets.py`; alternativa Docker en README). Añade MOODLE_TOKEN_KEYS a .env sólo si la variable no existe y no imprime su valor. Ejecutarlo nuevamente conserva la configuración. El helper de instalación Cloud ya invoca este paso. No compartir .env ni subirlo a Git. Después construir la imagen y arrancar Compose; migrate aplica 0003 y health exige `token_encryption: true` además de PostgreSQL y Redis.

La clave es un secreto local de cifrado, no un token para un proxy HTTPS. Para producción usar un gestor de secretos que inyecte el valor real en MOODLE_TOKEN_KEYS y adaptar el despliegue a ese mecanismo; no configurarlo como placeholder de un proxy. La aplicación acepta hasta cinco claves Fernet separadas por coma: la primera cifra, todas permiten descifrar.

Rotación: conservar respaldo seguro de la base y claves, generar una clave nueva mediante un mecanismo seguro, configurar `nueva,anterior` y recrear API/worker para cargar esa configuración. Ejecutar `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml exec api python -m app.cli rotate-moodle-tokens`. Sólo si termina correctamente, retirar la clave antigua y recrear los procesos. El comando recifra todos los tokens en una transacción y revierte todo si alguno no puede descifrarse. No imprime tokens ni claves. Asegurar que no haya otros escritores con configuración de claves anterior durante la rotación. Los respaldos antiguos todavía requieren sus claves antiguas; conservarlas en el almacén de respaldos según su retención.

Los tokens Moodle almacenados en backups sólo son recuperables conservando las claves correctas. La pérdida de todas las claves exige volver a introducir cada token; no hay una puerta de recuperación. El campo token_encryption de health valida el formato de las claves, no prueba que puedan descifrar todos los tokens existentes.

La salida a Moodle es directa, HTTPS/443, sin proxy heredado de variables ni redirecciones. Se requiere resolución DNS A/AAAA y ruta de red permitida hacia el Moodle público. La política de red de Codex puede necesitar el dominio del Moodle cuando se conozca. No se añaden destinos ficticios. Moodle privado/VPN requiere una futura política explícita de destinos autorizados; esta versión bloquea direcciones internas sin excepciones.

## Actualización a Fase 4 y operación de colas

Respaldar base y claves. Reconstruir e iniciar Compose; migrate aplica 0004 y 0005 de manera aditiva. Se conservan migraciones previas. Se añaden los servicios maintenance (worker de coordinación) y beat (planificador); worker consume sólo validation. Mantener exactamente un Beat para este despliegue. Escalar workers de validación es posible, pero los límites por Moodle siguen siendo conservadores y deben calibrarse en una instalación de ensayo.

`docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml up --build -d --wait --wait-timeout 120` espera salud y migración. En Cloud usar la compilación previa de scripts/cloud-install.py y --no-build. El arranque puede tardar hasta el primer ciclo de 15 segundos de Beat. /health/ready comprueba revisión 0006, Redis, cifrado y heartbeats de recuperación de validaciones y matrículas no mayores de 90 segundos. Ese heartbeat lo escribe una tarea real del worker de mantenimiento; no comprueba accesibilidad de cada Moodle. Consultar logs de worker, maintenance y beat si falta. No iniciar sólo API/worker omitiendo mantenimiento.

Variables: CSV_MAX_BYTES (1 KiB–50 MiB; predeterminado 10 MiB), CSV_MAX_ROWS (1–100000; predeterminado 50000), CSV_MAX_OPERATIONS (1–200000; predeterminado 100000 por importación y validación) y VALIDATION_MAX_PAGES (1–500; predeterminado 50 páginas de 100 participantes por curso). Reiniciar procesos tras cambiar valores. El parser también limita columnas, longitud de campos y celdas; ver csv-imports.md. No aumentar valores sin pruebas y recursos adecuados.

Los originales están en csv_contents, no en un directorio público ni un volumen adicional. pg_dump/pg_restore incluye originales, resultados y caché; mantener respaldos cifrados y claves antiguas de cifrado según retención. No hay purga automática de CSV: definir una política organizativa antes de producción. Limitar almacenamiento, frecuencia de cargas y tamaño del cuerpo también en el proxy de producción.

Si Redis deja de estar disponible después de crear una validación, PostgreSQL conserva queued. Mantenimiento la publica nuevamente cuando el broker se recupera. Cancelar por API deja historial; una llamada de lectura ya enviada puede terminar, pero un worker que perdió su lease no puede persistir resultados nuevos. failed conserva motivo y progreso previo; crear una nueva validación tras resolver el motivo. No manipular leases manualmente en producción. La suite usa bases/esquemas y Redis dedicados; nunca ejecutarla contra datos de la aplicación.

El heartbeat del coordinador no sustituye el health check individual del worker de validación; supervisar ambos.

## Actualización a Fase 5

Respaldar PostgreSQL y claves, reconstruir imagen e iniciar todos los servicios. migrate aplica 0006, con leases, fechas de ejecución/publicación, vínculo de registros con validación, reintentos y trazabilidad de reconciliación. No se borran registros ni se cambian resultados existentes. Los borradores anteriores resuelven su vínculo de validación al ejecutarse. enrollment-worker consume sólo la cola enrollment; maintenance atiende ambos coordinadores y un único Beat programa sus recuperaciones cada 15 segundos. Readiness exige revisión 0006 y dos heartbeats recientes.

Conservar ENROLLMENT_WRITES_ENABLED=false hasta disponer de autorización y Moodle de ensayo configurado. Habilitarla requiere recrear API y workers; la API exige start para cada trabajo y los operadores requieren concesiones al destino. Esta variable no sustituye los permisos/evidencias ni calibra la capacidad de Moodle. El despliegue de prueba en nube permanece con escrituras deshabilitadas.

Para varios trabajos autorizados: `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml up -d --scale enrollment-worker=2`, ajustando antes max_concurrency del destino tras ensayos. La concurrencia de cada trabajo es uno y el gate de solicitudes conserva su límite agregado. No usar PgBouncer en modo transaction para los workers de matrícula: los advisory locks de ejecución requieren afinidad de sesión; usar conexión directa a PostgreSQL o pooling de sesión.

## Interfaz y proxy — Fase 6

Compose añade web (Nginx sin privilegios, puerto local 8080), con assets compilados mediante npm ci. /api se reenvía al servicio api; las rutas profundas resuelven la SPA. En producción terminar TLS en un proxy, preservar Host y Origin y establecer SESSION_COOKIE_SECURE=true. No cambiar Origin para eludir CSRF. No publicar PostgreSQL ni Redis. Consultar frontend.md para desarrollo Windows y pruebas de navegador.
