# Manual del administrador — Fase 4

1. Iniciar servicios y verificar health según README.
2. Crear el primer administrador desde terminal interactiva; no hay credenciales predeterminadas.
3. Iniciar sesión por API/Swagger y configurar el Bearer en Authorize.
4. Crear usuarios con roles apropiados. Asignar administrador sólo cuando se necesite gestionar cuentas; supervisor puede consultar auditoría.
5. Consultar usuarios con paginación y filtros; desactivar para retirar acceso sin perder referencias.
6. Consultar eventos en /api/v1/audit-logs. Revisar fallos repetidos de autenticación y denegaciones.
7. Cerrar sesión al terminar; usar logout-all si se sospecha exposición de un token. Un cambio de contraseña también cierra todas las sesiones.

Los detalles de endpoints y permisos están en authentication.md. Ya se pueden configurar y probar conexiones Moodle por API. Ya hay importación y validación CSV por API, sin interfaz gráfica todavía; usar un Moodle de pruebas y un token de mínimo privilegio. Para Windows, respaldo, diagnóstico y actualización consultar README y deployment.md.

## Administrar Moodle

Como administrador, crear la conexión, revisar su URL normalizada y ejecutar /test. Consultar status y last_error_code del JSON, no sólo el HTTP 200: una comprobación fallida puede quedar registrada como status=error. limited significa que la conexión responde pero faltan funciones entre las evaluadas. verified significa que se anunciaron todas, no que se hayan probado matrículas ni permisos sobre cada curso. Consultar /checks para historial y /audit-logs para acciones. Tras editar debe comprobarse de nuevo; no se reutiliza una verificación antigua. Desactivar con PATCH active=false.

## Flujo CSV

1. Dar al operador acceso a la conexión Moodle de pruebas.
2. Cargar archivos, revisar encabezados y vista previa; corregir errores estructurales antes de continuar.
3. Seleccionar un perfil o mapear columnas y tipos de identificadores. Especificar roles reales; no asumir que el rol de estudiante tiene ID 5.
4. Normalizar y revisar operaciones válidas localmente, inválidas y duplicadas. Filas y operaciones tienen cantidades distintas.
5. Crear una validación con las importaciones deseadas y consultar progreso/records. Puede cerrarse el navegador: el worker continúa.
6. Revisar errores, usuarios/cursos no visibles, pendientes de evidencia y matrículas existentes. El administrador sólo debe registrar una evidencia de rol/visibilidad después de comprobarla en Moodle.
7. Corregir archivo/perfil o configuración y crear una importación/validación nueva. Los resultados previos se conservan. Cancelar detiene trabajo futuro de esa validación.

completed significa análisis terminado, no matrícula realizada ni elegibilidad de todos los registros. pending significa comprobación/revisión incompleta aunque el porcentaje de análisis llegue al 100 %. No existe todavía botón o endpoint para matricular. Consultar csv-imports.md para formatos y contratos.
