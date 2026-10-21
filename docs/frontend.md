# Interfaz administrativa — Fase 6

React, TypeScript, Vite, Tailwind, Lucide, TanStack Query, React Router, React Hook Form, Zod y Recharts. Inter se empaqueta con @fontsource/inter para evitar solicitudes externas. Playwright verifica recorridos reales de navegador; Prettier mantiene el formato. No se añaden bibliotecas de componentes ni datos demo al runtime.

## Windows y desarrollo

Instalar Git, Docker Desktop/WSL2, Node.js 24 y Python 3.12 con uv. Seguir README para .env, clave, migraciones y administrador inicial. Compose construye y publica web en puerto local 8080. Para desarrollar sin reconstruir Nginx:

```powershell
cd frontend
npm ci
npm run dev
```

Vite reenvía /api a la API local en puerto 8000; API_PROXY_TARGET permite otro destino de desarrollo. No cambiar changeOrigin: el backend comprueba Origin/Host. `npm run build` comprueba TypeScript y genera dist; `npm run format:check` comprueba formato. Estas verificaciones se ejecutaron en Linux; las instrucciones Windows no se ejecutaron en Windows.

## Sesión y permisos

Iniciar sesión con el administrador creado interactivamente. No existe cuenta predeterminada. Cookie HttpOnly/SameSite Strict; no se guardan tokens en almacenamiento JavaScript. Activar SESSION_COOKIE_SECURE=true para HTTPS productivo. Mantener mismo origen para web/API y preservar Host en el proxy. Los permisos visuales acompañan comprobaciones en servidor; supervisores y consulta sólo ven destinos concedidos.

## Recorrido

Conexiones permite crear, editar, desactivar, probar y consultar funciones y verificaciones; el token nunca se muestra completo. Conceder acceso a operadores y documentar evidencias reales de rol/visibilidad por curso. Nueva matriculación carga CSV, muestra vista previa, mapea columnas y guarda/actualiza perfiles; selecciona importaciones y valida en worker independiente. Revisar errores y pendientes antes de crear un borrador.

Procesos muestra progreso persistido, registros, intentos y eventos, con acciones confirmadas de inicio, pausa, reanudación, cancelación, duplicación de configuración y reintentos elegibles. Las escrituras deshabilitadas bloquean inicio/reanudación. Cerrar el navegador no detiene workers. Historial, Errores, Usuarios, Auditoría y Configuración consultan datos reales. Reportes permite filtros, vista paginada y exportaciones CSV/XLSX/PDF; ver reports.md.

Dashboard y detalle consultan periódicamente la API. Estado de conexión corresponde a la última verificación persistida, no a una garantía continua. Velocidad y estimación sólo se muestran con datos suficientes; incluyen pausas en el tiempo total. El progreso no equivale a matrículas confirmadas.

## Pruebas de navegador

Usar exclusivamente PostgreSQL dedicado con base cuyo nombre termine en _test y Redis dedicado, sin otros workers. Nunca apuntar a la aplicación ni a producción. Instalar Chromium mediante `npx playwright install chromium` desde frontend, o indicar PLAYWRIGHT_CHROMIUM_EXECUTABLE para Chromium ya instalado. En esta nube se usó /usr/bin/chromium porque la descarga del CDN devolvió 403, manteniendo verificación TLS.

Desde backend, configurar DATABASE_URL, REDIS_URL, RUN_BROWSER_TESTS=1 y ejecutar:

```powershell
uv sync --frozen
uv run python -m tests.run_browser_tests
```

El harness crea y elimina un esquema exclusivo, inicia API, worker de validación y Vite, ejecuta siete pruebas y detiene sus procesos. Datos y credenciales ficticias sólo existen en fixtures de pruebas. La validación del CSV usa un rol local inválido y no consulta Moodle; la validación elegible del recorrido de borrador es una fixture, no una verificación real. Las escrituras están forzadas a false. No ejecutar este harness a la vez que integración sobre el mismo Redis.
