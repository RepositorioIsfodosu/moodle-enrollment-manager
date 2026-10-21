# Configuración e integración Moodle — Fase 3

## Fuentes oficiales verificadas

Se consultó el código oficial de Moodle 4.5, rama MOODLE_405_STABLE, referencia observada `cae172ee4aeec1d7a6eaba7bb5ae12a5f0fe3772`:

- [webservice/externallib.php](https://github.com/moodle/moodle/blob/cae172ee4aeec1d7a6eaba7bb5ae12a5f0fe3772/webservice/externallib.php): get_site_info_parameters y get_site_info_returns; functions, release y version.
- [webservice/rest/locallib.php](https://github.com/moodle/moodle/blob/cae172ee4aeec1d7a6eaba7bb5ae12a5f0fe3772/webservice/rest/locallib.php): wstoken, wsfunction, moodlewsrestformat y serialización de respuestas/errores JSON.
- [user/externallib.php](https://github.com/moodle/moodle/blob/cae172ee4aeec1d7a6eaba7bb5ae12a5f0fe3772/user/externallib.php): definiciones de get_users y get_users_by_field.
- [course/externallib.php](https://github.com/moodle/moodle/blob/cae172ee4aeec1d7a6eaba7bb5ae12a5f0fe3772/course/externallib.php): get_courses.
- [enrol/externallib.php](https://github.com/moodle/moodle/blob/cae172ee4aeec1d7a6eaba7bb5ae12a5f0fe3772/enrol/externallib.php): get_enrolled_users.
- [enrol/manual/externallib.php](https://github.com/moodle/moodle/blob/cae172ee4aeec1d7a6eaba7bb5ae12a5f0fe3772/enrol/manual/externallib.php): enrol_users, estructura enrolments y retorno null.

Esto verifica el contrato implementado de get_site_info y la existencia de las otras funciones evaluadas; no garantiza compatibilidad universal. La documentación de servicios web generada por cada instalación es la autoridad para las funciones y parámetros habilitados en ella. Los métodos de consulta y matrícula restantes se implementarán y probarán en fases posteriores.

## Preparación en Moodle

En una instalación de pruebas administrada y autorizada: habilitar servicios web y protocolo REST; crear un usuario técnico de mínimo privilegio y un servicio externo personalizado habilitado que permita ese usuario. Añadir core_webservice_get_site_info. Crear un token asociado al usuario/servicio, con expiración y restricciones adecuadas. No usar la cuenta administradora para procesamiento habitual. Los nombres/rutas de menús varían según versión; consultar Administración del sitio > Servidor > Servicios web y la documentación local de API.

La prueba de conexión sólo necesita get_site_info. Las futuras consultas/matrículas requerirán funciones y capacidades adicionales, asignación del usuario técnico a los contextos apropiados y matriculación manual habilitada en los cursos. No habilitar todas las funciones por comodidad. Verificar permisos en Moodle de ensayo antes de configurar producción.

## Contrato HTTP utilizado

POST `<base_url>/webservice/rest/server.php`, application/x-www-form-urlencoded:

- wstoken: token del servicio (sólo en el cuerpo, nunca en URL).
- wsfunction: core_webservice_get_site_info.
- moodlewsrestformat: json.

No se envía serviceshortnames: el código oficial define un valor predeterminado vacío y lo marca obsoleto. La respuesta incluye sitename, siteurl y functions con name/version. release y version son opcionales. Sólo se guardan nombre del sitio, release/version si existen, nombres de funciones y latencia. No se persisten username, fullname, userid, avatar ni toda la respuesta. El siteurl debe coincidir con la base canónica configurada; no se sigue automáticamente otra URL.

Se comparan las funciones anunciadas con core_webservice_get_site_info, core_user_get_users, core_user_get_users_by_field, core_course_get_courses, core_enrol_get_enrolled_users y enrol_manual_enrol_users. Son funciones evaluadas, no un requisito conjunto para esta prueba de lectura. Si falta alguna el estado es limited; si están todas, verified. Ninguno de esos estados confirma permisos de matrícula por curso ni disponibilidad de roles/grupos. No se hacen llamadas a las otras funciones en esta fase.

**Dato crítico para Fase 5:** enrol_manual_enrol_users recibe una colección enrolments (roleid, userid, courseid y otros parámetros definidos en su contrato) pero su retorno declarado es null. No ofrece una lista de éxitos por operación. Un HTTP 200 o null no se tratará como confirmación individual; el motor deberá reconciliar y tratar resultados ambiguos. No se implementa matrícula todavía.

## API administrativa de la aplicación

Todos estos endpoints requieren administrador:

- POST /api/v1/moodle-connections: name, base_url, token, description y limits.
- GET /api/v1/moodle-connections: offset/limit y active.
- GET /api/v1/moodle-connections/{id}: detalle seguro, sin token ni ciphertext.
- PATCH /api/v1/moodle-connections/{id}: editar campos o desactivar con active=false. Cambiar base_url requiere token nuevo. No se eliminan datos históricos.
- POST /api/v1/moodle-connections/{id}/test: comprobación de lectura y resultado persistido.
- GET /api/v1/moodle-connections/{id}/checks: historial paginado.

base_url sólo admite HTTPS, dominio DNS público, puerto 443 y ruta sencilla de instalación, por ejemplo /campus; no admitir el endpoint REST completo como base. service_url se deriva y no se configura arbitrariamente. Tokens y claves nunca se devuelven. La URL se valida sintácticamente al guardar y se resuelve/valida de nuevo antes de cada solicitud.

limits contiene timeout_seconds (3–60, predeterminado 15), min_probe_interval_seconds (5–3600, predeterminado 30), requests_per_minute (1–120, predeterminado 10) y max_concurrency (fijado en 1 en esta fase). El intervalo real es el mayor de min_probe_interval_seconds y ceil(60/requests_per_minute). No son garantías de capacidad para matrículas.

/test devuelve 200 si terminó y registró una comprobación, incluso cuando status=error. Revisar last_error_code: unsafe_destination, invalid_token, insufficient_permissions, function_unavailable, remote_rate_limited, timeout, http_error, transport_error, invalid_response, response_too_large, redirect_not_allowed, sensitive_response o site_url_mismatch. Otros errores Moodle se clasifican moodle_error sin repetir el mensaje remoto. 429 y Retry-After indican cooldown/comprobación en curso; 409 indica desactivación o edición durante la prueba; 503 indica cifrado/datos no disponibles. Una edición durante la llamada descarta el resultado antiguo y se audita.

## Validación y limitaciones

Se prueban contratos y errores con un simulador HTTPX y un servidor HTTPS local con CA efímera. No se configura ese simulador como conexión de la aplicación ni se usa fuera de pruebas. No se han proporcionado URL/token de un Moodle real; no se afirma compatibilidad validada con una instalación concreta ni se realizaron matrículas. Para esa validación, el administrador debe introducir el token por la API segura sobre HTTPS y ejecutar /test en el Moodle de ensayo. No pegar tokens en chat.
