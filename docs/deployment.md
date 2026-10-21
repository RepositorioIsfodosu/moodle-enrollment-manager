# Instalación, operación y despliegue

Seguir README para Windows y Docker. Variables de Compose: POSTGRES_USER, POSTGRES_PASSWORD y POSTGRES_DB; backend recibe DATABASE_URL y REDIS_URL por red privada Docker. No publicar PostgreSQL ni Redis a Internet. Para contraseñas con caracteres reservados de URL configurar una URL correctamente codificada mediante una adaptación revisada del despliegue; el ejemplo local usa caracteres simples.

`/api/v1/health/live` indica que responde la API. `/api/v1/health/ready` comprueba PostgreSQL, revisión Alembic 0003 y Redis, devolviendo 503 al fallar. No representa disponibilidad de Moodle ni del worker. Verificar el worker mediante `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml exec worker celery -A app.workers.celery_app:celery_app inspect ping`. No existen tareas de matrícula en fase 3.

## Copias de seguridad

Antes de migrar: `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml exec -T db pg_dump -U enrollment -d enrollment -Fc > backup.dump`. En Windows usar una terminal que preserve salida binaria o generar primero el archivo dentro del contenedor y copiarlo con docker cp. Guardar cifrado fuera del servidor, con acceso restringido. Probar restauraciones en base separada mediante pg_restore; no restaurar sobre producción sin plan de recuperación. Los volúmenes persisten al reiniciar.

## Diagnóstico

Consultar `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml logs api migrate worker`. Ante 503 revisar salud de db/redis y migración. Si falla una migración detener el despliegue e investigar; no borrar volúmenes como solución. Al cambiar contraseña de un PostgreSQL ya inicializado, cambiar también el rol en la base: las variables de la imagen no rotan la contraseña existente.

## Producción pendiente

La fase 3 todavía no es una entrega productiva: faltan importaciones, retención completa, frontend y motor de matrícula. La gestión de conexiones y el cifrado de tokens Moodle ya están implementados. Autenticación y RBAC de la API ya están implementados. Antes de producción añadir TLS con proxy inverso, secretos gestionados, backups verificados, política de logs y pruebas contra Moodle de ensayo. No introducir tokens reales en esta fase.

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
