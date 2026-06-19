"""
Class Bot — HTML Generator
Generates print-friendly HTML pages from lesson data.
"""

import os
from pathlib import Path
from datetime import datetime
from jinja2 import Template

OUTPUT_DIR = Path(__file__).parent / "tmp"
OUTPUT_DIR.mkdir(exist_ok=True)

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{title}} - Plano de Aula</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  
  body {
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    background: #f0f2f5;
    color: #333;
    padding: 20px;
  }

  .container {
    max-width: 800px;
    margin: 0 auto;
    background: white;
    border-radius: 12px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.1);
    overflow: hidden;
  }

  .header {
    background: linear-gradient(135deg, #667eea, #764ba2);
    color: white;
    padding: 30px;
    text-align: center;
  }

  .header h1 { font-size: 24px; margin-bottom: 8px; }
  .header .meta { opacity: 0.9; font-size: 14px; }

  .content { padding: 30px; }

  .section { margin-bottom: 24px; }
  .section h2 {
    font-size: 16px;
    color: #667eea;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 8px;
    padding-bottom: 4px;
    border-bottom: 2px solid #eee;
  }
  .section p { line-height: 1.7; font-size: 15px; white-space: pre-wrap; }

  .print-bar {
    position: sticky;
    bottom: 0;
    background: white;
    padding: 16px 30px;
    border-top: 1px solid #eee;
    display: flex;
    gap: 12px;
    justify-content: center;
  }

  .btn {
    padding: 12px 32px;
    border: none;
    border-radius: 8px;
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
    transition: transform 0.1s;
  }
  .btn:active { transform: scale(0.97); }

  .btn-print {
    background: linear-gradient(135deg, #667eea, #764ba2);
    color: white;
  }
  .btn-back {
    background: #e0e0e0;
    color: #555;
  }

  .footer {
    text-align: center;
    padding: 12px;
    color: #999;
    font-size: 12px;
  }

  @media print {
    body { background: white; padding: 0; }
    .container { box-shadow: none; border-radius: 0; }
    .print-bar { display: none !important; }
    .header { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  }

  @media (max-width: 600px) {
    body { padding: 0; }
    .container { border-radius: 0; }
    .header { padding: 20px; }
    .header h1 { font-size: 20px; }
    .content { padding: 20px; }
    .btn { padding: 14px 24px; font-size: 16px; }
  }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>📚 {{title}}</h1>
    <div class="meta">
      {{category}} · {{level}} · {{date}}{{time_str}}
    </div>
  </div>

  <div class="content">
    {% if objective %}
    <div class="section">
      <h2>🎯 Objetivo</h2>
      <p>{{objective}}</p>
    </div>
    {% endif %}

    {% if content %}
    <div class="section">
      <h2>📖 Conteúdo</h2>
      <p>{{content}}</p>
    </div>
    {% endif %}

    {% if activities %}
    <div class="section">
      <h2>✏️ Atividades</h2>
      <p>{{activities}}</p>
    </div>
    {% endif %}

    {% if evaluation %}
    <div class="section">
      <h2>📝 Avaliação</h2>
      <p>{{evaluation}}</p>
    </div>
    {% endif %}

    {% if materials %}
    <div class="section">
      <h2>🧰 Materiais</h2>
      <p>{{materials}}</p>
    </div>
    {% endif %}

    {% if notes %}
    <div class="section">
      <h2>💡 Observações</h2>
      <p>{{notes}}</p>
    </div>
    {% endif %}
  </div>

  <div class="print-bar">
    <button class="btn btn-back" onclick="window.close()">← Fechar</button>
    <button class="btn btn-print" onclick="window.print()">🖨️ Imprimir</button>
  </div>

  <div class="footer">
    Gerado pelo Class Bot em {{generated_at}}
  </div>
</div>
</body>
</html>"""


def generate_lesson_html(lesson: dict) -> str:
    """
    Generate an HTML file from lesson data.
    Returns the absolute file path.
    """
    template = Template(HTML_TEMPLATE)

    time_val = lesson.get('time', '')
    time_str = f" às {time_val}" if time_val else ""

    html = template.render(
        title=lesson.get('title', 'Sem título'),
        category=lesson.get('category_name', 'Sem categoria'),
        level=lesson.get('level', 'N/A').capitalize(),
        date=lesson.get('date', 'N/A'),
        time_str=time_str,
        objective=lesson.get('objective', ''),
        content=lesson.get('content', ''),
        activities=lesson.get('activities', ''),
        evaluation=lesson.get('evaluation', ''),
        materials=lesson.get('materials', ''),
        notes=lesson.get('notes', ''),
        generated_at=datetime.now().strftime("%d/%m/%Y %H:%M"),
    )

    safe_title = "".join(c if c.isalnum() or c in '-_' else '_' for c in lesson.get('title', 'aula'))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"aula_{safe_title}_{timestamp}.html"
    filepath = OUTPUT_DIR / filename

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(html)

    return str(filepath)
