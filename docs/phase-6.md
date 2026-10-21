# Informe técnico — Fase 6

## Implementación

Interfaz administrativa React/TypeScript conectada a FastAPI, sin datos demo en runtime: sesión, dashboard filtrado, conexiones y concesiones, evidencias administrativas, carga CSV, vista previa, mapeo y perfiles editables, validación asíncrona, borradores, procesos, historial, errores, usuarios, auditoría y configuración. Diseño responsive, fuentes locales, formularios etiquetados, diálogos accesibles y mensajes de error explícitos.

Archivos creados: frontend completo (src, configuración, lockfile, Dockerfile, Nginx y pruebas), backend/app/api/v1/endpoints/overview.py, backend/tests/integration/test_ui_api.py, backend/tests/browser_seed.py, backend/tests/run_browser_tests.py, docs/frontend.md y este informe.

Archivos modificados: dependencias de autenticación, endpoints auth/imports/jobs/validations, esquemas auth, configuración y main, pyproject/uv.lock para versión 0.6.0; Compose/env.example, script de instalación cloud, .gitignore, README y guías architecture/authentication/deployment/security/user-guide. No cambia el modelo de datos: Alembic conserva 0006.

Sesión web mediante cookie HttpOnly y protección CSRF por Origin/Host más cabecera; Bearer sigue disponible. Nuevas consultas paginadas y agregados respetan autorización por propietario/destino. Tokens Moodle permanecen cifrados y nunca vuelven al navegador. Nginx sin privilegios sirve SPA y /api en el mismo origen, con CSP y cabeceras de seguridad.

## Verificación

Resultados ejecutados en Linux: 202 pruebas backend aprobadas con PostgreSQL/Redis dedicados (una advertencia heredada de Starlette); seis pruebas Chromium aprobadas, Ruff check y formato del backend/script modificado correctos, Prettier correcto y build TypeScript/Vite correcto. Compilación Docker de API y web correcta. Proxy Nginx verificado: raíz y ruta profunda 200, readiness 200 con cinco comprobaciones verdaderas, acceso sin sesión 401 y cabeceras CSP/nosniff presentes. Se corrigieron permisos de lectura para Nginx sin privilegios y healthcheck local sin proxy. Vite muestra avisos de anotaciones de Zod que no impiden compilar. El recorrido de navegador cubre sesión y recarga, carga/mapeo/perfiles/validación con worker real, creación/cancelación de borradores, conexiones con token oculto, consulta y navegación móvil, y error de servidor/diálogo accesible. Nunca se ejecutan matrículas reales.

## Inicio

Seguir README para Windows y Docker. `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml up --build -d` construye y arranca web, API, PostgreSQL, Redis, migración, workers, mantenimiento y Beat. Crear el administrador con el comando interactivo del README. Desarrollo y harness en frontend.md.

## Límites y siguiente fase

Reportes ofrece indicadores reales; exportaciones profesionales CSV/XLSX/PDF quedan para Fase 7. No se validó una instalación Moodle real ni una capacidad de carga productiva. Mantener ENROLLMENT_WRITES_ENABLED=false hasta aceptación autorizada en Moodle de ensayo. Restan aceptación/calibración y revisión integral productiva de Fase 8. No se inicia Fase 7 en esta entrega.
