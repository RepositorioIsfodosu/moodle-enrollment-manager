import json
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.core.config import get_settings
from app.db.session import get_session
from app.models import User
from app.reports.query import TITLES, Filters, projection, report_query, summary
from app.reports.render import ReportRenderError, export_report
from app.services.audit import audit

router = APIRouter(prefix="/reports", tags=["reports"])
reader = require_permission("reports:read")

FILTER_DOCS = {
    "parameters": [
        {"name": name, "in": "query", "required": False, "schema": schema}
        for name, schema in Filters.model_json_schema()["properties"].items()
    ]
}


def parse_filters(request: Request):
    allowed = set(Filters.model_fields) | {"offset", "limit", "format"}
    if any(
        k not in allowed or len(request.query_params.getlist(k)) > 1 for k in request.query_params
    ):
        raise HTTPException(422, "Filtro desconocido o repetido")
    try:
        return Filters.model_validate(
            {k: v for k, v in request.query_params.items() if k in Filters.model_fields and v != ""}
        )
    except ValidationError:
        raise HTTPException(
            422,
            "Filtros no válidos: comprueba fechas con zona horaria, estados y campos del reporte",
        ) from None


class ReportView(BaseModel):
    title: str
    generated_at: datetime
    filters: dict[str, Any]
    summary: dict[str, Any]
    columns: list[str]
    items: list[dict[str, Any]]
    total: int
    offset: int
    limit: int
    export_limit: int


def dataset(db, actor, filters, offset, limit):
    # A single PostgreSQL snapshot keeps totals, groups and displayed rows consistent.
    with Session(db.get_bind().execution_options(isolation_level="REPEATABLE READ")) as snapshot:
        q = report_query(snapshot, actor, filters)
        stats = summary(snapshot, q, filters.kind)
        p = projection(q, filters.kind).subquery()
        total = snapshot.scalar(select(func.count()).select_from(p))
        columns = list(p.c.keys())
        order_columns = columns if filters.kind in {"course", "campus"} else columns[:1]
        order = [p.c[c].asc().nulls_last() for c in order_columns]
        rows = [
            dict(r)
            for r in snapshot.execute(
                select(p).order_by(*order).offset(offset).limit(limit)
            ).mappings()
        ]
    return stats, columns, rows, total


@router.get("", response_model=ReportView, openapi_extra=FILTER_DOCS)
def preview(
    filters: Filters = Depends(parse_filters),
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    actor: User = Depends(reader),
    db: Session = Depends(get_session),
):
    stats, columns, rows, total = dataset(db, actor, filters, offset, limit)
    return ReportView(
        title=TITLES[filters.kind],
        generated_at=datetime.now(UTC),
        filters=filters.model_dump(mode="json", exclude_none=True),
        summary=stats,
        columns=columns,
        items=rows,
        total=total,
        offset=offset,
        limit=limit,
        export_limit=get_settings().report_export_max_rows,
    )


@router.get("/export", openapi_extra=FILTER_DOCS)
def export(
    filters: Filters = Depends(parse_filters),
    format: Literal["csv", "xlsx", "pdf"] = "csv",
    actor: User = Depends(reader),
    db: Session = Depends(get_session),
):
    maximum = get_settings().report_export_max_rows
    stats, columns, rows, total = dataset(db, actor, filters, 0, maximum + 1)
    if total > maximum:
        raise HTTPException(
            413, f"El reporte supera {maximum} filas. Reduce el período o aplica filtros."
        )
    generated = datetime.now(UTC)
    safe_filters = filters.model_dump(mode="json", exclude_none=True)
    try:
        body = export_report(
            format,
            TITLES[filters.kind],
            generated,
            json.dumps(safe_filters, ensure_ascii=False),
            stats,
            columns,
            rows,
        )
    except ReportRenderError as error:
        raise HTTPException(422, str(error)) from None

    audit(
        db,
        "report.exported",
        actor.id,
        kind=filters.kind,
        format=format,
        rows=total,
        operations=stats["total_operations"],
    )
    db.commit()
    mime = {
        "csv": "text/csv; charset=utf-8",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pdf": "application/pdf",
    }[format]
    return Response(
        body,
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="reporte-{filters.kind}-{generated:%Y%m%dT%H%M%SZ}.{format}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
