# Seguridad

Implementado: Argon2id con sal aleatoria, parámetros explícitos y rehash al entrar; contraseñas de 12–128 caracteres; tokens de sesión aleatorios de 256 bits guardados sólo como SHA-256; caducidad absoluta y revocación en PostgreSQL; RBAC en servidor; bloqueo transaccional para último administrador y coordinación de cambios de credenciales; auditoría sin cuerpos ni secretos; validación de entrada sin reflejar valores sensibles; respuestas no-store y nosniff. No hay cuenta ni contraseña predeterminada.

Login limita por IP de conexión y cuenta en Redis mediante contador y TTL atómicos. Devuelve 429 con Retry-After, o 503 si el limitador no funciona. Errores de contraseña, usuario ausente y cuenta inactiva comparten mensaje. El hash ficticio para cuentas inexistentes reduce diferencias temporales, sin prometer tiempo constante de todo el endpoint. Los intentos fallidos también quedan auditados. El cambio de contraseña requiere contraseña actual y usa los mismos límites. La confianza en proxy headers está deshabilitada por defecto.

La interfaz usa cookie HttpOnly/SameSite con protección CSRF; CORS no está abierto. Usar TLS ante acceso remoto y limitar permisos del operador de infraestructura. No poner Bearer en URL ni logs. El contenedor backend ejecuta como usuario sin privilegios. PostgreSQL y Redis sólo se exponen por red interna Compose. Las pruebas de integración usan servicios separados y una base cuyo nombre termina en _test; no usar el broker real para ellas.

Implementado en Fase 3: cifrado autenticado de tokens Moodle, rotación y protección SSRF descritos a continuación. Los permisos de trabajos, frontend y motor se implementaron en fases posteriores. La revisión local y sus límites están en security-review.md; retención de transitorios y operación en operations.md. La política organizativa de datos, aceptación real y revisión productiva siguen pendientes. El campo token_ciphertext sólo recibe valores cifrados desde la API. La auditoría se conserva sin borrado por API; purgar sesiones caducadas no elimina historial. No hay MFA ni flujo de recuperación por correo. Esta fase no debe exponerse como producto terminado.

## Seguridad de conexiones Moodle

Sólo administrador tiene connections:manage. El token se recibe como SecretStr, se cifra con Fernet y no vuelve al cliente (sólo token_configured). Ni claves, ni cuerpos remotos, ni mensajes Moodle sin filtrar se guardan en auditoría. No se exponen nombres de usuario remoto ni URLs de avatar. Si Moodle refleja el token en los metadatos que se iban a exponer, la respuesta se rechaza. Cambiar el destino exige proporcionar token nuevo para evitar reenviar una credencial existente a otro sitio por accidente. Desactivar conserva registros históricos y bloquea comprobaciones posteriores.

SSRF: HTTPS exclusivo, DNS válido, puerto 443, rutas base simples, sin credenciales/query/fragment. IPs literales rechazadas. A/AAAA deben ser exclusivamente públicos; se bloquean privados, loopback, link-local, metadata, reservados, multicast e IPv6 de transición. DNS acotado y IP fijada en el transporte, manteniendo verificación TLS de hostname/SNI. Redirecciones y proxies ambientales deshabilitados. No se permite un flag para saltar la validación. El filtro reduce riesgos de aplicación y debe complementarse con controles de salida de red.

Respuesta de Moodle limitada a 1 MiB, sin contenido comprimido inesperado, con esquema validado y errores clasificados. No se reintenta automáticamente. Las comprobaciones tienen exclusión/cooldown persistido por conexión y deadline de lectura comprobado entre chunks, además del timeout de conexión/lectura HTTPX; DNS y espera de un chunk pueden extender la duración total hasta sus límites respectivos. requests_per_minute y min_probe_interval_seconds limitan estas comprobaciones. El control de carga del motor de Fase 5 se describe más abajo; la configuración no garantiza capacidad de Moodle.

La clave se almacena localmente en .env ignorado y protegido; en producción se requiere gestión externa de secretos y respaldo de claves. La protección no impide a un administrador de infraestructura con acceso al proceso obtener claves. Los logs HTTPX/httpcore se restringen a WARNING; no habilitar dumps de cuerpos ni logs de entorno en producción.

## CSV y alcance de acceso — Fase 4

Administrador puede revisar todo; operador sólo sus archivos/perfiles/importaciones y validaciones propias en conexiones concedidas. Supervisor/consulta pueden leer validaciones de una conexión únicamente si el administrador les concede ese alcance; no acceden a originales CSV. Los permisos se suman: un operador con un rol explícito adicional de lectura puede obtener ese alcance según la concesión. Las concesiones no muestran tokens. Revocar acceso o desactivar un usuario impide continuar nuevas comprobaciones del proceso.

Se limita el stream recibido, se exige extensión CSV y tipo de contenido, se valida codificación/estructura, se rechazan controles binarios y encabezados ambiguos. No se usan nombres de archivo como rutas. Descarga de originales sólo por propietario/administrador, attachment y nosniff. Los originales pueden contener fórmulas suministradas por el usuario; abrirlos en una hoja de cálculo requiere revisión segura. La exportación de Fase 7 protege prefijos de fórmulas; ver reports.md. React muestra valores como texto escapado.

Los datos personales necesarios se guardan en PostgreSQL bajo autorización, sin cuerpos CSV en auditoría/logs. La caché remota conserva sólo IDs y campos mínimos para resolver las consultas; elimina claves de matrícula de grupos y otros datos no utilizados. Rechaza reflejos del token antes de guardar la caché. El worker redacta excepciones inesperadas y registra internal_error; no publica parámetros de base de datos a Celery.

La revisión de rol y visibilidad es una declaración administrativa trazable, no una respuesta API inventada. Requiere referencia, caducidad hasta siete días y versión de conexión vigente. Debe confirmar asignabilidad del rol por el usuario técnico y acceso a todos los participantes del curso, incluidos grupos separados y restricciones por contexto. full_enrollment_visibility es false por defecto: no basta una lista vacía para marcar ausencia. groups_authorized confirma por separado permisos de gestionar grupos. Cambios de Moodle no sincronizados pueden invalidar cualquier snapshot; el motor de Fase 5 revalida antes de escribir.

## Ejecución — Fase 5

ENROLLMENT_WRITES_ENABLED=false bloquea inicio/reanudación por defecto. Sólo operadores/administrador con jobs:write pueden iniciar trabajos propios o administrados, con usuario activo, acceso concedido y versión vigente de conexión. Supervisor/consulta pueden leer procesos de destinos concedidos sin mutarlos. Los guards repiten autorización y versión antes de llamadas; los permisos pueden cambiar después de enviar una solicitud, que no se puede deshacer.

Se vuelve a comprobar evidencia vigente de rol y visibilidad antes de escribir. HTTP 200/null no se considera una confirmación individual. Intención y resultado incierto se guardan antes del envío, sin token/parámetros sensibles. El cliente de escritura sólo admite las dos funciones oficiales revisadas. No hay reintentos de escrituras ambiguas; otros trabajos sobre el mismo usuario/curso se bloquean hasta reconciliar la incertidumbre. Los reintentos explícitos conservan trazabilidad y errores previos.

El límite de solicitudes y circuito se comparten por URL canónica entre probes, validación y matrícula. Locks de sesión requieren PostgreSQL directo o pool de sesión. No debe usarse un pool transaccional que reasigne conexiones mientras el worker mantiene advisory locks. Mantener servicios internos fuera de Internet, backups y claves recuperables. La aceptación real y calibración previa a producción siguen pendientes.

## Navegador — Fase 6

Cookie HttpOnly/SameSite Strict y CSRF por cabecera más comprobación estricta Origin/Host; Bearer conserva compatibilidad. Activar SESSION_COOKIE_SECURE con HTTPS. Nginx aplica CSP, nosniff, no-referrer, DENY y no-store fuera de assets versionados. Fuentes locales, sin CDN. Los permisos se comprueban en servidor aunque se oculten acciones visuales. Reportes aplica autorización del servidor y exporta datos con protección de fórmulas y límites explícitos; ver reports.md.

## Revisión local — Fase 8

cryptography actualizado a 50.0.2 tras avisos de seguridad; auditorías y alcance en security-review.md. Overlay endurecido y respaldo/restauración aislada en operations.md. No declarar aceptación productiva a partir de estas pruebas; seguir acceptance.md.
