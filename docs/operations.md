# Operación, respaldo y recuperación — Fase 8

## Despliegue endurecido

Construir primero las imágenes. En PowerShell, Linux o macOS, desde la raíz:

```powershell
docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml -f infrastructure/compose.production.yaml up --build -d --wait --wait-timeout 120
```

El overlay activa reinicio de servicios, filesystem de sólo lectura y /tmp temporal para web/API/workers/Beat, eliminación de capabilities, no-new-privileges, límites de procesos/CPU/memoria y rotación de logs. PostgreSQL/Redis conservan volúmenes y permisos de inicialización. Los límites son presupuestos iniciales, no capacidad garantizada; revisar memoria y CPU de la máquina y calibrar antes de operar. El rol inicial de PostgreSQL del Compose es administrativo; el overlay no cambia roles de base. Para producción separar credenciales de migración y aplicación con privilegios mínimos mediante una configuración de DATABASE_URL revisada, sin reutilizar el superusuario para runtime. Mantener un único Beat. La migración sigue siendo un proceso previo de una sola ejecución.

SESSION_COOKIE_SECURE=true en la API del overlay requiere HTTPS. No utilizar este modo como interfaz HTTP pública. Los puertos publicados siguen ligados a loopback; un gateway TLS debe atender el nombre real. infrastructure/nginx-tls.conf.example documenta el gateway de host: sustituir hostname y rutas de certificado por valores reales, verificar nginx -t, instalar certificados de una CA apropiada y configurar DNS. El gateway debe preservar Host y Origin. La plantilla sobrescribe X-Forwarded-For; la API sigue ignorándolo de manera deliberada y limita además por cuenta. Su límite por IP de conexión se comparte entre clientes del proxy; el gateway aplica su propio límite de login por IP. Si existe otro proxy delante, configurar explícitamente sus redes de confianza para real_ip; nunca confiar en cabeceras arbitrarias del cliente.

HSTS sólo corresponde al gateway HTTPS. La prueba local utiliza un certificado efímero de pruebas, confiado explícitamente y con hostname verificado; no representa un certificado público ni una instalación HTTPS real. El backend y los workers continúan sin poder usar HTTP, IPs internas ni saltar TLS para Moodle.

Para volver al modo de desarrollo HTTP local, recrear sólo con compose.yaml y la configuración local SESSION_COOKIE_SECURE=false. Esta reversión no borra volúmenes. No mantener un overlay productivo con cookies inseguras para eludir problemas de configuración TLS.

## Copias binarias portables

Con Python 3.12 instalado, elegir un directorio protegido **fuera** del checkout. Ejemplo Windows:

```powershell
py -3 scripts/backup.py C:\RespaldosProtegidos\matriculas-20261021.dump
py -3 scripts/restore-check.py C:\RespaldosProtegidos\matriculas-20261021.dump
```

En Linux usar python3 y una ruta fuera del repositorio. El directorio debe existir. backup.py usa pg_dump custom directamente sobre un archivo binario, evita la corrupción por redirección de PowerShell, crea con permisos privados donde el sistema los aplica, sincroniza archivo y manifiesto SHA-256, y rechaza sobrescritura o destinos dentro del proyecto. --env-file y --compose-file permiten otro despliegue revisado; por defecto utiliza infrastructure/.env y compose.yaml. Sólo lee PostgreSQL; no detiene trabajos.

**El archivo no se cifra automáticamente.** Cifrar y copiar fuera del servidor mediante el mecanismo organizativo de respaldos; aplicar ACL de Windows o permisos Unix y controlar acceso al directorio. Respaldar MOODLE_TOKEN_KEYS y claves antiguas por un canal seguro separado. No poner claves, tokens ni contraseñas en argumentos, Git o chat. SHA-256 detecta corrupción accidental; un manifiesto junto al archivo no prueba autenticidad frente a un atacante que pueda modificar ambos. Mantener copias inmutables/autenticadas y retención definida.

restore-check.py verifica SHA-256 y restaura un archivo **confiable** en un contenedor PostgreSQL 16 nuevo, sin red ni puertos ni workers. PostgreSQL tiene autenticación local trust exclusivamente en ese contenedor aislado; no reutilizar esta configuración en la aplicación. No monta el directorio del respaldo dentro del contenedor: envía sus bytes por stdin. Exige revisión 0006, comprueba tablas y cantidades, y elimina contenedor y volumen anónimo al terminar. No restaura sobre ninguna base existente, no cifra el respaldo y no valida las claves ni credenciales Moodle.

El resultado comprueba restaurabilidad del esquema y datos seleccionados, no RPO/RTO ni toda la semántica de la aplicación. Programar ensayos con copias representativas, comprobar originales CSV, descifrado de tokens con claves recuperadas y acceso de usuarios en una red de recuperación restringida, con escrituras Moodle deshabilitadas. Un dump malicioso puede ejecutar SQL: usar sólo archivos de procedencia confiable.

## Recuperación de incidente

1. Deshabilitar escrituras y detener despachos hacia Moodle; una solicitud enviada no puede deshacerse. Conservar evidencias y no modificar leases manualmente.
2. Diagnosticar PostgreSQL, Redis, workers y ambos heartbeats de recuperación. Redis no conserva la única copia de progreso. Recuperar el broker y dejar que Beat/mantenimiento republiquen estados persistidos; no generar múltiples Beat.
3. Si es necesaria restauración real, preparar una base nueva, PostgreSQL compatible, respaldo y claves recuperadas. Detener API/workers/Beat del destino antes de restaurar para impedir actividad con datos viejos; no usar down -v.
4. Validar la copia con restore-check, restaurar mediante procedimiento aprobado en la base nueva, aplicar migraciones compatibles y cambiar DATABASE_URL de forma segura. Conservar la base anterior hasta terminar las comprobaciones. No automatizamos una sustitución destructiva.
5. Antes de reactivar trabajadores después de restaurar un snapshot antiguo, reconciliar con Moodle de ensayo/producción autorizado los envíos que pudieran haberse realizado después del respaldo. El estado restaurado puede preceder una matrícula remota confirmada; no asumir idempotencia entre instantáneas por el mero éxito de pg_restore.
6. Comprobar salud, concesiones, evidencias y resultados inciertos. Reanudar gradualmente con autorización y límites calibrados; conservar auditoría del incidente.

## Retención y almacenamiento

`python -m app.cli purge-transient-data --days 30` sólo simula cantidades. Añadir --execute aplica en una transacción la eliminación de sesiones caducadas y cachés de validaciones terminales con finished_at anterior al período elegido (7–3650 días). Conserva caché de trabajos en curso o sin finalización, sesiones vigentes, usuarios, archivos originales, validaciones, matrículas, intentos y auditoría. La operación ejecutada se audita con cantidades, sin contenidos.

Desde Compose ejecutar con `exec api python -m app.cli ...`. No hay cron de eliminación habilitado por defecto. Antes de programarlo, definir retención y frecuencia con el responsable. La eliminación de originales/historial por obligaciones legales requiere una política organizativa y proceso específico; no existe una purga global automática de esos datos. Esto preserva el historial permanente solicitado, pero no sustituye una política legal completa. Supervisar tamaño de PostgreSQL, archivos, auditoría y copias; conservar y verificar respaldos según esa política.

## Supervisión

Vigilar /api/v1/health/ready y healthchecks de cada worker; heartbeat reciente no significa Moodle disponible ni progreso de un trabajo concreto. Supervisar latencia real de Moodle, 429/5xx, circuitos, uncertain, colas, leases vencidos, disco y memoria de los procesos. No inventar CPU/memoria de Moodle: obtenerlos sólo de una fuente autorizada si existe. No registrar cuerpos HTTP, secretos ni CSV; no activar logs DEBUG de clientes HTTP. Rotación de logs Docker no archiva automáticamente la auditoría de PostgreSQL.
