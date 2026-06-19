"""
Class Bot — PDF Generator
Generates print-ready PDF files from lesson data.
"""

import os
from pathlib import Path
from datetime import datetime
from fpdf import FPDF

OUTPUT_DIR = Path(__file__).parent / "tmp"
OUTPUT_DIR.mkdir(exist_ok=True)


def _safe_text(text: str) -> str:
    """Make text safe for PDF output — remove emojis and replace special chars."""
    if not text:
        return ""
    # Remove emojis (Unicode ranges for emoji blocks)
    import re
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"   # symbols & pictographs
        "\U0001F680-\U0001F6FF"   # transport & map
        "\U0001F1E0-\U0001F1FF"   # flags
        "\U00002702-\U000027B0"   # dingbats
        "\U000024C2-\U0001F251"   # enclosed characters
        "\U0001F900-\U0001F9FF"   # supplemental symbols
        "\U0001FA00-\U0001FA6F"   # chess symbols
        "\U0001FA70-\U0001FAFF"   # symbols extended-A
        "\U00002600-\U000026FF"   # misc symbols
        "\U0000FE00-\U0000FE0F"   # variation selectors
        "]+",
        flags=re.UNICODE,
    )
    text = emoji_pattern.sub("", text)

    # Replace special Unicode chars with ASCII equivalents
    replacements = {
        "\u2014": "-",    # em dash
        "\u2013": "-",    # en dash
        "\u2022": "*",    # bullet
        "\u2026": "...",  # ellipsis
        "\u201c": '"',   # left double quote
        "\u201d": '"',   # right double quote
        "\u2018": "'",   # left single quote
        "\u2019": "'",   # right single quote
        "\u00a0": " ",   # non-breaking space
    }
    for orig, repl in replacements.items():
        text = text.replace(orig, repl)
    return text


class LessonPDF(FPDF):
    """Custom PDF class for lesson plans."""

    def header(self):
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(102, 126, 234)
        self.cell(0, 10, "Class Bot - Aula", ln=True, align="C")
        self.set_draw_color(102, 126, 234)
        self.set_line_width(0.5)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(6)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(150)
        self.cell(
            0, 10,
            f'Gerado em {datetime.now().strftime("%d/%m/%Y %H:%M")} | Pagina {self.page_no()}',
            align="C",
        )


def generate_lesson_pdf(lesson: dict) -> str:
    """
    Generate a PDF file from lesson data.
    Returns the absolute file path.
    """
    pdf = LessonPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    # Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(50, 50, 50)
    title = _safe_text(lesson.get("title", "Sem titulo"))
    pdf.cell(0, 12, title, ln=True)
    pdf.ln(2)

    # Meta info box
    pdf.set_fill_color(245, 247, 250)
    pdf.set_draw_color(200, 200, 200)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(80, 80, 80)

    category = lesson.get("category_name", "Sem categoria")
    level = lesson.get("level", "N/A").capitalize()
    date = lesson.get("date", "")
    time_val = lesson.get("time", "")

    meta_parts = []
    if category and category != "Sem categoria":
        meta_parts.append(f"Categoria: {category}")
    if level and level != "N/A":
        meta_parts.append(f"Nivel: {level}")
    if date:
        date_str = date
        if time_val:
            date_str += f" as {time_val}"
        meta_parts.append(f"Data: {date_str}")

    meta_text = "  |  ".join(meta_parts) if meta_parts else ""
    if meta_text:
        pdf.multi_cell(0, 7, _safe_text(meta_text), fill=True)
        pdf.ln(6)

    # Sections
    sections = [
        ("Objetivo", lesson.get("objective", "")),
        ("Conteudo", lesson.get("content", "")),
        ("Atividades", lesson.get("activities", "")),
        ("Avaliacao", lesson.get("evaluation", "")),
        ("Materiais", lesson.get("materials", "")),
        ("Observacoes", lesson.get("notes", "")),
    ]

    for section_title, section_content in sections:
        if not section_content or not section_content.strip():
            continue

        # Section header
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(102, 126, 234)
        pdf.cell(0, 8, _safe_text(section_title), ln=True)

        # Section content
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(50, 50, 50)
        pdf.multi_cell(0, 6, _safe_text(section_content))
        pdf.ln(4)

    # Save
    safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in lesson.get("title", "aula"))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"aula_{safe_title}_{timestamp}.pdf"
    filepath = OUTPUT_DIR / filename
    pdf.output(str(filepath))

    return str(filepath)
