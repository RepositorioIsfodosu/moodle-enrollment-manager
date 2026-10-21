# Informe técnico — Fase 7

## Cambios

Reportes funcionales general, confirmadas, errores, pendientes, auditoría, curso y recinto; filtros por fecha, instalación, proceso, archivo, usuario, curso, estado, error y metadatos. Previsualización paginada y exportaciones CSV UTF-8 BOM, XLSX y PDF con encabezado, filtros, totales, observaciones y paginación PDF.

Creados: backend/app/reports/query.py, backend/app/reports/render.py, backend/app/api/v1/endpoints/reports.py, backend/tests/integration/test_reports.py, backend/tests/unit/test_report_render.py, frontend/src/pages/reports.tsx y docs/reports.md. Modificados: registro de rutas/versiones/configuración, dependencias y lockfiles, rutas frontend, dashboard (retirada de vista provisional), pruebas Chromium, Compose/env.example y documentación principal. Versiones 0.7.0; Alembic permanece 0006 sin cambio de esquema.

Seguridad: autorización en backend, snapshot consistente, agrupación por instalación/curso, protección de fórmulas, escape PDF, rechazo de celdas Excel no representables, límite explícito sin truncado y auditoría segura. openpyxl y ReportLab se justifican en reports.md.

## Verificación

Regresión completa: 231 pruebas backend aprobadas. Después del ajuste final de fecha de confirmación se repitieron las 29 pruebas de reportes (15 integración y 14 generación de archivos), todas aprobadas. Siete recorridos Chromium aprobados, incluida descarga y lectura de CSV/XLSX/PDF. Ruff check y formato del backend/script modificado correctos, Prettier correcto y TypeScript/Vite compilado. Imágenes API/web construidas; Compose saludable, migración con salida cero, SPA/proxy y controles de salud verificados. OpenAPI 0.7.0 contiene parámetros de filtros. Advertencias conocidas: Starlette TestClient y anotaciones Zod, sin fallos de pruebas o build. Las pruebas son exclusivamente con servicios dedicados y datos de pruebas, sin matrículas Moodle reales.

## Inicio

Desde la raíz: `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml up --build -d`. En Windows usar Docker Desktop con WSL2 y seguir README. Iniciar sesión y abrir Reportes; aplicar filtros y descargar CSV/XLSX/PDF. Configurar REPORT_EXPORT_MAX_ROWS si procede y recrear servicios. Desarrollo y pruebas en frontend.md; contrato y límites en reports.md.

## Pendientes

La Fase 8 corresponde a revisión integral, pruebas de carga controladas, aceptación en Moodle de ensayo autorizado y preparación productiva. No se ha probado Windows ni una instalación Moodle real en esta fase. No afirmar capacidad productiva por los resultados de simulación. Las exportaciones se generan bajo solicitud y límite; no hay exportación masiva ilimitada en segundo plano. Para alfabetos fuera de fuentes PDF estándar se requiere incorporar una fuente apropiada. No iniciar Fase 8 automáticamente.
