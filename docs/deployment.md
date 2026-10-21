# Instalación, operación y despliegue

Seguir README para Windows y Docker. Variables de Compose: POSTGRES_USER, POSTGRES_PASSWORD y POSTGRES_DB; backend recibe DATABASE_URL y REDIS_URL por red privada Docker. No publicar PostgreSQL ni Redis a Internet. Para contraseñas con caracteres reservados de URL configurar una URL correctamente codificada mediante una adaptación revisada del despliegue; el ejemplo local usa caracteres simples.

`/api/v1/health/live` indica que responde la API. `/api/v1/health/ready` comprueba PostgreSQL, revisión Alembic 0002 y Redis, devolviendo 503 al fallar. No representa disponibilidad de Moodle ni del worker. Verificar el worker mediante `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml exec worker celery -A app.workers.celery_app:celery_app inspect ping`. No existen tareas de matrícula en fase 2.

## Copias de seguridad

Antes de migrar: `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml exec -T db pg_dump -U enrollment -d enrollment -Fc > backup.dump`. En Windows usar una terminal que preserve salida binaria o generar primero el archivo dentro del contenedor y copiarlo con docker cp. Guardar cifrado fuera del servidor, con acceso restringido. Probar restauraciones en base separada mediante pg_restore; no restaurar sobre producción sin plan de recuperación. Los volúmenes persisten al reiniciar.

## Diagnóstico

Consultar `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml logs api migrate worker`. Ante 503 revisar salud de db/redis y migración. Si falla una migración detener el despliegue e investigar; no borrar volúmenes como solución. Al cambiar contraseña de un PostgreSQL ya inicializado, cambiar también el rol en la base: las variables de la imagen no rotan la contraseña existente.

## Producción pendiente

La fase 2 todavía no es una entrega productiva: faltan integración Moodle, cifrado de tokens Moodle, retención completa, frontend y motor de matrícula. Autenticación y RBAC de la API ya están implementados. Antes de producción añadir TLS con proxy inverso, secretos gestionados, backups verificados, política de logs y pruebas contra Moodle de ensayo. No introducir tokens reales en esta fase.

## Codex Cloud

Usar el checkout existente, sin crear worktrees. La compilación puede necesitar el proxy inyectado y su CA: `DOCKER_CONFIG=/workspace/.docker-build python3 scripts/cloud-install.py`. El helper resuelve el hostname del proxy y monta la CA sólo durante la compilación mediante BuildKit; no desactiva TLS ni copia secretos a las capas. Después ejecutar Compose con `up --no-build -d --wait --wait-timeout 120`. No se presupone que los procesos sobrevivan a una nueva tarea.

El script crea infrastructure/.env sólo si no existe, con contraseña aleatoria local. No cambia contraseñas de volúmenes PostgreSQL existentes. `.venv`, cachés y archivos .env son salidas locales ignoradas y no se suben al repositorio.

## Actualización de Fase 1 a Fase 2

Respaldar la base, actualizar el checkout e imagen, y ejecutar Compose. El servicio migrate aplica 0002 antes de arrancar API/worker. La revisión normaliza los correos a minúsculas; si detecta colisiones aborta para que un administrador resuelva los datos, sin fusionar cuentas. Añade auth_sessions y los cuatro roles, sin crear usuarios. Repetir upgrade es seguro. No ejecutar pruebas automatizadas contra la base de la aplicación.

Crear el primer administrador con el comando interactivo del README. Para purgar sesiones caducadas: `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml exec api python -m app.cli purge-sessions`. No borra auditoría. Hacerlo periódicamente desde el planificador operativo; no hay servicio de limpieza automática aún.

Configurar en infrastructure/.env SESSION_TTL_SECONDS (300–86400, predeterminado 28800), LOGIN_IP_LIMIT (1–1000, predeterminado 30), LOGIN_ACCOUNT_LIMIT (1–100, predeterminado 10) y LOGIN_WINDOW_SECONDS (10–3600, predeterminado 300). Reiniciar API para aplicar cambios. El límite es una ventana fija compartida en Redis por IP de conexión y por correo normalizado; cuenta también accesos correctos y cambios de contraseña. Redis inaccesible bloquea nuevos logins con 503; las sesiones existentes siguen consultándose en PostgreSQL.

El contenedor API usa --no-proxy-headers: ignora X-Forwarded-For. Detrás de un proxy inverso el límite por IP será compartido por los clientes de ese proxy; se mantiene el límite por cuenta. Antes de exponerlo, configurar y probar una cadena de proxies de confianza que sobrescriba las cabeceras y conserve el rate limiting. No habilitar confianza indiscriminada en cabeceras del cliente. TLS obligatorio fuera del desarrollo local; CORS sigue cerrado y no se aceptan sesiones por cookie.
