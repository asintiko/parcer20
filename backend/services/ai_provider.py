from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI, OpenAI

from config.ai_models import (
    AI_REQUEST_TIMEOUT_SECONDS,
    AI_RETRY_COUNT,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_TEXT_MODEL,
)

logger = logging.getLogger(__name__)


JsonDict = Dict[str, Any]
MessageList = List[Dict[str, Any]]


class DeepSeekTextProvider:
    """Shared OpenAI-compatible text provider backed by DeepSeek."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        default_model: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        self.api_key = (api_key or DEEPSEEK_API_KEY).strip()
        self.base_url = (base_url or DEEPSEEK_BASE_URL).strip()
        self.default_model = (default_model or DEEPSEEK_TEXT_MODEL).strip() or "deepseek-chat"
        self.timeout_seconds = float(timeout_seconds or AI_REQUEST_TIMEOUT_SECONDS)
        self.enabled = bool(self.api_key)
        self._async_client: Optional[AsyncOpenAI] = None
        self._sync_client: Optional[OpenAI] = None

    def _get_async_client(self) -> AsyncOpenAI:
        if not self.enabled:
            raise RuntimeError("deepseek_not_configured")
        if self._async_client is None:
            self._async_client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout_seconds,
            )
        return self._async_client

    def _get_sync_client(self) -> OpenAI:
        if not self.enabled:
            raise RuntimeError("deepseek_not_configured")
        if self._sync_client is None:
            self._sync_client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout_seconds,
            )
        return self._sync_client

    def _record_usage(self, model: str, usage: Any, *, kind: str) -> None:
        """Capture token usage for cost tracking. Process-local counters; emit info log."""
        if usage is None:
            return
        try:
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        except Exception:  # noqa: BLE001
            return
        if prompt_tokens == 0 and completion_tokens == 0:
            return
        self.last_usage = {
            "model": model,
            "kind": kind,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
        # Cumulative counters (lazy init).
        self.cumulative_usage = getattr(self, "cumulative_usage", None) or {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "calls": 0,
        }
        self.cumulative_usage["prompt_tokens"] += prompt_tokens
        self.cumulative_usage["completion_tokens"] += completion_tokens
        self.cumulative_usage["calls"] += 1
        logger.info(
            "DeepSeek usage: model=%s kind=%s prompt=%d completion=%d total=%d (cumulative=%d)",
            model,
            kind,
            prompt_tokens,
            completion_tokens,
            prompt_tokens + completion_tokens,
            self.cumulative_usage["prompt_tokens"] + self.cumulative_usage["completion_tokens"],
        )

    @staticmethod
    def _extract_text_content(raw_content: Any) -> str:
        if raw_content is None:
            return ""
        if isinstance(raw_content, str):
            return raw_content.strip()
        if isinstance(raw_content, list):
            parts: List[str] = []
            for item in raw_content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
                elif isinstance(item, str):
                    parts.append(item)
            return "\n".join(part for part in parts if part).strip()
        return str(raw_content).strip()

    @staticmethod
    def _ensure_json_keyword(messages: MessageList) -> MessageList:
        """DeepSeek rejects response_format=json_object unless prompt mentions 'json'."""
        for msg in messages:
            content = msg.get("content")
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            if "json" in text.lower():
                return messages
        hint = {"role": "system", "content": "Respond strictly as a single JSON object."}
        return [hint, *messages]

    @staticmethod
    def _is_retryable_error(exc: BaseException) -> bool:
        """Decide whether DeepSeek error deserves a retry.

        Retry on:
            - 5xx
            - 429 rate limit
            - timeout / network errors
            - empty / malformed JSON responses
        Skip on terminal errors:
            - 400 invalid_request_error (e.g. bad schema)
            - 401 / 403 auth
            - 404
        """
        # OpenAI SDK exceptions expose status_code or .response.status_code
        status = getattr(exc, "status_code", None)
        if status is None:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
        if isinstance(status, int):
            if status in (400, 401, 403, 404):
                return False
            if status == 429 or status >= 500:
                return True
        # ValueError raised by _coerce_json_object → retry, model may stabilise
        if isinstance(exc, ValueError):
            return True
        # Treat anything else (network, timeout) as retryable
        return True

    @staticmethod
    def _retry_sleep(attempt: int) -> float:
        """Exponential backoff with jitter. attempt is 0-based."""
        base = 0.6 * (2 ** attempt)  # 0.6, 1.2, 2.4, ...
        cap = 8.0
        return min(cap, base) + random.uniform(0, 0.4)

    @staticmethod
    def _coerce_json_object(content: str) -> JsonDict:
        if not content:
            raise ValueError("empty_ai_response")
        try:
            payload = json.loads(content)
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass

        start = content.find("{")
        while start != -1:
            depth = 0
            for idx in range(start, len(content)):
                ch = content[idx]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = content[start:idx + 1]
                        payload = json.loads(candidate)
                        if isinstance(payload, dict):
                            return payload
                        break
            start = content.find("{", start + 1)
        raise ValueError("invalid_json_ai_response")

    async def complete_json(
        self,
        *,
        messages: MessageList,
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
    ) -> JsonDict:
        retry_count = max(0, int(AI_RETRY_COUNT))
        last_error: Optional[Exception] = None
        for attempt in range(retry_count + 1):
            try:
                response = await self._get_async_client().chat.completions.create(
                    model=model or self.default_model,
                    messages=self._ensure_json_keyword(messages),
                    response_format={"type": "json_object"},
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                self._record_usage(model or self.default_model, getattr(response, 'usage', None), kind='json')
                content = self._extract_text_content(response.choices[0].message.content)
                return self._coerce_json_object(content)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("DeepSeek JSON completion failed on attempt %s: %s", attempt + 1, exc)
                if not self._is_retryable_error(exc):
                    logger.warning("DeepSeek terminal error, no retry: %s", exc)
                    break
                if attempt < retry_count:
                    import asyncio as _asyncio
                    await _asyncio.sleep(self._retry_sleep(attempt))
        raise RuntimeError(str(last_error or "deepseek_request_failed"))

    async def complete_text(
        self,
        *,
        messages: MessageList,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> str:
        retry_count = max(0, int(AI_RETRY_COUNT))
        last_error: Optional[Exception] = None
        for attempt in range(retry_count + 1):
            try:
                response = await self._get_async_client().chat.completions.create(
                    model=model or self.default_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                self._record_usage(model or self.default_model, getattr(response, 'usage', None), kind='text')
                return self._extract_text_content(response.choices[0].message.content)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("DeepSeek text completion failed on attempt %s: %s", attempt + 1, exc)
        raise RuntimeError(str(last_error or "deepseek_request_failed"))

    async def complete_with_tools(
        self,
        *,
        messages: MessageList,
        tools: List[Dict[str, Any]],
        tool_choice: Any = "auto",
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: Optional[int] = 900,
    ) -> Any:
        """Native OpenAI-compatible tool-calling completion.

        Returns the raw `response.choices[0].message` so the caller can
        inspect both `content` and `tool_calls`. Raises RuntimeError when
        the provider is not configured (caller should fall back gracefully).
        """
        if not self.enabled:
            raise RuntimeError("deepseek_not_configured")
        retry_count = max(0, int(AI_RETRY_COUNT))
        last_error: Optional[Exception] = None
        for attempt in range(retry_count + 1):
            try:
                response = await self._get_async_client().chat.completions.create(
                    model=model or self.default_model,
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                self._record_usage(model or self.default_model, getattr(response, "usage", None), kind="tools")
                return response.choices[0].message
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "DeepSeek tool-call completion failed on attempt %s: %s",
                    attempt + 1,
                    exc,
                )
        raise RuntimeError(str(last_error or "deepseek_request_failed"))

    def complete_json_sync(
        self,
        *,
        messages: MessageList,
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        retry_count: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
    ) -> JsonDict:
        effective_retry_count = max(
            0,
            int(AI_RETRY_COUNT if retry_count is None else retry_count),
        )
        last_error: Optional[Exception] = None
        for attempt in range(effective_retry_count + 1):
            try:
                response = self._get_sync_client().chat.completions.create(
                    model=model or self.default_model,
                    messages=self._ensure_json_keyword(messages),
                    response_format={"type": "json_object"},
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout_seconds,
                )
                self._record_usage(model or self.default_model, getattr(response, 'usage', None), kind='json')
                content = self._extract_text_content(response.choices[0].message.content)
                return self._coerce_json_object(content)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("DeepSeek sync JSON completion failed on attempt %s: %s", attempt + 1, exc)
                if not self._is_retryable_error(exc):
                    logger.warning("DeepSeek terminal error (sync), no retry: %s", exc)
                    break
                if attempt < effective_retry_count:
                    time.sleep(self._retry_sleep(attempt))
        raise RuntimeError(str(last_error or "deepseek_request_failed"))


_default_provider: Optional[DeepSeekTextProvider] = None


def get_text_ai_provider() -> DeepSeekTextProvider:
    global _default_provider
    if _default_provider is None:
        _default_provider = DeepSeekTextProvider()
    return _default_provider
