"""
TDLib-based Telegram client manager
- Manages a single TDLib session stored on disk (volume)
- Exposes helpers for auth flow, chats, messages and documents
"""
import asyncio
import ctypes
import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Callable, Awaitable

from sqlalchemy.orm import Session

from database.models import HiddenBotChat

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class TDLibUnavailableError(RuntimeError):
    """Raised when libtdjson is missing or cannot be loaded."""


class TDJsonClient:
    """Low-level wrapper around libtdjson using ctypes."""

    def __init__(self, lib_path: str):
        self.lib_path = lib_path
        self.lib = ctypes.CDLL(lib_path)

        # Configure signatures
        self.lib.td_json_client_create.restype = ctypes.c_void_p
        self.lib.td_json_client_send.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        self.lib.td_json_client_receive.argtypes = [ctypes.c_void_p, ctypes.c_double]
        self.lib.td_json_client_receive.restype = ctypes.c_char_p
        self.lib.td_json_client_execute.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        self.lib.td_json_client_execute.restype = ctypes.c_char_p
        self.lib.td_json_client_destroy.argtypes = [ctypes.c_void_p]

        self.client = self.lib.td_json_client_create()

    def send(self, query: Dict[str, Any]) -> None:
        self.lib.td_json_client_send(self.client, json.dumps(query).encode("utf-8"))

    def receive(self, timeout: float = 0.5) -> Optional[Dict[str, Any]]:
        result = self.lib.td_json_client_receive(self.client, ctypes.c_double(timeout))
        if result:
            data = ctypes.cast(result, ctypes.c_char_p).value
            if data:
                return json.loads(data.decode("utf-8"))
        return None

    def execute(self, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        result = self.lib.td_json_client_execute(self.client, json.dumps(query).encode("utf-8"))
        if result:
            data = ctypes.cast(result, ctypes.c_char_p).value
            if data:
                return json.loads(data.decode("utf-8"))
        return None

    def destroy(self) -> None:
        if self.client:
            self.lib.td_json_client_destroy(self.client)
            self.client = None


class TelegramTDLibManager:
    """Singleton-style manager for TDLib interactions."""

    def __init__(self):
        self.api_id = int(os.getenv("TDLIB_API_ID") or os.getenv("TELEGRAM_API_ID", "0"))
        self.api_hash = os.getenv("TDLIB_API_HASH") or os.getenv("TELEGRAM_API_HASH", "")
        self.database_directory = os.getenv("TDLIB_DATABASE_DIR", "/app/sessions/tdlib")
        self.files_directory = os.getenv("TDLIB_FILES_DIR", os.path.join(self.database_directory, "files"))
        self.system_language_code = os.getenv("TDLIB_LANGUAGE_CODE", "en")
        self.device_model = os.getenv("TDLIB_DEVICE_MODEL", "server")
        self.application_version = os.getenv("TDLIB_APP_VERSION", "1.0")
        self.system_version = os.getenv("TDLIB_SYSTEM_VERSION", "server")
        self.database_encryption_key = os.getenv("TDLIB_ENCRYPTION_KEY", "")
        self.use_test_dc = self._env_bool("TDLIB_USE_TEST_DC", False)
        self.ignore_file_names = self._env_bool("TDLIB_IGNORE_FILE_NAMES", False)
        self.lib_path = os.getenv("TDLIB_LIB_PATH", "/usr/local/lib/libtdjson.so")
        self.log_verbosity = int(os.getenv("TDLIB_LOG_VERBOSITY", "1"))
        self.log_file = os.getenv("TDLIB_LOG_FILE", os.path.join(self.database_directory, "tdlib.log"))

        self._client: Optional[TDJsonClient] = None
        self._receive_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False
        self._pending: Dict[str, asyncio.Future] = {}
        self._auth_state_raw: str = "authorizationStateWaitPhoneNumber"
        self._phone_number: Optional[str] = None
        self._me: Optional[Dict[str, Any]] = None
        self._chat_cache: Dict[int, Dict[str, Any]] = {}
        self._user_cache: Dict[int, Dict[str, Any]] = {}
        self._load_error: Optional[Exception] = None
        self._params_applied = False
        self._encryption_checked = False
        self._new_message_handlers: List[Callable[[Dict[str, Any]], Awaitable[None]]] = []
        self._last_code_info: Optional[Dict[str, Any]] = None

    @staticmethod
    def _env_bool(key: str, default: bool = False) -> bool:
        value = os.getenv(key)
        if value is None:
            return default
        return str(value).lower() in ("1", "true", "yes", "y", "on")

    async def start(self) -> None:
        if self._client:
            return

        if not self.api_id or not self.api_hash:
            raise RuntimeError("TDLib API credentials are not configured")

        os.makedirs(self.database_directory, exist_ok=True)
        os.makedirs(self.files_directory, exist_ok=True)

        self._loop = asyncio.get_running_loop()

        try:
            self._client = TDJsonClient(self.lib_path)
        except Exception as exc:  # noqa: BLE001
            self._load_error = exc
            logger.error("Failed to load TDLib library from %s: %s", self.lib_path, exc)
            raise TDLibUnavailableError(f"TDLib library not available at {self.lib_path}") from exc

        # Configure TDLib logging to a persistent file for easier diagnostics
        try:
            os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
            self._client.execute(
                {
                    "@type": "setLogStream",
                    "log_stream": {
                        "@type": "logStreamFile",
                        "path": self.log_file,
                        "max_file_size": 50_000_000,
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to set TDLib log stream to %s: %s", self.log_file, exc)
        self._client.execute({"@type": "setLogVerbosityLevel", "new_verbosity_level": self.log_verbosity})

        self._running = True
        self._receive_thread = threading.Thread(target=self._run_receive_loop, name="tdlib-receiver", daemon=True)
        self._receive_thread.start()

        state_info = self._client.execute({"@type": "getAuthorizationState"})
        if isinstance(state_info, dict):
            self._auth_state_raw = state_info.get("@type", self._auth_state_raw)

        await self._apply_tdlib_parameters()
        await self._handle_auth_state_change(self._auth_state_raw)
        self._client.send({"@type": "getAuthorizationState"})

    def _run_receive_loop(self) -> None:
        while self._running and self._client:
            try:
                update = self._client.receive(timeout=0.5)
                if update is None:
                    continue
                if self._loop:
                    asyncio.run_coroutine_threadsafe(self._handle_incoming(update), self._loop)
            except Exception as exc:  # noqa: BLE001
                logger.exception("TDLib receive loop error: %s", exc)
                time.sleep(0.5)

    async def _handle_incoming(self, update: Dict[str, Any]) -> None:
        extra = update.get("@extra")
        if extra and extra in self._pending:
            future = self._pending.pop(extra)
            if not future.done():
                future.set_result(update)
            return
        await self._process_update(update)

    async def _process_update(self, update: Dict[str, Any]) -> None:
        update_type = update.get("@type")
        if update_type == "updateAuthorizationState":
            auth_state = update.get("authorization_state", {})
            self._auth_state_raw = auth_state.get("@type", self._auth_state_raw)
            self._last_code_info = auth_state.get("code_info")
            if self._last_code_info:
                code_type = (self._last_code_info.get("type") or {}).get("@type")
                timeout = self._last_code_info.get("timeout")
                phone = self._last_code_info.get("phone_number") or self._phone_number
                logger.info("TDLib auth: code requested via %s (timeout=%s, phone=%s)", code_type, timeout, phone)
            await self._handle_auth_state_change(self._auth_state_raw)
            if self._auth_state_raw == "authorizationStateReady":
                self._phone_number = auth_state.get("code_info", {}).get("phone_number", self._phone_number)
        elif update_type == "updateUser":
            user = update.get("user")
            if user:
                self._user_cache[user.get("id")] = user
                if self._me and self._me.get("id") == user.get("id"):
                    self._me = user
        elif update_type == "updateOption":
            if update.get("name") == "my_id":
                try:
                    self._me = {"id": int(update.get("value", {}).get("value", "0"))}
                except Exception:
                    pass
        elif update_type == "updateNewMessage":
            message = update.get("message")
            if message:
                chat_id = message.get("chat_id")
                if chat_id and chat_id in self._chat_cache:
                    self._chat_cache[chat_id]["last_message"] = self._format_message(message)
                formatted = self._format_message(message)
                for handler in list(self._new_message_handlers):
                    try:
                        asyncio.create_task(handler(formatted or {}))
                    except Exception:  # noqa: BLE001
                        logger.exception("Failed to dispatch new message handler")
        elif update_type == "updateChatLastMessage":
            chat_id = update.get("chat_id")
            last_message = update.get("last_message")
            if chat_id and last_message and chat_id in self._chat_cache:
                self._chat_cache[chat_id]["last_message"] = self._format_message(last_message)

    async def _send_request(self, payload: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
        if not self._client:
            await self.start()
        if not self._loop:
            self._loop = asyncio.get_running_loop()

        extra = str(uuid.uuid4())
        payload["@extra"] = extra

        future: asyncio.Future = self._loop.create_future()
        self._pending[extra] = future

        self._client.send(payload)

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(extra, None)

    async def _apply_tdlib_parameters(self) -> None:
        if not self._client or self._params_applied:
            return
        parameters = {
            "@type": "setTdlibParameters",
            "database_directory": self.database_directory,
            "files_directory": self.files_directory,
            "use_message_database": True,
            "use_chat_info_database": True,
            "use_file_database": True,
            "use_secret_chats": False,
            "system_language_code": self.system_language_code,
            "device_model": self.device_model,
            "system_version": self.system_version,
            "application_version": self.application_version,
            "enable_storage_optimizer": True,
            "api_id": self.api_id,
            "api_hash": self.api_hash,
            "use_test_dc": self.use_test_dc,
            "ignore_file_names": self.ignore_file_names,
            "database_encryption_key": self.database_encryption_key or "",
        }
        try:
            await self._send_request(parameters, timeout=10)
            self._params_applied = True
        except Exception as exc:  # noqa: BLE001
            self._params_applied = False
            logger.error("Failed to apply TDLib parameters: %s", exc)

    async def _apply_database_encryption_key(self) -> None:
        if not self._client or self._encryption_checked:
            return
        try:
            await self._send_request(
                {
                    "@type": "checkDatabaseEncryptionKey",
                    "encryption_key": self.database_encryption_key or "",
                },
                timeout=10,
            )
            self._encryption_checked = True
        except Exception as exc:  # noqa: BLE001
            self._encryption_checked = False
            logger.error("Failed to apply TDLib encryption key: %s", exc)

    async def _handle_auth_state_change(self, raw_state: str) -> None:
        if raw_state == "authorizationStateWaitTdlibParameters":
            self._params_applied = False
            await self._apply_tdlib_parameters()
        elif raw_state == "authorizationStateWaitEncryptionKey":
            await self._apply_database_encryption_key()
        elif raw_state in ("authorizationStateLoggingOut", "authorizationStateClosed"):
            self._params_applied = False
            self._encryption_checked = False
        elif raw_state == "authorizationStateReady":
            self._params_applied = True
            self._encryption_checked = True

    async def get_auth_state(self) -> Dict[str, Any]:
        if self._load_error:
            return {
                "state": "tdlib_unavailable",
                "raw_state": str(self._load_error),
                "is_authorized": False,
            }

        try:
            await self.start()
        except RuntimeError as exc:
            return {
                "state": "misconfigured",
                "raw_state": str(exc),
                "is_authorized": False,
            }

        state = self._map_auth_state(self._auth_state_raw)
        user_info = None
        if self._auth_state_raw == "authorizationStateReady":
            user_info = await self._get_me()

        return {
            "state": state,
            "raw_state": self._auth_state_raw,
            "is_authorized": state == "ready",
            "phone_number": self._phone_number,
            "user": user_info,
            "code_info": self._last_code_info,
        }

    def _map_auth_state(self, raw_state: str) -> str:
        return {
            "authorizationStateWaitPhoneNumber": "wait_phone_number",
            "authorizationStateWaitCode": "wait_code",
            "authorizationStateWaitPassword": "wait_password",
            "authorizationStateReady": "ready",
            "authorizationStateClosing": "closing",
            "authorizationStateClosed": "closed",
            "authorizationStateLoggingOut": "logging_out",
            "authorizationStateWaitTdlibParameters": "wait_tdlib_parameters",
            "authorizationStateWaitEncryptionKey": "wait_encryption_key",
        }.get(raw_state, "unknown")

    async def set_phone_number(self, phone: str) -> Dict[str, Any]:
        self._phone_number = phone
        response = await self._send_request(
            {
                "@type": "setAuthenticationPhoneNumber",
                "phone_number": phone,
                "settings": {
                    "allow_flash_call": False,
                    "allow_missed_call": False,
                    "is_current_phone_number": False,
                },
            }
        )
        return response

    async def check_code(self, code: str) -> Dict[str, Any]:
        return await self._send_request({"@type": "checkAuthenticationCode", "code": code})

    async def resend_code(self) -> Dict[str, Any]:
        """
        Request Telegram to resend the authentication code.
        Works only when authorizationStateWaitCode is active.
        """
        return await self._send_request({"@type": "resendAuthenticationCode"})

    async def check_password(self, password: str) -> Dict[str, Any]:
        return await self._send_request({"@type": "checkAuthenticationPassword", "password": password})

    async def logout(self) -> Dict[str, Any]:
        return await self._send_request({"@type": "logOut"})

    async def _get_me(self) -> Optional[Dict[str, Any]]:
        if self._me and "first_name" in self._me:
            return self._format_user(self._me)
        try:
            me_response = await self._send_request({"@type": "getMe"})
            if me_response.get("@type") == "user":
                self._me = me_response
                self._user_cache[me_response.get("id")] = me_response
                return self._format_user(me_response)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fetch self info: %s", exc)
        return None

    def _format_user(self, user: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": user.get("id"),
            "first_name": user.get("first_name"),
            "last_name": user.get("last_name"),
            "username": user.get("username"),
            "phone_number": user.get("phone_number"),
            "is_bot": user.get("type", {}).get("@type") == "userTypeBot",
        }

    async def list_chats(
        self,
        db: Session,
        include_hidden: bool = False,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        chat_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        List Telegram chats (bots, groups, supergroups, channels).

        Args:
            db: Database session
            include_hidden: Include chats marked as hidden
            search: Search query for chat titles
            limit: Maximum number of chats to return
            offset: Number of chats to skip
            chat_types: List of chat types to include; defaults to ['private', 'group', 'supergroup', 'channel']

        Returns:
            Dict with 'total' count and 'items' list of chat info
        """
        limit = min(max(limit, 1), 500)
        offset = max(offset, 0)

        hidden_ids = {row[0] for row in db.query(HiddenBotChat.chat_id).all()}

        chats = await self._fetch_bot_chats(
            search=search,
            limit=limit + offset,
            allowed_types=chat_types or ["private", "group", "supergroup", "channel"]
        )

        filtered: List[Dict[str, Any]] = []
        for chat in chats:
            chat_id = chat.get("chat_id")
            is_hidden = chat_id in hidden_ids
            if is_hidden and not include_hidden:
                continue
            chat["is_hidden"] = is_hidden
            filtered.append(chat)

        total = len(filtered)
        sliced = filtered[offset : offset + limit]
        return {"total": total, "items": sliced}

    async def list_bot_chats(
        self,
        db: Session,
        include_hidden: bool = False,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        chat_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Legacy helper that restricts to private chats (bots) only.
        """
        return await self.list_chats(
            db=db,
            include_hidden=include_hidden,
            search=search,
            limit=limit,
            offset=offset,
            chat_types=chat_types or ["private"]
        )

    async def get_chat_info(self, chat_id: int, allowed_types: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """
        Public wrapper around internal chat fetcher to reuse type-mapping logic.
        """
        return await self._get_chat_info(
            chat_id=chat_id,
            allowed_types=allowed_types or ["private", "group", "supergroup", "channel"]
        )

    async def _fetch_bot_chats(
        self,
        search: Optional[str],
        limit: int,
        allowed_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch chats from TDLib with type filtering.

        Args:
            search: Search query for chat titles
            limit: Maximum number of chats to fetch
            allowed_types: List of allowed chat types (passed to _get_chat_info)

        Returns:
            List of chat info dicts
        """
        request_payload: Dict[str, Any]
        if search:
            request_payload = {"@type": "searchChats", "query": search, "limit": limit}
        else:
            request_payload = {"@type": "getChats", "limit": limit}

        try:
            response = await self._send_request(request_payload)
        except Exception as exc:  # noqa: BLE001
            logger.error("TDLib chat fetch failed: %s", exc)
            return []

        chat_ids: List[int] = response.get("chat_ids") or []
        chats: List[Dict[str, Any]] = []
        for chat_id in chat_ids:
            info = await self._get_chat_info(chat_id, allowed_types=allowed_types)
            if info:
                chats.append(info)
        return chats

    async def _get_chat_info(
        self,
        chat_id: int,
        allowed_types: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get chat info with flexible type filtering.

        Args:
            chat_id: Telegram chat ID
            allowed_types: List of allowed types: ['private', 'group', 'basicGroup', 'supergroup', 'channel']
                           If None, only allow private bot chats (backward compatible)

        Returns:
            Chat info dict with chat_type field, or None if filtered out
        """
        if chat_id in self._chat_cache:
            cached = self._chat_cache.get(chat_id)
            # Check if cached chat matches allowed types
            if allowed_types is not None:
                cached_type = cached.get("chat_type", "")
                type_mapping_reverse = {
                    'bot': 'private',
                    'user': 'private',
                    'group': 'group',
                    'supergroup': 'supergroup',
                    'channel': 'channel',
                }
                mapped_type = type_mapping_reverse.get(cached_type, cached_type)
                if mapped_type not in allowed_types and cached_type not in allowed_types:
                    return None
            return cached

        try:
            chat = await self._send_request({"@type": "getChat", "chat_id": chat_id})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fetch chat %s: %s", chat_id, exc)
            return None

        chat_type = chat.get("type", {}) if isinstance(chat, dict) else {}
        chat_type_name = chat_type.get("@type", "")

        # Default: only private bots if not specified (backward compatible)
        if allowed_types is None:
            allowed_types = ["private"]

        # Map friendly names to TDLib types
        type_mapping = {
            'private': 'chatTypePrivate',
            'group': 'chatTypeBasicGroup',
            'basicGroup': 'chatTypeBasicGroup',
            'supergroup': 'chatTypeSupergroup',
            'channel': 'chatTypeSupergroup',  # channels are supergroups with is_channel=true
        }

        allowed_tdlib_types = [type_mapping.get(t, t) for t in allowed_types]

        # Filter by type
        if chat_type_name not in allowed_tdlib_types:
            return None

        # Get type-specific info
        formatted = None

        if chat_type_name == "chatTypePrivate":
            user_id = chat_type.get("user_id")
            if not user_id:
                return None

            user = await self._ensure_user(user_id)
            if not user:
                return None

            is_bot = user.get("type", {}).get("@type") == "userTypeBot"

            # If only private bots allowed, filter out non-bots
            if allowed_types == ["private"] and not is_bot:
                return None

            formatted = {
                "chat_id": chat_id,
                "title": chat.get("title") or user.get("first_name") or ("Bot" if is_bot else "User"),
                "username": user.get("usernames", {}).get("editable_username") or user.get("username"),
                "chat_type": "bot" if is_bot else "user",
                "last_message": self._format_message(chat.get("last_message")),
            }

        elif chat_type_name == "chatTypeBasicGroup":
            group_id = chat_type.get("basic_group_id")
            if not group_id:
                return None

            try:
                group = await self._send_request({"@type": "getBasicGroup", "basic_group_id": group_id})
            except Exception as exc:
                logger.warning("Failed to fetch basic group %s: %s", group_id, exc)
                return None

            formatted = {
                "chat_id": chat_id,
                "title": chat.get("title") or "Group",
                "username": None,
                "chat_type": "group",
                "member_count": group.get("member_count"),
                "last_message": self._format_message(chat.get("last_message")),
            }

        elif chat_type_name == "chatTypeSupergroup":
            supergroup_id = chat_type.get("supergroup_id")
            if not supergroup_id:
                return None

            try:
                supergroup = await self._send_request({
                    "@type": "getSupergroup",
                    "supergroup_id": supergroup_id
                })
            except Exception as exc:
                logger.warning("Failed to fetch supergroup %s: %s", supergroup_id, exc)
                return None

            is_channel = supergroup.get("is_channel", False)

            formatted = {
                "chat_id": chat_id,
                "title": chat.get("title") or ("Channel" if is_channel else "Supergroup"),
                "username": supergroup.get("usernames", {}).get("editable_username") or supergroup.get("username"),
                "chat_type": "channel" if is_channel else "supergroup",
                "member_count": supergroup.get("member_count"),
                "last_message": self._format_message(chat.get("last_message")),
            }

        if formatted:
            self._chat_cache[chat_id] = formatted
            return formatted

        return None

    async def _ensure_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        user = await self._send_request({"@type": "getUser", "user_id": user_id})
        if user.get("@type") == "user":
            self._user_cache[user_id] = user
            return user
        return None

    def _format_message(self, message: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not message or not isinstance(message, dict):
            return None
        text = ""
        document_info = None
        content = message.get("content") or {}
        if content.get("@type") == "messageText":
            text = content.get("text", {}).get("text", "")
        elif content.get("@type") == "messageDocument":
            caption = content.get("caption", {}).get("text", "")
            document = content.get("document", {}) or {}
            file_name = document.get("file_name") or "document.pdf"
            mime_type = document.get("mime_type")
            file_obj = document.get("document", {}) or {}
            file_id = file_obj.get("id")
            remote_id = (file_obj.get("remote") or {}).get("id")
            local_path = (file_obj.get("local") or {}).get("path")
            document_info = {
                "file_id": file_id,
                "file_name": file_name,
                "mime_type": mime_type,
                "size": file_obj.get("expected_size") or file_obj.get("size"),
                "remote_id": remote_id,
                "local_path": local_path,
                "download_url": f"/api/tg/files/{file_id}" if file_id is not None else None,
            }
            text = caption or f"[PDF] {file_name}"
        return {
            "chat_id": message.get("chat_id"),
            "id": message.get("id"),
            "date": message.get("date"),
            "is_outgoing": message.get("is_outgoing", False),
            "sender_id": message.get("sender_id"),
            "text": text,
            "document": document_info,
        }

    def add_new_message_handler(self, handler: Callable[[Dict[str, Any]], Awaitable[None]]) -> None:
        """Register async handler invoked on every updateNewMessage."""
        if handler not in self._new_message_handlers:
            self._new_message_handlers.append(handler)

    async def hide_chat(self, chat_id: int, db: Session, title: Optional[str] = None) -> None:
        exists = db.get(HiddenBotChat, chat_id)
        if exists:
            return
        db.add(HiddenBotChat(chat_id=chat_id, title_snapshot=title))
        db.commit()

    async def unhide_chat(self, chat_id: int, db: Session) -> None:
        hidden = db.get(HiddenBotChat, chat_id)
        if hidden:
            db.delete(hidden)
            db.commit()

    async def get_messages(
        self,
        chat_id: int,
        limit: int = 50,
        from_message_id: int = 0,
        fetch_all: bool = False,
    ) -> Dict[str, Any]:
        limit = min(max(limit, 1), 200)
        if not fetch_all:
            payload = {
                "@type": "getChatHistory",
                "chat_id": chat_id,
                "from_message_id": from_message_id,
                "offset": 0,
                "limit": limit,
                "only_local": False,
            }
            response = await self._send_request(payload)
            messages = response.get("messages", [])
            formatted = [self._format_message(msg) for msg in messages if msg]
            return {"items": formatted, "total": response.get("total_count", len(formatted))}

        # fetch full history
        batch_size = 100
        collected: List[Dict[str, Any]] = []
        current_from = 0
        safety_batches = 400
        for _ in range(safety_batches):
            payload = {
                "@type": "getChatHistory",
                "chat_id": chat_id,
                "from_message_id": current_from,
                "offset": 0,
                "limit": batch_size,
                "only_local": False,
            }
            response = await self._send_request(payload)
            messages = response.get("messages", [])
            if not messages:
                break
            collected.extend(messages)
            oldest = messages[-1]
            oldest_id = oldest.get("id")
            if not oldest_id or len(messages) < batch_size:
                break
            current_from = oldest_id
        formatted = [self._format_message(msg) for msg in collected if msg]
        formatted.sort(key=lambda x: x.get("date") or 0)
        return {"items": formatted, "total": len(formatted)}

    async def send_message(self, chat_id: int, text: str) -> Dict[str, Any]:
        payload = {
            "@type": "sendMessage",
            "chat_id": chat_id,
            "input_message_content": {
                "@type": "inputMessageText",
                "text": {
                    "@type": "formattedText",
                    "text": text,
                    "entities": [],
                },
            },
        }
        response = await self._send_request(payload)
        return self._format_message(response) if isinstance(response, dict) else {"status": "sent"}

    async def send_document(self, chat_id: int, file_path: str, caption: str = "") -> Dict[str, Any]:
        payload = {
            "@type": "sendMessage",
            "chat_id": chat_id,
            "input_message_content": {
                "@type": "inputMessageDocument",
                "document": {"@type": "inputFileLocal", "path": file_path},
                "caption": {
                    "@type": "formattedText",
                    "text": caption or "",
                    "entities": [],
                },
            },
        }
        response = await self._send_request(payload, timeout=60)
        return self._format_message(response) if isinstance(response, dict) else {"status": "sent"}

    async def get_message(self, chat_id: int, message_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetch and format message by chat/message id.
        """
        response = await self._send_request(
            {
                "@type": "getMessage",
                "chat_id": chat_id,
                "message_id": message_id,
            },
            timeout=30,
        )
        if not isinstance(response, dict):
            return None
        if response.get("@type") == "error":
            return None
        return self._format_message(response)

    async def download_file(self, file_id: int, priority: int = 32, synchronous: bool = True) -> Optional[str]:
        file_response = await self._send_request(
            {
                "@type": "downloadFile",
                "file_id": file_id,
                "priority": priority,
                "offset": 0,
                "limit": 0,
                "synchronous": synchronous,
            },
            timeout=60,
        )
        if not isinstance(file_response, dict):
            return None
        local = file_response.get("local") or {}
        if local.get("is_downloading_completed"):
            return local.get("path")
        return None

    def stop(self) -> None:
        self._running = False
        if self._receive_thread and self._receive_thread.is_alive():
            self._receive_thread.join(timeout=1)
        if self._client:
            try:
                self._client.destroy()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to destroy TDLib client: %s", exc)
        self._client = None


_manager: Optional[TelegramTDLibManager] = None


def get_tdlib_manager() -> TelegramTDLibManager:
    global _manager
    if _manager is None:
        _manager = TelegramTDLibManager()
    return _manager
