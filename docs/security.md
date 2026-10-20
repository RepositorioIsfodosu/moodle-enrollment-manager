# Seguridad de los fundamentos

No hay endpoints de administración ni matrículas en fase 1. Los health checks no devuelven excepciones ni credenciales. CORS no habilita orígenes externos. Contenedor backend sin privilegios; PostgreSQL y Redis sin puertos públicos. No guardar .env en Git. El campo token_ciphertext prepara el almacenamiento cifrado; no constituye implementación de cifrado y no debe recibir tokens hasta fase 3.

Pendientes: hash seguro y sesiones (fase 2), RBAC y auditoría de operaciones, cifrado autenticado con clave externa, SSRF con validación de resolución y destino, TLS, retención y sanitización de errores Moodle. Los logs iniciales son estructurados para mensajes de aplicación; revisión completa de logging y redacción pendiente. No asumir protección productiva completa.
