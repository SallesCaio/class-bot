# Class Bot — Automação Teacher

Bot Telegram para auxiliar professores a criar, organizar e exportar planos de aula com IA.

## Funcionalidades

- 🤖 **Criar aulas com IA** — diga o tópico e a IA monta o plano completo
- 📚 Criar planos de aula manualmente com categorias e níveis
- 📅 Agenda com notificações automáticas (1h e 15min antes)
- 📄 Exportar aula como PDF
- 🌐 Exportar aula como HTML (pronto para impressão)
- 🔍 Buscar e filtrar aulas
- 📁 Categorias personalizadas
- 📊 Estatísticas

## Stack

- Python 3.11+
- python-telegram-bot v22+
- SQLite (banco local)
- fpdf2 (geração de PDF)
- Jinja2 (templates HTML)
- OpenRouter API (IA — Owl Alpha)
- Render (deploy 24/7)

## Setup Local

```bash
pip install -r requirements.txt
```

Crie um arquivo `.env` com:
```
BOT_TOKEN=SEU_TOKEN_AQUI
OPENROUTER_API_KEY=SUA_KEY_AQUI
```

```bash
python bot.py
```

## Configurar IA (OpenRouter)

1. Crie conta em [openrouter.ai](https://openrouter.ai)
2. Vá em **Keys** → Create API Key
3. Adicione no `.env`: `OPENROUTER_API_KEY=sua-key`
4. Reinicie o bot

Modelo usado: `openrouter/owl-alpha` (gratuito)

## Deploy

Deploy automático via Render (Background Worker).
Conecte o GitHub repo e adicione as env vars `BOT_TOKEN` e `OPENROUTER_API_KEY`.
