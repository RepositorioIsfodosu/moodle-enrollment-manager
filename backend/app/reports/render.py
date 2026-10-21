"""Bounded in-memory exports, spreadsheet formula protection and escaped PDF text."""

import csv
import re
from datetime import date, datetime
from io import BytesIO, StringIO
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle


class ReportRenderError(ValueError):
    pass


def display(value):
    if value is None:
        return "Sin datos"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def safe_cell(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    text = display(value)
    # Includes leading whitespace/control characters used to hide formula prefixes.
    return (
        "'" + text
        if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n"))
        else text
    )


def export_report(format, title, generated, filters, summary, columns, rows):
    if format == "xlsx":
        for row in rows:
            for value in row.values():
                text = display(safe_cell(value))
                if len(text) > 32767 or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text):
                    raise ReportRenderError(
                        "Excel no admite una celda del reporte. Utiliza CSV para conservar su contenido."
                    )
    metadata = [
        title,
        "Moodle Enrollment Manager",
        "Generado UTC: " + generated.isoformat(),
        "Filtros: " + filters,
        "Total de operaciones/eventos: " + str(summary["total_operations"]),
        "Estados: " + str(summary["counts"]),
        "Porcentajes: " + str(summary["percentages"]),
        "Fechas de filtro: creación del registro/evento, límites inclusivos.",
        "Confirmación: observación persistida; Sin datos indica ausencia de evidencia fechada.",
    ]
    names = {display(row["proceso"]) for row in rows if "proceso" in row}
    if len(names) == 1:
        metadata.insert(2, "Proceso: " + next(iter(names)))
    if format == "csv":
        stream = StringIO(newline="")
        writer = csv.writer(stream)
        for line in metadata:
            writer.writerow([safe_cell(line)])
        writer.writerow(columns)
        writer.writerows([[safe_cell(row[c]) for c in columns] for row in rows])
        return stream.getvalue().encode("utf-8-sig")
    stream = BytesIO()
    if format == "xlsx":
        book = Workbook()
        info = book.active
        info.title = "Resumen"
        for line in metadata:
            info.append([safe_cell(line)])
        info.column_dimensions["A"].width = 110
        info["A1"].font = Font(bold=True, size=18, color="334155")
        info["A2"].font = Font(bold=True, size=12)
        for row in info:
            row[0].alignment = Alignment(wrap_text=True, vertical="top")
        info.row_dimensions[4].height = 75
        sheet = book.create_sheet("Resultados")
        sheet.append(columns)
        for row in rows:
            sheet.append([safe_cell(row[c]) for c in columns])
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="334155")
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = min(
                48, max(14, len(str(column[0].value)) + 3)
            )
        book.save(stream)
    else:
        styles = getSampleStyleSheet()
        normal = styles["Normal"]
        normal.fontSize = 7
        normal.leading = 10
        doc = SimpleDocTemplate(
            stream,
            pagesize=landscape(A3),
            rightMargin=28,
            leftMargin=28,
            topMargin=28,
            bottomMargin=32,
        )
        elements = [
            Paragraph(escape(line), styles["Heading1"] if i == 0 else normal)
            for i, line in enumerate(metadata)
        ]
        elements.append(Spacer(1, 14))
        data = [[Paragraph(escape(c), normal) for c in columns]] + [
            [Paragraph(escape(display(row[c])), normal) for c in columns] for row in rows
        ]
        table = LongTable(
            data,
            repeatRows=1,
            splitInRow=1,
            colWidths=[(landscape(A3)[0] - 56) / len(columns)] * len(columns),
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        elements.append(table)

        def page_number(canvas, document):
            canvas.setFont("Helvetica", 8)
            canvas.drawRightString(
                landscape(A3)[0] - 28, 16, f"Moodle Enrollment Manager | Página {document.page}"
            )

        doc.build(elements, onFirstPage=page_number, onLaterPages=page_number)
    return stream.getvalue()
