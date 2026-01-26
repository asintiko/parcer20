"""
Authentication Service for Telegram QR Code Login
Uses Telethon for QR code generation and authentication
"""
import os
import asyncio
from typing import Optional, Dict
from datetime import datetime, timedelta
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
import qrcode
import io
import base64
from jose import jwt, JWTError
import redis.asyncio as aioredis

# Configuration - all sensitive values MUST be set via environment variables
API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "720"))
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# Validate required environment variables at import time
_missing_vars = []
if not API_ID:
    _missing_vars.append("TELEGRAM_API_ID")
if not API_HASH:
    _missing_vars.append("TELEGRAM_API_HASH")
if not JWT_SECRET:
    _missing_vars.append("JWT_SECRET")
if _missing_vars:
    raise EnvironmentError(f"Missing required environment variables: {', '.join(_missing_vars)}")

API_ID = int(API_ID)

# Global client storage
auth_clients: Dict[str, TelegramClient] = {}
auth_sessions: Dict[str, dict] = {}


async def get_redis():
    """Get Redis client"""
    return await aioredis.from_url(REDIS_URL, decode_responses=True)


def create_jwt_token(user_id: int, phone: str) -> str:
    """Create JWT token for authenticated user"""
    expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
    payload = {
        "user_id": user_id,
        "phone": phone,
        "exp": expire,
        "iat": datetime.utcnow()
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token


def verify_jwt_token(token: str) -> Optional[dict]:
    """Verify and decode JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        return None


async def generate_qr_login(session_id: str) -> dict:
    """
    Generate QR code for Telegram login
    Returns QR code as base64 image and login token
    """
    try:
        # Create temporary client for QR auth
        session_path = f"sessions/qr_auth_{session_id}"
        client = TelegramClient(session_path, API_ID, API_HASH)

        # Store client reference
        auth_clients[session_id] = client

        # Connect but don't authenticate yet
        await client.connect()
        print(f"[QR GEN] Session {session_id}: Client connected")

        # Request QR login
        qr_login = await client.qr_login()
        print(f"[QR GEN] Session {session_id}: QR login object created")

        # Store session info
        auth_sessions[session_id] = {
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
            "qr_login": qr_login,
            "token": qr_login.token.hex()
        }
        print(f"[QR GEN] Session {session_id}: Session stored")

        # Generate QR code URL (tg:// format)
        qr_url = qr_login.url

        # Create QR code image
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qr_url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        # Convert to base64
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        img_str = base64.b64encode(buffer.getvalue()).decode()

        return {
            "session_id": session_id,
            "qr_code": f"data:image/png;base64,{img_str}",
            "url": qr_url,
            "expires_in": 300  # 5 minutes
        }

    except Exception as e:
        # Clean up on error
        if session_id in auth_clients:
            try:
                await auth_clients[session_id].disconnect()
            except Exception:
                pass
            del auth_clients[session_id]
        if session_id in auth_sessions:
            del auth_sessions[session_id]
        raise Exception(f"Failed to generate QR login: {str(e)}")


async def check_qr_login_status(session_id: str) -> dict:
    """
    Check if QR code has been scanned and user is authenticated
    Returns status and JWT token if authenticated
    """
    if session_id not in auth_sessions:
        return {"status": "expired", "message": "Session not found or expired"}

    session_info = auth_sessions[session_id]

    if session_info["status"] == "authenticated":
        return {
            "status": "authenticated",
            "token": session_info.get("jwt_token"),
            "user": session_info.get("user_info")
        }

    client = auth_clients.get(session_id)
    if not client:
        return {"status": "error", "message": "Client not found"}

    try:
        # Check if user is already authorized (QR was scanned)
        is_auth = await client.is_user_authorized()
        print(f"[AUTH CHECK] Session {session_id}: is_authorized={is_auth}")

        if is_auth:
            # QR was scanned successfully
            print(f"[AUTH SUCCESS] Session {session_id}: Getting user info...")
            me = await client.get_me()
            print(f"[AUTH SUCCESS] Session {session_id}: User {me.id} - {me.phone}")

            # Create JWT token
            jwt_token = create_jwt_token(me.id, me.phone or "")

            # Update session
            auth_sessions[session_id]["status"] = "authenticated"
            auth_sessions[session_id]["jwt_token"] = jwt_token
            auth_sessions[session_id]["user_info"] = {
                "id": me.id,
                "first_name": me.first_name,
                "last_name": me.last_name,
                "username": me.username,
                "phone": me.phone
            }

            # Store token in Redis
            redis = await get_redis()
            await redis.setex(
                f"auth_token:{me.id}",
                JWT_EXPIRATION_HOURS * 3600,
                jwt_token
            )

            # ВАЖНО: Сохраняем информацию о подключенном userbot
            await redis.set("userbot:connected", "true")
            await redis.set("userbot:phone", me.phone or "")
            await redis.set("userbot:user_id", str(me.id))

            await redis.close()

            # Копируем сессию в постоянное хранилище для userbot
            import shutil
            import os
            temp_session = f"sessions/qr_auth_{session_id}.session"
            permanent_session = "sessions/userbot.session"

            if os.path.exists(temp_session):
                # Создаем директорию если не существует
                os.makedirs("sessions", exist_ok=True)
                # Копируем файл сессии
                shutil.copy2(temp_session, permanent_session)
                print(f"[AUTH SUCCESS] Session file copied to {permanent_session}")

            return {
                "status": "authenticated",
                "token": jwt_token,
                "user": auth_sessions[session_id]["user_info"]
            }
        else:
            # Still waiting for QR scan
            return {"status": "pending", "message": "Waiting for QR scan"}

    except SessionPasswordNeededError:
        return {"status": "password_required", "message": "2FA password required"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def cleanup_session(session_id: str):
    """Clean up authentication session"""
    if session_id in auth_clients:
        try:
            await auth_clients[session_id].disconnect()
        except Exception:
            pass
        del auth_clients[session_id]

    if session_id in auth_sessions:
        del auth_sessions[session_id]


async def logout_user(token: str) -> bool:
    """Logout user and invalidate token"""
    payload = verify_jwt_token(token)
    if not payload:
        return False

    user_id = payload.get("user_id")
    if not user_id:
        return False

    # Remove from Redis
    try:
        redis = await get_redis()
        await redis.delete(f"auth_token:{user_id}")
        await redis.close()
        return True
    except Exception:
        return False


async def verify_user_token(token: str) -> Optional[dict]:
    """Verify user token and return user info"""
    payload = verify_jwt_token(token)
    if not payload:
        return None

    user_id = payload.get("user_id")

    # Check if token exists in Redis
    try:
        redis = await get_redis()
        stored_token = await redis.get(f"auth_token:{user_id}")
        await redis.close()

        if stored_token != token:
            return None

        return payload
    except Exception:
        # If Redis fails, just verify the JWT signature
        return payload
