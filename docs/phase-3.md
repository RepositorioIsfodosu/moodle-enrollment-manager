# Entrega técnica — Fase 3

## Funcionalidades implementadas

Administración de múltiples conexiones Moodle mediante API: crear, listar con paginación/filtro de activación, consultar, editar y desactivar sin borrar historial. URL del servicio derivada de la base canónica, descripción, token cifrado, límites validados, versión de configuración y estado. Sólo administrador tiene acceso en esta fase.

Comprobación de sólo lectura con core_webservice_get_site_info: información seleccionada del sitio, versión/release cuando Moodle los devuelve, funciones anunciadas, funciones evaluadas ausentes, latencia y fecha UTC. Estados unverified, verified, limited, error y disabled. Historial paginado de verificaciones y eventos de auditoría. Una comprobación fallida no se presenta como conexión correcta por tener HTTP 200.

Cliente HTTPX real con parámetros REST verificados en fuente oficial de Moodle 4.5. No usa respuestas simuladas en ejecución normal. Las otras funciones se evalúan por su presencia en el servicio; no se invocan aún. El retorno null de enrol_manual_enrol_users está documentado para que el motor futuro no lo confunda con confirmaciones individuales.

## Seguridad y fiabilidad

Tokens cifrados con Fernet/MultiFernet, claves externas al código en MOODLE_TOKEN_KEYS. Ni el token ni su ciphertext se devuelven. Se genera una clave local sin imprimirla y sin sobrescribir configuración previa. CLI de rotación transaccional; un token no descifrable revierte toda la operación. Respaldo y rotación documentados.

Protección SSRF: sólo HTTPS/443, dominio DNS y ruta base simple; sin credenciales/query/fragment ni IP literal. Validación A/AAAA completa, destinos exclusivamente públicos y bloqueo de metadata/transición IPv6. IP fijada al socket, con Host y SNI originales y certificado verificado. Sin redirects, proxies ambientales ni reintentos automáticos. Las excepciones de prueba para CA y routing sólo existen dentro de tests.

Respuesta limitada, errores remotos sanitizados y metadatos seleccionados. Los tokens reflejados en campos que se expondrían causan rechazo de la respuesta. Cambiar destino exige token nuevo. Las comprobaciones usan reserva/cooldown persistido; no mantienen bloqueo de base durante la solicitud. Una edición concurrente invalida el resultado previo. Esto no sustituye los controles del motor de matrícula de fase 5 ni garantiza capacidad del servidor Moodle.

## Archivos creados

- backend/app/integrations/moodle/client.py y urls.py.
- backend/app/core/token_vault.py.
- backend/app/schemas/moodle.py.
- backend/app/services/moodle_connections.py.
- backend/app/api/v1/endpoints/moodle.py.
- backend/alembic/versions/0003_moodle_connections.py.
- scripts/init-secrets.py.
- Pruebas unitarias Moodle/cifrado/inicialización, pruebas de integración de conexiones y TLS, y fixtures comunes de pruebas.
- Este informe; se amplía docs/moodle-api.md con fuentes oficiales y contrato exacto.

Actualizados: modelos, configuración, main.py, CLI, pyproject.toml, uv.lock, Compose, env.example, instalador Cloud, .gitignore, README y documentos de arquitectura, seguridad, base de datos, despliegue y uso. Las migraciones previas permanecen intactas. Las fixtures de autenticación se comparten sin retirar sus pruebas.

## Verificaciones

- **109 pruebas aprobadas**, con PostgreSQL 16 y Redis 7 dedicados a pruebas y RUN_INTEGRATION=1. Cubren regresiones de fases 1/2, permisos, cifrado/rotación, preservación de claves, URL/DNS/IPs prohibidos, contrato REST, timeout, respuestas ambiguas/HTML, HTTP y errores Moodle, límites de tamaño, redirecciones, ausencia de filtración de tokens, historial, cooldown y descarte de resultados obsoletos.
- Servidor HTTPS local real con CA efímera: SNI y Host correctos, respuesta REST válida; hostname de certificado incorrecto rechazado antes de enviar el token. Este servidor sólo corre durante el test.
- Rotación CLI probada con una fila inválida: rollback completo; tras corregirla, recifrado y retirada de clave anterior exitosos.
- Migración 0003: upgrade, downgrade a 0002 en base de ensayo, nuevo upgrade y repetición sin cambios. Alembic check sin diferencias con modelos.
- Ruff check/format y uv sync --frozen correctos; construcción Docker y arranque Compose con migración terminada en cero. API, PostgreSQL, Redis y worker saludables.
- Inicialización de clave probada por repetición y con formatos de configuración existentes; no imprime el valor y conserva lo existente.

Persiste la advertencia de deprecación de TestClient/Starlette de fases anteriores. No se ha probado Windows en una máquina Windows ni se afirma que la CI de GitHub haya pasado sin consultar su ejecución.

## Ejecución

Seguir README para copiar .env, sustituir contraseña PostgreSQL e inicializar la clave sin mostrarla. Arranque: `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml up --build -d --wait --wait-timeout 120`.

En Cloud: `DOCKER_CONFIG=/workspace/.docker-build python3 scripts/cloud-install.py`, seguido del comando Compose con `--no-build` en lugar de `--build`. Crear el primer administrador si hace falta con `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml exec api python -m app.cli create-admin`; nunca introducir claves o contraseñas en chat.

Desde backend: `uv run pytest tests/unit -q`; para integración configurar base PostgreSQL terminada en _test y Redis dedicados, DATABASE_URL, REDIS_URL y RUN_INTEGRATION=1, ejecutar `uv run alembic upgrade head` y `uv run pytest -q`. Las pruebas generan su propia clave efímera y no requieren token Moodle. Nunca usar el Redis de la aplicación para esta suite.

## Limitaciones y siguiente fase

**No se ha validado una instalación Moodle real**: no hay URL/token proporcionados. La integración está verificada con simulador HTTPX y HTTPS; un administrador deberá configurar un Moodle de ensayo y ejecutar /test para confirmar esa instalación. Nunca se realizaron matrículas reales ni se guardó un token Moodle real. Las funciones anunciadas no prueban permisos de ejecución por curso.

Sólo destinos públicos HTTPS/443; no se admiten Moodle privados/VPN sin una política futura explícita. La política de salida de Cloud puede requerir el dominio real cuando se configure. No hay frontend ni CSV ni motor de matrículas; el sistema completo aún no está listo para producción.

Siguiente fase: **Fase 4 — Importación y validación CSV**. No se inicia automáticamente.
