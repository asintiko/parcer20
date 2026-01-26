"""
Telegram Bot для извлечения текста из PDF чеков (Uzum Bank и другие)
"""
import os
import logging
import tempfile
from io import BytesIO

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
import asyncio

# PDF parsing libraries
import pdfplumber
from pdf2image import convert_from_bytes
import pytesseract

# Load environment
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("PDF_BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("PDF_BOT_TOKEN не установлен в .env файле!")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def extract_text_from_pdf_plumber(pdf_bytes: bytes) -> str:
    """Извлечение текста из PDF с помощью pdfplumber (для текстовых PDF)"""
    text_content = []
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_content.append(page_text)
    except Exception as e:
        logger.error(f"pdfplumber error: {e}")
    return "\n".join(text_content)


def extract_text_with_ocr(pdf_bytes: bytes) -> str:
    """Извлечение текста из PDF через OCR (для сканов и изображений)"""
    text_content = []
    try:
        # Convert PDF to images
        images = convert_from_bytes(pdf_bytes, dpi=300)
        for i, image in enumerate(images):
            # Use Tesseract OCR
            text = pytesseract.image_to_string(image, lang='rus+eng')
            if text.strip():
                text_content.append(text)
    except Exception as e:
        logger.error(f"OCR error: {e}")
    return "\n".join(text_content)


def parse_receipt_data(text: str) -> dict:
    """Парсинг извлеченного текста в структурированные данные"""
    data = {}
    
    # Ключевые поля чека Uzum Bank
    field_mappings = {
        'Sender': 'sender_card',
        'Sender name': 'sender_name',
        'Receiver': 'receiver_card',
        'Receiver name': 'receiver_name',
        'Transaction ID': 'transaction_id',
        'Transaction date': 'transaction_date',
        'Received date': 'received_date',
        'Receiver fee': 'receiver_fee',
        'Receiver amount': 'receiver_amount',
        'Sender fee': 'sender_fee',
        'Sender amount': 'sender_amount',
        # Русские варианты
        'Отправитель': 'sender_card',
        'Имя отправителя': 'sender_name',
        'Получатель': 'receiver_card',
        'Имя получателя': 'receiver_name',
        'ID транзакции': 'transaction_id',
        'Дата транзакции': 'transaction_date',
        'Дата получения': 'received_date',
        'Комиссия получателя': 'receiver_fee',
        'Сумма получателя': 'receiver_amount',
        'Комиссия отправителя': 'sender_fee',
        'Сумма отправителя': 'sender_amount',
    }
    
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        for field_name, field_key in field_mappings.items():
            if line.startswith(field_name):
                # Извлекаем значение после названия поля
                value = line.replace(field_name, '').strip()
                # Убираем лишние символы
                if value.startswith(':'):
                    value = value[1:].strip()
                if value:
                    data[field_key] = value
                break
    
    return data


def format_receipt_output(raw_text: str, parsed_data: dict) -> str:
    """Форматирование вывода для пользователя"""
    output = []
    
    output.append("📄 **ИЗВЛЕЧЕННЫЕ ДАННЫЕ ИЗ ЧЕКА**\n")
    output.append("=" * 40)
    
    if parsed_data:
        output.append("\n📊 **Структурированные данные:**\n")
        
        field_labels = {
            'sender_card': '💳 Карта отправителя',
            'sender_name': '👤 Имя отправителя',
            'receiver_card': '💳 Карта получателя',
            'receiver_name': '👤 Имя получателя',
            'transaction_id': '🔢 ID транзакции',
            'transaction_date': '📅 Дата транзакции',
            'received_date': '📅 Дата получения',
            'receiver_fee': '💰 Комиссия получателя',
            'receiver_amount': '💵 Сумма получателя',
            'sender_fee': '💰 Комиссия отправителя',
            'sender_amount': '💵 Сумма отправителя',
        }
        
        for key, label in field_labels.items():
            if key in parsed_data:
                output.append(f"{label}: `{parsed_data[key]}`")
    
    output.append("\n" + "=" * 40)
    output.append("\n📝 **Полный текст:**\n")
    output.append("```")
    output.append(raw_text[:3000] if len(raw_text) > 3000 else raw_text)
    output.append("```")
    
    return "\n".join(output)


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Обработка команды /start"""
    welcome_text = """
👋 **Привет! Я бот для извлечения данных из PDF чеков.**

📤 Просто отправьте мне PDF файл чека, и я извлеку из него все текстовые данные.

**Поддерживаемые форматы:**
• PDF с текстом (Uzum Bank, и др.)
• Сканы чеков (через OCR)

**Команды:**
• /start - Показать это сообщение
• /help - Помощь

Отправьте PDF файл чека, чтобы начать! 📎
    """
    await message.answer(welcome_text, parse_mode="Markdown")


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Обработка команды /help"""
    help_text = """
📖 **Помощь**

**Как использовать бота:**
1. Отправьте PDF файл чека
2. Бот извлечет текст и данные
3. Получите структурированный результат

**Поддерживаемые банки:**
• Uzum Bank
• И другие банки Узбекистана

При возникновении проблем - свяжитесь с администратором.
    """
    await message.answer(help_text, parse_mode="Markdown")


@dp.message(lambda message: message.document is not None)
async def handle_document(message: Message):
    """Обработка входящих документов"""
    document = message.document
    
    # Проверяем, что это PDF
    if not document.file_name.lower().endswith('.pdf'):
        await message.answer("⚠️ Пожалуйста, отправьте файл в формате PDF.")
        return
    
    # Отправляем статус обработки
    status_msg = await message.answer("⏳ Обрабатываю PDF файл...")
    
    try:
        # Скачиваем файл
        file = await bot.get_file(document.file_id)
        file_bytes = await bot.download_file(file.file_path)
        pdf_bytes = file_bytes.read()
        
        # Сначала пробуем извлечь текст напрямую (текстовый PDF)
        text = extract_text_from_pdf_plumber(pdf_bytes)
        
        # Если текста нет или его мало - используем OCR
        if not text or len(text.strip()) < 50:
            await status_msg.edit_text("🔍 Текст не найден, запускаю OCR...")
            text = extract_text_with_ocr(pdf_bytes)
        
        if not text or not text.strip():
            await status_msg.edit_text("❌ Не удалось извлечь текст из PDF. Возможно файл пустой или защищен.")
            return
        
        # Парсим структурированные данные
        parsed_data = parse_receipt_data(text)
        
        # Форматируем вывод
        output = format_receipt_output(text, parsed_data)
        
        # Отправляем результат (разбиваем на части если длинный)
        await status_msg.delete()
        
        if len(output) > 4000:
            # Разбиваем на части
            parts = [output[i:i+4000] for i in range(0, len(output), 4000)]
            for part in parts:
                await message.answer(part, parse_mode="Markdown")
        else:
            await message.answer(output, parse_mode="Markdown")
            
        logger.info(f"Processed PDF from user {message.from_user.id}: {document.file_name}")
        
    except Exception as e:
        logger.error(f"Error processing PDF: {e}")
        await status_msg.edit_text(f"❌ Ошибка при обработке PDF: {str(e)}")


@dp.message()
async def handle_other(message: Message):
    """Обработка других сообщений"""
    await message.answer("📎 Отправьте мне PDF файл чека для извлечения данных.")


async def main():
    """Запуск бота"""
    logger.info("Starting PDF Receipt Bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
