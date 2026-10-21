# Manual del administrador — Fase 3

1. Iniciar servicios y verificar health según README.
2. Crear el primer administrador desde terminal interactiva; no hay credenciales predeterminadas.
3. Iniciar sesión por API/Swagger y configurar el Bearer en Authorize.
4. Crear usuarios con roles apropiados. Asignar administrador sólo cuando se necesite gestionar cuentas; supervisor puede consultar auditoría.
5. Consultar usuarios con paginación y filtros; desactivar para retirar acceso sin perder referencias.
6. Consultar eventos en /api/v1/audit-logs. Revisar fallos repetidos de autenticación y denegaciones.
7. Cerrar sesión al terminar; usar logout-all si se sospecha exposición de un token. Un cambio de contraseña también cierra todas las sesiones.

Los detalles de endpoints y permisos están en authentication.md. Ya se pueden configurar y probar conexiones Moodle por API. No hay todavía interfaz gráfica ni importaciones; usar un Moodle de pruebas y un token de mínimo privilegio. Para Windows, respaldo, diagnóstico y actualización consultar README y deployment.md.

## Administrar Moodle

Como administrador, crear la conexión, revisar su URL normalizada y ejecutar /test. Consultar status y last_error_code del JSON, no sólo el HTTP 200: una comprobación fallida puede quedar registrada como status=error. limited significa que la conexión responde pero faltan funciones entre las evaluadas. verified significa que se anunciaron todas, no que se hayan probado matrículas ni permisos sobre cada curso. Consultar /checks para historial y /audit-logs para acciones. Tras editar debe comprobarse de nuevo; no se reutiliza una verificación antigua. Desactivar con PATCH active=false.
