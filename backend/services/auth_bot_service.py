"""Auth bot + OTP helpers."""
from __future__ import annotations

import json
import os
import secrets
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import redis
import redis.asyncio as aioredis
from jose import JWTError, jwt


REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

AUTH_CODE_TTL_SECONDS = int(os.getenv("AUTH_CODE_TTL_SECONDS", "120"))
AUTH_CODE_LENGTH = int(os.getenv("AUTH_CODE_LENGTH", "6"))
AUTH_MAX_ATTEMPTS = int(os.getenv("AUTH_MAX_ATTEMPTS", "3"))
AUTH_RATE_LIMIT_PER_MIN = int(os.getenv("AUTH_RATE_LIMIT_PER_MIN", "10"))
AUTH_RATE_LIMIT_BLOCK_MINUTES = int(os.getenv("AUTH_RATE_LIMIT_BLOCK_MINUTES", "5"))

JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
LAUNCH_SESSION_TTL_HOURS = int(os.getenv("LAUNCH_SESSION_TTL_HOURS", "24"))
CHAT_SESSION_TTL_HOURS = int(os.getenv("CHAT_SESSION_TTL_HOURS", "1"))
AUTH_EVENT_CHANNEL = os.getenv("AUTH_EVENT_CHANNEL", "auth:events")
AUTH_SESSION_INDEX_KEY = os.getenv("AUTH_SESSION_INDEX_KEY", "auth:sessions:index")
AUTH_SESSION_KEY_PREFIX = os.getenv("AUTH_SESSION_KEY_PREFIX", "auth:sessions:")
AUTH_REVOKED_PREFIX = os.getenv("AUTH_REVOKED_PREFIX", "auth:sessions:revoked:")
AUTH_OTP_SCAN_LIMIT = int(os.getenv("AUTH_OTP_SCAN_LIMIT", "200"))
AUTH_ACTIVITY_TTL_SECONDS = int(os.getenv("AUTH_ACTIVITY_TTL_SECONDS", "172800"))

_sync_redis_client: Optional[redis.Redis] = None
_async_redis_client: Optional[aioredis.Redis] = None

if not JWT_SECRET:
    raise EnvironmentError("JWT_SECRET environment variable is required")


@dataclass
class OTPRecord:
    code: str
    purpose: str
    subject: str
    context: Dict[str, Any]
    attempts: int
    created_at: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "code": self.code,
                "purpose": self.purpose,
                "subject": self.subject,
                "context": self.context,
                "attempts": self.attempts,
                "created_at": self.created_at,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "OTPRecord":
        payload = json.loads(raw)
        return cls(
            code=str(payload.get("code") or ""),
            purpose=str(payload.get("purpose") or ""),
            subject=str(payload.get("subject") or ""),
            context=payload.get("context") or {},
            attempts=int(payload.get("attempts") or 0),
            created_at=str(payload.get("created_at") or datetime.utcnow().isoformat()),
        )


async def get_redis():
    global _async_redis_client
    if _async_redis_client is None:
        _async_redis_client = aioredis.from_url(
            REDIS_URL,
            decode_responses=True,
            max_connections=20,
        )
    return _async_redis_client


async def close_redis_pool() -> None:
    global _async_redis_client, _sync_redis_client
    if _async_redis_client is not None:
        with suppress(Exception):
            await _async_redis_client.aclose()
    _async_redis_client = None
    if _sync_redis_client is not None:
        with suppress(Exception):
            _sync_redis_client.close()
    _sync_redis_client = None


def _otp_key(purpose: str, subject: str) -> str:
    return f"otp:req:{purpose}:{subject}"


def _rate_key(ip_or_actor: str) -> str:
    return f"otp:rate:{ip_or_actor}"


def _block_key(ip_or_actor: str) -> str:
    return f"otp:block:{ip_or_actor}"


def _generate_numeric_code(length: int) -> str:
    return "".join(str(secrets.randbelow(10)) for _ in range(max(4, length)))


def _new_session_id() -> str:
    return secrets.token_hex(16)


def _session_key(session_id: str) -> str:
    return f"{AUTH_SESSION_KEY_PREFIX}{session_id}"


def _revoked_key(session_id: str) -> str:
    return f"{AUTH_REVOKED_PREFIX}{session_id}"


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _get_sync_redis() -> redis.Redis:
    global _sync_redis_client
    if _sync_redis_client is None:
        _sync_redis_client = redis.Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
        )
    return _sync_redis_client


def _payload_ttl_seconds(payload: Dict[str, Any], fallback_seconds: int = 3600) -> int:
    now_ts = int(datetime.utcnow().timestamp())
    exp_ts = _to_int(payload.get("exp"))
    if exp_ts and exp_ts > now_ts:
        return max(60, exp_ts - now_ts)
    return max(60, fallback_seconds)


def _is_session_revoked(session_id: Optional[str]) -> bool:
    if not session_id:
        return False
    try:
        redis_client = _get_sync_redis()
        return bool(redis_client.exists(_revoked_key(session_id)))
    except Exception:
        # Fail open to avoid taking API down when Redis has transient issues.
        return False


def is_session_revoked(session_id: Optional[str]) -> bool:
    return _is_session_revoked(session_id)


async def publish_auth_event(event: str, payload: Optional[Dict[str, Any]] = None) -> int:
    redis_client = await get_redis()
    message = json.dumps(
        {
            "event": str(event or "").strip(),
            "payload": payload or {},
            "ts": datetime.utcnow().isoformat(),
        },
        ensure_ascii=False,
    )
    try:
        return int(await redis_client.publish(AUTH_EVENT_CHANNEL, message))
    except Exception:
        return 0


async def register_active_session(
    *,
    token_payload: Dict[str, Any],
    token_kind: str,
    user_id: Optional[int] = None,
    ip_address: Optional[str] = None,
    subject: Optional[str] = None,
) -> Optional[str]:
    session_id = str(token_payload.get("sid") or "").strip()
    if not session_id:
        return None

    now = datetime.utcnow()
    ttl_seconds = _payload_ttl_seconds(token_payload)
    expires_at = now + timedelta(seconds=ttl_seconds)

    try:
        redis_client = await get_redis()
        now_iso = now.isoformat()
        await redis_client.hset(
            _session_key(session_id),
            mapping={
                "session_id": session_id,
                "token_kind": token_kind,
                "subject": subject or "",
                "user_id": str(user_id) if user_id is not None else "",
                "ip_address": ip_address or "",
                "created_at": now_iso,
                "last_activity_at": now_iso,
                "expires_at": expires_at.isoformat(),
                "exp_ts": str(int(expires_at.timestamp())),
            },
        )
        await redis_client.expire(_session_key(session_id), ttl_seconds)
        await redis_client.zadd(AUTH_SESSION_INDEX_KEY, {session_id: int(expires_at.timestamp())})
        return session_id
    except Exception:
        return None


async def list_active_sessions(limit: int = 100) -> List[Dict[str, Any]]:
    redis_client = await get_redis()
    now_ts = int(datetime.utcnow().timestamp())
    await redis_client.zremrangebyscore(AUTH_SESSION_INDEX_KEY, "-inf", now_ts)

    ids = await redis_client.zrevrange(AUTH_SESSION_INDEX_KEY, 0, max(0, int(limit) - 1))
    if not ids:
        return []

    rows: List[Dict[str, Any]] = []
    stale_ids: List[str] = []
    for session_id in ids:
        data = await redis_client.hgetall(_session_key(session_id))
        if not data:
            stale_ids.append(session_id)
            continue
        if _is_session_revoked(session_id):
            continue
        rows.append(
            {
                "session_id": data.get("session_id") or session_id,
                "token_kind": data.get("token_kind") or "",
                "subject": data.get("subject") or "",
                "user_id": _to_int(data.get("user_id")),
                "ip_address": data.get("ip_address") or None,
                "created_at": data.get("created_at"),
                "last_activity_at": data.get("last_activity_at"),
                "expires_at": data.get("expires_at"),
            }
        )
    if stale_ids:
        await redis_client.zrem(AUTH_SESSION_INDEX_KEY, *stale_ids)
    return rows


async def touch_active_session(session_id: Optional[str], *, last_activity: Optional[datetime] = None) -> bool:
    sid = str(session_id or "").strip()
    if not sid:
        return False

    now = last_activity or datetime.utcnow()
    key = _session_key(sid)
    try:
        redis_client = await get_redis()
        exists = await redis_client.exists(key)
        if not exists:
            return False
        await redis_client.hset(key, mapping={"last_activity_at": now.isoformat()})
        current_ttl = await redis_client.ttl(key)
        min_ttl = max(300, AUTH_ACTIVITY_TTL_SECONDS)
        if current_ttl is None or int(current_ttl) < min_ttl:
            await redis_client.expire(key, min_ttl)
        return True
    except Exception:
        return False


async def revoke_active_session(
    session_id: str,
    *,
    suppress_event: bool = False,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    sid = str(session_id or "").strip()
    if not sid:
        return False, None

    redis_client = await get_redis()
    session_key = _session_key(sid)
    data = await redis_client.hgetall(session_key)
    if not data:
        return False, None

    exp_ts = _to_int(data.get("exp_ts")) or int((datetime.utcnow() + timedelta(hours=1)).timestamp())
    now_ts = int(datetime.utcnow().timestamp())
    ttl_seconds = max(60, exp_ts - now_ts)
    await redis_client.setex(_revoked_key(sid), ttl_seconds, "1")
    await redis_client.delete(session_key)
    await redis_client.zrem(AUTH_SESSION_INDEX_KEY, sid)
    if not suppress_event:
        with suppress(Exception):
            await publish_auth_event(
                "session_revoked",
                {
                    "session_id": sid,
                    "token_kind": data.get("token_kind"),
                    "ip": data.get("ip_address"),
                    "subject": data.get("subject"),
                },
            )
    return True, data


async def list_pending_otp_requests(limit: int = AUTH_OTP_SCAN_LIMIT) -> List[Dict[str, Any]]:
    redis_client = await get_redis()
    rows: List[Dict[str, Any]] = []
    count = 0

    async for key in redis_client.scan_iter(match="otp:req:*"):
        if count >= max(1, int(limit)):
            break
        raw = await redis_client.get(key)
        if not raw:
            continue
        ttl = await redis_client.ttl(key)
        try:
            record = OTPRecord.from_json(raw)
        except Exception:
            continue
        rows.append(
            {
                "purpose": record.purpose,
                "subject": record.subject,
                "context": record.context,
                "attempts": int(record.attempts or 0),
                "expires_in": int(ttl or 0),
                "created_at": record.created_at,
            }
        )
        count += 1
    return rows


async def clear_pending_otp_requests(
    *,
    clear_rate_limits: bool = True,
    scan_limit: int = 5000,
) -> Dict[str, int]:
    """
    Delete pending OTP keys and (optionally) related rate-limit keys.
    Useful for emergency recovery when clients are stuck in stale OTP flow.
    """
    redis_client = await get_redis()
    limit = max(1, int(scan_limit))

    deleted_requests = 0
    scanned_requests = 0
    async for key in redis_client.scan_iter(match="otp:req:*"):
        if scanned_requests >= limit:
            break
        scanned_requests += 1
        deleted_requests += int(await redis_client.delete(key) or 0)

    deleted_rate = 0
    deleted_blocks = 0
    if clear_rate_limits:
        scanned_rate = 0
        async for key in redis_client.scan_iter(match="otp:rate:*"):
            if scanned_rate >= limit:
                break
            scanned_rate += 1
            deleted_rate += int(await redis_client.delete(key) or 0)

        scanned_blocks = 0
        async for key in redis_client.scan_iter(match="otp:block:*"):
            if scanned_blocks >= limit:
                break
            scanned_blocks += 1
            deleted_blocks += int(await redis_client.delete(key) or 0)

    return {
        "deleted_requests": int(deleted_requests),
        "deleted_rate": int(deleted_rate),
        "deleted_blocks": int(deleted_blocks),
    }


class OTPManager:
    """Temporary OTP storage in Redis with strict TTL."""

    def __init__(self, redis_client=None):
        self.redis = redis_client

    async def _client(self):
        if self.redis is not None:
            return self.redis
        return await get_redis()

    async def check_rate_limit(self, actor_key: str) -> Tuple[bool, Optional[int]]:
        redis = await self._client()
        block_key = _block_key(actor_key)
        ttl = await redis.ttl(block_key)
        if ttl and ttl > 0:
            return False, ttl

        rate_key = _rate_key(actor_key)
        current = await redis.incr(rate_key)
        if current == 1:
            await redis.expire(rate_key, 60)
        if current > AUTH_RATE_LIMIT_PER_MIN:
            block_seconds = max(60, AUTH_RATE_LIMIT_BLOCK_MINUTES * 60)
            await redis.setex(block_key, block_seconds, "1")
            return False, block_seconds
        return True, None

    async def generate_code(self, purpose: str, subject: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        code = _generate_numeric_code(AUTH_CODE_LENGTH)
        record = OTPRecord(
            code=code,
            purpose=purpose,
            subject=subject,
            context=context or {},
            attempts=0,
            created_at=datetime.utcnow().isoformat(),
        )
        redis = await self._client()
        await redis.setex(_otp_key(purpose, subject), AUTH_CODE_TTL_SECONDS, record.to_json())
        return {
            "code": code,
            "expires_in": AUTH_CODE_TTL_SECONDS,
            "code_length": AUTH_CODE_LENGTH,
        }

    async def verify_code(self, purpose: str, subject: str, input_code: str) -> Tuple[bool, Dict[str, Any]]:
        redis = await self._client()
        key = _otp_key(purpose, subject)
        raw = await redis.get(key)
        if not raw:
            return False, {"error": "code_expired"}

        record = OTPRecord.from_json(raw)
        record.attempts += 1

        if secrets.compare_digest(record.code, input_code.strip()):
            await redis.delete(key)
            return True, {"context": record.context}

        if record.attempts >= AUTH_MAX_ATTEMPTS:
            await redis.delete(key)
            return False, {"error": "max_attempts"}

        remaining_ttl = await redis.ttl(key)
        if remaining_ttl and int(remaining_ttl) > 0:
            await redis.setex(key, int(remaining_ttl), record.to_json())
        else:
            await redis.delete(key)
            return False, {"error": "code_expired"}
        return False, {"error": "invalid_code", "attempts_left": AUTH_MAX_ATTEMPTS - record.attempts}


def create_launch_session_token(*, ip_address: str) -> str:
    now = datetime.utcnow()
    exp = now + timedelta(hours=max(1, LAUNCH_SESSION_TTL_HOURS))
    payload = {
        "kind": "launch_session",
        "sid": _new_session_id(),
        "ip": ip_address,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_launch_session_token(token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    if payload.get("kind") != "launch_session":
        return None
    if _is_session_revoked(str(payload.get("sid") or "")):
        return None
    return payload


def create_chat_access_token(*, chat_id: int, user_id: Optional[int] = None) -> str:
    now = datetime.utcnow()
    exp = now + timedelta(hours=max(1, CHAT_SESSION_TTL_HOURS))
    payload = {
        "kind": "chat_access",
        "sid": _new_session_id(),
        "chat_id": int(chat_id),
        "user_id": user_id,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_chat_access_token(token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    if payload.get("kind") != "chat_access":
        return None
    if _is_session_revoked(str(payload.get("sid") or "")):
        return None
    return payload
