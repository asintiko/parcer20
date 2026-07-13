"""
Authentication Service for Telegram QR Code Login
Uses Telethon for QR code generation and authentication
"""
import os
import json
import asyncio
import secrets
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from contextlib import suppress
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
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "72"))
ACCESS_TOKEN_TTL_MINUTES = int(os.getenv("ACCESS_TOKEN_TTL_MINUTES", "4320"))
REFRESH_TOKEN_TTL_DAYS = int(os.getenv("REFRESH_TOKEN_TTL_DAYS", "30"))
TWO_FA_TEMP_TOKEN_TTL_MINUTES = int(os.getenv("TWO_FA_TEMP_TOKEN_TTL_MINUTES", "5"))
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
AUTH_SESSION_TTL_SECONDS = int(os.getenv("AUTH_SESSION_TTL_SECONDS", "600"))
AUTH_MAX_ACTIVE_SESSIONS = int(os.getenv("AUTH_MAX_ACTIVE_SESSIONS", "20"))
REFRESH_KEY_PREFIX = "auth:refresh:"
REFRESH_FAMILY_KEY_PREFIX = "auth:refresh_family:"
TEMP_2FA_TOKEN_KIND = "two_fa_pending"

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
_redis_pool: Optional[aioredis.Redis] = None
logger = logging.getLogger(__name__)


async def get_redis():
    """Get pooled Redis client."""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(
            REDIS_URL,
            decode_responses=True,
            max_connections=20,
        )
    return _redis_pool


async def close_redis_pool() -> None:
    global _redis_pool
    if _redis_pool is not None:
        with suppress(Exception):
            await _redis_pool.aclose()
    _redis_pool = None


def _utcnow() -> datetime:
    return datetime.utcnow()


def _new_token_id() -> str:
    return secrets.token_hex(16)


def _refresh_key(jti: str) -> str:
    return f"{REFRESH_KEY_PREFIX}{jti}"


def _refresh_family_key(family_id: str) -> str:
    return f"{REFRESH_FAMILY_KEY_PREFIX}{family_id}"


def _is_revoked_session_id(session_id: Optional[str]) -> bool:
    sid = str(session_id or "").strip()
    if not sid:
        return False
    try:
        from services.auth_bot_service import is_session_revoked

        return bool(is_session_revoked(sid))
    except Exception:
        logger.debug("Failed to check revoked session sid=%s", sid, exc_info=True)
        return False


def create_jwt_token(user_id: int, phone: str) -> str:
    """Create JWT token for authenticated user"""
    expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
    payload = {
        "kind": "qr_user",
        "user_id": user_id,
        "phone": phone,
        "exp": expire,
        "iat": datetime.utcnow()
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token


def create_app_user_token(
    *,
    user_id: int,
    username: str,
    role: str,
    permissions_version: int,
    display_name: Optional[str] = None,
    sid: Optional[str] = None,
    ttl_minutes: Optional[int] = None,
) -> str:
    """Create JWT token for RBAC app login."""
    ttl = max(1, int(ttl_minutes or ACCESS_TOKEN_TTL_MINUTES))
    session_id = (sid or _new_token_id()).strip()
    expire = _utcnow() + timedelta(minutes=ttl)
    payload: Dict[str, Any] = {
        "kind": "app_user",
        "sub": str(int(user_id)),
        "user_id": int(user_id),
        "username": username,
        "display_name": display_name or username,
        "role": role,
        "permissions_version": int(permissions_version or 1),
        "sid": session_id,
        "exp": expire,
        "iat": _utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_jwt_token(token: str) -> Optional[dict]:
    """Verify and decode JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        return None


def create_temp_2fa_token(
    *,
    user_id: int,
    username: str,
    role: str,
    permissions_version: int,
    requires_setup: bool = False,
) -> str:
    expires = _utcnow() + timedelta(minutes=max(1, TWO_FA_TEMP_TOKEN_TTL_MINUTES))
    payload: Dict[str, Any] = {
        "kind": TEMP_2FA_TOKEN_KIND,
        "sub": str(int(user_id)),
        "user_id": int(user_id),
        "username": username,
        "role": role,
        "permissions_version": int(permissions_version or 1),
        "requires_2fa_setup": bool(requires_setup),
        "jti": _new_token_id(),
        "exp": expires,
        "iat": _utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_temp_2fa_token(token: str) -> Optional[Dict[str, Any]]:
    payload = verify_jwt_token(token)
    if not payload:
        return None
    if str(payload.get("kind") or "") != TEMP_2FA_TOKEN_KIND:
        return None
    return payload


async def _save_refresh_record(
    *,
    jti: str,
    family_id: str,
    user_id: int,
    sid: str,
    role: str,
    username: str,
    permissions_version: int,
    ttl_seconds: int,
) -> None:
    redis = await get_redis()
    now = _utcnow()
    expires_at = now + timedelta(seconds=max(60, ttl_seconds))
    record = {
        "jti": jti,
        "family_id": family_id,
        "user_id": int(user_id),
        "sid": sid,
        "role": role,
        "username": username,
        "permissions_version": int(permissions_version or 1),
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    await redis.setex(_refresh_key(jti), ttl_seconds, json.dumps(record, ensure_ascii=False))
    await redis.setex(_refresh_family_key(family_id), ttl_seconds, "active")


async def create_refresh_token(
    *,
    user_id: int,
    username: str,
    role: str,
    permissions_version: int,
    family_id: Optional[str] = None,
    sid: Optional[str] = None,
    ttl_days: Optional[int] = None,
) -> Dict[str, Any]:
    now = _utcnow()
    effective_days = int(ttl_days) if ttl_days is not None else int(REFRESH_TOKEN_TTL_DAYS)
    ttl_seconds = max(60, effective_days * 24 * 3600)
    exp = now + timedelta(seconds=ttl_seconds)
    token_jti = _new_token_id()
    refresh_family_id = (family_id or _new_token_id()).strip()
    session_id = (sid or _new_token_id()).strip()
    payload: Dict[str, Any] = {
        "kind": "refresh_token",
        "sub": str(int(user_id)),
        "user_id": int(user_id),
        "username": username,
        "role": role,
        "permissions_version": int(permissions_version or 1),
        "family_id": refresh_family_id,
        "sid": session_id,
        "jti": token_jti,
        "exp": exp,
        "iat": now,
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    await _save_refresh_record(
        jti=token_jti,
        family_id=refresh_family_id,
        user_id=int(user_id),
        sid=session_id,
        role=role,
        username=username,
        permissions_version=int(permissions_version or 1),
        ttl_seconds=ttl_seconds,
    )
    return {
        "token": token,
        "jti": token_jti,
        "family_id": refresh_family_id,
        "sid": session_id,
        "expires_at": exp.isoformat(),
    }


async def verify_refresh_token(token: str) -> Optional[Dict[str, Any]]:
    payload = verify_jwt_token(token)
    if not payload:
        return None
    if str(payload.get("kind") or "") != "refresh_token":
        return None
    if _is_revoked_session_id(payload.get("sid")):
        return None

    token_jti = str(payload.get("jti") or "").strip()
    family_id = str(payload.get("family_id") or "").strip()
    if not token_jti or not family_id:
        return None

    redis = await get_redis()
    family_state = await redis.get(_refresh_family_key(family_id))
    if not family_state:
        return None
    record_raw = await redis.get(_refresh_key(token_jti))
    if not record_raw:
        return None
    try:
        record = json.loads(record_raw)
    except Exception:
        return None
    if int(record.get("user_id") or 0) != int(payload.get("user_id") or 0):
        return None
    return payload


async def rotate_refresh_token(token: str, *, ttl_days: Optional[int] = None) -> Optional[Dict[str, Any]]:
    payload = await verify_refresh_token(token)
    if not payload:
        return None

    token_jti = str(payload.get("jti") or "").strip()
    family_id = str(payload.get("family_id") or "").strip()
    user_id = int(payload.get("user_id"))
    username = str(payload.get("username") or f"user-{user_id}")
    role = str(payload.get("role") or "operator")
    permissions_version = int(payload.get("permissions_version") or 1)
    sid = str(payload.get("sid") or _new_token_id())

    redis = await get_redis()
    await redis.delete(_refresh_key(token_jti))

    return await create_refresh_token(
        user_id=user_id,
        username=username,
        role=role,
        permissions_version=permissions_version,
        family_id=family_id,
        sid=sid,
        ttl_days=ttl_days,
    )


async def revoke_refresh_family(family_id: Optional[str]) -> None:
    fid = str(family_id or "").strip()
    if not fid:
        return
    redis = await get_redis()
    await redis.delete(_refresh_family_key(fid))


async def generate_qr_login(session_id: str) -> dict:
    """
    Generate QR code for Telegram login
    Returns QR code as base64 image and login token
    """
    try:
        await _cleanup_stale_auth_sessions()
        if len(auth_sessions) >= AUTH_MAX_ACTIVE_SESSIONS:
            raise RuntimeError("Too many active auth sessions, try again later")

        # Create temporary client for QR auth
        session_path = f"sessions/qr_auth_{session_id}"
        client = TelegramClient(session_path, API_ID, API_HASH)

        # Store client reference
        auth_clients[session_id] = client

        # Connect but don't authenticate yet
        await client.connect()
        logger.info("[QR GEN] Session %s: Client connected", session_id)

        # Request QR login
        qr_login = await client.qr_login()
        logger.info("[QR GEN] Session %s: QR login object created", session_id)

        # Store session info
        auth_sessions[session_id] = {
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
            "qr_login": qr_login,
            "token": qr_login.token.hex()
        }
        logger.info("[QR GEN] Session %s: Session stored", session_id)

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
        logger.info("[AUTH CHECK] Session %s: is_authorized=%s", session_id, is_auth)

        if is_auth:
            # QR was scanned successfully
            logger.info("[AUTH SUCCESS] Session %s: Getting user info...", session_id)
            me = await client.get_me()
            logger.info("[AUTH SUCCESS] Session %s: User %s - %s", session_id, me.id, me.phone)

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
                logger.info("[AUTH SUCCESS] Session file copied to %s", permanent_session)

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


async def _cleanup_stale_auth_sessions() -> None:
    now = datetime.utcnow()
    stale: list[str] = []
    for sid, info in list(auth_sessions.items()):
        created_raw = str(info.get("created_at") or "").strip()
        try:
            created_at = datetime.fromisoformat(created_raw)
        except Exception:
            created_at = now - timedelta(seconds=AUTH_SESSION_TTL_SECONDS + 1)
        age = (now - created_at).total_seconds()
        if age > AUTH_SESSION_TTL_SECONDS:
            stale.append(sid)

    for sid in stale:
        await cleanup_session(sid)


async def logout_user(token: str) -> bool:
    """Logout user and invalidate token"""
    payload = verify_jwt_token(token)
    if not payload:
        return False

    user_id = payload.get("user_id") or payload.get("sub")
    try:
        user_id = int(user_id)
    except Exception:
        user_id = None

    sid = str(payload.get("sid") or "").strip()
    refresh_family = str(payload.get("family_id") or "").strip()

    try:
        redis = await get_redis()
        if user_id:
            await redis.delete(f"auth_token:{user_id}")
        if str(payload.get("kind") or "") == "refresh_token":
            token_jti = str(payload.get("jti") or "").strip()
            if token_jti:
                await redis.delete(_refresh_key(token_jti))
        if refresh_family:
            await revoke_refresh_family(refresh_family)
        if sid:
            with suppress(Exception):
                from services.auth_bot_service import revoke_active_session

                await revoke_active_session(sid, suppress_event=True)
        return True
    except Exception:
        return False


async def verify_user_token(token: str) -> Optional[dict]:
    """Verify user token and return user info"""
    payload = verify_jwt_token(token)
    if not payload:
        return None

    if _is_revoked_session_id(payload.get("sid")):
        return None

    token_kind = str(payload.get("kind") or "")
    if token_kind == "refresh_token":
        refresh_payload = await verify_refresh_token(token)
        return refresh_payload

    user_id = payload.get("user_id") or payload.get("sub")
    try:
        user_id = int(user_id)
    except Exception:
        user_id = None
    if not user_id:
        return payload

    # Check if token exists in Redis
    try:
        redis = await get_redis()
        stored_token = await redis.get(f"auth_token:{user_id}")

        if stored_token and stored_token != token:
            return None

        return payload
    except Exception:
        # If Redis fails, just verify the JWT signature
        return payload
