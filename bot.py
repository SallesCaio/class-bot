"""
Class Bot — Automação Teacher
Telegram bot for teachers to create, manage, and export lesson plans.

Stack: python-telegram-bot v22+, SQLite, fpdf2, Jinja2
Deploy: Render (Background Worker)
"""

import os
import logging
from datetime import datetime, timedelta, time as dtime
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, ContextTypes,
)

from database import (
    init_db, upsert_user, get_user,
    add_category, get_categories, get_category_by_name, delete_category,
    add_lesson, get_lesson, get_lessons, update_lesson, delete_lesson, search_lessons,
    add_schedule, get_schedules, get_pending_notifications, mark_notified, delete_schedule,
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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Conversation States ─────────────────────────────────────────
# Lesson creation
(L_TITLE, L_CATEGORY, L_LEVEL, L_OBJECTIVE, L_CONTENT,
 L_ACTIVITIES, L_EVALUATION, L_MATERIALS, L_NOTES, L_DATE, L_TIME) = range(11)

# Schedule creation
(S_LESSON, S_DATE, S_TIME) = range(11, 14)

# Lesson editing
(E_SELECT, E_FIELD, E_VALUE) = range(14, 17)

# Category management
(C_NAME,) = range(17, 18)

# Search
(SEARCH_TERM,) = range(18, 19)


# ─── Keyboards ───────────────────────────────────────────────────
def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📚 Minhas Aulas", callback_data="menu_lessons"),
            InlineKeyboardButton("➕ Criar Aula", callback_data="menu_create"),
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


def level_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Iniciante", callback_data="level_iniciante")],
        [InlineKeyboardButton("🟡 Intermediário", callback_data="level_intermediario")],
        [InlineKeyboardButton("🔴 Avançado", callback_data="level_avancado")],
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
    buttons.append([InlineKeyboardButton("⬅️ Voltar", callback_data="cat_back")])
    return InlineKeyboardMarkup(buttons)


# ─── Helper Functions ────────────────────────────────────────────
def format_lesson_summary(lesson: dict) -> str:
    """Format a single lesson as a short summary."""
    parts = [f"📚 *{lesson['title']}*"]
    if lesson.get('category_name'):
        parts.append(f"   📁 {lesson['category_name']}")
    parts.append(f"   📊 Nível: {lesson['level'].capitalize()}")
    if lesson.get('date'):
        date_str = lesson['date']
        if lesson.get('time'):
            date_str += f" às {lesson['time']}"
        parts.append(f"   📅 {date_str}")
    return "\n".join(parts)


def format_lesson_detail(lesson: dict) -> str:
    """Format a single lesson with full details."""
    lines = [
        f"📚 *{lesson['title']}*",
        f"📁 Categoria: {lesson.get('category_name', 'Sem categoria')}",
        f"📊 Nível: {lesson['level'].capitalize()}",
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
        "Bem-vindo ao *Class Bot* — seu assistente de aulas.\n\n"
        "Aqui você pode:\n"
        "📚 Criar e gerenciar planos de aula\n"
        "📅 Agendar aulas com notificações\n"
        "📄 Exportar em PDF ou HTML para impressão\n"
        "🔍 Buscar e filtrar suas aulas\n\n"
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
        "/aulas — Listar suas aulas\n"
        "/criar — Criar nova aula\n"
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


# ─── Lesson Creation (ConversationHandler) ──────────────────────

async def lesson_create_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start lesson creation flow."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            "➕ *Criar Nova Aula*\n\n"
            "Passo 1/11: Qual o *título* da aula?",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "➕ *Criar Nova Aula*\n\n"
            "Passo 1/11: Qual o *título* da aula?",
            parse_mode="Markdown"
        )
    return L_TITLE


async def lesson_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['lesson'] = {'title': update.message.text}
    user_id = update.effective_user.id

    cats = get_categories(user_id)
    if not cats:
        # No categories — ask to create one
        await update.message.reply_text(
            "📁 Você ainda não tem categorias.\n\n"
            "Digite o nome da primeira categoria:",
            parse_mode="Markdown"
        )
        context.user_data['lesson']['awaiting_category'] = True
        return L_CATEGORY

    await update.message.reply_text(
        "Passo 2/11: Escolha a *categoria*:",
        parse_mode="Markdown",
        reply_markup=category_inline_keyboard(user_id, include_new=True)
    )
    return L_CATEGORY


async def lesson_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cat_new":
        await query.edit_message_text("Digite o nome da nova categoria:")
        context.user_data['lesson']['awaiting_category'] = True
        return L_CATEGORY

    if query.data == "cat_back":
        await query.edit_message_text(
            "❌ Operação cancelada.",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    cat_id = int(query.data.replace("cat_", ""))
    context.user_data['lesson']['category_id'] = cat_id

    await query.edit_message_text(
        "Passo 3/11: Qual o *nível* da aula?",
        parse_mode="Markdown",
        reply_markup=level_keyboard()
    )
    return L_LEVEL


async def lesson_category_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle text input for new category."""
    name = update.message.text.strip()
    user_id = update.effective_user.id
    cat_id = add_category(user_id, name)
    context.user_data['lesson']['category_id'] = cat_id

    await update.message.reply_text(
        f"✅ Categoria *{name}* criada!\n\n"
        "Passo 3/11: Qual o *nível* da aula?",
        parse_mode="Markdown",
        reply_markup=level_keyboard()
    )
    return L_LEVEL


async def lesson_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    level = query.data.replace("level_", "")
    context.user_data['lesson']['level'] = level

    await query.edit_message_text(
        "Passo 4/11: Qual o *objetivo* da aula?\n\n"
        "(ou /pular para deixar em branco)",
        parse_mode="Markdown"
    )
    return L_OBJECTIVE


async def lesson_objective(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text != "/pular":
        context.user_data['lesson']['objective'] = update.message.text
    else:
        context.user_data['lesson']['objective'] = ""

    await update.message.reply_text(
        "Passo 5/11: Qual o *conteúdo* da aula?\n\n"
        "(ou /pular para deixar em branco)",
        parse_mode="Markdown"
    )
    return L_CONTENT


async def lesson_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text != "/pular":
        context.user_data['lesson']['content'] = update.message.text
    else:
        context.user_data['lesson']['content'] = ""

    await update.message.reply_text(
        "Passo 6/11: Quais *atividades* serão realizadas?\n\n"
        "(ou /pular para deixar em branco)",
        parse_mode="Markdown"
    )
    return L_ACTIVITIES


async def lesson_activities(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text != "/pular":
        context.user_data['lesson']['activities'] = update.message.text
    else:
        context.user_data['lesson']['activities'] = ""

    await update.message.reply_text(
        "Passo 7/11: Como será a *avaliação*?\n\n"
        "(ou /pular para deixar em branco)",
        parse_mode="Markdown"
    )
    return L_EVALUATION


async def lesson_evaluation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text != "/pular":
        context.user_data['lesson']['evaluation'] = update.message.text
    else:
        context.user_data['lesson']['evaluation'] = ""

    await update.message.reply_text(
        "Passo 8/11: Quais *materiais* são necessários?\n\n"
        "(ou /pular para deixar em branco)",
        parse_mode="Markdown"
    )
    return L_MATERIALS


async def lesson_materials(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text != "/pular":
        context.user_data['lesson']['materials'] = update.message.text
    else:
        context.user_data['lesson']['materials'] = ""

    await update.message.reply_text(
        "Passo 9/11: Alguma *observação*?\n\n"
        "(ou /pular para deixar em branco)",
        parse_mode="Markdown"
    )
    return L_NOTES


async def lesson_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text != "/pular":
        context.user_data['lesson']['notes'] = update.message.text
    else:
        context.user_data['lesson']['notes'] = ""

    await update.message.reply_text(
        "Passo 10/11: Qual a *data* da aula? (DD/MM/AAAA)\n\n"
        "(ou /pular para deixar sem data)",
        parse_mode="Markdown"
    )
    return L_DATE


async def lesson_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text != "/pular":
        # Validate date format
        try:
            datetime.strptime(update.message.text, "%d/%m/%Y")
            context.user_data['lesson']['date'] = update.message.text
        except ValueError:
            await update.message.reply_text(
                "❌ Formato inválido. Use DD/MM/AAAA\n\n"
                "Tente novamente ou /pular:",
                parse_mode="Markdown"
            )
            return L_DATE
    else:
        context.user_data['lesson']['date'] = ""

    await update.message.reply_text(
        "Passo 11/11: Qual o *horário* da aula? (HH:MM)\n\n"
        "(ou /pular para deixar sem horário)",
        parse_mode="Markdown"
    )
    return L_TIME


async def lesson_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text != "/pular":
        try:
            datetime.strptime(update.message.text, "%H:%M")
            context.user_data['lesson']['time'] = update.message.text
        except ValueError:
            await update.message.reply_text(
                "❌ Formato inválido. Use HH:MM\n\n"
                "Tente novamente ou /pular:",
                parse_mode="Markdown"
            )
            return L_TIME
    else:
        context.user_data['lesson']['time'] = ""

    # Save lesson
    data = context.user_data['lesson']
    user_id = update.effective_user.id
    lesson_id = add_lesson(
        user_id=user_id,
        title=data['title'],
        category_id=data.get('category_id'),
        level=data.get('level', 'iniciante'),
        objective=data.get('objective', ''),
        content=data.get('content', ''),
        activities=data.get('activities', ''),
        evaluation=data.get('evaluation', ''),
        materials=data.get('materials', ''),
        notes=data.get('notes', ''),
        date=data.get('date', ''),
        time=data.get('time', ''),
    )

    lesson = get_lesson(lesson_id, user_id)

    await update.message.reply_text(
        f"✅ *Aula criada com sucesso!*\n\n"
        f"{format_lesson_detail(lesson)}\n\n"
        "O que deseja fazer agora?",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )

    context.user_data.pop('lesson', None)
    return ConversationHandler.END


# ─── Lesson Listing & Detail ─────────────────────────────────────

async def cmd_lessons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all lessons for the user."""
    user_id = update.effective_user.id
    lessons = get_lessons(user_id, limit=20)

    if not lessons:
        text = "📚 Você ainda não tem aulas criadas.\n\nUse /criar para criar sua primeira aula!"
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard())
        else:
            await update.message.reply_text(text, reply_markup=main_menu_keyboard())
        return

    buttons = []
    for lesson in lessons:
        date_str = lesson.get('date', 'Sem data')
        btn_text = f"📚 {lesson['title']} ({date_str})"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"lesson_{lesson['id']}")])

    buttons.append([InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="menu_back")])
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
        await query.edit_message_text("❌ Aula não encontrada.", reply_markup=main_menu_keyboard())
        return

    text = format_lesson_detail(lesson)

    buttons = [
        [
            InlineKeyboardButton("📄 Exportar PDF", callback_data=f"export_pdf_{lesson_id}"),
            InlineKeyboardButton("🌐 Exportar HTML", callback_data=f"export_html_{lesson_id}"),
        ],
        [
            InlineKeyboardButton("📅 Agendar", callback_data=f"schedule_{lesson_id}"),
            InlineKeyboardButton("✏️ Editar", callback_data=f"edit_{lesson_id}"),
        ],
        [
            InlineKeyboardButton("🗑️ Excluir", callback_data=f"delete_{lesson_id}"),
        ],
        [InlineKeyboardButton("⬅️ Voltar às Aulas", callback_data="menu_lessons")],
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
        # Cleanup
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
                    "Abra o arquivo no navegador e clique em 🖨️ Imprimir.\n"
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

    context.user_data['delete_lesson_id'] = lesson_id

    buttons = [
        [
            InlineKeyboardButton("✅ Sim, excluir", callback_data=f"confirm_delete_{lesson_id}"),
            InlineKeyboardButton("❌ Não, cancelar", callback_data=f"lesson_{lesson_id}"),
        ]
    ]
    await query.edit_message_text(
        f"⚠️ Tem certeza que deseja excluir a aula:\n\n"
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
            "Para agendar, vá em 'Minhas Aulas' → selecione uma aula → 'Agendar'."
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
        status_1h = "✅" if s['notified_1h'] else "⏳"
        status_15 = "✅" if s['notified_15min'] else "⏳"
        lines.append(
            f"📚 *{s['title']}*\n"
            f"   📅 {s['scheduled_date']} às {s['scheduled_time']}\n"
            f"   📊 {s['level'].capitalize()} | 📁 {s.get('category_name', 'Sem categoria')}\n"
            f"   Notificações: 1h {status_1h} | 15min {status_15}\n"
        )

    buttons = [
        [InlineKeyboardButton("📅 Ver Hoje", callback_data="schedule_today")],
        [InlineKeyboardButton("📅 Ver Semana", callback_data="schedule_week")],
        [InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="menu_back")],
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
        "Você receberá notificações 1 hora e 15 minutos antes da aula.\n\n"
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
            await update.callback_query.edit_message_text(
                text, parse_mode="Markdown"
            )
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

    buttons.append([InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="menu_back")])
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
    buttons.append([InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="menu_back")])

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


# ─── Menu Callback Router ────────────────────────────────────────

async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route main menu button presses."""
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "menu_back" or data == "menu_lessons":
        await cmd_lessons(update, context)
    elif data == "menu_create":
        await lesson_create_start(update, context)
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


async def schedule_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show today's schedule."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    today = datetime.now().strftime("%Y-%m-%d")
    schedules = get_schedules(user_id, from_date=today, to_date=today)

    if not schedules:
        await query.edit_message_text(
            "📅 Nenhula aula agendada para hoje.",
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
        lines.append(
            f"📚 *{s['title']}*\n"
            f"   📅 {s['scheduled_date']} às {s['scheduled_time']}\n"
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
    current_time = now.strftime("%H:%M")

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
                        f"📅 Hoje às {sched['time']}\n"
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
                        f"📅 Hoje às {sched['time']}\n"
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


# ─── Main ────────────────────────────────────────────────────────

def main() -> None:
    """Start the bot."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set! Set the BOT_TOKEN environment variable.")
        return

    # Initialize database
    init_db()

    # Build application
    app = Application.builder().token(BOT_TOKEN).build()

    # ── Conversation Handlers ──

    # Lesson creation
    lesson_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(lesson_create_start, pattern="^menu_create$"),
            CommandHandler("criar", lesson_create_start),
        ],
        states={
            L_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, lesson_title)],
            L_CATEGORY: [
                CallbackQueryHandler(lesson_category, pattern="^cat_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, lesson_category_text),
            ],
            L_LEVEL: [CallbackQueryHandler(lesson_level, pattern="^level_")],
            L_OBJECTIVE: [
                CommandHandler("pular", lesson_objective),
                MessageHandler(filters.TEXT & ~filters.COMMAND, lesson_objective),
            ],
            L_CONTENT: [
                CommandHandler("pular", lesson_content),
                MessageHandler(filters.TEXT & ~filters.COMMAND, lesson_content),
            ],
            L_ACTIVITIES: [
                CommandHandler("pular", lesson_activities),
                MessageHandler(filters.TEXT & ~filters.COMMAND, lesson_activities),
            ],
            L_EVALUATION: [
                CommandHandler("pular", lesson_evaluation),
                MessageHandler(filters.TEXT & ~filters.COMMAND, lesson_evaluation),
            ],
            L_MATERIALS: [
                CommandHandler("pular", lesson_materials),
                MessageHandler(filters.TEXT & ~filters.COMMAND, lesson_materials),
            ],
            L_NOTES: [
                CommandHandler("pular", lesson_notes),
                MessageHandler(filters.TEXT & ~filters.COMMAND, lesson_notes),
            ],
            L_DATE: [
                CommandHandler("pular", lesson_date),
                MessageHandler(filters.TEXT & ~filters.COMMAND, lesson_date),
            ],
            L_TIME: [
                CommandHandler("pular", lesson_time),
                MessageHandler(filters.TEXT & ~filters.COMMAND, lesson_time),
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

    # Conversation handlers
    app.add_handler(lesson_conv)
    app.add_handler(schedule_conv)
    app.add_handler(category_conv)

    # Menu callback router (must be last)
    app.add_handler(CallbackQueryHandler(menu_router))

    # Error handler
    app.add_error_handler(error_handler)

    # ── Notification Job ──
    # Check every 5 minutes
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

    # ── Start Polling ──
    logger.info("Class Bot starting...")
    app.run_polling(drop_pending_updates=True, close_loop=False)


if __name__ == "__main__":
    main()
