"""Centralised AI model configuration.

Every parameter falls back to its previous hard-coded default so that
existing deployments keep working without any env changes.
"""

from __future__ import annotations

import os

DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip() or "https://api.deepseek.com"
DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_TEXT_MODEL: str = os.getenv("DEEPSEEK_TEXT_MODEL", "deepseek-chat").strip() or "deepseek-chat"
AI_REQUEST_TIMEOUT_SECONDS: float = float(os.getenv("AI_REQUEST_TIMEOUT_SECONDS", "45"))
AI_MAX_TOOL_CALLS_PER_REQUEST: int = int(os.getenv("AI_MAX_TOOL_CALLS_PER_REQUEST", "6"))
AI_MAX_TOOL_ROUNDS: int = int(os.getenv("AI_MAX_TOOL_ROUNDS", "3"))
AI_RETRY_COUNT: int = int(os.getenv("AI_RETRY_COUNT", "2"))
AI_AGENT_RECEIPT_GRACE_MINUTES: int = int(os.getenv("AI_AGENT_RECEIPT_GRACE_MINUTES", "5"))


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


# ── AI Agent feature flags ───────────────────────────────────────────────────
AI_AGENT_NATIVE_TOOLS: bool = _bool_env("AI_AGENT_NATIVE_TOOLS", True)
AI_AGENT_MUTATION_TOOLS_ENABLED: bool = _bool_env("AI_AGENT_MUTATION_TOOLS_ENABLED", True)
AI_AGENT_AUTOMATION_REQUIRES_CONFIRM: bool = _bool_env("AI_AGENT_AUTOMATION_REQUIRES_CONFIRM", True)

# ── Mapping Agent (analyze_with_ai) ──────────────────────────────────────────
MAPPING_AI_MODEL: str = os.getenv("AUTOMATION_MAPPING_AI_MODEL", DEEPSEEK_TEXT_MODEL)
MAPPING_AI_TEMPERATURE: float = float(os.getenv("AUTOMATION_MAPPING_AI_TEMPERATURE", "0.3"))
MAPPING_AI_MAX_TOKENS: int = int(os.getenv("AUTOMATION_MAPPING_AI_MAX_TOKENS", "200"))

# ── Verification Agent (verify_transaction_with_ai) ──────────────────────────
VERIFY_AI_MODEL: str = os.getenv("AUTOMATION_VERIFY_AI_MODEL", DEEPSEEK_TEXT_MODEL)
VERIFY_AI_TEMPERATURE: float = float(os.getenv("AUTOMATION_VERIFY_AI_TEMPERATURE", "0.1"))
VERIFY_AI_MAX_TOKENS: int = int(os.getenv("AUTOMATION_VERIFY_AI_MAX_TOKENS", "500"))
