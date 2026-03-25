import asyncio
import sqlite3
import logging
import urllib.parse
from datetime import datetime
from typing import List, Dict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import aiohttp

BOT_TOKEN = "8575653382:AAE6zqc32Dc3kBqo7B1IRhF7jRRpYySG7q8"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DB_FILE = "search_history.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            query TEXT,
            searched_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_search(user_id, username, query):
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "INSERT INTO searches (user_id, username, query, searched_at) VALUES (?, ?, ?, ?)",
        (user_id, username or "unknown", query, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()

def get_history(user_id, limit=10):
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute(
        "SELECT query, searched_at FROM searches WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return rows

async def search_duckduckgo(query, max_results=5):
    results = []
    encoded = urllib.parse.quote(query)
    try:
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json(content_type=None)
        if data.get("AbstractText"):
            results.append({
                "title": data.get("Heading", query),
                "url": data.get("AbstractURL", ""),
                "snippet": data["AbstractText"][:200] + "..."
            })
        for topic in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict) and topic.get("Text") and topic.get("FirstURL"):
                results.append({
                    "title": topic["Text"][:60],
                    "url": topic["FirstURL"],
                    "snippet": topic["Text"][:150]
                })
    except Exception as e:
        logger.warning(f"DuckDuckGo error: {e}")
    return results[:max_results]

def build_social_links(query):
    q = urllib.parse.quote(query)
    return {
        "🌐 Google":    f"https://www.google.com/search?q={q}",
        "📘 VK":        f"https://vk.com/search?c[q]={q}&c[section]=people",
        "📸 Instagram": f"https://www.instagram.com/explore/search/keyword/?q={q}",
        "✈️ Telegram":  f"https://t.me/s/{q}",
        "▶️ YouTube":   f"https://www.youtube.com/results?search_query={q}",
        "🐦 Twitter/X": f"https://twitter.com/search?q={urllib.parse.quote(query)}&src=typed_query",
        "💼 LinkedIn":  f"https://www.linkedin.com/search/results/all/?keywords={q}",
        "👾 Reddit":    f"https://www.reddit.com/search/?q={q}",
    }

async def cmd_start(update, context):
    text = (
        "👋 Привет! Я бот для поиска по ключевым словам.\n\n"
        "🔍 Просто напишите что хотите найти — и я дам вам:\n"
        "  • Результаты из интернета\n"
        "  • Ссылки для поиска в соцсетях\n\n"
        "📋 Команды:\n"
        "  /search <запрос> — поиск\n"
        "  /history — история ваших поисков\n"
        "  /help — справка"
    )
    await update.message.reply_text(text)

async def cmd_help(update, context):
    text = (
        "ℹ️ <b>Как пользоваться ботом</b>\n\n"
        "1️⃣ Напишите любое ключевое слово или фразу\n"
        "2️⃣ Бот найдёт информацию в интернете\n"
        "3️⃣ Получите прямые ссылки для поиска в:\n"
        "   Google, VK, Instagram, Telegram, YouTube\n\n"
        "📌 /history — последние 10 поисков"
    )
    await update.message.reply_text(text, parse_mode="HTML")

async def cmd_history(update, context):
    user_id = update.effective_user.id
    rows = get_history(user_id)
    if not rows:
        await update.message.reply_text("📭 История поиска пуста.")
        return
    lines = ["📋 <b>Ваши последние поиски:</b>\n"]
    for i, (q, t) in enumerate(rows, 1):
        lines.append(f"{i}. <code>{q}</code>\n   🕒 {t}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

async def do_search(update, context, query):
    user = update.effective_user
    msg = await update.message.reply_text(f"🔍 Ищу: <b>{query}</b>...", parse_mode="HTML")
    save_search(user.id, user.username, query)
    web_results = await search_duckduckgo(query)
    response_lines = [f"🔎 <b>Результаты:</b> <code>{query}</code>\n"]
    if web_results:
        response_lines.append("🌐 <b>Из интернета:</b>")
        for r in web_results:
            title = r['title'][:50]
            snippet = r['snippet'][:120]
            url = r['url']
            if url:
                response_lines.append(f"• <a href='{url}'>{title}</a>\n  {snippet}\n")
            else:
                response_lines.append(f"• <b>{title}</b>\n  {snippet}\n")
    else:
        response_lines.append("⚠️ Используйте ссылки ниже.\n")
    social = build_social_links(query)
    keyboard = []
    items = list(social.items())
    for i in range(0, len(items), 2):
        row = [InlineKeyboardButton(items[i][0], url=items[i][1])]
        if i + 1 < len(items):
            row.append(InlineKeyboardButton(items[i+1][0], url=items[i+1][1]))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔁 Новый поиск", callback_data="new_search")])
    response_lines.append("\n📱 <b>Искать в соцсетях:</b>")
    await msg.edit_text(
        "\n".join(response_lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )

async def handle_message(update, context):
    query = update.message.text.strip()
    if not query:
        return
    await do_search(update, context, query)

async def cmd_search(update, context):
    if not context.args:
        await update.message.reply_text("✏️ Напишите запрос: /search <ключевые слова>")
        return
    query = " ".join(context.args)
    await do_search(update, context, query)

async def handle_callback(update, context):
    query = update.callback_query
    await query.answer()
    if query.data == "new_search":
        await query.message.reply_text("✏️ Напишите новый поисковый запрос:")

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
