import pytest

from app.schemas.csv import Mapping
from app.services.csv_parser import CsvError, normalize, parse_csv, resolved_mapping


def normalized(content, mapping=None, delimiter=",", encoding="utf-8", maximum=100):
    headers, rows, _ = parse_csv(content, encoding, delimiter, 100)
    return normalize(rows, resolved_mapping(mapping or Mapping(), headers), maximum)


def test_bom_multiple_courses_roles_groups_and_duplicate_rows():
    content = b"\xef\xbb\xbfusername;course1;role1;group1;course2;role2\nAlice;BIO;5;G1;CHEM;6\nalice;BIO;5;G1;;\n"
    rows = normalized(content, delimiter=";")
    assert len(rows) == 3
    assert rows[0]["payload"]["user_identifier"] == "alice"
    assert rows[0]["payload"]["group_identifier"] == "G1"
    assert rows[1]["payload"]["course_identifier"] == "CHEM"
    assert rows[2]["local_status"] == "duplicate"
    assert rows[2]["source_row"] == 3


def test_explicit_mapping_role_alias_ids_and_metadata():
    mapping = Mapping(
        user_column="Usuario",
        user_field="idnumber",
        course_field="id",
        default_role_id=5,
        courses=[{"course": "Curso", "role": "Rol"}],
        role_map={"student": 5},
        metadata_columns={"campus": "Recinto"},
    )
    rows = normalized(b"Usuario,Curso,Rol,Recinto\nA,00101,student,Norte\n", mapping)
    assert rows[0]["payload"] == {
        "user_field": "idnumber",
        "user_identifier": "A",
        "course_field": "id",
        "course_identifier": "101",
        "role_id": 5,
        "group_field": "name",
        "group_identifier": "",
        "metadata": {"campus": "Norte"},
    }


@pytest.mark.parametrize(
    "body,code",
    [
        (b"username,course1,role1\n,BIO,5\n", "missing_user"),
        (b"username,course1,role1\nalice,,5\n", "missing_course"),
        (b"username,course1\nalice,BIO\n", "missing_role"),
        (b"username,course1,role1\nalice,BIO,student\n", "unknown_role"),
        (b"email,course1,role1\nwrong,BIO,5\n", "invalid_email"),
    ],
)
def test_invalid_operations_are_preserved(body, code):
    rows = normalized(body)
    assert len(rows) == 1 and rows[0]["local_status"] == "invalid"
    assert rows[0]["error_code"] == code


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"a,a\n1,2\n",
        b"a,A\n1,2\n",
        b"a,b\n1\n",
        b"a,b\n\n",
        b"a,b\n",
        b"a,b\n1,2\x00",
        b'a,b\n1,"unterminated',
        b"a,b\n1,\xff",
        b"a,b\n1," + b"X" * 4097,
    ],
)
def test_bad_content_rejected(body):
    with pytest.raises(CsvError):
        parse_csv(body, "utf-8", ",", 100)


def test_encoding_is_explicit_and_delimiter_detection_is_bounded():
    body = "username|course1|role1\njosé|BIO|5\n".encode("cp1252")
    headers, rows, delimiter = parse_csv(body, "cp1252", "auto", 100)
    assert headers == ["username", "course1", "role1"] and delimiter == "|"
    assert rows[0]["username"] == "josé"
    with pytest.raises(CsvError):
        parse_csv(body, "utf-8", "auto", 100)


def test_limits_missing_columns_and_empty_multi_course_row():
    with pytest.raises(CsvError):
        parse_csv(b"a,b\n1,2\n3,4\n", "utf-8", ",", 1)
    with pytest.raises(CsvError):
        normalized(b"username,course1,role1\na,BIO,5\nb,BIO,5\n", maximum=1)
    with pytest.raises(CsvError):
        normalized(b"username,course1,role1\na,BIO,5\n", Mapping(user_column="missing"))
    row = normalized(b"username,course1,course2\nalice,,\n")[0]
    assert row["error_code"] == "missing_course"


def test_numeric_course_and_group_reject_invalid_ids():
    assert (
        normalized(b"username,course1,role1\na,nope,5\n", Mapping(course_field="id"))[0][
            "error_code"
        ]
        == "invalid_course_id"
    )
    assert (
        normalized(b"username,course1,role1,group1\na,BIO,5,nope\n", Mapping(group_field="id"))[0][
            "error_code"
        ]
        == "invalid_group_id"
    )


def test_quoted_fields_multiline_and_no_shared_default_mutation():
    body = b'username,course1,role1,note\nalice,BIO,5,"line1\nline2"\n'
    _, rows, _ = parse_csv(body, "utf-8", ",", 100)
    assert rows[0]["note"] == "line1\nline2"
    mapping = Mapping()
    assert resolved_mapping(mapping, ["username", "course1"]).courses
    assert mapping.courses == []
