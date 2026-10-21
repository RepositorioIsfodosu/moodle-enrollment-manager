# Aceptación antes de producción

Estado: aceptación en Moodle real **pendiente**. Las pruebas locales y de simulador no la sustituyen. No habilitar ENROLLMENT_WRITES_ENABLED ni enviar matrículas reales por el hecho de publicar este repositorio o entorno.

## Prerrequisitos externos

Un responsable debe proporcionar URL pública HTTPS de un Moodle de ensayo compatible, autorización explícita para matricular cuentas/cursos de prueba y credenciales por un mecanismo seguro (configuración cifrada de la aplicación o gestor de secretos, nunca chat). Esta versión bloquea destinos internos/VPN; no relajar SSRF para completar una aceptación. También se necesitan versión Moodle, servicio y funciones habilitadas, permisos del usuario técnico, IDs/identificadores conocidos, curso/rol asignable, ventana de prueba, límites acordados y un responsable de infraestructura.

Configurar DNS/certificado HTTPS real del gestor, claves recuperables, respaldo probado y política de datos. Los valores conservadores de configuración no garantizan capacidad de Moodle. Medir condiciones de ensayo y mantener capacidad para detener el proceso.

## Recorrido a registrar

Usar sólo cuentas/cursos de ensayo autorizados. Guardar fecha UTC, versión del gestor/commit, versión Moodle, condiciones de prueba, IDs de procesos y evidencias verificables sin tokens:

1. Crear administrador e iniciar sesión HTTPS. Verificar cookie HttpOnly/Secure/SameSite, cierre, caducidad y permisos con operador/supervisor/consulta.
2. Crear conexión y probar funciones/permisos. Conceder destino al operador; documentar asignabilidad real del rol y visibilidad completa con referencia y caducidad. Verificar grupos por separado si se utilizarán.
3. Importar CSV pequeño representativo: matrícula nueva, ya existente, usuario inexistente, curso inexistente, duplicado y campos inválidos. Probar varias columnas courseN y los identificadores efectivamente utilizados, perfiles, BOM y metadatos. Comparar filas con operaciones, sin crear usuarios/cursos.
4. Validar y comparar cada resultado con Moodle. Un curso/usuario no visible no demuestra inexistencia; pending exige resolver visibilidad/permisos antes de ejecutar.
5. Habilitar escrituras exclusivamente en el entorno autorizado. Iniciar un trabajo pequeño con límites acordados y confirmar rol/grupo en Moodle, no sólo HTTP 200.
6. Cerrar navegador, consultar desde otra sesión, pausar/reanudar y cancelar cooperativamente. Comprobar que una solicitud enviada puede terminar y que la cancelación no promete reversión.
7. En ensayo, interrumpir worker y broker de forma controlada, registrar momento y evidencia remota, recuperar servicios y comprobar reconciliación sin duplicar envíos inciertos. No simular una caída destructiva en producción.
8. Reintentar sólo errores elegibles y resolver token inválido/permisos insuficientes sin reintentos ilimitados. Probar revocación de concesión y desactivación de conexión.
9. Comparar reportes CSV/XLSX/PDF con registros persistidos y Moodle; verificar filtros, permisos, incertidumbre, metadatos y fecha de observación. Probar límites de exportación.
10. Ensayar respaldo/recuperación de base y claves con escrituras deshabilitadas. Contrastar matrículas posteriores al snapshot antes de reactivar workers.

## Calibración de carga real

Aumentar gradualmente el número de operaciones y concurrencia **sólo** dentro del acuerdo de ensayo. Medir solicitudes por operación, latencia p50/p95, errores, circuitos, retrasos y tiempo de reconciliación. La verificación estándar de participantes puede requerir múltiples páginas por curso: el costo depende de participantes y permisos, no sólo de batch_size. El benchmark local sin pacing no predice ese costo de red ni la capacidad de Moodle.

Registrar límite agregado por instalación, pausas, tamaño de lote, timeout, umbrales y ventana. Detener ante degradación sostenida o umbral acordado; no aumentar automáticamente hasta saturar. Si el responsable ofrece métricas reales de Moodle, usarlas con autorización. Documentar decisión, límites y responsables antes de habilitar producción.

## Cierre

La Fase 8 no se declara cerrada mientras falten esta aceptación, calibración en Moodle y configuración productiva real. Registrar resultados y cualquier impedimento. No marcar pasos no ejecutados como aprobados. No hay despliegue público automático ni aceptación ficticia en este repositorio.
