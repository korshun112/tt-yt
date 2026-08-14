import os
import re
import logging
import json
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes
)
import yt_dlp

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

USERS_FILE = "users.json"
STATS_FILE = "stats.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

def load_users():
    """Загружает список пользователей из файла."""
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_users(users):
    """Сохраняет список пользователей в файл."""
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(users), f, ensure_ascii=False, indent=2)

def add_user(user_id):
    """Добавляет пользователя в базу, если его там нет."""
    users = load_users()
    if user_id not in users:
        users.add(user_id)
        save_users(users)
        return True
    return False

def load_stats():
    """Загружает статистику использования."""
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"total_downloads": 0}

def save_stats(stats):
    """Сохраняет статистику использования."""
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

def increment_stats():
    """Увеличивает счётчик скачиваний."""
    stats = load_stats()
    stats["total_downloads"] += 1
    save_stats(stats)
    return stats["total_downloads"]

async def download_video(url: str) -> str:
    """
    Скачивает видео с TikTok или YouTube без водяного знака.
    Возвращает путь к файлу или None в случае ошибки.
    """
    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": "downloads/%(title)s_%(id)s.%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extract_flat": False,
        "format_sort": ["res:1080", "codec:avc", "size"],
        "merge_output_format": "mp4",
        "postprocessors": [{
            "key": "FFmpegVideoConvertor",
            "preferedformat": "mp4",
        }],
    }

    os.makedirs("downloads", exist_ok=True)

    try:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            filename = ydl.prepare_filename(info)
            if not os.path.exists(filename):
                base = os.path.splitext(filename)[0]
                for f in os.listdir("downloads"):
                    if f.startswith(os.path.basename(base)):
                        return os.path.join("downloads", f)
            return filename
    except Exception as e:
        logger.error(f"Ошибка скачивания: {e}")
        return None

def is_valid_url(url: str) -> bool:
    """Проверяет, является ли ссылка валидной для скачивания."""
    patterns = [
        r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/",
        r"(https?://)?(www\.)?(tiktok\.com)/",
        r"(https?://)?(www\.)?(instagram\.com)/",
        r"(https?://)?(www\.)?(pinterest\.com|pin\.it)/",
    ]
    return any(re.search(pattern, url) for pattern in patterns)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start."""
    user = update.effective_user
    is_new = add_user(user.id)

    welcome_text = (
        "👋 *Привет! Я бот для скачивания видео без водяных знаков!*\n\n"
        "📌 *Поддерживаемые платформы:*\n"
        "• TikTok (tiktok.com)\n"
        "• YouTube / Shorts (youtube.com, youtu.be)\n"
        "• Instagram (публичные посты/Reels)\n"
        "• Pinterest (pinterest.com, pin.it)\n\n"
        "🔹 *Как пользоваться:*\n"
        "Просто отправьте мне ссылку на видео — я скачаю его без водяного знака и пришлю вам.\n\n"
        "👨‍💼 *Администратор:* /admin — для управления ботом"
    )

    keyboard = [[InlineKeyboardButton("📊 Статистика", callback_data="stats")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if is_new:
        await update.message.reply_text(
            "✅ Вы успешно зарегистрированы в боте!",
            parse_mode="Markdown"
        )

    await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=reply_markup)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений (ссылок)."""
    user = update.effective_user
    text = update.message.text.strip()
    add_user(user.id)

    if not is_valid_url(text):
        await update.message.reply_text(
            "❌ *Неверная ссылка!*\n\n"
            "Поддерживаются ссылки на:\n"
            "• TikTok (tiktok.com)\n"
            "• YouTube / Shorts (youtube.com, youtu.be)\n"
            "• Instagram (instagram.com)\n"
            "• Pinterest (pinterest.com, pin.it)",
            parse_mode="Markdown"
        )
        return

    status_msg = await update.message.reply_text("⏳ *Скачиваю видео...*", parse_mode="Markdown")

    try:
        filename = await download_video(text)
        if filename and os.path.exists(filename):
            increment_stats()
            await status_msg.delete()
            with open(filename, "rb") as f:
                await update.message.reply_video(
                    video=f,
                    caption="✅ *Видео без водяного знака готово!*",
                    parse_mode="Markdown",
                    supports_streaming=True
                )
            os.remove(filename)
        else:
            await status_msg.edit_text(
                "❌ *Не удалось скачать видео.*\n\n"
                "Возможные причины:\n"
                "• Ссылка недоступна\n"
                "• Видео защищено от скачивания\n"
                "• Попробуйте позже",
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Ошибка обработки: {e}")
        await status_msg.edit_text("❌ *Произошла ошибка. Попробуйте позже.*", parse_mode="Markdown")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на inline-кнопки."""
    query = update.callback_query
    await query.answer()

    if query.data == "stats":
        stats = load_stats()
        users = load_users()
        await query.edit_message_text(
            f"📊 *Статистика бота*\n\n"
            f"👥 Всего пользователей: {len(users)}\n"
            f"📥 Всего скачиваний: {stats['total_downloads']}",
            parse_mode="Markdown"
        )

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Открывает админ-панель."""
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⛔ *Доступ запрещён.*", parse_mode="Markdown")
        return

    keyboard = [
        [InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("👥 Пользователи", callback_data="admin_users")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔧 *Админ-панель*\n\nВыберите действие:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок админ-панели."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user

    if user.id != ADMIN_ID:
        await query.edit_message_text("⛔ *Доступ запрещён.*", parse_mode="Markdown")
        return

    if query.data == "admin_stats":
        stats = load_stats()
        users = load_users()
        await query.edit_message_text(
            f"📊 *Статистика бота*\n\n"
            f"👥 Всего пользователей: {len(users)}\n"
            f"📥 Всего скачиваний: {stats['total_downloads']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]
            ])
        )

    elif query.data == "admin_users":
        users = load_users()
        if not users:
            await query.edit_message_text(
                "👥 *Пользователи*\n\nПока нет зарегистрированных пользователей.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]
                ])
            )
            return
        user_list = "\n".join([f"• `{uid}`" for uid in sorted(users)])
        await query.edit_message_text(
            f"👥 *Пользователи*\n\n{user_list}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]
            ])
        )

    elif query.data == "admin_broadcast":
        context.user_data["broadcast_mode"] = True
        await query.edit_message_text(
            "📢 *Рассылка*\n\n"
            "Отправьте сообщение, которое нужно разослать всем пользователям.\n"
            "Поддерживаются текст, фото, видео, документы.\n\n"
            "Для отмены отправьте /cancel",
            parse_mode="Markdown"
        )

    elif query.data == "admin_back":
        keyboard = [
            [InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton("👥 Пользователи", callback_data="admin_users")],
        ]
        await query.edit_message_text(
            "🔧 *Админ-панель*\n\nВыберите действие:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик сообщений для рассылки."""
    user = update.effective_user
    if user.id != ADMIN_ID:
        return

    if not context.user_data.get("broadcast_mode"):
        return

    users = load_users()
    if not users:
        await update.message.reply_text("❌ *Нет пользователей для рассылки.*", parse_mode="Markdown")
        context.user_data["broadcast_mode"] = False
        return

    await update.message.reply_text(
        f"📢 *Начинаю рассылку для {len(users)} пользователей...*",
        parse_mode="Markdown"
    )

    success = 0
    failed = 0

    for user_id in users:
        try:
            await context.bot.copy_message(
                chat_id=user_id,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )
            success += 1
            await asyncio.sleep(0.05)  
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
            failed += 1

    context.user_data["broadcast_mode"] = False

    await update.message.reply_text(
        f"✅ *Рассылка завершена!*\n\n"
        f"✅ Успешно: {success}\n"
        f"❌ Ошибок: {failed}",
        parse_mode="Markdown"
    )

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена режима рассылки."""
    user = update.effective_user
    if user.id != ADMIN_ID:
        return

    if context.user_data.get("broadcast_mode"):
        context.user_data["broadcast_mode"] = False
        await update.message.reply_text("✅ *Рассылка отменена.*", parse_mode="Markdown")

def main():
    """Главная функция запуска бота."""
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("cancel", cancel_broadcast))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND & ~filters.TEXT, broadcast_handler))

    app.add_handler(CallbackQueryHandler(button_callback, pattern="^stats$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))

    logger.info("🚀 Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
