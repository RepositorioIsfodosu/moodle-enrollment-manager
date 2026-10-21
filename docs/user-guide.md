# Manual del administrador — Fase 2

1. Iniciar servicios y verificar health según README.
2. Crear el primer administrador desde terminal interactiva; no hay credenciales predeterminadas.
3. Iniciar sesión por API/Swagger y configurar el Bearer en Authorize.
4. Crear usuarios con roles apropiados. Asignar administrador sólo cuando se necesite gestionar cuentas; supervisor puede consultar auditoría.
5. Consultar usuarios con paginación y filtros; desactivar para retirar acceso sin perder referencias.
6. Consultar eventos en /api/v1/audit-logs. Revisar fallos repetidos de autenticación y denegaciones.
7. Cerrar sesión al terminar; usar logout-all si se sospecha exposición de un token. Un cambio de contraseña también cierra todas las sesiones.

Los detalles de endpoints y permisos están en authentication.md. No hay interfaz gráfica, conexión Moodle ni importaciones todavía. No enviar tokens Moodle a esta versión. Para Windows, respaldo, diagnóstico y actualización consultar README y deployment.md.
