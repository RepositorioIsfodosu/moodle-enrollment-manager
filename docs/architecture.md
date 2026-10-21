# Arquitectura y alcance

FastAPI expone `/api/v1/`; PostgreSQL 16 conserva usuarios, permisos, conexiones, archivos, trabajos, operaciones, intentos y auditoría. Redis 7 transporta tareas Celery; no es la fuente de verdad. API y worker son procesos independientes. Alembic ejecuta migraciones en un servicio previo al arranque. Python 3.12, SQLAlchemy, Pydantic v2 y HTTPX están preparados. El frontend React/TypeScript se implementará en la fase 6.

La fase 2 añade autenticación y RBAC sobre la infraestructura inicial; todavía no hay motor de matrícula. Las transiciones, reservas `FOR UPDATE SKIP LOCKED`, leases, reconciliación y rate limiting se implementarán y probarán en la fase 5. La configuración conservadora de un worker con concurrencia 1 no constituye garantía de capacidad de Moodle.

## Riesgos Moodle

Funciones habilitadas, capacidades y parámetros dependen del servicio y versión. Antes de integrar se verificará la documentación oficial y el servicio destino. Una respuesta HTTP exitosa no es confirmación individual; timeout después de enviar exige resultado incierto y reconciliación antes de reintentar. La comprobación de matrícula previa puede quedar obsoleta. Roles y grupos requieren validación explícita. No se enviarán matrículas reales sin autorización y un Moodle de pruebas.

HTTPX se incluye por el cliente Moodle previsto; uvicorn ejecuta ASGI, psycopg conecta PostgreSQL y pydantic-settings valida el entorno. No se han añadido bibliotecas de exportación o autenticación antes de su fase.

## Autenticación implementada

Argon2id mediante argon2-cffi evita implementar criptografía propia. email-validator respalda EmailStr de Pydantic para validar y normalizar identidades. Son las dos dependencias directas añadidas en fase 2 y sus dependencias transitivas están fijadas en uv.lock. Sesiones opacas revocables en PostgreSQL, permisos centralizados en core/permissions.py, dependencias FastAPI para autorización y servicios compartidos de auditoría y coordinación. Los permisos de módulos futuros están definidos, pero esos endpoints no existen todavía.

## Conexiones Moodle — Fase 3

Cliente HTTPX encapsulado que sólo invoca core_webservice_get_site_info; los endpoints administrativos están separados del servicio de comprobación. El cliente no ofrece todavía métodos de matrícula, resolución de usuarios ni cursos. Fernet/MultiFernet de cryptography aporta cifrado autenticado y rotación de claves. dnspython se declara ahora como dependencia directa para resolver A y AAAA con tiempos limitados; ya era transitiva de email-validator. HTTPcore soporta sni_hostname: se verifica ese comportamiento contra su versión fijada y con un servidor TLS real de pruebas.

La URL se normaliza, se rechazan esquemas inseguros/credenciales/puertos alternativos, se validan todas las direcciones DNS como públicas y la conexión se fija a una IP. SNI y Host mantienen el nombre original. No se reutiliza DNS al abrir el socket ni se siguen redirecciones. No hay fallback automático que pueda repetir una llamada. Las capacidades anunciadas son evidencia del servicio del token, no autorización probada en cada curso.
