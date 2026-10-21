# Reportes y exportaciones — Fase 7

## Alcance y permisos

La sección Reportes consulta PostgreSQL: no llama a Moodle ni ejecuta matrículas. Administradores ven todos los trabajos; operadores sólo los propios en destinos concedidos; supervisores ven trabajos en destinos concedidos. Consulta no tiene reports:read. Auditoría exige además audit:read y conserva el alcance global del módulo de auditoría existente; no implica acceso a trabajos sin concesión.

Tipos: general, matrículas confirmadas, errores e incertidumbre, pendientes, auditoría administrativa, por curso y por recinto. Confirmadas exige estado confirmed; existing se presenta por separado. Pendientes incluye pending y reserved. Los grupos por curso incluyen identidad de instalación Moodle, identificador de curso y estado, evitando mezclar instalaciones con nombres iguales. Son operaciones solicitadas, no usuarios únicos. Los grupos por recinto incluyen el valor exacto y estado; la instalación superior puede restringirlos.

## Filtros y fechas

La instalación se selecciona en la barra superior. Los demás filtros se aplican al pulsar Aplicar filtros. Las coincidencias de usuario, curso, estado, código de error, recinto y período son exactas. Los filtros son acumulativos y los tipos de reporte restringen estados adicionalmente: pedir successful con state=failed produce cero resultados.

Fechas desde/hasta son inclusivas y filtran creación de registros o eventos, no fecha de ejecución. La interfaz convierte la hora local del navegador a ISO con zona; la API rechaza fechas sin zona o intervalos invertidos. Fechas de archivo exportado usan UTC explícita. La fecha de confirmación procede del máximo observed_at persistido en intentos confirmed_by_observation, nunca de la fecha de creación del intento; queda Sin datos si no existe evidencia fechada. Un estado confirmed sin fecha no recibe una fecha inventada.

Para recinto/período configurar en el perfil de mapeo CSV metadata_columns con claves campus y academic_period, respectivamente. Ejemplo: `{"metadata_columns":{"campus":"recinto","academic_period":"periodo"}}`. Estas claves se recuperan desde la operación original vinculada por validación. Sin datos significa ausencia de metadatos; no se infieren a partir del nombre de curso o usuario. El reporte representa la operación consolidada del trabajo, no vuelve a multiplicar filas duplicadas del CSV.

## API

GET /api/v1/reports devuelve title, generated_at, filters, summary (total_operations, counts y percentages), columns, items, total, offset, limit y export_limit. La paginación admite limit de 1–100 y offset >=0. En reportes agrupados total representa filas de grupos; summary.total_operations conserva operaciones de origen. En auditoría total_operations cuenta eventos y counts/percentages están vacíos. Un reporte vacío tiene cero y porcentajes vacíos, sin división por cero.

Parámetros: kind=general|successful|errors|pending|audit|course|campus, since/until ISO con zona, connection_id/job_id/file_id UUID, user, course, state, error_code, campus, academic_period. Auditoría admite fechas, actor_id y action; rechaza filtros de matrículas. Los demás tipos rechazan filtros exclusivos de auditoría. Se rechazan parámetros desconocidos o repetidos. Los parámetros de filtro están documentados también en OpenAPI.

GET /api/v1/reports/export usa los mismos filtros y format=csv|xlsx|pdf. Devuelve attachment, no-store y nosniff. No acepta filtros para seleccionar datos ajenos. Cada solicitud usa un snapshot PostgreSQL REPEATABLE READ para que filas, grupos y totales sean coherentes entre sí; una exportación nueva puede reflejar cambios posteriores a la vista previa. Las consultas de resumen se agrupan en SQL.

## Formatos y límites

CSV UTF-8 BOM: encabezado, filtros, indicadores, observaciones y tabla. XLSX: hojas Resumen y Resultados, encabezados, filtro y primera fila fija. PDF A3 horizontal: título, indicadores, filtros, tabla con cabecera repetida y número de página; filas largas pueden continuar en otra página. El diseño usa fuentes PDF estándar orientadas al español; alfabetos que no cubren esas fuentes pueden requerir una fuente adicional antes de distribución internacional.

openpyxl genera archivos XLSX reales sin automatizar Excel. ReportLab genera PDF reales sin navegador ni servicios externos. Son las únicas dependencias directas nuevas; sus dependencias transitivas quedan fijadas en uv.lock.

CSV y XLSX anteponen apóstrofo a valores que podrían ejecutarse como fórmulas, incluso con espacios iniciales o caracteres de tabulación/salto. PDF escapa texto como texto, no HTML ejecutable. El apóstrofo protector forma parte del archivo exportado. XLSX rechaza con 422 celdas de más de 32767 caracteres o controles no representables; ofrece CSV en vez de truncar silenciosamente.

REPORT_EXPORT_MAX_ROWS limita filas de resultado: 10000 por defecto, configurable entre 1 y 50000. Si se supera, HTTP 413 pide refinar filtros; jamás se descarga sólo una parte sin advertirlo. Para reportes agrupados se cuentan grupos, no operaciones subyacentes. La vista previa sigue disponible por páginas. La generación es síncrona y acotada; no hay tareas de exportación ilimitada ni archivos permanentes en el servidor. Los artefactos contienen datos personales: restringir distribución y aplicar retención a las descargas fuera de la aplicación.

Cada exportación completada añade report.exported con responsable, tipo, formato, filas y total; no guarda cuerpo, token ni filtros con identificadores personales en el contexto de auditoría. El reporte de auditoría no incluye safe_context ni credenciales. Un fallo de generación no se registra como exportación completada.

## Verificación y operación

Seguir frontend.md para el harness Chromium y README para PostgreSQL/Redis de pruebas dedicados. La regresión incluye endpoints, autorización, concesiones, agregados, filtros, paginación, formatos, fórmulas, límites, metadatos ausentes y auditoría; el navegador descarga los tres formatos y aplica filtros. No hay Moodle real involucrado.

Después de actualizar, reconstruir imágenes y recrear Compose para incorporar bibliotecas y REPORT_EXPORT_MAX_ROWS. El esquema permanece en Alembic 0006: no hay tablas nuevas ni migración de datos en esta fase. ENROLLMENT_WRITES_ENABLED permanece false en el entorno validado.
