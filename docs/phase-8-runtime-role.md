# Fase 8 — Actualización 0.8.1

Se resolvió el aprovisionamiento de permisos PostgreSQL que estaba pendiente de implementación: migraciones y runtime pueden utilizar credenciales separadas mediante un overlay explícito. La aceptación/calibración de Moodle y configuración del destino productivo siguen pendientes; no se declara completada toda la Fase 8.

## Archivos y comportamiento

Creados: backend/app/services/database_roles.py, backend/tests/integration/test_database_roles.py, backend/tests/unit/test_database_roles.py, scripts/runtime-url.py, infrastructure/compose.runtime-role.yaml, docs/runtime-database.md y este informe.

Modificados: CLI, harness de navegador, versiones/lockfiles 0.8.1, README y guías de operación, seguridad, despliegue, base de datos, frontend y Fase 8. No se añaden dependencias ni se cambia el modelo de datos: Alembic 0006.

create-runtime-role crea exclusivamente un rol PostgreSQL nuevo mediante la identidad administrativa. grant-runtime-role refresca una matriz explícita sin cambiar contraseña y rechaza atributos administrativos, memberships, ownership y concesiones inseguras de PUBLIC. API/workers/Beat reciben sólo la credencial reducida; db-permissions verifica permisos y conexión después de migrar y antes de su arranque. Contraseña incorrecta, identidad administrativa o destino/opciones no admitidas causan error, sin fallback.

El rol reducido puede operar la aplicación y no puede modificar esquema, catálogo de roles, revisión Alembic, auditoría, eventos ni originales CSV. No puede borrar historial. Los permisos de actualización necesarios para estados de trabajos/registros se conservan. El administrador/migrador sigue siendo una identidad privilegiada; no se promete inmutabilidad frente a él ni a quien controla Docker.

runtime-url.py crea un archivo privado fuera del repositorio, con contraseña URL-encoded (no cifrada), sin sobrescritura y con eliminación de archivos parciales. Las contraseñas de los nuevos comandos sólo se reciben mediante getpass, nunca argumentos. La creación usa un verificador SCRAM; auditoría y mensajes excluyen contraseñas/verificadores.

## Verificación ejecutada

- 252 pruebas backend aprobadas, una omitida de carga optativa. El benchmark previo de 1000 operaciones no se repitió porque el motor no cambió; no se afirma una medición de carga nueva con estas identidades.
- 19 pruebas nuevas focalizadas aprobadas y repetidas tras los ajustes finales: pipeline con PostgreSQL reducido, denegaciones reales de DDL/tampering, ownership/memberships/PUBLIC, opciones de URL y persistencia segura de credenciales.
- Siete recorridos Chromium aprobados: ahora API y worker utilizan un rol reducido efímero; la preparación usa propietario y se limpian rol/esquema incluso ante fallos de preparación.
- Docker aislado con migración, concesión de permisos, todos los servicios saludables, sesión HttpOnly a través de Nginx y tres exportaciones reales. Comprobación privada: contraseña administrativa ausente del entorno API. Contraseña de runtime incorrecta rechazada; refresco con credenciales correctas verificado otra vez con imagen final.
- Ruff check/formato con los comandos de CI, Prettier, build TypeScript/Vite, imágenes Docker y Alembic check correctos. Advertencias heredadas de Starlette/Zod sin fallos. No se afirma ejecución remota de GitHub Actions.

## Ejecución y pendientes

Seguir runtime-database.md: migrar, crear rol con el CLI administrativo, generar archivo privado con la misma contraseña y añadir compose.runtime-role.yaml. Para HTTPS añadir también compose.production.yaml y configurar gateway/certificados reales. Comandos Windows/Linux en esa guía; las pruebas se ejecutaron sólo en Linux.

El entorno real de desarrollo sigue usando Compose base, con escrituras Moodle deshabilitadas y sin roles/cuentas de prueba añadidos a su base. El despliegue y datos de QA se eliminan al terminar. Se preservaron .env y claves existentes.

Para cerrar la aceptación externa siguen faltando URL pública HTTPS de Moodle de ensayo, credenciales por canal seguro y autorización explícita de cuentas/cursos/operaciones, además de la configuración productiva del destino. No suplirlo con datos inventados ni habilitar matrículas por un simple mensaje de continuar. Procedimiento en acceptance.md.
