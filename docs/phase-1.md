# Entrega de Fase 1

## Implementado

Repositorio inicialmente vacío. Se crean backend FastAPI, configuración validada con Pydantic, SQLAlchemy y 13 tablas, migración inicial Alembic explícita, conexión PostgreSQL, Redis, instancia Celery independiente, imágenes Docker sin usuario root y orquestación Compose. Endpoints live/ready, Swagger y logs JSON de aplicación. Restricciones de estados, unicidad por trabajo e integridad referencial en base de datos. Todavía no hay lógica de matrícula.

Archivos principales: backend/pyproject.toml y uv.lock; app/core/config.py, app/db/session.py, app/models/, app/main.py, app/workers/celery_app.py; alembic/; tests/unit/ y tests/integration/; backend/Dockerfile; infrastructure/compose.yaml y env.example; scripts/cloud-install.py; .github/workflows/backend.yml; README y docs. Son archivos nuevos; no existía código previo que modificar.

## Validaciones ejecutadas

- Seis pruebas pasan: liveness; readiness con error sanitizado; esquema migrado y readiness real; unicidad de correo con rollback; clave foránea rechazada; existencia de restricción de estados.
- PostgreSQL 16 y Redis 7 reales dentro de Docker.
- Upgrade, segundo upgrade sin cambios, downgrade en base de ensayo vacía y nuevo upgrade; Alembic check sin diferencias.
- Ruff check y format check correctos.
- Imagen backend construida con dependencias del lockfile; ajuste de confianza TLS y resolución del proxy en Codex Cloud. Construcción repetida correctamente.
- Arranque Compose, migración con salida cero, API healthy y petición HTTP de readiness con PostgreSQL y Redis verdaderos; worker responde pong por Redis.

Advertencia conocida: TestClient de Starlette informa deprecación de su transporte HTTPX en las versiones resueltas. Las pruebas pasan; revisar compatibilidad antes de actualizar dependencias. No se añade otra biblioteca sólo para silenciarla.

## Límites y siguiente fase

La CI se configura, pero su ejecución en GitHub debe comprobarse allí tras subir el commit. La instalación Windows se documenta; no se ha ejecutado en un equipo Windows. No hay frontend, autenticación, cifrado de tokens, CRUD Moodle, carga CSV ni motor de trabajos. Las pruebas de concurrencia, reintentos, recuperación y matrícula se implementarán con esas funcionalidades. Ninguna matrícula real fue solicitada ni ejecutada. No es una entrega lista para producción.

Arranque reproducible: comandos del README. Próxima fase: autenticación, roles, autorización y auditoría inicial; esperar instrucciones antes de implementarla.
