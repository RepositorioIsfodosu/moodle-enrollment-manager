# Revisión de seguridad — 21 de octubre de 2026

## Cambios y evidencias

pip-audit 2.9.0 examinó el directorio real de paquetes de la venv, no una resolución vacía. Se identificaron cuatro avisos sobre cryptography 46.0.7: PYSEC-2026-3552, PYSEC-2026-3553, PYSEC-2026-3554 y GHSA-537c-gmf6-5ccf. Se actualizó a cryptography 50.0.2 y el rango declarado >=50,<51. La revisión posterior de 63 distribuciones no reportó vulnerabilidades conocidas. npm audit revisó el grafo frontend (208 dependencias totales) sin avisos. Estos resultados dependen de las bases de avisos consultadas y no demuestran ausencia de vulnerabilidades desconocidas.

La primera invocación de pip-audit --local no encontró distribuciones en el entorno superpuesto de uv; se descartó como evidencia. El resultado válido usa --path .venv/lib/python3.12/site-packages y verifica que se examinaron paquetes. La caché se sitúa en un directorio escribible sin deshabilitar TLS, hashes ni verificación de artefactos. pip-audit es una herramienta de QA temporal, no dependencia runtime del producto.

La regresión automatizada comprueba cifrado/rotación, autenticación, sesiones, CSRF, permisos, SSRF, TLS y estados/recuperación del motor. No se modificaron ni regeneraron las claves reales del entorno al actualizar cryptography. Los tokens ya cifrados conservan formato Fernet; cualquier rotación productiva sigue el procedimiento y los respaldos de claves documentados.

La imagen backend excluye tests y .env* del contexto final para separar fixtures de producción y evitar copiar archivos locales de secretos.

Se añadió overlay de filesystem de sólo lectura, capacidades eliminadas, no-new-privileges, límites y logs rotados; fue arrancado y verificado con los healthchecks de servicios. Se comprobó una plantilla de gateway TLS con certificado efímero local: verificación de CA y hostname activas, readiness 200 y HSTS. No se instaló un certificado público ni se expuso un despliegue a Internet.

Se optimizó el rechazo de exportaciones demasiado grandes: el conteo se comprueba dentro del snapshot antes de cargar filas en memoria. Se conserva HTTP 413 y nunca se trunca la descarga. Los límites no sustituyen supervisión de memoria ni una prueba representativa de exportaciones mayores.

Se implementó respaldo binario con archivo nuevo, permisos privados donde aplica, fsync y SHA-256; restauración sólo en contenedor temporal sin red, eliminado con su volumen. Prueba con datos ficticios: esquema 0006, conexión cifrada, CSV original de 24 bytes, trabajo, registro y auditoría recuperados. No se restauró la aplicación ni se copiaron sus secretos a fixtures.

## Alcance y riesgos que permanecen

- No es una auditoría externa, un pentest completo ni un escaneo de todas las bibliotecas del sistema operativo de las imágenes. No hay aceptación real de Moodle, calibración de su carga ni medición de capacidad productiva.
- El token Moodle está cifrado en PostgreSQL, pero un operador con acceso a proceso/claves puede descifrarlo; hace falta gestión de secretos y copias protegidas de claves.
- El Compose de desarrollo utiliza el rol administrador inicial de PostgreSQL. El overlay productivo por sí solo no cambia ese rol; compose.runtime-role.yaml (0.8.1) añade la separación, matriz explícita y comprobaciones documentadas en runtime-database.md. Aplicarlo al destino productivo tras aprovisionar sus credenciales.
- El gateway real, DNS, certificados, red de salida, monitorización y políticas de respaldo/retención corresponden al entorno productivo. La configuración local no los demuestra.
- Se mantiene la comprobación SSRF sin excepciones para IPs internas. No permitir destinos privados para saltar esta restricción; un Moodle interno requiere diseño de una política autorizada adicional.
- La API ignora cabeceras proxy no confiables. El límite por IP de conexión será compartido detrás de Nginx; el gateway aplica un límite adicional por IP real sólo cuando su cadena de confianza esté configurada correctamente.
- No hay MFA ni recuperación de contraseña por correo. No hay borrado global automático de CSV/historial ni política legal universal. La purga implementada conserva originales e historial y sólo elimina transitorios elegibles mediante ejecución explícita.
- Backups y descargas contienen datos personales. Los dumps no se cifran automáticamente. La autenticidad externa, almacenamiento inmutable y RPO/RTO requieren procedimientos organizativos.
- Restaurar un snapshot antiguo no revierte Moodle. Reconciliar operaciones posteriores al respaldo antes de reactivar escrituras; ver operations.md.

## Repetir auditorías

Desde backend, con entorno instalado: `uv run --with pip-audit==2.9.0 pip-audit --path .venv/lib/python3.12/site-packages`. En esta nube usar PIP_CACHE_DIR y --cache-dir sobre /workspace para cachés escribibles; conservar proxy/CA existentes. Desde frontend: `npm audit --audit-level=low`. Revisar avisos y compatibilidad, actualizar lockfiles de forma controlada y repetir las pruebas afectadas. CI incluye ambas comprobaciones y falla si se reportan vulnerabilidades.
