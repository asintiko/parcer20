"""Keyless web search via DuckDuckGo HTML.

Returns short text snippets for a query. No API keys, best-effort: any network
or parse failure yields an empty list instead of raising, so batch callers can
keep going on the next item.
"""
from __future__ import annotations

import logging
from typing import List

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_DDG_HTML_URL = "https://html.duckduckgo.com/html/"
_USER_AGENT = "Mozilla/5.0"
_MIN_SNIPPET_LEN = 20


async def search_web(query: str, *, limit: int = 3, timeout: float = 10.0) -> List[str]:
    """Return up to ``limit`` text snippets for ``query`` (empty list on failure)."""
    query = (query or "").strip()
    if not query:
        return []
    try:
        async with httpx.AsyncClient(timeout=timeout) as client_http:
            response = await client_http.get(
                _DDG_HTML_URL,
                params={"q": query},
                headers={"User-Agent": _USER_AGENT},
            )
            if response.status_code != 200:
                return []
            soup = BeautifulSoup(response.text, "html.parser")
            snippets: List[str] = []
            for r in soup.find_all("a", class_="result__snippet", limit=max(1, limit)):
                text = r.get_text(strip=True)
                if text and len(text) > _MIN_SNIPPET_LEN:
                    snippets.append(text)
            return snippets[:limit]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Web search error for %r: %s", query, exc)
        return []


async def search_operator_snippets(operator_raw: str, *, limit: int = 3, timeout: float = 10.0) -> List[str]:
    """Snippets describing a payment operator / merchant in the Uzbekistan context."""
    query = f"{operator_raw} Узбекистан приложение оплата"
    return await search_web(query, limit=limit, timeout=timeout)


async def search_operator_text(operator_raw: str) -> str:
    """Backwards-compatible single-string helper for legacy callers."""
    snippets = await search_operator_snippets(operator_raw)
    if snippets:
        return "\n".join(snippets)
    return "Информация не найдена"
