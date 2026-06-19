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


class LessonPDF(FPDF):
    """Custom PDF class for lesson plans."""

    def __init__(self):
        super().__init__()
        # Embed a Unicode-compatible font
        font_dir = Path(__file__).parent / "fonts"
        font_dir.mkdir(exist_ok=True)
        self.font_dir = font_dir
        self._setup_fonts()

    def _setup_fonts(self):
        """Setup fonts — use built-in Helvetica for ASCII, fallback for Unicode."""
        # fpdf2 built-in fonts: Helvetica, Times, Courier
        # For PT-BR accents we use a simple approach: replace common chars
        pass

    def header(self):
        self.set_font('Helvetica', 'B', 14)
        self.set_text_color(102, 126, 234)
        self.cell(0, 10, 'Class Bot - Plano de Aula', ln=True, align='C')
        self.set_draw_color(102, 126, 234)
        self.set_line_width(0.5)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(6)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(150)
        self.cell(0, 10, f'Gerado em {datetime.now().strftime("%d/%m/%Y %H:%M")} | Pagina {self.page_no()}', align='C')


def _clean(text: str) -> str:
    """Replace PT-BR accented chars for Helvetica compatibility."""
    replacements = {
        'á': 'a', 'à': 'a', 'â': 'a', 'ã': 'a', 'ä': 'a',
        'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
        'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
        'ó': 'o', 'ò': 'o', 'ô': 'o', 'õ': 'o', 'ö': 'o',
        'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u',
        'ç': 'c', 'ñ': 'n',
        'Á': 'A', 'À': 'A', 'Â': 'A', 'Ã': 'A',
        'É': 'E', 'È': 'E', 'Ê': 'E',
        'Í': 'I', 'Ì': 'I',
        'Ó': 'O', 'Ò': 'O', 'Ô': 'O', 'Õ': 'O',
        'Ú': 'U', 'Ù': 'U',
        'Ç': 'C',
    }
    for orig, repl in replacements.items():
        text = text.replace(orig, repl)
    return text


def generate_lesson_pdf(lesson: dict) -> str:
    """
    Generate a PDF file from lesson data.
    Returns the absolute file path.
    """
    pdf = LessonPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    # Title
    pdf.set_font('Helvetica', 'B', 16)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(0, 12, _clean(lesson.get('title', 'Sem titulo')), ln=True)
    pdf.ln(2)

    # Meta info box
    pdf.set_fill_color(245, 247, 250)
    pdf.set_draw_color(200, 200, 200)
    pdf.set_font('Helvetica', '', 10)
    pdf.set_text_color(80, 80, 80)

    meta_y = pdf.get_y()
    category = lesson.get('category_name', 'Sem categoria')
    level = lesson.get('level', 'N/A').capitalize()
    date = lesson.get('date', 'N/A')
    time_val = lesson.get('time', '')

    meta_text = _clean(f"Categoria: {category}  |  Nivel: {level}  |  Data: {date}  {time_val}")
    pdf.multi_cell(0, 7, meta_text, fill=True)
    pdf.ln(6)

    # Sections
    sections = [
        ('Objetivo', lesson.get('objective', '')),
        ('Conteudo', lesson.get('content', '')),
        ('Atividades', lesson.get('activities', '')),
        ('Avaliacao', lesson.get('evaluation', '')),
        ('Materiais', lesson.get('materials', '')),
        ('Observacoes', lesson.get('notes', '')),
    ]

    for section_title, section_content in sections:
        if not section_content or not section_content.strip():
            continue

        # Section header
        pdf.set_font('Helvetica', 'B', 12)
        pdf.set_text_color(102, 126, 234)
        pdf.cell(0, 8, _clean(section_title), ln=True)

        # Section content
        pdf.set_font('Helvetica', '', 11)
        pdf.set_text_color(50, 50, 50)
        pdf.multi_cell(0, 6, _clean(section_content))
        pdf.ln(4)

    # Save
    safe_title = "".join(c if c.isalnum() or c in '-_' else '_' for c in lesson.get('title', 'aula'))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"aula_{safe_title}_{timestamp}.pdf"
    filepath = OUTPUT_DIR / filename
    pdf.output(str(filepath))

    return str(filepath)
