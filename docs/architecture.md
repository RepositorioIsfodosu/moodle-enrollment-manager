# Arquitectura y alcance

FastAPI expone `/api/v1/`; PostgreSQL 16 conserva usuarios, permisos, conexiones, archivos, trabajos, operaciones, intentos y auditoría. Redis 7 transporta tareas Celery; no es la fuente de verdad. API y worker son procesos independientes. Alembic ejecuta migraciones en un servicio previo al arranque. Python 3.12, SQLAlchemy, Pydantic v2 y HTTPX están preparados. El frontend React/TypeScript sirve una SPA mediante Nginx, que también publica /api en el mismo origen. Los datos proceden de la API; TanStack Query actualiza el progreso sin mantener los trabajos vivos. Véase frontend.md.

La fase 2 añadió autenticación y RBAC; la fase 5 incorpora transiciones, reservas `FOR UPDATE SKIP LOCKED`, leases, reconciliación y rate limiting, descritos más abajo. La configuración conservadora de un worker con concurrencia 1 no constituye garantía de capacidad de Moodle.

## Riesgos Moodle

Funciones habilitadas, capacidades y parámetros dependen del servicio y versión. Antes de integrar se verificará la documentación oficial y el servicio destino. Una respuesta HTTP exitosa no es confirmación individual; timeout después de enviar exige resultado incierto y reconciliación antes de reintentar. La comprobación de matrícula previa puede quedar obsoleta. Roles y grupos requieren validación explícita. No se enviarán matrículas reales sin autorización y un Moodle de pruebas.

HTTPX se incluye por el cliente Moodle previsto; uvicorn ejecuta ASGI, psycopg conecta PostgreSQL y pydantic-settings valida el entorno. No se han añadido bibliotecas de exportación o autenticación antes de su fase.

## Autenticación implementada

Argon2id mediante argon2-cffi evita implementar criptografía propia. email-validator respalda EmailStr de Pydantic para validar y normalizar identidades. Son las dos dependencias directas añadidas en fase 2 y sus dependencias transitivas están fijadas en uv.lock. Sesiones opacas revocables en PostgreSQL, permisos centralizados en core/permissions.py, dependencias FastAPI para autorización y servicios compartidos de auditoría y coordinación. Los permisos de módulos futuros están definidos, pero esos endpoints no existen todavía.

## Conexiones Moodle — Fase 3

Cliente HTTPX encapsulado que sólo invoca core_webservice_get_site_info; los endpoints administrativos están separados del servicio de comprobación. El cliente no ofrece todavía métodos de matrícula, resolución de usuarios ni cursos. Fernet/MultiFernet de cryptography aporta cifrado autenticado y rotación de claves. dnspython se declara ahora como dependencia directa para resolver A y AAAA con tiempos limitados; ya era transitiva de email-validator. HTTPcore soporta sni_hostname: se verifica ese comportamiento contra su versión fijada y con un servidor TLS real de pruebas.

La URL se normaliza, se rechazan esquemas inseguros/credenciales/puertos alternativos, se validan todas las direcciones DNS como públicas y la conexión se fija a una IP. SNI y Host mantienen el nombre original. No se reutiliza DNS al abrir el socket ni se siguen redirecciones. No hay fallback automático que pueda repetir una llamada. Las capacidades anunciadas son evidencia del servicio del token, no autorización probada en cada curso.

## Importación y validación — Fase 4

La API recibe bytes CSV con tamaño acotado antes de almacenarlos, analiza contenido en threadpool y guarda el original en PostgreSQL. Usa csv, hashlib y codecs de Python: no se añade un parser de multipart ni detección de codificación opaca. Los perfiles resuelven encabezados; la normalización crea operaciones inmutables con sus metadatos y errores locales.

La validación se persiste antes de publicar. Workers consumen validation.batch en cola validation, hasta 50 operaciones por tarea. Consultas de usuarios se agrupan de 50 en 50; IDs de curso usan una consulta agrupada oficial, y shortname/idnumber se consultan una vez por valor y proceso. Participantes se paginan por curso con límite y cache persistida. Las llamadas de validación al mismo base_url tienen exclusión Redis y separación mínima compartidas. Estos mecanismos no prometen capacidad de Moodle y comparten ahora el gate del motor de matrícula.

Celery Beat publica validation.recover cada 15 segundos en cola maintenance, atendida por un worker distinto. Esto evita que tareas de validación largas bloqueen la recuperación. Una publicación perdida se vuelve a intentar después de 60 segundos; un lease abandonado vence a los 600 segundos y tiene hasta tres recuperaciones. Cada escritura de resultado comprueba el lease y el estado bajo bloqueo de fila. No se mantiene ese bloqueo durante HTTP. Cancelación y cambios de acceso/configuración se comprueban antes de llamadas y al persistir. Un error de validación remota no se reintenta indefinidamente: queda visible y requiere una nueva validación.

La Fase 4 no convierte una validación en autorización de matrícula: el motor de Fase 5 requiere inicio explícito y vuelve a comprobar condiciones.

## Motor Fase 5

La API persiste trabajos y comandos; workers independientes consumen enrollment. Cada trabajo tiene un lease renovable y cursor de estados por registro, con slots de instalación y exclusión por usuario/curso mediante advisory locks de sesión. Redis sólo transporta mensajes y coordina solicitudes; Beat/maintenance recuperan despachos perdidos desde PostgreSQL.

ExecutionReader reutiliza resolución y modelos filtrados de la validación con caché nueva por lote y guards vinculados al trabajo. La whitelist de escritura está separada de lectura. Cada intento se persiste antes de HTTP; el resultado se observa mediante lecturas y se mantiene incierto cuando falta evidencia. El circuito es persistido, las solicitudes de los tres flujos comparten gate y las pausas se ajustan ante latencia. Ver enrollment-engine.md y phase-5.md.

## Reportes — Fase 7

Proyecciones autorizadas y agregados SQL sobre trabajos, registros y metadatos de origen; snapshots REPEATABLE READ para coherencia entre totales y filas. API paginada y exportaciones acotadas con openpyxl/ReportLab; no requieren Moodle ni Redis. Auditoría de exportaciones completadas sin contextos técnicos. Ver reports.md.

## Operación — Fase 8

Se añade overlay endurecido sin modificar el esquema (0006), backup binario portable y restauración en PostgreSQL desechable sin red. Purga transaccional optativa de sesiones caducadas y cachés terminales, preservando originales e historial. Exportaciones sobre límite se rechazan antes de materializar filas. CI integra backend, navegador, build y auditorías; carga simulada optativa. La validación productiva externa permanece pendiente; ver operations.md y acceptance.md.
