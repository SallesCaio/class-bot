# Class Bot — Automação Teacher

Bot Telegram para auxiliar professores a criar, organizar e exportar planos de aula.

## Funcionalidades

- 📚 Criar planos de aula com categorias e níveis
- 📅 Agenda com notificações automáticas
- 📄 Exportar aula como PDF
- 🌐 Exportar aula como HTML (pronto para impressão)
- 🔍 Buscar e filtrar aulas

## Stack

- Python 3.11+
- python-telegram-bot v22+
- SQLite (banco local)
- fpdf2 (geração de PDF)
- Jinja2 (templates HTML)
- Render (deploy 24/7)

## Setup Local

```bash
pip install -r requirements.txt
python bot.py
```

## Deploy

Deploy automático via Render (Background Worker).
