# CSV, perfiles y validación — Fase 4

## Contrato de carga y límites

POST `/api/v1/csv-files?filename=archivo.csv&encoding=utf-8&delimiter=auto` recibe el cuerpo como **bytes del CSV**, con Content-Type text/csv o application/octet-stream. No es multipart ni JSON. Un navegador puede enviar un objeto File directamente como body; la interfaz de arrastrar/soltar y selección múltiple se implementará en fase 6. Para varios archivos, hacer una petición por archivo y reunir sus importaciones en una validación (hasta 20). No se hacen llamadas a Moodle durante carga/normalización.

UTF-8 y UTF-8 BOM son admitidos. CP1252 y Latin-1 requieren encoding explícito; no se adivinan silenciosamente. delimiter puede ser auto, coma, punto y coma, tabulador o barra vertical; auto es heurístico sobre los primeros 8192 caracteres, y puede requerir elección manual. Se exige encabezado. Hay límite configurable de bytes/filas/operaciones, máximo fijo de 200 columnas, 100 caracteres por encabezado, 4096 por campo, 1 millón de celdas y 50 columnas de curso. Se rechazan encabezados vacíos o duplicados sin distinguir mayúsculas, filas vacías, ancho inconsistente, controles y comillas mal formadas. El error indica registro lógico cuando corresponde, sin copiar datos sensibles.

La respuesta contiene id, nombre seguro, SHA-256 del original, bytes, filas, codificación/delimitador seleccionados, encabezados y primeras 20 filas. GET /csv-files lista archivos propios (administrador ve todos); GET /csv-files/{id} muestra detalle y /original descarga los bytes exactos bajo autorización. El original nunca se ejecuta ni se publica como archivo web.

## Perfil y normalización

POST /import-profiles recibe name y mapping; GET /import-profiles lista perfiles propios; PUT /import-profiles/{id} actualiza uno autorizado. POST /csv-files/{id}/normalize recibe profile_id o mapping. Cada normalización crea una importación inmutable; editar un perfil no cambia resultados anteriores. GET /csv-imports/{id} resume la importación y /operations ofrece paginación y filtro pending/invalid/duplicate.

Ejemplo de mapping (IDs y nombres ilustrativos; deben corresponder a Moodle real):

```json
{
  "user_column": "Usuario",
  "user_field": "idnumber",
  "course_field": "shortname",
  "courses": [{"course": "Curso", "role": "Rol", "group": "Grupo"}],
  "group_field": "name",
  "role_map": {"estudiante": 5},
  "metadata_columns": {"campus": "Recinto", "period": "Periodo"}
}
```

user_field admite username/email/idnumber; course_field id/shortname/idnumber; group_field id/name/idnumber. Si no se indica user_column se busca username, email o idnumber. Si se indica una columna propia, configurar también su user_field correcto. Sin courses explícito se reconocen courseN/roleN/groupN, ordenados por N. roleN debe contener un ID entero positivo o una etiqueta presente en role_map. default_role_id es opcional y nunca se asume automáticamente. Los IDs de cursos se canonizan; username/email se normalizan en minúsculas y se valida el formato de correo.

Una fila puede producir varias operaciones. Los slots courseN vacíos sin datos asociados se omiten; una fila sin curso produce un error conservado. Se mantienen usuario, curso, rol, grupo y metadatos configurados. Duplicados internos conservan origen y motivo; los metadatos de recinto/período no hacen distinta una misma operación Moodle. source_row cuenta registros CSV incluyendo encabezado=1, no líneas físicas de campos multilínea.

## Autorizar conexiones y evidencias

Administrador: POST /moodle-connections/{id}/grants con user_id concede alcance; DELETE /moodle-connections/{id}/grants/{user_id} revoca. Un operador aún necesita su rol y ser propietario de la importación; una concesión no permite ver archivos ajenos. Supervisor/consulta con concesión pueden consultar validaciones del destino, sin descargar originales.

Moodle 4.5 estándar no ofrece en las funciones revisadas un catálogo de roles asignables por el token. Además, get_enrolled_users puede filtrar por grupos/contexto sin que una lista vacía pruebe ausencia. **No se inventa esa comprobación.** Un administrador debe revisar el usuario técnico en Moodle y registrar una evidencia real:

POST /moodle-connections/{id}/role-approvals recibe course_id, role_id, expires_at (fecha con zona horaria dentro de siete días), reference (referencia explicativa de al menos 20 caracteres), full_enrollment_visibility y groups_authorized. Los dos booleanos son false por defecto. La evidencia debe confirmar asignabilidad del rol y, para afirmar ausencia, visibilidad completa de participantes del curso (grupos separados, permisos de ver participantes y estados). groups_authorized confirma gestión de grupos cuando se solicita. No marcar true por conveniencia. La declaración es manual, no una respuesta de Moodle.

La evidencia se vincula a la versión actual de conexión; editarla exige revisión nueva. GET /moodle-connections/{id}/role-approvals lista evidencias; DELETE /role-approvals/{id} revoca sin borrar historial. Los resultados exponen approval_id y role_evidence_source=administrator_attestation; no ocultan el origen manual de la evidencia.

## Validación asíncrona

POST /validations recibe connection_id e import_ids y devuelve 202 con progreso persistido. GET /validations lista procesos autorizados; GET /validations/{id} informa estado y conteos; /records pagina resultados con filtros status/error_code. POST /validations/{id}/cancel cancela cooperativamente. No se muta Moodle. Un fallo conserva progreso y motivo; tras corregirlo crear una validación nueva, no modificar resultados históricos.

Estados del proceso: queued, running, completed, failed, cancelled. completed significa que se terminó el análisis, aun si hay registros pendientes de revisión. checked incluye registros cuyo análisis concluyó como pending; por eso 100 % no significa listo para matricular. Estados de registro: valid, invalid, duplicate, existing y pending. valid sólo significa precondiciones comprobadas con las evidencias disponibles y snapshot de lectura; nunca confirma una matrícula ni garantiza vigencia futura.

Se detectan duplicados entre importaciones antes de consultar Moodle y entre identificadores distintos que resuelven a los mismos IDs. Se agrupan hasta 50 usuarios por field y varios cursos por ID; shortname/idnumber se consultan una vez por valor y proceso. Los participantes se consultan con onlyactive=1, orden por id y paginación de 100. Un límite alcanzado, detalles no divulgados, funciones ausentes o evidencia incompleta producen pending/failed, nunca una matrícula nueva supuesta. Usuario/curso no encontrado se informa también como potencialmente no visible; no se confunden permisos con inexistencia demostrada.

El worker sólo usa funciones oficiales verificadas: core_webservice_get_site_info; core_user_get_users_by_field (field, values[N]); core_course_get_courses_by_field (field=ids y value separado por comas para IDs, o shortname/idnumber); core_enrol_get_enrolled_users (courseid y options[N][name/value]); core_group_get_course_groups (courseid) si hay grupos. Se verifica el servicio anunciado antes de usarlas. Para declarar elegibilidad también debe anunciar enrol_manual_enrol_users y, si procede, core_group_add_group_members, pero **no se invocan**. El cliente de lectura rechaza funciones de escritura.

Fuentes oficiales: [usuarios](https://github.com/moodle/moodle/blob/cae172ee4aeec1d7a6eaba7bb5ae12a5f0fe3772/user/externallib.php), [cursos](https://github.com/moodle/moodle/blob/cae172ee4aeec1d7a6eaba7bb5ae12a5f0fe3772/course/externallib.php), [matrículas/visibilidad](https://github.com/moodle/moodle/blob/cae172ee4aeec1d7a6eaba7bb5ae12a5f0fe3772/enrol/externallib.php), [grupos](https://github.com/moodle/moodle/blob/cae172ee4aeec1d7a6eaba7bb5ae12a5f0fe3772/group/externallib.php) y [catálogo](https://github.com/moodle/moodle/blob/cae172ee4aeec1d7a6eaba7bb5ae12a5f0fe3772/lib/db/services.php), Moodle 4.5. Validar versiones y permisos en el Moodle destino antes de producción.

## Continuidad y límites

Colas validation/maintenance separadas; Beat agenda recuperación. PostgreSQL conserva filas, resultados, caché, leases y publicación. Un worker reiniciado continúa lo no comprobado, con hasta tres recuperaciones de lease abandonado. La publicación perdida se recupera pasados 60 segundos y el lease abandonado vence en 600. No hay reintentos Moodle ilimitados. Rate limiting y exclusión por URL canónica se comparten con pruebas de conexión y matrículas de Fase 5; las pruebas administrativas conservan además su cooldown. Consultar enrollment-engine.md.

Las lecturas paginadas son un snapshot de comprobaciones, no una transacción distribuida con Moodle. Los datos y permisos pueden cambiar durante/después del análisis. El límite de escaneo y respuestas de 1 MiB son deliberados; no desactivarlos para forzar un resultado. No se dispone de métricas de CPU/memoria de Moodle. El motor de Fase 5 revalida y reconcilia con autorización explícita para la ejecución.
