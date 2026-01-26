"""
Telegram Bot using Aiogram 3.x for manual receipt input
Handles user messages and forwards them to Celery for processing
"""
import os
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
import json
from workers.celery_worker import queue_receipt_task

load_dotenv()

# Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Handle /start command"""
    welcome_text = """
🇺🇿 **Uzbek Receipt Parser**

Привет! Я бот для парсинга финансовых чеков.

**Как использовать:**
1. Отправьте мне текст чека (скопируйте из SMS или уведомления банка)
2. Или перешлите сообщение с чеком
3. Я обработаю и извлеку все данные о транзакции

**Поддерживаются форматы:**
- Humo Card уведомления (с эмодзи)
- SMS от банков (обычный текст)
- Любые другие форматы (через AI)

Отправьте чек для начала!
    """
    await message.answer(welcome_text, parse_mode="Markdown")


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Handle /help command"""
    help_text = """
**Примеры поддерживаемых форматов:**

1️⃣ **Humo Card:**
```
💸 Оплата
➖ 400.000,00 UZS
📍 OQ P2P>TASHKENT
💳 HUMOCARD *6714
🕓 12:58 05.04.2025
💰 535.000,40 UZS
```

2️⃣ **SMS формат:**
```
Pokupka: XK FAMILY SHOP, TOSHKENT, 02.04.25 11:48 
karta ***0907. summa:80000.00 UZS, balans:2527792.14 UZS
```

3️⃣ **Краткий формат:**
```
HUMOCARD *6921: oplata 200000.00 UZS; SmartBank P2P HUMO U; 
25-04-02 15:33; Dostupno: 1852200.28 UZS
```

Просто отправьте любой из этих форматов!
    """
    await message.answer(help_text, parse_mode="Markdown")


@dp.message(F.text)
async def handle_text_message(message: types.Message):
    """Handle incoming text messages (receipts)"""
    raw_text = message.text
    
    # Validate minimum length
    if len(raw_text) < 20:
        await message.answer("❌ Текст слишком короткий. Отправьте полный чек.")
        return
    
    # Check for keywords to filter obvious non-receipts
    keywords = ['UZS', 'USD', 'summa', 'karta', 'HUMOCARD', 'oplata', 'Оплата', 'Пополнение']
    if not any(keyword in raw_text for keyword in keywords):
        await message.answer("❌ Это не похоже на чек. Проверьте текст и попробуйте снова.")
        return
    
    # Send processing message
    status_msg = await message.answer("⏳ Обрабатываю чек...")
    
    # Dispatch Celery task for async processing
    try:
        task_data = {
            'raw_text': raw_text,
            'source_type': 'MANUAL',
            'source_chat_id': message.chat.id,
            'source_message_id': message.message_id,
            'user_id': message.from_user.id,
            'status_message_id': status_msg.message_id,
            'added_via': 'telegram'
        }

        task_id = queue_receipt_task(task_data)
        await status_msg.edit_text(
            f"✅ Задача поставлена в обработку.\nID: `{task_id}`\n"
            "Обработка займет несколько секунд.",
            parse_mode="Markdown"
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка при постановке задачи в обработку: {str(e)}")


@dp.message(F.photo | F.document)
async def handle_media(message: types.Message):
    """Handle photos and documents (future OCR support)"""
    await message.answer(
        "📷 Обработка изображений пока не поддерживается.\n"
        "Пожалуйста, отправьте текст чека (скопируйте из SMS или уведомления)."
    )


async def main():
    """Main bot startup"""
    print("🤖 Starting Telegram Bot...")
    
    # Start polling
    print("✅ Bot is running! Press Ctrl+C to stop.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped")
