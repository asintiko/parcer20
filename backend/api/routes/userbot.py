"""
API Routes for Userbot Management
Manages Telegram userbot configuration and connection
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional
import os
from dotenv import load_dotenv, set_key, find_dotenv

load_dotenv()

from api.dependencies import require_sources_scope, require_tab_access

router = APIRouter(
    prefix="/api/userbot",
    tags=["userbot"],
    dependencies=[Depends(require_tab_access("userbot")), Depends(require_sources_scope)],
)

# Request/Response Models
class UserbotConfig(BaseModel):
    api_id: str
    api_hash: str
    phone_number: str
    target_chat_ids: List[str] = Field(default_factory=list)


class UserbotStatus(BaseModel):
    is_connected: bool
    phone_number: Optional[str] = None
    monitored_chats: Optional[List[str]] = None


class SuccessResponse(BaseModel):
    success: bool
    message: str


def get_env_file_path():
    """Get the path to .env file"""
    env_path = find_dotenv()
    if not env_path:
        # If not found, use default path
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
    return env_path


def update_env_variable(key: str, value: str):
    """Update or add an environment variable to .env file"""
    env_path = get_env_file_path()

    if os.path.exists(env_path):
        set_key(env_path, key, value)
    else:
        # Create .env file if it doesn't exist
        with open(env_path, 'w') as f:
            f.write(f"{key}={value}\n")


@router.get("/config", response_model=UserbotConfig)
async def get_userbot_config():
    """Get current userbot configuration from environment"""

    api_id = os.getenv("TELEGRAM_API_ID", "")
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    phone_number = os.getenv("USERBOT_PHONE", "")
    target_chat_ids_str = os.getenv("TARGET_CHAT_IDS", "")

    # Parse chat IDs
    target_chat_ids = [
        chat_id.strip()
        for chat_id in target_chat_ids_str.split(",")
        if chat_id.strip()
    ] if target_chat_ids_str else []

    return UserbotConfig(
        api_id=api_id,
        api_hash=api_hash,
        phone_number=phone_number,
        target_chat_ids=target_chat_ids
    )


@router.post("/config", response_model=SuccessResponse)
async def update_userbot_config(config: UserbotConfig):
    """Update userbot configuration in .env file"""

    try:
        # Update environment variables in .env file
        update_env_variable("TELEGRAM_API_ID", config.api_id)
        update_env_variable("TELEGRAM_API_HASH", config.api_hash)
        update_env_variable("USERBOT_PHONE", config.phone_number)

        # Join chat IDs with comma
        chat_ids_str = ",".join(config.target_chat_ids)
        update_env_variable("TARGET_CHAT_IDS", chat_ids_str)

        # Reload environment variables
        load_dotenv(override=True)

        return SuccessResponse(
            success=True,
            message="Configuration updated successfully. Please restart the userbot container for changes to take effect."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update configuration: {str(e)}")


@router.get("/status", response_model=UserbotStatus)
async def get_userbot_status():
    """Get current userbot connection status"""

    import redis.asyncio as aioredis

    try:
        # Проверяем статус подключения в Redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        redis = await aioredis.from_url(redis_url, decode_responses=True)

        is_connected = await redis.get("userbot:connected") == "true"
        phone_number = await redis.get("userbot:phone")
        target_chat_ids_str = os.getenv("TARGET_CHAT_IDS", "")

        monitored_chats = [
            chat_id.strip()
            for chat_id in target_chat_ids_str.split(",")
            if chat_id.strip()
        ] if target_chat_ids_str else []

        await redis.close()

        return UserbotStatus(
            is_connected=is_connected,
            phone_number=phone_number if is_connected else None,
            monitored_chats=monitored_chats if is_connected else None
        )
    except Exception as e:
        # Если Redis недоступен, возвращаем disconnected
        return UserbotStatus(
            is_connected=False,
            phone_number=None,
            monitored_chats=None
        )


@router.post("/connect", response_model=SuccessResponse)
async def connect_userbot():
    """Connect userbot (restart userbot container)"""

    try:
        # Check if configuration is valid
        api_id = os.getenv("TELEGRAM_API_ID", "")
        api_hash = os.getenv("TELEGRAM_API_HASH", "")
        phone_number = os.getenv("USERBOT_PHONE", "")

        if not api_id or api_id == "your_api_id_from_my_telegram_org":
            raise HTTPException(status_code=400, detail="API ID is not configured")

        if not api_hash or api_hash == "your_api_hash_from_my_telegram_org":
            raise HTTPException(status_code=400, detail="API Hash is not configured")

        if not phone_number or phone_number == "+998901234567":
            raise HTTPException(status_code=400, detail="Phone number is not configured")

        # TODO: Implement actual connection by restarting userbot container
        # For now, return success message

        return SuccessResponse(
            success=True,
            message="Userbot connection initiated. Please restart the userbot container using: docker-compose restart userbot"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect userbot: {str(e)}")


@router.post("/disconnect", response_model=SuccessResponse)
async def disconnect_userbot():
    """Disconnect userbot (stop userbot container)"""

    import redis.asyncio as aioredis

    try:
        # Удаляем данные о подключении из Redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        redis = await aioredis.from_url(redis_url, decode_responses=True)

        await redis.delete("userbot:connected")
        await redis.delete("userbot:phone")
        await redis.delete("userbot:user_id")

        await redis.close()

        # Удаляем файл сессии
        import os as os_module
        session_file = "sessions/userbot.session"
        if os_module.path.exists(session_file):
            os_module.remove(session_file)

        return SuccessResponse(
            success=True,
            message="Userbot disconnected successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to disconnect userbot: {str(e)}")
