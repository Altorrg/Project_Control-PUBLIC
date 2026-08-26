from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any


RESOURCE_DIR = Path(__file__).resolve().parent.parent / "eroforrasok"
DOCUMENT_HEADER_IMAGE = RESOURCE_DIR / "fejlec_minta.png"
DOCUMENT_FONT_REGULAR = RESOURCE_DIR / "DejaVuSans.ttf"
DOCUMENT_FONT_BOLD = RESOURCE_DIR / "DejaVuSans-Bold.ttf"


def _lines(value: object, canvas: Any, font_name: str, font_size: int, width: float) -> list[str]:
    """Wrap text using the PDF font metrics instead of a character count."""
    words = " ".join(str(value or "").split()).split(" ")
    if not words or words == [""]:
        return ["-"]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if current and canvas.stringWidth(candidate, font_name, font_size) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def build_offer_request_pdf(snapshot: dict[str, Any]) -> bytes:
    """Create a deterministic, printable offer-request PDF from a saved snapshot."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
    except ImportError as exc:  # pragma: no cover - deployment dependency check
        raise RuntimeError("A PDF-exporthoz a ReportLab csomag telepítése szükséges.") from exc

    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    regular = "ProjectControlDocument"
    bold = "ProjectControlDocumentBold"
    if regular not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(regular, str(DOCUMENT_FONT_REGULAR)))
    if bold not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(bold, str(DOCUMENT_FONT_BOLD)))

    page_width, page_height = A4
    left, right = 46, 46
    top, bottom = page_height - 34, 48
    y = top

    def page_header() -> None:
        nonlocal y
        header_width = page_width - left - right
        header_height = header_width * 649 / 4129
        header_image = DOCUMENT_HEADER_IMAGE if DOCUMENT_HEADER_IMAGE.exists() else (RESOURCE_DIR / "utiber_fejlec.png")
        if header_image.exists():
            pdf.drawImage(
                str(header_image),
                left,
                y - header_height,
                width=header_width,
                height=header_height,
                preserveAspectRatio=True,
                mask="auto",
            )
            y -= header_height + 8
        else:
            pdf.setFillColorRGB(0.08, 0.20, 0.29)
            pdf.setFont(bold, 13)
            pdf.drawString(left, y - 10, "PROJECT CONTROL")
            pdf.setFont(regular, 9)
            pdf.setFillColorRGB(0.40, 0.40, 0.40)
            pdf.drawRightString(page_width - right, y - 10, "Minta Webalkalmazás")
            y -= 22
        pdf.setStrokeColorRGB(0.20, 0.20, 0.20)
        pdf.setLineWidth(0.8)
        pdf.line(left, y, page_width - right, y)
        y -= 25
        pdf.setFillColorRGB(0.08, 0.20, 0.29)
        pdf.setFont(bold, 18)
        pdf.drawString(left, y, str(snapshot.get("title") or "AJÁNLATKÉRŐ").upper())
        y -= 25

    def ensure_space(required: float) -> None:
        nonlocal y
        if y - required >= bottom:
            return
        pdf.showPage()
        y = top
        page_header()

    def block(label: str, value: object) -> None:
        nonlocal y
        text_lines = _lines(value, pdf, regular, 9.3, page_width - left - right - 4)
        required = 19 + len(text_lines) * 13 + 10
        ensure_space(required)
        pdf.setFillColorRGB(0.93, 0.96, 0.97)
        pdf.roundRect(left, y - 15, page_width - left - right, 17, 2, fill=1, stroke=0)
        pdf.setFillColorRGB(0.08, 0.20, 0.29)
        pdf.setFont(bold, 9.2)
        pdf.drawString(left + 7, y - 4, label)
        y -= 29
        pdf.setFont(regular, 9.3)
        for line in text_lines:
            pdf.drawString(left + 2, y, line)
            y -= 13
        y -= 8

    pdf.setTitle(str(snapshot.get("title") or "Ajánlatkérő"))
    page_header()
    block("Projekt", snapshot.get("project_name"))
    block("Munkaszám", snapshot.get("work_number"))
    block("Szakág", snapshot.get("discipline"))
    block("Címzett", snapshot.get("company_name"))
    block("Előzmények", snapshot.get("history"))
    block("Tervezési feladat részletezése", snapshot.get("task_description"))
    block("Ajánlatkérés", snapshot.get("request_text"))
    block("Ajánlati határidő", snapshot.get("response_deadline"))
    block("Ütemezés", snapshot.get("schedule_text"))
    block("Pénzügyek", snapshot.get("finance_text"))
    block("Megjegyzés", snapshot.get("note"))
    block("Csatolmányok", snapshot.get("attachments"))
    block("Kapcsolat", snapshot.get("contacts"))
    block("Dátum", snapshot.get("document_date"))
    pdf.save()
    return output.getvalue()


def build_offer_request_word(snapshot: dict[str, Any]) -> bytes:
    """Create an editable DOCX offer request from the same saved snapshot as the PDF."""
    try:
        from docx import Document
        from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Pt, RGBColor
    except ImportError as exc:  # pragma: no cover - deployment dependency check
        raise RuntimeError("A Word-exporthoz a python-docx csomag telepítése szükséges.") from exc

    document = Document()
    section = document.sections[0]
    section.top_margin = Pt(42)
    section.bottom_margin = Pt(42)
    section.left_margin = Pt(46)
    section.right_margin = Pt(46)

    normal = document.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(9.5)

    header = document.add_paragraph()
    header.paragraph_format.space_after = Pt(3)
    if DOCUMENT_HEADER_IMAGE.exists():
        header.add_run().add_picture(
            str(DOCUMENT_HEADER_IMAGE),
            width=section.page_width - section.left_margin - section.right_margin,
        )

    separator = document.add_paragraph()
    separator.paragraph_format.space_after = Pt(12)
    paragraph_properties = separator._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom_border = OxmlElement("w:bottom")
    bottom_border.set(qn("w:val"), "single")
    bottom_border.set(qn("w:sz"), "6")
    bottom_border.set(qn("w:space"), "1")
    bottom_border.set(qn("w:color"), "333333")
    borders.append(bottom_border)
    paragraph_properties.append(borders)

    title = document.add_paragraph()
    title.alignment = WD_PARAGRAPH_ALIGNMENT.LEFT
    title.paragraph_format.space_after = Pt(12)
    title_run = title.add_run(str(snapshot.get("title") or "AJÁNLATKÉRŐ").upper())
    title_run.bold = True
    title_run.font.name = "Arial"
    title_run.font.size = Pt(18)
    title_run.font.color.rgb = RGBColor(20, 51, 74)

    def block(label: str, value: object) -> None:
        heading = document.add_paragraph()
        heading.paragraph_format.space_before = Pt(3)
        heading.paragraph_format.space_after = Pt(2)
        heading_run = heading.add_run(label)
        heading_run.bold = True
        heading_run.font.name = "Arial"
        heading_run.font.size = Pt(9.5)
        heading_run.font.color.rgb = RGBColor(20, 51, 74)

        body = document.add_paragraph()
        body.paragraph_format.space_after = Pt(8)
        body_run = body.add_run(str(value or "-"))
        body_run.font.name = "Arial"
        body_run.font.size = Pt(9.5)

    document.core_properties.title = str(snapshot.get("title") or "Ajánlatkérő")
    for label, key in (
        ("Projekt", "project_name"),
        ("Munkaszám", "work_number"),
        ("Szakág", "discipline"),
        ("Címzett", "company_name"),
        ("Előzmények", "history"),
        ("Tervezési feladat részletezése", "task_description"),
        ("Ajánlatkérés", "request_text"),
        ("Ajánlati határidő", "response_deadline"),
        ("Ütemezés", "schedule_text"),
        ("Pénzügyek", "finance_text"),
        ("Megjegyzés", "note"),
        ("Csatolmányok", "attachments"),
        ("Kapcsolat", "contacts"),
        ("Dátum", "document_date"),
    ):
        block(label, snapshot.get(key))

    output = BytesIO()
    document.save(output)
    return output.getvalue()
