# Instalación, operación y despliegue

Seguir README para Windows y Docker. Variables de Compose: POSTGRES_USER, POSTGRES_PASSWORD y POSTGRES_DB; backend recibe DATABASE_URL y REDIS_URL por red privada Docker. No publicar PostgreSQL ni Redis a Internet. Para contraseñas con caracteres reservados de URL configurar una URL correctamente codificada mediante una adaptación revisada del despliegue; el ejemplo local usa caracteres simples.

`/api/v1/health/live` indica que responde la API. `/api/v1/health/ready` comprueba PostgreSQL, revisión Alembic 0001 y Redis, devolviendo 503 al fallar. No representa disponibilidad de Moodle ni del worker. Verificar el worker mediante `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml exec worker celery -A app.workers.celery_app:celery_app inspect ping`. No existen tareas de matrícula en fase 1.

## Copias de seguridad

Antes de migrar: `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml exec -T db pg_dump -U enrollment -d enrollment -Fc > backup.dump`. En Windows usar una terminal que preserve salida binaria o generar primero el archivo dentro del contenedor y copiarlo con docker cp. Guardar cifrado fuera del servidor, con acceso restringido. Probar restauraciones en base separada mediante pg_restore; no restaurar sobre producción sin plan de recuperación. Los volúmenes persisten al reiniciar.

## Diagnóstico

Consultar `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml logs api migrate worker`. Ante 503 revisar salud de db/redis y migración. Si falla una migración detener el despliegue e investigar; no borrar volúmenes como solución. Al cambiar contraseña de un PostgreSQL ya inicializado, cambiar también el rol en la base: las variables de la imagen no rotan la contraseña existente.

## Producción pendiente

La fase 1 no es desplegable públicamente: faltan autenticación, cifrado de tokens, autorización, limitación de solicitudes, retención, frontend y motor de matrícula. Antes de producción añadir TLS con proxy inverso, secretos gestionados, backups verificados, política de logs y pruebas contra Moodle de ensayo. No introducir tokens reales en esta fase.

## Codex Cloud

Usar el checkout existente, sin crear worktrees. La compilación puede necesitar el proxy inyectado y su CA: `DOCKER_CONFIG=/workspace/.docker-build python3 scripts/cloud-install.py`. El helper resuelve el hostname del proxy y monta la CA sólo durante la compilación mediante BuildKit; no desactiva TLS ni copia secretos a las capas. Después ejecutar Compose con `up --no-build -d --wait --wait-timeout 120`. No se presupone que los procesos sobrevivan a una nueva tarea.

El script crea infrastructure/.env sólo si no existe, con contraseña aleatoria local. No cambia contraseñas de volúmenes PostgreSQL existentes. `.venv`, cachés y archivos .env son salidas locales ignoradas y no se suben al repositorio.
