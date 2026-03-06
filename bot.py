import os
import asyncio
import html
import logging
from typing import Optional

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, BotCommand

# =========================
# НАСТРОЙКИ
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set")

DB_PATH = "users.db"

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()


# =========================
# БАЗА ДАННЫХ
# =========================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id      INTEGER NOT NULL,
                user_id      INTEGER NOT NULL,
                username     TEXT,
                first_name   TEXT,
                last_name    TEXT,
                is_bot       INTEGER DEFAULT 0,
                joined_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, user_id)
            )
        """)
        await db.commit()


async def save_user(
    chat_id: int,
    user_id: int,
    username: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
    is_bot: bool
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (
                chat_id, user_id, username, first_name, last_name, is_bot, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                username   = excluded.username,
                first_name = excluded.first_name,
                last_name  = excluded.last_name,
                is_bot     = excluded.is_bot,
                updated_at = CURRENT_TIMESTAMP
        """, (
            chat_id,
            user_id,
            username,
            first_name,
            last_name,
            1 if is_bot else 0
        ))
        await db.commit()


async def get_users(chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT user_id, username, first_name, last_name
            FROM users
            WHERE chat_id = ? AND is_bot = 0
            ORDER BY first_name COLLATE NOCASE
        """, (chat_id,))
        rows = await cursor.fetchall()
        return rows


def user_display_name(
    username: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str]
) -> str:
    full_name = " ".join(x for x in [first_name, last_name] if x)
    if full_name.strip():
        return full_name.strip()
    if username:
        return f"@{username}"
    return "пользователь"


def chunk_text(text: str, limit: int = 4000):
    parts = []
    current = ""

    for line in text.split("\n"):
        candidate = (current + "\n" + line).strip() if current else line
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                parts.append(current)
            if len(line) <= limit:
                current = line
            else:
                for i in range(0, len(line), limit):
                    parts.append(line[i:i + limit])
                current = ""

    if current:
        parts.append(current)

    return parts


# =========================
# КОМАНДЫ
# =========================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Я работаю в группе.\n"
        "Команды:\n"
        "/help — помощь\n"
        "/all текст — упомянуть всех сохранённых участников"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Доступные команды:\n"
        "/help — показать это сообщение\n"
        "/all текст — отметить всех пользователей, которых я сохранил\n\n"
        "Дополнительно:\n"
        "Если кто-то напишет ровно: ясно\n"
        "я отвечу: хуясно"
    )


@dp.message(Command("all"))
async def cmd_all(message: Message, command: CommandObject):
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Эта команда работает только в группе.")
        return

    users = await get_users(message.chat.id)

    if not users:
        await message.answer("Я пока никого не сохранил в этой группе.")
        return

    extra_text = (command.args or "").strip()
    if not extra_text:
        extra_text = "Внимание всем!"

    mentions = []
    for user_id, username, first_name, last_name in users:
        name = user_display_name(username, first_name, last_name)
        safe_name = html.escape(name)
        mentions.append(f'<a href="tg://user?id={user_id}">{safe_name}</a>')

    text = ", ".join(mentions) + "\n\n" + html.escape(extra_text)

    for part in chunk_text(text):
        await message.answer(part, disable_web_page_preview=True)


# =========================
# СОХРАНЕНИЕ ПОЛЬЗОВАТЕЛЕЙ
# =========================
@dp.message(F.new_chat_members)
async def on_new_chat_members(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return

    for user in message.new_chat_members:
        await save_user(
            chat_id=message.chat.id,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            is_bot=user.is_bot
        )


@dp.message()
async def on_any_message(message: Message):
    if message.chat.type in ("group", "supergroup") and message.from_user:
        await save_user(
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            is_bot=message.from_user.is_bot
        )

    if message.text:
        text = message.text.strip().lower()
        if text == "ясно":
            await message.reply("хуясно")


# =========================
# ЗАПУСК
# =========================
async def set_bot_commands():
    commands = [
        BotCommand(command="help", description="Показать помощь"),
        BotCommand(command="all", description="Отметить всех: /all текст"),
    ]
    await bot.set_my_commands(commands)


async def main():
    await init_db()
    await set_bot_commands()
    print("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
