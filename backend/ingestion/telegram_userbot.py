"""
MTProto Userbot using Telethon for monitoring target chats
Listens to specific chat IDs and forwards receipts to processing
"""
import os
import asyncio
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from dotenv import load_dotenv
import json
from datetime import datetime
from workers.celery_worker import queue_receipt_task

load_dotenv()

# Configuration
API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
PHONE = os.getenv("USERBOT_PHONE")
SESSION_PATH = "sessions/userbot"

# Target chat IDs to monitor
TARGET_CHATS = [int(x.strip()) for x in os.getenv("TARGET_CHAT_IDS", "915326936,856264490,7028509569").split(",")]


async def resolve_peers(client: TelegramClient):
    """
    Resolve peer entities for target chats
    This is critical for MTProto to cache access_hash
    """
    print("🔍 Resolving target chat entities...")
    
    for chat_id in TARGET_CHATS:
        try:
            # Try to get entity (this caches the access_hash)
            entity = await client.get_entity(chat_id)
            print(f"✅ Resolved chat ID {chat_id}: {getattr(entity, 'title', 'User')}")
        except Exception as e:
            print(f"⚠️  Could not resolve chat ID {chat_id}: {e}")
            print(f"   Make sure you have interacted with this chat before or it's accessible to your account")


async def start_userbot():
    """Start MTProto userbot and monitor target chats"""
    print("🤖 Starting Telegram Userbot (MTProto)...")
    
    # Create Telethon client
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    
    # Event handler for new messages in target chats
    @client.on(events.NewMessage(chats=TARGET_CHATS))
    async def incoming_handler(event):
        """Handle incoming messages from monitored chats"""
        raw_text = event.message.message
        sender_id = event.sender_id
        msg_id = event.id
        chat_id = event.chat_id
        
        # Skip empty messages
        if not raw_text or len(raw_text) < 20:
            return
        
        # Check for receipt indicators
        keywords = ['UZS', 'USD', 'summa', 'karta', 'HUMOCARD', 'oplata', 'Оплата', 'Пополнение']
        if not any(keyword in raw_text for keyword in keywords):
            return
        
        print(f"📨 New receipt detected from chat {chat_id} (sender: {sender_id})")
        
        # Add to processing queue
        try:
            task_data = {
                'raw_text': raw_text,
                'source_type': 'AUTO',
                'source_chat_id': chat_id,
                'source_message_id': msg_id,
                'sender_id': sender_id,
                'timestamp': datetime.now().isoformat(),
                'added_via': 'userbot'
            }
            
            task_id = queue_receipt_task(task_data)
            print(f"✅ Задача отправлена в Celery (task_id={task_id})")
            
        except Exception as e:
            print(f"❌ Error dispatching receipt task: {e}")
    
    # Start client
    await client.start(phone=PHONE)
    print("✅ Userbot authenticated")
    
    # Check authorization
    if not await client.is_user_authorized():
        print("⚠️  User not authorized, requesting code...")
        await client.send_code_request(PHONE)
        code = input("Enter the code you received: ")
        try:
            await client.sign_in(PHONE, code)
        except SessionPasswordNeededError:
            password = input("Two-factor authentication enabled. Enter your password: ")
            await client.sign_in(password=password)
    
    # Resolve target peers
    await resolve_peers(client)
    
    print(f"✅ Monitoring {len(TARGET_CHATS)} chats: {TARGET_CHATS}")
    print("✅ Userbot is running! Press Ctrl+C to stop.")
    
    # Keep alive
    await client.run_until_disconnected()


async def main():
    """Main entry point with error handling"""
    max_retries = 5
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            await start_userbot()
            break
        except FloodWaitError as e:
            wait_time = e.seconds
            print(f"⚠️  Flood wait error. Waiting {wait_time} seconds...")
            await asyncio.sleep(wait_time)
            retry_count += 1
        except KeyboardInterrupt:
            print("\n👋 Userbot stopped by user")
            break
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            retry_count += 1
            if retry_count < max_retries:
                wait_time = min(2 ** retry_count, 60)  # Exponential backoff (max 60s)
                print(f"🔄 Retrying in {wait_time} seconds... (attempt {retry_count}/{max_retries})")
                await asyncio.sleep(wait_time)
            else:
                print("❌ Max retries reached. Exiting.")
                break


if __name__ == "__main__":
    asyncio.run(main())
