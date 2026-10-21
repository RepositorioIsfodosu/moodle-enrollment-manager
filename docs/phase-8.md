# Fase 8 — Verificación local y preparación operativa

**Estado: trabajo local verificado; Fase 8 no cerrada por aceptación/calibración Moodle y configuración productiva pendientes.** No se han ejecutado matrículas reales ni desplegado el sistema en un destino público.

## Implementación

- cryptography actualizado de 46.0.7 a 50.0.2 por cuatro avisos de seguridad; claves existentes conservadas.
- Imagen backend sin fixtures de tests ni archivos .env*; dependencias de desarrollo excluidas.
- Overlay de Compose: permisos reducidos, filesystem de sólo lectura en procesos de aplicación, reinicio, límites y rotación de logs. Plantilla de gateway HTTPS con HSTS y límite adicional de login; no incluye certificados productivos.
- Scripts portables backup.py y restore-check.py: dump custom binario, no sobrescritura, permisos, fsync, SHA-256 y restauración exclusivamente en contenedor aislado eliminado con su volumen.
- Purga optativa de transitorios con simulación por defecto; sólo sesiones caducadas y cachés antiguas de validaciones terminales. Se preservan CSV, historial y auditoría y se registra la purga ejecutada.
- Rechazo de exportaciones excesivas antes de cargar sus filas en memoria.
- CI ampliada: backend, frontend, Chromium, auditorías de dependencias y carga simulada optativa por workflow_dispatch.
- Benchmark reproducible de 1000 operaciones, con métricas y límites de interpretación. Documentación operativa, revisión de seguridad y plan de aceptación en español.

Creados: app/services/maintenance.py; tests/integration/test_maintenance.py y test_controlled_load.py; infrastructure/compose.production.yaml y nginx-tls.conf.example; scripts/backup.py y restore-check.py; docs/operations.md, acceptance.md, load-testing.md, security-review.md, benchmarks/2026-10-21-simulated-load.json y este informe.

Modificados: CLI, endpoints de reportes, versión API/backend/frontend y lockfiles (0.8.0), .dockerignore backend, workflow de calidad y documentación principal/arquitectura/seguridad/despliegue/manual. Sin cambios de modelos ni migraciones; Alembic conserva 0006.

## Pruebas y resultados

Regresión completa: **233 aprobadas y una omitida explícitamente** (carga optativa). Carga ejecutada por separado: **una aprobada con 1000 operaciones**, 40 lotes, sin escrituras simuladas duplicadas. Registra 14151 lecturas simuladas, validación 28,28 s, procesamiento 250,15 s y API ASGI p95 103,2 ms con cuatro lecturas concurrentes. Las respuestas remotas son simuladas y pace=False sólo en test; no son capacidad Moodle ni SLO productivo. Ver load-testing.md.

Auditoría Python: 63 distribuciones sin avisos tras actualización; frontend: grafo de 208 dependencias sin avisos conocidos. Revisión sujeta a datos del scanner, no garantía de ausencia de fallos. Ruff check/formato, Prettier, TypeScript/Vite y compilación Docker ejecutados. Siete recorridos Chromium aprobados con API/worker/Vite reales; imágenes finales y Compose base saludables. Alembic check no detectó diferencias. La advertencia heredada de Starlette y los avisos de anotaciones Zod no causaron fallos.

Overlay productivo arrancado con servicios saludables; inspección confirmó filesystem de sólo lectura y usuario sin privilegios en API/web/worker, cookie Secure activa y escrituras Moodle deshabilitadas. Prueba TLS local con CA/hostname verificados, HSTS y readiness correctos. Al terminar se restaura el Compose base para desarrollo local, sin borrar volúmenes.

Respaldo de una base de fixtures separada restaurado sin red: revisión 0006, un usuario inactivo de prueba, una conexión cifrada, un CSV con sus 24 bytes originales, un trabajo, un registro y un evento de auditoría. Verificados rechazo de sobrescritura y checksum inválido. No se restauraron datos reales del entorno ni se validó recuperación de sus claves. Simulación de purga en el runtime sin modificaciones. La ejecución remota de GitHub Actions no se declara verificada desde esta sesión.

## Comandos

Desarrollo local: `docker compose --env-file infrastructure/.env -f infrastructure/compose.yaml up --build -d`. Windows: Docker Desktop/WSL2 y Python 3.12, siguiendo README. Overlay HTTPS: añadir `-f infrastructure/compose.production.yaml` y configurar antes un gateway real; ver operations.md. Las instrucciones Windows están documentadas pero no se ejecutaron en Windows.

Desde backend con PostgreSQL/Redis dedicados *_test: `RUN_INTEGRATION=1 uv run pytest -q` en Bash; para Windows establecer la variable con PowerShell. Benchmark optativo: `RUN_INTEGRATION=1 RUN_LOAD_TESTS=1 LOAD_ROWS=1000 uv run pytest tests/integration/test_controlled_load.py -q`. Navegador: frontend npm ci y Chromium, luego `RUN_BROWSER_TESTS=1 uv run python -m tests.run_browser_tests` con servicios dedicados. No usar el broker real para pruebas.

## Pendiente para cerrar

URL pública HTTPS de Moodle de ensayo, credenciales configuradas por canal seguro, autorización explícita de las operaciones y cuentas/cursos, aceptación registrada y calibración acordada con su responsable. Configuración productiva de DNS/TLS, secretos, roles PostgreSQL separados de mínimo privilegio, monitorización, respaldos/retención y recuperación de claves. El procedimiento completo está en acceptance.md; no marcarlo como ejecutado por las pruebas locales. ENROLLMENT_WRITES_ENABLED permanece false.
