# Pruebas de carga controladas

## Ejecución local sin Moodle

Usar PostgreSQL y Redis **dedicados**, una base cuyo nombre termine en _test, y nunca el broker de la aplicación. Instalar dependencias bloqueadas y aplicar migraciones. Desde backend, con DATABASE_URL y REDIS_URL apuntando a esos servicios:

```powershell
$env:RUN_INTEGRATION = '1'
$env:RUN_LOAD_TESTS = '1'
$env:LOAD_ROWS = '1000'
uv run pytest tests/integration/test_controlled_load.py -q
```

En Bash exportar las mismas variables. LOAD_ROWS admite 100–2000; por defecto 1000. LOAD_RESULT_PATH permite indicar un artefacto JSON; el valor por defecto usa el directorio temporal del sistema. Las pruebas normales omiten explícitamente este caso si no se habilita RUN_LOAD_TESTS. GitHub Actions lo ejecuta sólo al lanzar manualmente workflow_dispatch y conserva el JSON como artefacto; el resultado remoto debe consultarse en Actions, no se presupone por las pruebas locales.

El fixture crea un esquema temporal y datos ficticios exclusivamente de pruebas. El constructor del cliente Moodle real está prohibido en el caso; todas las lecturas/escrituras usan un simulador paginado. Sólo el proceso de prueba habilita escrituras para ese simulador mediante monkeypatch; el despliegue conserva ENROLLMENT_WRITES_ENABLED=false. No habilitar esa variable en infrastructure/.env para ejecutar esta prueba.

Comprueba carga y normalización CSV, validación por lotes, 1000 resultados observados, unicidad de envíos simulados, redelivery inocua, 40 lecturas API ASGI mediante TestClient con concurrencia cuatro, y exportaciones reales CSV/XLSX/PDF. PostgreSQL es real. El procesamiento se ejecuta antes de las lecturas API y exportaciones; no representa un ensayo mixto simultáneo ni HTTP a través de Internet. Las pruebas de navegador separadas sí usan API/worker/Vite con conexiones HTTP locales.

## Medición del 21 de octubre de 2026

Artefacto: [2026-10-21-simulated-load.json](benchmarks/2026-10-21-simulated-load.json). La máquina y software visibles se registran allí; los recursos son compartidos y no constituyen un servidor dedicado de referencia.

| Medida | Resultado local |
|---|---:|
| Operaciones / escrituras simuladas únicas | 1000 / 1000 |
| Lotes de 25 | 40 |
| Carga y validación | 28,28 s |
| Procesamiento persistido | 250,15 s |
| Lecturas simuladas (incluye site info) | 14151 |
| API ASGI, 40 solicitudes / concurrencia | 40 / 4 |
| Mediana / p95 API | 46,7 / 103,2 ms |
| Exportación CSV / XLSX / PDF | 0,062 / 0,197 / 3,148 s |

No son SLO, umbrales de aceptación ni capacidad Moodle. pace=False suprime deliberadamente rate limiting y pausas únicamente en el test; las respuestas simuladas no incluyen latencia real. Los tiempos incluyen persistencia y verificaciones de seguridad del gestor y dependen de la máquina. No se prometen matrículas por segundo en producción.

La paginación de participantes obliga a releer páginas antes/después de escrituras para observar rol/grupo sin confiar en caché de validación. El costo varía con tamaño del curso y posición del usuario; un archivo de mil filas no implica mil solicitudes. No aumentar RPM ni reutilizar resultados antiguos sólo para mejorar el benchmark. Para cursos con grandes listas, evaluar con el responsable de Moodle el costo real, las funciones oficiales disponibles y límites de visibilidad; no inventar filtros API ni confirmaciones.

## Carga sobre Moodle de ensayo

Seguir acceptance.md. Requiere destino público HTTPS, credenciales seguras y autorización explícita para las cuentas/cursos y operaciones. Acordar límites y criterio de suspensión, empezar pequeño, aumentar gradualmente y registrar latencia, errores, circuitos e incertidumbre. Verificar integridad y recuperación antes de aumentar volumen. Esta prueba real permanece pendiente; no se ejecuta automáticamente en CI.
