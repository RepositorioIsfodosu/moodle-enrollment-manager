# Arquitectura y alcance

FastAPI expone `/api/v1/`; PostgreSQL 16 conserva usuarios, permisos, conexiones, archivos, trabajos, operaciones, intentos y auditoría. Redis 7 transporta tareas Celery; no es la fuente de verdad. API y worker son procesos independientes. Alembic ejecuta migraciones en un servicio previo al arranque. Python 3.12, SQLAlchemy, Pydantic v2 y HTTPX están preparados. El frontend React/TypeScript se implementará en la fase 6.

La fase 1 contiene infraestructura y esquema inicial, no un motor de matrícula. Las transiciones, reservas `FOR UPDATE SKIP LOCKED`, leases, reconciliación y rate limiting se implementarán y probarán en la fase 5. La configuración conservadora de un worker con concurrencia 1 no constituye garantía de capacidad de Moodle.

## Riesgos Moodle

Funciones habilitadas, capacidades y parámetros dependen del servicio y versión. Antes de integrar se verificará la documentación oficial y el servicio destino. Una respuesta HTTP exitosa no es confirmación individual; timeout después de enviar exige resultado incierto y reconciliación antes de reintentar. La comprobación de matrícula previa puede quedar obsoleta. Roles y grupos requieren validación explícita. No se enviarán matrículas reales sin autorización y un Moodle de pruebas.

HTTPX se incluye por el cliente Moodle previsto; uvicorn ejecuta ASGI, psycopg conecta PostgreSQL y pydantic-settings valida el entorno. No se han añadido bibliotecas de exportación o autenticación antes de su fase.
