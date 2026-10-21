import csv
import hashlib
import io
import json
import re
import unicodedata

from email_validator import EmailNotValidError, validate_email

from app.schemas.csv import CourseColumn, Mapping


class CsvError(ValueError):
    pass


MESSAGES = {
    "invalid_email": "Correo electrónico con formato no válido",
    "suspension_not_disclosed": "Moodle no expuso el estado de suspensión del usuario",
    "missing_user": "Identificador de usuario vacío",
    "missing_course": "Identificador de curso vacío",
    "invalid_course_id": "El ID de curso debe ser entero positivo",
    "invalid_group_id": "El ID de grupo debe ser entero positivo",
    "missing_role": "Falta rol y no hay rol predeterminado configurado",
    "unknown_role": "Rol no numérico sin correspondencia en el perfil",
    "duplicate_operation": "Operación repetida dentro de la importación",
    "cross_file_duplicate": "Operación repetida entre importaciones del proceso",
    "resolved_duplicate": "Identificadores distintos resuelven a la misma operación Moodle",
    "user_not_found_or_not_visible": "Usuario no encontrado o no visible para el servicio",
    "course_not_found_or_not_visible": "Curso no encontrado o no visible para el servicio",
    "ambiguous_user": "Identificador de usuario ambiguo",
    "ambiguous_course": "Identificador de curso ambiguo",
    "ambiguous_group": "Identificador de grupo ambiguo",
    "group_not_found": "Grupo no encontrado en el curso",
    "enrollment_visibility_unverified": "Falta evidencia de visibilidad completa de matrículas en el curso",
    "role_assignability_unverified": "Falta revisión vigente del administrador sobre el rol asignable",
    "group_permission_unverified": "Falta evidencia de autorización para gestionar grupos",
    "enrollment_scan_limit": "No se pudo completar la consulta de matrículas dentro del límite",
    "enrollment_details_unavailable": "Moodle no expuso roles/grupos necesarios para comprobar la matrícula",
    "enrollment_function_unavailable": "El servicio no anuncia la función de matriculación manual",
    "group_function_unavailable": "El servicio no anuncia la función de asignación de grupos",
    "function_unavailable": "El servicio no anuncia una función requerida para esta comprobación",
    "course_lookup_warning": "Moodle devolvió advertencias al resolver el curso",
    "suspended_user": "Usuario suspendido; requiere revisión",
}


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def parse_csv(content: bytes, encoding: str, delimiter: str, max_rows: int):
    if not content or b"\x00" in content:
        raise CsvError("Archivo vacío o contenido binario no admitido")
    try:
        text = content.decode("utf-8-sig" if encoding == "utf-8" else encoding)
    except UnicodeError:
        raise CsvError(
            "Codificación no válida; seleccionar UTF-8, CP1252 o Latin-1 explícitamente"
        ) from None
    if any(ord(c) < 32 and c not in "\r\n\t" for c in text):
        raise CsvError("Caracteres de control no admitidos")
    try:
        separator = (
            csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
            if delimiter == "auto"
            else delimiter
        )
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=separator, strict=True)
        headers = [unicodedata.normalize("NFC", x.strip()) for x in next(reader)]
        if not headers or len(headers) > 200 or any(not x or len(x) > 100 for x in headers):
            raise CsvError("Encabezados vacíos, demasiado largos o más de 200 columnas")
        if len({x.casefold() for x in headers}) != len(headers):
            raise CsvError("Encabezados duplicados o ambiguos")
        rows = []
        cells = 0
        for number, values in enumerate(reader, 2):
            if not values or all(not v.strip() for v in values):
                raise CsvError(f"Registro CSV {number}: fila vacía")
            if len(values) != len(headers):
                raise CsvError(f"Registro CSV {number}: número de columnas incompatible")
            if any(len(v) > 4096 for v in values):
                raise CsvError(f"Registro CSV {number}: campo mayor de 4096 caracteres")
            cells += len(values)
            if len(rows) >= max_rows or cells > 1000000:
                raise CsvError("Límite de filas o celdas excedido")
            rows.append(dict(zip(headers, values, strict=True)))
        if not rows:
            raise CsvError("CSV sin registros de datos")
        return headers, rows, separator
    except (csv.Error, StopIteration):
        raise CsvError("Estructura CSV no válida; revisar delimitador y comillas") from None


def resolved_mapping(mapping: Mapping, headers: list[str]) -> Mapping:
    result = mapping.model_copy(deep=True)
    lookup = {x.casefold(): x for x in headers}
    if result.user_column is None:
        for field in (result.user_field, "username", "email", "idnumber"):
            if field in lookup:
                result.user_column, result.user_field = lookup[field], field
                break
    if not result.courses:
        slots = sorted(
            (int(match[1]), header)
            for header in headers
            if (match := re.fullmatch(r"course([1-9][0-9]*)", header, re.IGNORECASE))
        )
        result.courses = [
            CourseColumn(course=header, role=lookup.get(f"role{n}"), group=lookup.get(f"group{n}"))
            for n, header in slots
        ]
    columns = [result.user_column, *result.metadata_columns.values()]
    for slot in result.courses:
        columns.extend([slot.course, slot.role, slot.group])
    if not result.user_column or not result.courses or len(result.courses) > 50:
        raise CsvError("Configurar columna de usuario y entre 1 y 50 columnas de curso")
    if len({slot.course for slot in result.courses}) != len(result.courses):
        raise CsvError("Columnas de curso repetidas en el perfil")
    if any(column is not None and column not in headers for column in columns):
        raise CsvError("El perfil referencia una columna inexistente")
    return result


def clean(value: str, casefold=False) -> str:
    value = unicodedata.normalize("NFC", value.strip())
    return value.casefold() if casefold else value


def positive_id(value: str) -> int | None:
    if not re.fullmatch(r"[0-9]{1,10}", value):
        return None
    number = int(value)
    return number if 0 < number <= 2147483647 else None


def normalize(rows, mapping: Mapping, max_operations: int):
    seen, operations = set(), []
    for number, row in enumerate(rows, 2):
        emitted = False
        for slot, columns in enumerate(mapping.courses, 1):
            course = clean(row[columns.course])
            role_text = clean(row[columns.role]) if columns.role else ""
            group = clean(row[columns.group]) if columns.group else ""
            # Empty courseN without accompanying data is an unused slot, not an error.
            if not course and not role_text and not group and len(mapping.courses) > 1:
                continue
            emitted = True
            user = clean(row[mapping.user_column], mapping.user_field in ("username", "email"))
            role = positive_id(role_text) if role_text else mapping.default_role_id
            if role_text and role is None:
                role = mapping.role_map.get(role_text)
            code = None
            if not user:
                code = "missing_user"
            elif not course:
                code = "missing_course"
            elif mapping.course_field == "id" and positive_id(course) is None:
                code = "invalid_course_id"
            elif group and mapping.group_field == "id" and positive_id(group) is None:
                code = "invalid_group_id"
            elif role is None:
                code = "unknown_role" if role_text else "missing_role"
            if not code and mapping.user_field == "email":
                try:
                    user = validate_email(user, check_deliverability=False).normalized.casefold()
                except EmailNotValidError:
                    code = "invalid_email"
            if mapping.course_field == "id" and positive_id(course):
                course = str(positive_id(course))
            if group and mapping.group_field == "id" and positive_id(group):
                group = str(positive_id(group))
            payload = {
                "user_field": mapping.user_field,
                "user_identifier": user,
                "course_field": mapping.course_field,
                "course_identifier": course,
                "role_id": role,
                "group_field": mapping.group_field,
                "group_identifier": group,
                "metadata": {
                    key: clean(row[column]) for key, column in mapping.metadata_columns.items()
                },
            }
            key = digest({k: v for k, v in payload.items() if k != "metadata"})
            status = "invalid" if code else "pending"
            if not code and key in seen:
                status, code = "duplicate", "duplicate_operation"
            elif not code:
                seen.add(key)
            operations.append(
                {
                    "source_row": number,
                    "slot": slot,
                    "payload": payload,
                    "operation_key": key,
                    "local_status": status,
                    "error_code": code,
                }
            )
            if len(operations) > max_operations:
                raise CsvError("Límite de operaciones normalizadas excedido")
        if not emitted:
            payload = {
                "user_field": mapping.user_field,
                "user_identifier": clean(row[mapping.user_column]),
                "course_field": mapping.course_field,
                "course_identifier": "",
                "role_id": None,
                "group_field": mapping.group_field,
                "group_identifier": "",
                "metadata": {},
            }
            operations.append(
                {
                    "source_row": number,
                    "slot": 0,
                    "payload": payload,
                    "operation_key": digest(payload),
                    "local_status": "invalid",
                    "error_code": "missing_course",
                }
            )
    if len(operations) > max_operations:
        raise CsvError("Límite de operaciones normalizadas excedido")
    return operations
