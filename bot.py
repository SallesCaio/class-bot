"""
Class Bot — Automação Teacher
Telegram bot for teachers to create, manage, and export lesson plans.

Stack: python-telegram-bot v22+, SQLite, fpdf2, Jinja2
Deploy: Render (Background Worker)
"""

import os
import logging
import json
from datetime import datetime, timedelta
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, ContextTypes,
)

from database import (
    init_db, upsert_user,
    add_category, get_categories, delete_category,
    add_lesson, get_lesson, get_lessons, delete_lesson, search_lessons,
    add_schedule, get_schedules, get_pending_notifications, mark_notified,
)
from pdf_generator import generate_lesson_pdf
from html_generator import generate_lesson_html

# ─── Load .env file ──────────────────────────────────────────────
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)

# ─── Configuration ───────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Conversation States ─────────────────────────────────────────
# Lesson creation with AI
(AI_TOPIC, AI_LEVEL, AI_CATEGORY, AI_CONFIRM) = range(4)

# Schedule creation
(S_DATE, S_TIME) = range(4, 6)

# Category management
(C_NAME,) = range(6, 7)


# ─── Keyboards ───────────────────────────────────────────────────
def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🤖 Criar com IA", callback_data="menu_create_ai"),
            InlineKeyboardButton("📚 Minhas Aulas", callback_data="menu_lessons"),
        ],
        [
            InlineKeyboardButton("📅 Agenda", callback_data="menu_schedule"),
            InlineKeyboardButton("🔍 Buscar", callback_data="menu_search"),
        ],
        [
            InlineKeyboardButton("📁 Categorias", callback_data="menu_categories"),
            InlineKeyboardButton("📊 Estatísticas", callback_data="menu_stats"),
        ],
    ])


def level_keyboard(prefix: str = "lvl") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Iniciante", callback_data=f"{prefix}_iniciante")],
        [InlineKeyboardButton("🟡 Intermediário", callback_data=f"{prefix}_intermediario")],
        [InlineKeyboardButton("🔴 Avançado", callback_data=f"{prefix}_avancado")],
    ])


def category_inline_keyboard(user_id: int, include_new: bool = False) -> InlineKeyboardMarkup:
    cats = get_categories(user_id)
    buttons = []
    for cat in cats:
        buttons.append([InlineKeyboardButton(
            f"📁 {cat['name']}", callback_data=f"cat_{cat['id']}"
        )])
    if include_new:
        buttons.append([InlineKeyboardButton("➕ Nova categoria", callback_data="cat_new")])
    buttons.append([InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="menu_back")])
    return InlineKeyboardMarkup(buttons)


def back_menu_button() -> list:
    """Single back-to-menu button row."""
    return [InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="menu_back")]


# ─── AI Lesson Generator ─────────────────────────────────────────

# ─── AI Lesson Generator ─────────────────────────────────────────

def generate_lesson_with_ai(topic: str, level: str, category: str = "") -> dict | None:
    """
    Generate a lesson plan using available AI provider.
    Priority: OpenRouter (Owl Alpha) → OpenAI → Groq
    """
    system_prompt = """Você é um assistente especializado em criar planos de aula para professores.
Gere um plano de aula completo e bem estruturado.

Responda APENAS com um JSON válido no formato:
{
    "objetivo": "O que o aluno vai aprender (2-3 frases)",
    "conteudo": "Conteúdo detalhado da aula (tópicos, conceitos)",
    "atividades": "Atividades práticas e exercícios (lista)",
    "avaliacao": "Como avaliar o aprendizado (2-3 frases)",
    "materiais": "Materiais necessários (lista)",
    "observacoes": "Dicas para o professor (opcional)"
}

Regras:
- Linguagem clara e objetiva em português brasileiro
- Adapte ao nível solicitado (iniciante/intermediário/avançado)
- Seja prático — professor precisa usar na vida real
- Máximo 200 palavras por campo"""

    user_message = f"Tópico: {topic}\nNível: {level}"
    if category:
        user_message += f"\nCategoria: {category}"

    # ── 1. Try OpenRouter (Owl Alpha) ──
    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    if or_key:
        try:
            from openai import OpenAI
            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=or_key,
            )
            response = client.chat.completions.create(
                model="openrouter/owl-alpha",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=2000,
                temperature=0.7,
            )
            content = response.choices[0].message.content
            # Try to extract JSON from response
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                # Try to find JSON in the text
                import re
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    return json.loads(match.group())
                logger.error(f"OpenRouter: could not parse JSON from response: {content[:200]}")
        except ImportError:
            logger.info("openai package not installed, skipping OpenRouter")
        except Exception as e:
            logger.error(f"OpenRouter error: {e}")

    # ── 2. Try OpenAI ──
    if OPENAI_API_KEY:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=OPENAI_API_KEY)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                response_format={"type": "json_object"},
                max_tokens=1500,
                temperature=0.7,
            )
            content = response.choices[0].message.content
            return json.loads(content)
        except Exception as e:
            logger.error(f"OpenAI error: {e}")

    # ── 3. Try Groq (free) ──
    try:
        from groq import Groq
        groq_key = os.environ.get("GROQ_API_KEY", "")
        if groq_key:
            client = Groq(api_key=groq_key)
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                response_format={"type": "json_object"},
                max_tokens=1500,
                temperature=0.7,
            )
            content = response.choices[0].message.content
            return json.loads(content)
    except ImportError:
        logger.info("Groq not installed, skipping")
    except Exception as e:
        logger.error(f"Groq error: {e}")

    return None


# ─── Helper Functions ────────────────────────────────────────────
def format_lesson_detail(lesson: dict) -> str:
    """Format a single lesson with full details."""
    lines = [
        f"📚 *{lesson['title']}*",
        f"📁 Categoria: {lesson.get('category_name', 'Sem categoria')}",
        f"📊 Nível: {lesson.get('level', 'N/A').capitalize()}",
    ]
    if lesson.get('date'):
        dt = lesson['date']
        if lesson.get('time'):
            dt += f" às {lesson['time']}"
        lines.append(f"📅 {dt}")
    if lesson.get('objective'):
        lines.append(f"\n🎯 *Objetivo:*\n{lesson['objective']}")
    if lesson.get('content'):
        lines.append(f"\n📖 *Conteúdo:*\n{lesson['content']}")
    if lesson.get('activities'):
        lines.append(f"\n✏️ *Atividades:*\n{lesson['activities']}")
    if lesson.get('evaluation'):
        lines.append(f"\n📝 *Avaliação:*\n{lesson['evaluation']}")
    if lesson.get('materials'):
        lines.append(f"\n🧰 *Materiais:*\n{lesson['materials']}")
    if lesson.get('notes'):
        lines.append(f"\n💡 *Observações:*\n{lesson['notes']}")
    return "\n".join(lines)


# ─── Bot Commands ────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start command — register user and show main menu."""
    user = update.effective_user
    upsert_user(user.id, user.username or "", user.first_name or "")

    welcome = (
        f"👋 Olá, *{user.first_name or 'Professor'}*!\n\n"
        "Bem-vindo ao *Class Bot* — seu assistente de aulas com IA.\n\n"
        "🤖 *Criar com IA* — diga o tópico e a IA monta o plano\n"
        "📚 *Minhas Aulas* — ver e gerenciar aulas salvas\n"
        "📅 *Agenda* — aulas agendadas com notificações\n"
        "📄 *Exportar* — PDF ou HTML para impressão\n\n"
        "O que deseja fazer?"
    )
    await update.message.reply_text(
        welcome, parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel current conversation."""
    await update.message.reply_text(
        "❌ Operação cancelada.",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show help message."""
    help_text = (
        "📖 *Comandos disponíveis:*\n\n"
        "/start — Menu principal\n"
        "/criar — Criar aula com IA\n"
        "/aulas — Listar suas aulas\n"
        "/agenda — Ver agenda\n"
        "/buscar [termo] — Buscar aulas\n"
        "/categorias — Gerenciar categorias\n"
        "/ajuda — Mostrar esta ajuda\n"
        "/cancelar — Cancelar operação atual\n\n"
        "Use os botões do menu para navegar!"
    )
    await update.message.reply_text(
        help_text, parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )


# ─── AI Lesson Creation (ConversationHandler) ───────────────────

async def ai_create_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start AI lesson creation flow."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            "🤖 *Criar Aula com IA*\n\n"
            "Passo 1/3: Qual o *tópico* da aula?\n\n"
            "Exemplo: Introdução a Python, Fotossíntese, Revolução Francesa",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "🤖 *Criar Aula com IA*\n\n"
            "Passo 1/3: Qual o *tópico* da aula?\n\n"
            "Exemplo: Introdução a Python, Fotossíntese, Revolução Francesa",
            parse_mode="Markdown"
        )
    return AI_TOPIC


async def ai_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['ai_lesson'] = {'topic': update.message.text}

    await update.message.reply_text(
        f"📌 Tópico: *{update.message.text}*\n\n"
        "Passo 2/3: Qual o *nível* da aula?",
        parse_mode="Markdown",
        reply_markup=level_keyboard("ai_lvl")
    )
    return AI_LEVEL


async def ai_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    level = query.data.replace("ai_lvl_", "")
    context.user_data['ai_lesson']['level'] = level

    user_id = update.effective_user.id
    cats = get_categories(user_id)

    if not cats:
        # No categories — skip to generation
        context.user_data['ai_lesson']['category_name'] = ""
        return await ai_generate_lesson(update, context)

    buttons = []
    for cat in cats:
        buttons.append([InlineKeyboardButton(
            f"📁 {cat['name']}", callback_data=f"ai_cat_{cat['id']}"
        )])
    buttons.append([InlineKeyboardButton("⏭️ Pular (sem categoria)", callback_data="ai_cat_skip")])
    buttons.append(back_menu_button())

    await query.edit_message_text(
        f"📊 Nível: *{level.capitalize()}*\n\n"
        "Passo 3/3: Escolha a *categoria*:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return AI_CATEGORY


async def ai_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "ai_cat_skip":
        context.user_data['ai_lesson']['category_id'] = None
        context.user_data['ai_lesson']['category_name'] = ""
    elif query.data == "menu_back":
        await query.edit_message_text(
            "❌ Operação cancelada.",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END
    else:
        cat_id = int(query.data.replace("ai_cat_", ""))
        context.user_data['ai_lesson']['category_id'] = cat_id
        # Get category name
        cats = get_categories(update.effective_user.id)
        for cat in cats:
            if cat['id'] == cat_id:
                context.user_data['ai_lesson']['category_name'] = cat['name']
                break

    return await ai_generate_lesson(update, context)


async def ai_generate_lesson(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Generate lesson with AI and show for review."""
    query = update.callback_query
    data = context.user_data['ai_lesson']

    if query:
        await query.edit_message_text(
            f"⏳ *Gerando aula com IA...*\n\n"
            f"📌 Tópico: {data['topic']}\n"
            f"📊 Nível: {data['level'].capitalize()}\n"
            f"📁 Categoria: {data.get('category_name', 'Sem categoria')}\n\n"
            "Isso leva alguns segundos...",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"⏳ *Gerando aula com IA...*\n\n"
            f"📌 Tópico: {data['topic']}\n"
            f"📊 Nível: {data['level'].capitalize()}\n\n"
            "Isso leva alguns segundos...",
            parse_mode="Markdown"
        )

    # Generate
    result = generate_lesson_with_ai(
        topic=data['topic'],
        level=data['level'],
        category=data.get('category_name', '')
    )

    if not result:
        text = (
            "❌ *Erro ao gerar aula com IA*\n\n"
            "Nenhuma API de IA está configurada.\n\n"
            "Para usar esta funcionalidade, configure uma das APIs:\n"
            "• OpenRouter (OPENROUTER_API_KEY) — recomendado, usa Owl Alpha\n"
            "• OpenAI (OPENAI_API_KEY)\n"
            "• Groq (GROQ_API_KEY) — gratuito\n\n"
            "Acesse [openrouter.ai](https://openrouter.ai) para criar uma API key gratuita."
        )
        if query:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())
        else:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())
        context.user_data.pop('ai_lesson', None)
        return ConversationHandler.END

    # Store generated content
    context.user_data['ai_result'] = result

    # Show generated lesson for review
    review_text = (
        f"🤖 *Aula Gerada pela IA*\n\n"
        f"📌 *Tópico:* {data['topic']}\n"
        f"📊 *Nível:* {data['level'].capitalize()}\n"
        f"📁 *Categoria:* {data.get('category_name', 'Sem categoria')}\n\n"
        f"🎯 *Objetivo:*\n{result.get('objetivo', 'N/A')}\n\n"
        f"📖 *Conteúdo:*\n{result.get('conteudo', 'N/A')}\n\n"
        f"✏️ *Atividades:*\n{result.get('atividades', 'N/A')}\n\n"
        f"📝 *Avaliação:*\n{result.get('avaliacao', 'N/A')}\n\n"
        f"🧰 *Materiais:*\n{result.get('materiais', 'N/A')}\n\n"
        f"💡 *Observações:*\n{result.get('observacoes', 'N/A')}\n\n"
        "O que deseja fazer?"
    )

    buttons = [
        [
            InlineKeyboardButton("✅ Salvar Aula", callback_data="ai_save"),
            InlineKeyboardButton("🔄 Regerar", callback_data="ai_regen"),
        ],
        [
            InlineKeyboardButton("❌ Descartar", callback_data="ai_discard"),
        ],
        back_menu_button(),
    ]

    if query:
        await query.edit_message_text(
            review_text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await update.message.reply_text(
            review_text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    return AI_CONFIRM


async def ai_save_lesson(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save the AI-generated lesson."""
    query = update.callback_query
    await query.answer()

    data = context.user_data.get('ai_lesson', {})
    result = context.user_data.get('ai_result', {})
    user_id = update.effective_user.id

    # Get or create category
    cat_id = data.get('category_id')
    if not cat_id and data.get('category_name'):
        cat_id = add_category(user_id, data['category_name'])

    # Save lesson
    lesson_id = add_lesson(
        user_id=user_id,
        title=data['topic'],
        category_id=cat_id,
        level=data.get('level', 'iniciante'),
        objective=result.get('objetivo', ''),
        content=result.get('conteudo', ''),
        activities=result.get('atividades', ''),
        evaluation=result.get('avaliacao', ''),
        materials=result.get('materiais', ''),
        notes=result.get('observacoes', ''),
        date='',
        time='',
    )

    lesson = get_lesson(lesson_id, user_id)

    await query.edit_message_text(
        f"✅ *Aula salva com sucesso!*\n\n"
        f"{format_lesson_detail(lesson)}\n\n"
        "O que deseja fazer agora?",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )

    context.user_data.pop('ai_lesson', None)
    context.user_data.pop('ai_result', None)
    return ConversationHandler.END


async def ai_regenerate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Regenerate the lesson."""
    query = update.callback_query
    await query.answer()
    return await ai_generate_lesson(update, context)


async def ai_discard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Discard the generated lesson."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🗑️ Aula descartada.\n\nO que deseja fazer?",
        reply_markup=main_menu_keyboard()
    )
    context.user_data.pop('ai_lesson', None)
    context.user_data.pop('ai_result', None)
    return ConversationHandler.END


# ─── Lesson Listing & Detail ─────────────────────────────────────

async def cmd_lessons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all lessons for the user."""
    user_id = update.effective_user.id
    lessons = get_lessons(user_id, limit=20)

    if not lessons:
        text = "📚 Você ainda não tem aulas criadas.\n\nUse 🤖 Criar com IA para gerar sua primeira aula!"
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                text, parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
        else:
            await update.message.reply_text(
                text, parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
        return

    buttons = []
    for lesson in lessons:
        date_str = lesson.get('date', '') or 'Sem data'
        btn_text = f"📚 {lesson['title']} ({date_str})"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"lesson_{lesson['id']}")])

    buttons.append(back_menu_button())
    text = f"📚 *Suas Aulas* ({len(lessons)}):\n\nToque em uma aula para ver detalhes:"

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await update.message.reply_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )


async def lesson_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show lesson detail with action buttons."""
    query = update.callback_query
    await query.answer()

    lesson_id = int(query.data.replace("lesson_", ""))
    user_id = update.effective_user.id
    lesson = get_lesson(lesson_id, user_id)

    if not lesson:
        await query.edit_message_text(
            "❌ Aula não encontrada.",
            reply_markup=main_menu_keyboard()
        )
        return

    text = format_lesson_detail(lesson)

    buttons = [
        [
            InlineKeyboardButton("📄 Exportar PDF", callback_data=f"export_pdf_{lesson_id}"),
            InlineKeyboardButton("🌐 Exportar HTML", callback_data=f"export_html_{lesson_id}"),
        ],
        [
            InlineKeyboardButton("📅 Agendar", callback_data=f"schedule_{lesson_id}"),
            InlineKeyboardButton("🗑️ Excluir", callback_data=f"delete_{lesson_id}"),
        ],
        back_menu_button(),
    ]

    await query.edit_message_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ─── Export Functions ────────────────────────────────────────────

async def export_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Export lesson as PDF and send as document."""
    query = update.callback_query
    await query.answer()

    lesson_id = int(query.data.replace("export_pdf_", ""))
    user_id = update.effective_user.id
    lesson = get_lesson(lesson_id, user_id)

    if not lesson:
        await query.edit_message_text("❌ Aula não encontrada.", reply_markup=main_menu_keyboard())
        return

    await query.edit_message_text("⏳ Gerando PDF...")

    try:
        filepath = generate_lesson_pdf(lesson)
        with open(filepath, 'rb') as f:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=f,
                filename=f"aula_{lesson['title']}.pdf",
                caption=f"📄 PDF da aula: *{lesson['title']}*",
                parse_mode="Markdown",
            )
        os.remove(filepath)
    except Exception as e:
        logger.error(f"PDF generation error: {e}")
        await query.edit_message_text(
            f"❌ Erro ao gerar PDF: {e}",
            reply_markup=main_menu_keyboard()
        )
        return

    await query.edit_message_text(
        "✅ PDF enviado!\n\nO que deseja fazer?",
        reply_markup=main_menu_keyboard()
    )


async def export_html(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Export lesson as HTML and send as document."""
    query = update.callback_query
    await query.answer()

    lesson_id = int(query.data.replace("export_html_", ""))
    user_id = update.effective_user.id
    lesson = get_lesson(lesson_id, user_id)

    if not lesson:
        await query.edit_message_text("❌ Aula não encontrada.", reply_markup=main_menu_keyboard())
        return

    await query.edit_message_text("⏳ Gerando HTML...")

    try:
        filepath = generate_lesson_html(lesson)
        with open(filepath, 'rb') as f:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=f,
                filename=f"aula_{lesson['title']}.html",
                caption=(
                    f"🌐 HTML da aula: *{lesson['title']}*\n\n"
                    "Abra no navegador e clique em 🖨️ Imprimir.\n"
                    "Funciona no celular e no computador!"
                ),
                parse_mode="Markdown",
            )
        os.remove(filepath)
    except Exception as e:
        logger.error(f"HTML generation error: {e}")
        await query.edit_message_text(
            f"❌ Erro ao gerar HTML: {e}",
            reply_markup=main_menu_keyboard()
        )
        return

    await query.edit_message_text(
        "✅ HTML enviado!\n\nO que deseja fazer?",
        reply_markup=main_menu_keyboard()
    )


# ─── Lesson Deletion ─────────────────────────────────────────────

async def delete_lesson_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm lesson deletion."""
    query = update.callback_query
    await query.answer()

    lesson_id = int(query.data.replace("delete_", ""))
    user_id = update.effective_user.id
    lesson = get_lesson(lesson_id, user_id)

    if not lesson:
        await query.edit_message_text("❌ Aula não encontrada.", reply_markup=main_menu_keyboard())
        return

    buttons = [
        [
            InlineKeyboardButton("✅ Sim, excluir", callback_data=f"confirm_delete_{lesson_id}"),
            InlineKeyboardButton("❌ Não, cancelar", callback_data=f"lesson_{lesson_id}"),
        ],
        back_menu_button(),
    ]
    await query.edit_message_text(
        f"⚠️ Tem certeza que deseja excluir:\n\n"
        f"📚 *{lesson['title']}*\n\n"
        f"Esta ação não pode ser desfeita!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def delete_lesson_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Execute lesson deletion."""
    query = update.callback_query
    await query.answer()

    lesson_id = int(query.data.replace("confirm_delete_", ""))
    user_id = update.effective_user.id

    if delete_lesson(lesson_id, user_id):
        await query.edit_message_text(
            "✅ Aula excluída com sucesso!",
            reply_markup=main_menu_keyboard()
        )
    else:
        await query.edit_message_text(
            "❌ Erro ao excluir aula.",
            reply_markup=main_menu_keyboard()
        )


# ─── Schedule (Agenda) ───────────────────────────────────────────

async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show schedule overview."""
    user_id = update.effective_user.id
    today = datetime.now().strftime("%Y-%m-%d")
    next_week = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    schedules = get_schedules(user_id, from_date=today, to_date=next_week)

    if not schedules:
        text = (
            "📅 *Agenda*\n\n"
            "Nenhuma aula agendada para os próximos 7 dias.\n\n"
            "Para agendar, vá em 'Minhas Aulas' → selecione uma aula → '📅 Agendar'."
        )
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                text, parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
        else:
            await update.message.reply_text(
                text, parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
        return

    lines = ["📅 *Agenda — Próximos 7 dias*\n"]
    for s in schedules:
        # Format date from YYYY-MM-DD to DD/MM/YYYY
        try:
            dt = datetime.strptime(s['scheduled_date'], "%Y-%m-%d")
            date_str = dt.strftime("%d/%m/%Y")
        except (ValueError, TypeError):
            date_str = s['scheduled_date']

        lines.append(
            f"📚 *{s['title']}*\n"
            f"   📅 {date_str} às {s['scheduled_time']}\n"
            f"   📊 {s['level'].capitalize()} | 📁 {s.get('category_name', 'Sem categoria')}\n"
        )

    buttons = [
        [InlineKeyboardButton("📅 Ver Hoje", callback_data="schedule_today")],
        [InlineKeyboardButton("📅 Ver Semana", callback_data="schedule_week")],
        back_menu_button(),
    ]

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await update.message.reply_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )


async def schedule_lesson_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start scheduling a lesson."""
    query = update.callback_query
    await query.answer()

    lesson_id = int(query.data.replace("schedule_", ""))
    context.user_data['schedule_lesson_id'] = lesson_id

    lesson = get_lesson(lesson_id, update.effective_user.id)
    if not lesson:
        await query.edit_message_text("❌ Aula não encontrada.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    await query.edit_message_text(
        f"📅 *Agendar Aula*\n\n"
        f"📚 {lesson['title']}\n\n"
        "Qual a *data* do agendamento? (DD/MM/AAAA)",
        parse_mode="Markdown"
    )
    return S_DATE


async def schedule_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        datetime.strptime(update.message.text, "%d/%m/%Y")
        context.user_data['schedule_date'] = update.message.text
    except ValueError:
        await update.message.reply_text(
            "❌ Formato inválido. Use DD/MM/AAAA\n\nTente novamente:"
        )
        return S_DATE

    await update.message.reply_text(
        "Qual o *horário*? (HH:MM)",
        parse_mode="Markdown"
    )
    return S_TIME


async def schedule_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        datetime.strptime(update.message.text, "%H:%M")
        context.user_data['schedule_time'] = update.message.text
    except ValueError:
        await update.message.reply_text(
            "❌ Formato inválido. Use HH:MM\n\nTente novamente:"
        )
        return S_TIME

    user_id = update.effective_user.id
    lesson_id = context.user_data['schedule_lesson_id']
    date = context.user_data['schedule_date']
    time_val = context.user_data['schedule_time']

    # Convert DD/MM/AAAA to YYYY-MM-DD for storage
    dt = datetime.strptime(date, "%d/%m/%Y")
    stored_date = dt.strftime("%Y-%m-%d")

    add_schedule(user_id, lesson_id, stored_date, time_val)

    lesson = get_lesson(lesson_id, user_id)

    await update.message.reply_text(
        f"✅ *Aula agendada!*\n\n"
        f"📚 {lesson['title']}\n"
        f"📅 {date} às {time_val}\n\n"
        "Você receberá notificações 1 hora e 15 minutos antes.\n\n"
        "O que deseja fazer agora?",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )

    context.user_data.pop('schedule_lesson_id', None)
    context.user_data.pop('schedule_date', None)
    context.user_data.pop('schedule_time', None)
    return ConversationHandler.END


# ─── Search ──────────────────────────────────────────────────────

async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Search lessons by term."""
    args = context.args
    if not args:
        text = "🔍 *Buscar Aulas*\n\nDigite o termo de busca:\n\nExemplo: `/buscar python`"
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(text, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, parse_mode="Markdown")
        return

    term = " ".join(args)
    user_id = update.effective_user.id
    results = search_lessons(user_id, term)

    if not results:
        text = f"🔍 Nenhum resultado para: *{term}*"
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                text, parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
        else:
            await update.message.reply_text(
                text, parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
        return

    buttons = []
    for lesson in results:
        btn_text = f"📚 {lesson['title']}"
        if lesson.get('date'):
            btn_text += f" ({lesson['date']})"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"lesson_{lesson['id']}")])

    buttons.append(back_menu_button())
    text = f"🔍 *Resultados para '{term}'* ({len(results)}):"

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await update.message.reply_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )


# ─── Categories Management ──────────────────────────────────────

async def cmd_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show category management."""
    user_id = update.effective_user.id
    cats = get_categories(user_id)

    if not cats:
        text = (
            "📁 *Categorias*\n\n"
            "Você ainda não tem categorias.\n\n"
            "Digite o nome da primeira categoria:"
        )
        context.user_data['awaiting_new_category'] = True
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(text, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, parse_mode="Markdown")
        return

    buttons = []
    for cat in cats:
        buttons.append([InlineKeyboardButton(
            f"📁 {cat['name']}  ✕", callback_data=f"delcat_{cat['id']}"
        )])
    buttons.append([InlineKeyboardButton("➕ Nova Categoria", callback_data="cat_add")])
    buttons.append(back_menu_button())

    text = "📁 *Suas Categorias:*\n\nToque em uma categoria para excluí-la:"

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await update.message.reply_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )


async def category_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start adding a new category."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📁 *Nova Categoria*\n\nDigite o nome da categoria:",
        parse_mode="Markdown"
    )
    return C_NAME


async def category_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    user_id = update.effective_user.id
    add_category(user_id, name)

    await update.message.reply_text(
        f"✅ Categoria *{name}* criada!\n\nO que deseja fazer?",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END


async def category_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a category."""
    query = update.callback_query
    await query.answer()

    cat_id = int(query.data.replace("delcat_", ""))
    user_id = update.effective_user.id

    if delete_category(cat_id, user_id):
        await query.edit_message_text(
            "✅ Categoria excluída!",
            reply_markup=main_menu_keyboard()
        )
    else:
        await query.edit_message_text(
            "❌ Erro ao excluir categoria.",
            reply_markup=main_menu_keyboard()
        )


# ─── Statistics ──────────────────────────────────────────────────

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user statistics."""
    user_id = update.effective_user.id
    lessons = get_lessons(user_id, limit=1000)
    cats = get_categories(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    upcoming = get_schedules(user_id, from_date=today)

    total = len(lessons)
    by_level = {}
    for l in lessons:
        lvl = l.get('level', 'N/A')
        by_level[lvl] = by_level.get(lvl, 0) + 1

    lines = [
        "📊 *Estatísticas*\n",
        f"📚 Total de aulas: *{total}*",
        f"📁 Categorias: *{len(cats)}*",
        f"📅 Agendamentos futuros: *{len(upcoming)}*",
    ]

    if by_level:
        lines.append("\n*Por nível:*")
        for lvl, count in sorted(by_level.items()):
            emoji = {"iniciante": "🟢", "intermediario": "🟡", "avancado": "🔴"}.get(lvl, "⚪")
            lines.append(f"  {emoji} {lvl.capitalize()}: {count}")

    text = "\n".join(lines)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
    else:
        await update.message.reply_text(
            text, parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )


# ─── Schedule Today/Week ─────────────────────────────────────────

async def schedule_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show today's schedule."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    today = datetime.now().strftime("%Y-%m-%d")
    schedules = get_schedules(user_id, from_date=today, to_date=today)

    if not schedules:
        await query.edit_message_text(
            "📅 Nenhuma aula agendada para hoje.",
            reply_markup=main_menu_keyboard()
        )
        return

    lines = ["📅 *Aulas de Hoje*\n"]
    for s in schedules:
        lines.append(
            f"📚 *{s['title']}* — {s['scheduled_time']}\n"
            f"   📊 {s['level'].capitalize()} | 📁 {s.get('category_name', 'Sem categoria')}\n"
        )

    await query.edit_message_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )


async def schedule_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show week's schedule."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    today = datetime.now().strftime("%Y-%m-%d")
    next_week = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    schedules = get_schedules(user_id, from_date=today, to_date=next_week)

    if not schedules:
        await query.edit_message_text(
            "📅 Nenhuma aula agendada para esta semana.",
            reply_markup=main_menu_keyboard()
        )
        return

    lines = ["📅 *Aulas da Semana*\n"]
    for s in schedules:
        try:
            dt = datetime.strptime(s['scheduled_date'], "%Y-%m-%d")
            date_str = dt.strftime("%d/%m/%Y")
        except (ValueError, TypeError):
            date_str = s['scheduled_date']
        lines.append(
            f"📚 *{s['title']}*\n"
            f"   📅 {date_str} às {s['scheduled_time']}\n"
        )

    await query.edit_message_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )


# ─── Notification System ─────────────────────────────────────────

async def check_notifications(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Periodic job to check and send notifications."""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    pending = get_pending_notifications()

    for sched in pending:
        if sched['scheduled_date'] != today:
            continue

        sched_time = sched['scheduled_time']
        try:
            sched_dt = datetime.strptime(f"{today} {sched_time}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue

        diff_minutes = (sched_dt - now).total_seconds() / 60

        # 1 hour notification (between 55-65 minutes before)
        if 55 <= diff_minutes <= 65 and not sched['notified_1h']:
            try:
                await context.bot.send_message(
                    chat_id=sched['user_id'],
                    text=(
                        f"⏰ *Lembrete de Aula!*\n\n"
                        f"📚 *{sched['title']}*\n"
                        f"📅 Hoje às {sched['scheduled_time']}\n"
                        f"📊 {sched['level'].capitalize()}\n\n"
                        f"Falta 1 hora para sua aula!"
                    ),
                    parse_mode="Markdown"
                )
                mark_notified(sched['id'], '1h')
            except Exception as e:
                logger.error(f"Notification error (1h): {e}")

        # 15 minute notification (between 10-20 minutes before)
        if 10 <= diff_minutes <= 20 and not sched['notified_15min']:
            try:
                await context.bot.send_message(
                    chat_id=sched['user_id'],
                    text=(
                        f"🔴 *Aula em 15 minutos!*\n\n"
                        f"📚 *{sched['title']}*\n"
                        f"📅 Hoje às {sched['scheduled_time']}\n"
                        f"📊 {sched['level'].capitalize()}\n\n"
                        f"Prepare-se!"
                    ),
                    parse_mode="Markdown"
                )
                mark_notified(sched['id'], '15min')
            except Exception as e:
                logger.error(f"Notification error (15min): {e}")


# ─── Error Handler ───────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors."""
    logger.error(f"Exception while handling update: {context.error}", exc_info=context.error)


# ─── Menu Callback Router ────────────────────────────────────────

async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route main menu button presses."""
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "menu_back":
        await query.edit_message_text(
            "🏠 *Menu Principal*\n\nO que deseja fazer?",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
    elif data == "menu_lessons":
        await cmd_lessons(update, context)
    elif data == "menu_create_ai":
        await ai_create_start(update, context)
    elif data == "menu_schedule":
        await cmd_schedule(update, context)
    elif data == "menu_search":
        await cmd_search(update, context)
    elif data == "menu_categories":
        await cmd_categories(update, context)
    elif data == "menu_stats":
        await cmd_stats(update, context)
    elif data == "schedule_today":
        await schedule_today(update, context)
    elif data == "schedule_week":
        await schedule_week(update, context)
    elif data == "cat_add":
        await category_add_start(update, context)
    elif data.startswith("delcat_"):
        await category_delete(update, context)
    elif data.startswith("lesson_"):
        await lesson_detail(update, context)
    elif data.startswith("export_pdf_"):
        await export_pdf(update, context)
    elif data.startswith("export_html_"):
        await export_html(update, context)
    elif data.startswith("delete_"):
        await delete_lesson_confirm(update, context)
    elif data.startswith("confirm_delete_"):
        await delete_lesson_execute(update, context)
    elif data.startswith("schedule_"):
        await schedule_lesson_start(update, context)
    elif data == "ai_save":
        await ai_save_lesson(update, context)
    elif data == "ai_regen":
        await ai_regenerate(update, context)
    elif data == "ai_discard":
        await ai_discard(update, context)


# ─── Main ────────────────────────────────────────────────────────

def main() -> None:
    """Start the bot."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # ── Conversation Handlers ──

    # AI Lesson creation
    ai_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(ai_create_start, pattern="^menu_create_ai$"),
            CommandHandler("criar", ai_create_start),
        ],
        states={
            AI_TOPIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, ai_topic)],
            AI_LEVEL: [CallbackQueryHandler(ai_level, pattern="^ai_lvl_")],
            AI_CATEGORY: [CallbackQueryHandler(ai_category, pattern="^ai_cat_")],
            AI_CONFIRM: [
                CallbackQueryHandler(ai_save_lesson, pattern="^ai_save$"),
                CallbackQueryHandler(ai_regenerate, pattern="^ai_regen$"),
                CallbackQueryHandler(ai_discard, pattern="^ai_discard$"),
            ],
        },
        fallbacks=[CommandHandler("cancelar", cmd_cancel)],
        conversation_timeout=300,
    )

    # Schedule creation
    schedule_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(schedule_lesson_start, pattern="^schedule_\\d+$"),
        ],
        states={
            S_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, schedule_date)],
            S_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, schedule_time)],
        },
        fallbacks=[CommandHandler("cancelar", cmd_cancel)],
        conversation_timeout=300,
    )

    # Category creation
    category_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(category_add_start, pattern="^cat_add$"),
        ],
        states={
            C_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, category_add_name)],
        },
        fallbacks=[CommandHandler("cancelar", cmd_cancel)],
        conversation_timeout=300,
    )

    # ── Register Handlers ──
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ajuda", cmd_help))
    app.add_handler(CommandHandler("aulas", cmd_lessons))
    app.add_handler(CommandHandler("agenda", cmd_schedule))
    app.add_handler(CommandHandler("buscar", cmd_search))
    app.add_handler(CommandHandler("categorias", cmd_categories))
    app.add_handler(CommandHandler("estatisticas", cmd_stats))

    app.add_handler(ai_conv)
    app.add_handler(schedule_conv)
    app.add_handler(category_conv)

    app.add_handler(CallbackQueryHandler(menu_router))

    app.add_error_handler(error_handler)

    # ── Notification Job ──
    app.job_queue.run_repeating(check_notifications, interval=300, first=10)

    # ── Health Check Server (for Render) ──
    port = int(os.environ.get("PORT", 0))
    if port:
        from http.server import HTTPServer, BaseHTTPRequestHandler
        import threading

        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Class Bot OK\n")
            def do_HEAD(self):
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
            def log_message(self, format, *args):
                pass

        http_server = HTTPServer(("0.0.0.0", port), HealthHandler)
        http_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
        http_thread.start()
        logger.info(f"Health check server started on port {port}")

    logger.info("Class Bot starting...")
    app.run_polling(drop_pending_updates=True, close_loop=False)


if __name__ == "__main__":
    main()
