"""Excel (openpyxl) and PDF (ReportLab) versions of a ReportTable."""

from datetime import date
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.templatetags.ps_format import indian_grouping

from .tables import DATE

FOREST = "244A3C"


def _footer_line(business, user):
    return (f"{business.name} · generated {timezone.localtime():%d %b %Y %H:%M} by "
            f"{user.get_full_name() or user.username} · PetroSmart")


# --- Excel ------------------------------------------------------------------------


def to_xlsx(report, *, business, user):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = report.title[:31]
    sheet.append([report.title])
    sheet["A1"].font = Font(bold=True, size=14)
    sheet.append([f"{business.name} · {report.subtitle}"])
    sheet.append([])
    sheet.append([c.label for c in report.columns])
    header_row = sheet.max_row
    for cell in sheet[header_row]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=FOREST)
        cell.alignment = Alignment(wrap_text=True, vertical="top")

    def write(values, bold=False):
        sheet.append([float(v) if isinstance(v, Decimal) else v for v in values])
        for column, cell in zip(report.columns, sheet[sheet.max_row]):
            if column.numeric:
                cell.number_format = "#,##0.00"
            elif column.kind == DATE and isinstance(cell.value, date):
                cell.number_format = "DD-MM-YYYY"
            if bold:
                cell.font = Font(bold=True)

    for row in report.rows:
        write(row)
    if report.totals:
        write(report.totals, bold=True)
    sheet.append([])
    for note in report.notes:
        sheet.append([note])
    sheet.append([_footer_line(business, user)])

    for index, column in enumerate(report.columns, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = max(12, min(40, len(column.label) + 4))
    sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# --- PDF ----------------------------------------------------------------------------


def _pdf_text(value, column):
    if value is None or value == "":
        return "—" if column.numeric else ""
    if column.numeric:
        return indian_grouping(value)
    if isinstance(value, date):
        return value.strftime("%d-%m-%Y")
    return str(value)


def to_pdf(report, *, business, user):
    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                                 topMargin=12 * mm, bottomMargin=12 * mm, title=report.title, author=business.name)
    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small", fontSize=7.5, leading=9)
    cell = styles["BodyText"].clone("cell", fontSize=7.5, leading=9)
    number = cell.clone("number", alignment=TA_RIGHT)
    head = cell.clone("head", textColor=colors.white, fontName="Helvetica-Bold")
    head_number = head.clone("head_number", alignment=TA_RIGHT)

    # ReportLab's built-in fonts have no ₹ glyph, so PDFs show "Rs.". Text is
    # escaped because ReportLab reads <, > and & as markup.
    def plain(text):
        return escape(text.replace("₹", "Rs.").replace("−", "-"))

    def paragraph(value, column, bold=False, blank_empty=False):
        text = "" if blank_empty and value in (None, "") else _pdf_text(value, column)
        text = plain(text)
        return Paragraph(f"<b>{text}</b>" if bold else text, number if column.numeric else cell)

    data = [[Paragraph(plain(c.label), head_number if c.numeric else head) for c in report.columns]]
    for row in report.rows:
        data.append([paragraph(v, c) for v, c in zip(row, report.columns)])
    if report.totals:
        # Empty cells in the totals row are columns that are not added up, so they stay blank.
        data.append([paragraph(v, c, bold=True, blank_empty=True) for v, c in zip(report.totals, report.columns)])

    table = Table(data, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(f"#{FOREST}")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D3CCBE")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FBFAF6")]),
    ]
    if report.totals:
        style.append(("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F1EEE7")))
    table.setStyle(TableStyle(style))

    story = [
        Paragraph(plain(report.title), styles["Title"]),
        Paragraph(plain(f"{business.name} · {report.subtitle}"), styles["Normal"]),
        Spacer(1, 4 * mm),
        table if report.rows else Paragraph("No records for this period.", styles["Normal"]),
        Spacer(1, 4 * mm),
    ]
    story += [Paragraph(plain(note), small) for note in report.notes]
    story.append(Paragraph(plain(_footer_line(business, user)), small))
    document.build(story)
    return buffer.getvalue()
