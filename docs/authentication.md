# Autenticación, usuarios y API — Fase 2

## Uso inicial

Crear el primer administrador desde una terminal de confianza con el comando del README. La contraseña tiene entre 12 y 128 caracteres. El comando pide confirmación sin mostrarla; no acepta la contraseña por argumentos, variables de entorno ni chat. Si ya hay administrador activo, usar la API autenticada para crear otros administradores. Si se pierden todas las credenciales se requiere un procedimiento de recuperación operativo sobre la base de datos, con respaldo y auditoría; no hay un endpoint público de recuperación.

POST `/api/v1/auth/login` recibe JSON con `email` y `password`. Devuelve `access_token`, `token_type=bearer` y `expires_at`. Enviar el token como cabecera `Authorization: Bearer <token>`; nunca como parámetro de URL. Swagger admite Authorize con ese token. No copiar tokens a logs, tickets ni documentación. Todas las respuestas incluyen Cache-Control: no-store. Correo se normaliza a minúsculas.

Las sesiones caducan a las 8 horas por defecto, sin renovación automática ni refresh token. GET `/api/v1/auth/me` devuelve identidad, roles y permisos actuales. POST `/api/v1/auth/logout` revoca la sesión; POST `/api/v1/auth/logout-all` revoca todas las del usuario. POST `/api/v1/auth/change-password` recibe current_password y new_password, verifica la actual y revoca todas las sesiones, incluida la usada para cambiarla: es necesario volver a entrar. Desactivar una cuenta o cambiar roles también revoca sesiones. No se pueden deshacer operaciones ya autorizadas y en curso sólo revocando un token.

## Roles y autorización

| Rol | Acceso implementado | Permisos reservados para fases futuras |
|---|---|---|
| administrador | Usuarios, roles, auditoría y sesión propia | Conexiones, importaciones, trabajos y reportes |
| operador | Sesión propia | Importaciones, trabajos y reportes |
| supervisor | Sesión propia y auditoría | Lectura de trabajos y reportes |
| consulta | Sesión propia | Lectura de trabajos |

Los roles son fijos en esta fase, se pueden asignar varios y sus permisos se suman. No hay editor de permisos arbitrarios. Los futuros recursos también deberán aplicar estos permisos y las reglas de alcance por trabajo/conexión que se definan; los nombres de permiso no implementan por sí solos esas reglas.

## Endpoints administrativos

Todos requieren administrador y comprueban el permiso en el servidor:

- GET /api/v1/roles: roles y permisos.
- GET /api/v1/users: listado con offset, limit (1–100), search por correo y active.
- POST /api/v1/users: email, password, roles; devuelve 201. Contraseñas nunca se devuelven.
- GET /api/v1/users/{id}: detalle.
- PATCH /api/v1/users/{id}: active y/o roles. No admite null ni lista vacía de roles.
- POST /api/v1/users/{id}/reset-password: new_password; revoca sesiones. Comunicar la contraseña temporal por un canal seguro externo; no se envían correos desde la aplicación.

No se elimina físicamente un usuario: se desactiva para preservar referencias e historial. No se puede desactivar o quitar el rol al último administrador activo. Correo ya registrado devuelve 409. Los cambios y su evento se confirman en la misma transacción. UUID inexistente devuelve 404; falta de sesión, 401; falta de permiso, 403; validación, 422. Las respuestas de validación omiten los valores enviados para no reflejar contraseñas. La disponibilidad de base de datos devuelve errores genéricos 503.

## Auditoría

GET `/api/v1/audit-logs` permite administrador o supervisor. Filtros: action, actor_id, since, until, offset y limit. Fechas ISO8601 con zona horaria, almacenadas en UTC. Orden descendente por creación e ID. Registra bootstrap, login correcto/fallido/bloqueado, logout, revocación, cambios de contraseña, creación/actualización de usuarios, permisos denegados y limpieza de sesiones. No contiene contraseñas, tokens ni cuerpos de solicitudes. Los fallos de autenticación anónimos no identifican un actor confirmado. La auditoría no es un almacén inmutable frente a administradores de la base; para ello se requiere archivado externo y permisos de infraestructura.

## Seguridad del cliente

La interfaz usa una cookie HttpOnly SameSite=Strict, limitada a /api/v1. El login con X-Session-Mode: cookie devuelve authenticated y expires_at, nunca el token. Las mutaciones con cookie requieren Origin igual a Host y X-CSRF-Protection: 1; también el login en modo cookie. Bearer sigue disponible para clientes API. No hay tokens en localStorage ni sessionStorage. SESSION_COOKIE_SECURE debe ser true bajo HTTPS en producción. No hay MFA ni recuperación por correo todavía.

## Alcances añadidos en Fase 4

Administrador y operador tienen imports:read/imports:write. El operador gestiona sólo sus archivos, perfiles e importaciones. Para crear validaciones necesita concesión explícita de la conexión; administrador no necesita concesión adicional. GET /validations/connections devuelve opciones sin token. Supervisor/consulta pueden leer validaciones sólo en conexiones concedidas, sin acceder al archivo original. Los cambios de acceso se auditan y el worker los comprueba mientras procesa. jobs:write autoriza crear/iniciar/controlar trabajos propios o administrados; el motor añade comprobación de concesión y configuración vigente. Supervisor/consulta sólo leen trabajos de destinos concedidos.
