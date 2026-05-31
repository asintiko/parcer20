from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from config.ai_models import (
    AI_AGENT_NATIVE_TOOLS,
    AI_MAX_TOOL_CALLS_PER_REQUEST,
    AI_MAX_TOOL_ROUNDS,
    DEEPSEEK_TEXT_MODEL,
)
from services.ai_agent.session_service import create_message, create_run_event, update_run
from services.ai_agent.tool_registry import TOOL_DESCRIPTIONS, execute_tool
from services.ai_agent.tool_schemas import ARGS_MODELS, TOOL_SCHEMAS
from services.ai_provider import get_text_ai_provider

logger = logging.getLogger(__name__)


def _inject_allowed_chat_ids(
    scope: Optional[Dict[str, Any]],
    current_user: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Populate scope['allowed_chat_ids'] from the operator's RBAC allowed_sources.

    Agent read-tools restrict data via scope['allowed_chat_ids'], but the HTTP
    scope dependency never sets it — so without this every tool ignores per-source
    RBAC. Admins (role==admin) get no restriction. Operators get their
    allowed_sources; an empty list stays empty (tools treat falsy as "no filter",
    which is acceptable only because operators also lack the relevant tabs — the
    transactions API is the hard boundary).
    """
    if not isinstance(current_user, dict):
        return scope
    if str(current_user.get("role") or "").lower() == "admin":
        return scope
    raw = current_user.get("allowed_sources")
    if not isinstance(raw, list):
        return scope
    chat_ids: List[int] = []
    for item in raw:
        try:
            chat_ids.append(int(item))
        except (TypeError, ValueError):
            continue
    if not chat_ids:
        return scope
    enriched = dict(scope) if isinstance(scope, dict) else {}
    enriched["allowed_chat_ids"] = sorted(set(chat_ids))
    return enriched


SYSTEM_PROMPT_NATIVE = (
    "Ты встроенный ИИ-агент Parcer 2.0. Ты помогаешь пользователю работать с таблицей "
    "транзакций: находить и подсвечивать строки, применять фильтры, считать аналитику и "
    "отчеты, создавать и редактировать транзакции через preview+confirm.\n\n"
    "Правила выбора инструментов:\n"
    "- Для вопросов про сумму, итог, оборот, расход, поступление за период — "
    "`period_summary` (быстро) или `transaction_analytics` (если нужны подробные группировки).\n"
    "- Сравнить два периода — `compare_periods`.\n"
    "- Топ операторов / приложений за период — `top_operators` или `group_by_dimension`.\n"
    "- Если просят отчет/сводку/weekly — `report_builder` или `weekly_health_check`.\n"
    "- Если просят 'покажи/отфильтруй транзакции X' и нужно курсором показать действие — "
    "`apply_filters_with_cursor` (закроет чат после анимации). Если только данные нужны — "
    "`apply_table_filters`.\n"
    "- 'Отметь / выдели / поставь флаг на ...' — `mark_transaction_rows`.\n"
    "- 'Экспорт ...' — `export_transactions`.\n"
    "- 'Сбрось фильтры' — `clear_filters_with_cursor`.\n"
    "- 'Перемотай / открой / покажи #N' — `scroll_to_transaction` / `open_transaction_details`.\n"
    "- Если просят 'проверь чат X / найди ошибки в чате X' — `chat_vs_db_reconcile`.\n"
    "- 'Найди дубликаты' — `find_duplicate_transactions`.\n"
    "- 'Найди без маппинга / без оператора' — `find_orphan_transactions`.\n"
    "- 'Проверь здоровье / health-check / weekly' — `weekly_health_check`.\n"
    "- 'Исправь всё / fix all' — `weekly_report_autofix` (отдаст preview для confirm).\n"
    "- Если просят найти конкретную транзакцию по id или поиску — `table_search_and_navigate`.\n"
    "- Создание/редактирование транзакций — `create_transaction`/`update_transaction`/"
    "`bulk_update_transactions`. Эти инструменты возвращают preview, реальное изменение "
    "произойдет после подтверждения пользователем.\n"
    "- Если ответ — просто текст без действия, используй `show_chat_only_message`.\n"
    "- Любые datetime передавай в ISO 8601. Валюты используй коды UZS/USD/EUR/RUB.\n"
    f"- За один запрос можно вызвать максимум {AI_MAX_TOOL_CALLS_PER_REQUEST} инструментов "
    f"в сумме за {AI_MAX_TOOL_ROUNDS} раундов. Не вызывай инструменты впустую — если "
    "данных достаточно, отвечай текстом.\n"
    "- Если пользователь спрашивает про данные, на которые у инструментов нет фильтра — "
    "объясни ограничение текстом, не подменяй параметрами.\n"
)


class _ToolCallSpec(BaseModel):
    name: str
    arguments: Dict[str, Any] = {}
    tool_call_id: Optional[str] = None


class AgentOrchestrator:
    def __init__(self) -> None:
        self.provider = get_text_ai_provider()

    @staticmethod
    def _tool_progress_label(tool_name: str, progress: Dict[str, Any]) -> str:
        step = str(progress.get("step") or "").strip().lower()
        if tool_name == "transaction_analytics":
            return "Считаю итог за период"
        if tool_name == "report_builder":
            return "Собираю отчет"
        if tool_name == "apply_table_filters":
            return "Применяю фильтры"
        if tool_name == "table_search_and_navigate":
            return "Ищу транзакцию"
        if tool_name in {"create_transaction", "update_transaction", "bulk_update_transactions"}:
            return "Готовлю preview"
        if tool_name == "monitored_chat_sync_audit":
            return "Сверяю чеки"
        if tool_name in {"failed_receipt_investigator", "message_to_transaction_trace"}:
            return "Ищу ошибки"
        if tool_name in {"duplicate_merge_preview", "receipt_reparse_preview"}:
            return "Готовлю действия"
        if step == "planning":
            return "Понимаю запрос"
        return "Проверяю данные"

    @staticmethod
    def _progress_percent(progress: Dict[str, Any], default_percent: int) -> int:
        try:
            value = progress.get("percent")
            if value is None:
                return default_percent
            return max(0, min(100, int(value)))
        except Exception:
            return default_percent

    @staticmethod
    def _run_event_status(progress: Dict[str, Any]) -> str:
        if progress.get("failed"):
            return "failed"
        if progress.get("completed"):
            return "completed"
        return "running"

    @staticmethod
    def _tool_result_for_llm(tool_name: str, result: Dict[str, Any]) -> str:
        """Compact JSON-friendly summary fed back to the LLM as `tool` message."""
        compact: Dict[str, Any] = {
            "summary": result.get("summary"),
            "requires_confirmation": bool(result.get("confirmation_payload")),
        }
        if isinstance(result.get("ui_action"), dict):
            compact["ui_action_kind"] = result["ui_action"].get("kind")
        if isinstance(result.get("navigation_targets"), list) and result.get("navigation_targets"):
            compact["navigation_count"] = len(result["navigation_targets"])
        cards = result.get("cards")
        if isinstance(cards, list) and cards:
            compact["cards"] = [
                {
                    "type": c.get("type"),
                    "title": c.get("title"),
                }
                for c in cards[:3]
                if isinstance(c, dict)
            ]
        if isinstance(result.get("assistant_message"), str):
            compact["assistant_message"] = result["assistant_message"][:600]
        if isinstance(result.get("data"), dict):
            compact["data"] = result["data"]
        try:
            return json.dumps(compact, ensure_ascii=False, default=str)[:4000]
        except Exception:
            return json.dumps({"summary": str(result.get("summary") or "")}, ensure_ascii=False)

    @staticmethod
    def _build_history_messages(
        db: Session,
        thread_id: UUID,
        max_messages: int = 12,
        max_chars: int = 4000,
    ) -> List[Dict[str, Any]]:
        """Replay recent messages of the thread into the LLM context.

        Pulls last N user/assistant messages, oldest-first, capped by total chars.
        Tool messages are skipped (they belong to within-run loops only).
        """
        try:
            from database.models import AgentMessage
        except Exception:  # noqa: BLE001
            return []
        try:
            rows = (
                db.query(AgentMessage)
                .filter(
                    AgentMessage.thread_id == thread_id,
                    AgentMessage.role.in_(["user", "assistant"]),
                )
                .order_by(AgentMessage.created_at.desc())
                .limit(max(1, max_messages))
                .all()
            )
        except Exception:  # noqa: BLE001
            return []
        rows = list(reversed(rows))
        out: List[Dict[str, Any]] = []
        used = 0
        for row in rows:
            content = ""
            raw = getattr(row, "content_json", None) or getattr(row, "content", None)
            if isinstance(raw, str):
                try:
                    obj = json.loads(raw)
                except Exception:  # noqa: BLE001
                    obj = {"message": raw}
            elif isinstance(raw, dict):
                obj = raw
            else:
                obj = {}
            if obj.get("message"):
                content = str(obj["message"])
            elif obj.get("text"):
                content = str(obj["text"])
            else:
                continue
            if not content.strip():
                continue
            content = content[:1200]
            if used + len(content) > max_chars:
                break
            used += len(content)
            out.append({"role": row.role, "content": content})
        return out

    @staticmethod
    def _validate_arguments(
        tool_name: str, raw_arguments: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        model = ARGS_MODELS.get(tool_name)
        if model is None:
            return None, f"unknown_tool: {tool_name}"
        try:
            parsed = model.model_validate(raw_arguments or {})
            return parsed.model_dump(mode="python", exclude_none=False), None
        except ValidationError as exc:
            return None, exc.json()

    @staticmethod
    def _parse_tool_call_arguments(raw: Any) -> Dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}

    def _extract_tool_calls(self, message: Any) -> List[_ToolCallSpec]:
        tool_calls = getattr(message, "tool_calls", None) or []
        specs: List[_ToolCallSpec] = []
        for call in tool_calls:
            try:
                fn = getattr(call, "function", None)
                name = getattr(fn, "name", None) if fn is not None else None
                if not name:
                    continue
                raw_args = getattr(fn, "arguments", None)
                arguments = self._parse_tool_call_arguments(raw_args)
                tool_call_id = getattr(call, "id", None) or None
                specs.append(
                    _ToolCallSpec(name=name, arguments=arguments, tool_call_id=tool_call_id)
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to parse tool call: %s", exc)
        return specs

    @staticmethod
    def _serialize_assistant_tool_calls(specs: List[_ToolCallSpec]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for idx, spec in enumerate(specs):
            out.append(
                {
                    "id": spec.tool_call_id or f"call_{idx}",
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "arguments": json.dumps(spec.arguments, ensure_ascii=False),
                    },
                }
            )
        return out

    async def _run_native_loop(
        self,
        *,
        db: Session,
        thread_id: Optional[UUID],
        run_id: Optional[UUID],
        current_user: Dict[str, Any],
        scope: Optional[dict],
        user_text: str,
    ) -> Dict[str, Any]:
        """Native DeepSeek tool-calling loop.

        Returns a dict with keys: message, cards, navigation_targets,
        confirmation_payload, background_job, tool_results.

        When `thread_id`/`run_id` are None the loop runs headless: no thread
        history is replayed and no AgentRun/AgentRunEvent telemetry is persisted
        (used by `run_task` for scheduled routines).
        """
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT_NATIVE},
        ]
        if thread_id is not None:
            history = self._build_history_messages(db, thread_id)
            if history:
                messages.extend(history)
        messages.append({"role": "user", "content": user_text})

        cards: List[Dict[str, Any]] = []
        navigation_targets: List[Dict[str, Any]] = []
        tool_results: List[Dict[str, Any]] = []
        confirmation_payload: Optional[Dict[str, Any]] = None
        background_job: Optional[Dict[str, Any]] = None
        ui_action: Optional[Dict[str, Any]] = None

        total_tool_calls = 0
        max_calls = max(1, int(AI_MAX_TOOL_CALLS_PER_REQUEST))
        max_rounds = max(1, int(AI_MAX_TOOL_ROUNDS))
        final_text: str = ""

        for round_idx in range(max_rounds):
            try:
                message = await self.provider.complete_with_tools(
                    messages=messages,
                    tools=TOOL_SCHEMAS,
                    tool_choice="auto",
                    model=DEEPSEEK_TEXT_MODEL,
                    temperature=0.1,
                    max_tokens=900,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Native tool-call round %s failed", round_idx + 1)
                raise

            specs = self._extract_tool_calls(message)
            content_text = self.provider._extract_text_content(getattr(message, "content", None))

            if not specs:
                final_text = content_text or final_text
                break

            specs = specs[: max(0, max_calls - total_tool_calls)]
            if not specs:
                final_text = content_text or final_text
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": content_text or "",
                    "tool_calls": self._serialize_assistant_tool_calls(specs),
                }
            )

            for spec_index, spec in enumerate(specs, start=1):
                total_tool_calls += 1
                tool_name = spec.name
                arguments = spec.arguments

                validated, validation_error = self._validate_arguments(tool_name, arguments)
                if validation_error is not None:
                    if run_id is not None:
                        create_run_event(
                            db,
                            run_id=run_id,
                            event_type="failed",
                            label=f"Невалидные аргументы для {tool_name}",
                            status="failed",
                            payload={"tool_name": tool_name, "error": validation_error[:1000]},
                        )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": spec.tool_call_id or f"call_{spec_index}",
                            "name": tool_name,
                            "content": json.dumps(
                                {
                                    "error": "invalid_arguments",
                                    "detail": validation_error[:1000],
                                },
                                ensure_ascii=False,
                            ),
                        }
                    )
                    continue

                exec_args = {
                    **(validated or {}),
                    "_execution_context": {
                        "thread_id": str(thread_id) if thread_id is not None else None,
                        "run_id": str(run_id) if run_id is not None else None,
                        "user_id": int(
                            current_user.get("id") or current_user.get("user_id") or 0
                        ),
                    },
                }

                if run_id is not None:
                    create_run_event(
                        db,
                        run_id=run_id,
                        event_type="tool_selected",
                        label=f"Выбран инструмент: {tool_name}",
                        status="completed",
                        payload={"tool_name": tool_name, "arguments": validated},
                    )
                    update_run(
                        db,
                        run_id=run_id,
                        status="processing",
                        progress={
                            "step": "tool_execution",
                            "percent": min(95, 10 + total_tool_calls * 20),
                            "tool_name": tool_name,
                        },
                    )
                    create_run_event(
                        db,
                        run_id=run_id,
                        event_type="tool_started",
                        label=self._tool_progress_label(tool_name, {"step": "tool_execution"}),
                        status="running",
                        payload={"tool_name": tool_name},
                    )

                base_percent = min(95, 10 + total_tool_calls * 20)

                def progress_callback(
                    progress: Dict[str, Any], _name: str = tool_name, _base: int = base_percent
                ) -> None:
                    if run_id is None:
                        return
                    percent = self._progress_percent(progress, _base)
                    update_run(
                        db,
                        run_id=run_id,
                        status="processing",
                        progress={
                            "step": progress.get("step") or "tool_execution",
                            "percent": percent,
                            "tool_name": _name,
                        },
                    )
                    create_run_event(
                        db,
                        run_id=run_id,
                        event_type="tool_progress",
                        label=self._tool_progress_label(_name, progress),
                        status=self._run_event_status(progress),
                        payload={"tool_name": _name, **progress},
                    )

                try:
                    result = await execute_tool(
                        tool_name,
                        db=db,
                        current_user=current_user,
                        scope=scope,
                        arguments=exec_args,
                        progress_callback=progress_callback,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Tool %s raised", tool_name)
                    result = {
                        "summary": f"Инструмент {tool_name} упал: {exc}",
                        "cards": [
                            {
                                "type": "warning",
                                "title": f"Ошибка инструмента {tool_name}",
                                "body": str(exc),
                            }
                        ],
                    }

                tool_results.append({"name": tool_name, "result": result})
                if isinstance(result.get("cards"), list):
                    cards.extend(result["cards"])
                if isinstance(result.get("navigation_targets"), list):
                    navigation_targets.extend(result["navigation_targets"])
                if not confirmation_payload and isinstance(
                    result.get("confirmation_payload"), dict
                ):
                    confirmation_payload = result.get("confirmation_payload")
                if not background_job and isinstance(result.get("background_job"), dict):
                    background_job = result.get("background_job")
                if not ui_action and isinstance(result.get("ui_action"), dict):
                    ui_action = result.get("ui_action")

                if run_id is not None:
                    create_run_event(
                        db,
                        run_id=run_id,
                        event_type="tool_finished",
                        label="Готово",
                        status="completed",
                        payload={"tool_name": tool_name, "summary": result.get("summary")},
                    )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": spec.tool_call_id or f"call_{spec_index}",
                        "name": tool_name,
                        "content": self._tool_result_for_llm(tool_name, result),
                    }
                )

            if confirmation_payload or background_job:
                # Don't keep planning further rounds — preview must reach the user.
                break
            if total_tool_calls >= max_calls:
                break

        if not final_text:
            primary_assistant = next(
                (
                    str(item["result"].get("assistant_message"))
                    for item in tool_results
                    if isinstance(item.get("result"), dict)
                    and item["result"].get("assistant_message")
                ),
                None,
            )
            if primary_assistant:
                final_text = primary_assistant
            else:
                summary = next(
                    (
                        str(item["result"].get("summary"))
                        for item in tool_results
                        if isinstance(item.get("result"), dict)
                        and item["result"].get("summary")
                    ),
                    None,
                )
                final_text = summary or "Готово."

        return {
            "message": final_text,
            "cards": cards,
            "navigation_targets": navigation_targets,
            "tool_results": tool_results,
            "confirmation_payload": confirmation_payload,
            "background_job": background_job,
            "ui_action": ui_action,
        }

    async def run_task(
        self,
        *,
        db: Session,
        task_prompt: str,
        scope: Optional[dict] = None,
        current_user: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Headless native tool-calling run for scheduled routines.

        Runs the same native loop as `handle_message` but WITHOUT a thread or
        run: no AgentRun/AgentMessage/AgentRunEvent rows are written and no
        thread history is replayed. Mutations stay behind confirmation — a
        produced `confirmation_payload` is never auto-applied here; it is only
        noted in the returned summary so an operator can confirm it manually.
        """
        user = current_user if isinstance(current_user, dict) else {"role": "admin", "user_id": 0, "id": 0}
        run_scope = _inject_allowed_chat_ids(scope, user)

        if not AI_AGENT_NATIVE_TOOLS or not self.provider.enabled:
            message = (
                "AI provider не сконфигурирован — задайте DEEPSEEK_API_KEY на сервере. "
                "Без него рутина не может выполнить задачу через инструменты."
            )
            return {
                "message": message,
                "summary": message,
                "cards": [],
                "navigation_targets": [],
                "tool_results": [],
                "confirmation_payload": None,
                "background_job": None,
                "ui_action": None,
            }

        outcome = await self._run_native_loop(
            db=db,
            thread_id=None,
            run_id=None,
            current_user=user,
            scope=run_scope,
            user_text=task_prompt,
        )

        message = str(outcome.get("message") or "Готово").strip() or "Готово"
        summary = message
        if isinstance(outcome.get("confirmation_payload"), dict):
            summary += (
                "\n\nПредложено исправление, но оно требует ручного подтверждения — "
                "автоприменение в рутине отключено."
            )
        outcome["summary"] = summary
        return outcome

    async def _run_requested_tool(
        self,
        *,
        db: Session,
        thread_id: UUID,
        run_id: UUID,
        current_user: Dict[str, Any],
        scope: Optional[dict],
        tool_name: str,
        user_text: str,
    ) -> Dict[str, Any]:
        """Direct tool invocation when the UI explicitly picks a tool."""
        validated, error = self._validate_arguments(tool_name, {"query_text": user_text})
        if error and tool_name in ARGS_MODELS:
            # Try with empty args — many tools accept all-optional inputs.
            validated, error = self._validate_arguments(tool_name, {})
        exec_args = {
            **(validated or {}),
            "_execution_context": {
                "thread_id": str(thread_id),
                "run_id": str(run_id),
                "user_id": int(current_user.get("id") or current_user.get("user_id") or 0),
            },
        }
        create_run_event(
            db,
            run_id=run_id,
            event_type="tool_selected",
            label=f"Выбран инструмент: {tool_name}",
            status="completed",
            payload={"tool_name": tool_name, "arguments": validated, "requested_by_user": True},
        )
        update_run(
            db,
            run_id=run_id,
            status="processing",
            progress={"step": "tool_execution", "percent": 30, "tool_name": tool_name},
        )
        create_run_event(
            db,
            run_id=run_id,
            event_type="tool_started",
            label=self._tool_progress_label(tool_name, {"step": "tool_execution"}),
            status="running",
            payload={"tool_name": tool_name},
        )

        def progress_callback(progress: Dict[str, Any]) -> None:
            percent = self._progress_percent(progress, 30)
            update_run(
                db,
                run_id=run_id,
                status="processing",
                progress={
                    "step": progress.get("step") or "tool_execution",
                    "percent": percent,
                    "tool_name": tool_name,
                },
            )
            create_run_event(
                db,
                run_id=run_id,
                event_type="tool_progress",
                label=self._tool_progress_label(tool_name, progress),
                status=self._run_event_status(progress),
                payload={"tool_name": tool_name, **progress},
            )

        try:
            result = await execute_tool(
                tool_name,
                db=db,
                current_user=current_user,
                scope=scope,
                arguments=exec_args,
                progress_callback=progress_callback,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Requested tool %s raised", tool_name)
            result = {
                "summary": f"Инструмент {tool_name} упал: {exc}",
                "cards": [
                    {
                        "type": "warning",
                        "title": f"Ошибка инструмента {tool_name}",
                        "body": str(exc),
                    }
                ],
            }

        create_run_event(
            db,
            run_id=run_id,
            event_type="tool_finished",
            label="Готово",
            status="completed",
            payload={"tool_name": tool_name, "summary": result.get("summary")},
        )

        cards = list(result.get("cards") or [])
        navigation_targets = list(result.get("navigation_targets") or [])
        confirmation_payload = (
            result.get("confirmation_payload")
            if isinstance(result.get("confirmation_payload"), dict)
            else None
        )
        background_job = (
            result.get("background_job")
            if isinstance(result.get("background_job"), dict)
            else None
        )
        ui_action = (
            result.get("ui_action")
            if isinstance(result.get("ui_action"), dict)
            else None
        )

        message = (
            str(result.get("assistant_message") or result.get("summary") or "Готово.").strip()
            or "Готово."
        )
        return {
            "message": message,
            "cards": cards,
            "navigation_targets": navigation_targets,
            "tool_results": [{"name": tool_name, "result": result}],
            "confirmation_payload": confirmation_payload,
            "background_job": background_job,
            "ui_action": ui_action,
        }

    async def _provider_offline_fallback(
        self,
        *,
        db: Session,
        run_id: UUID,
        user_text: str,
    ) -> Dict[str, Any]:
        create_run_event(
            db,
            run_id=run_id,
            event_type="failed",
            label="AI оффлайн",
            status="failed",
            payload={"reason": "deepseek_not_configured"},
        )
        return {
            "message": (
                "AI provider не сконфигурирован — задайте DEEPSEEK_API_KEY на сервере. "
                "Без него агент не может планировать инструменты."
            ),
            "cards": [
                {
                    "type": "warning",
                    "title": "AI offline",
                    "body": "DEEPSEEK_API_KEY не задан, native tool-calling недоступен.",
                }
            ],
            "navigation_targets": [],
            "tool_results": [],
            "confirmation_payload": None,
            "background_job": None,
        }

    async def handle_message(
        self,
        *,
        db: Session,
        thread_id: UUID,
        run_id: UUID,
        current_user: Dict[str, Any],
        scope: Optional[dict],
        user_text: str,
        requested_tool: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Enforce per-source RBAC inside agent tools. Tools read
        # scope["allowed_chat_ids"]; the HTTP scope dependency never sets it, so
        # without this the agent ignores an operator's allowed_sources entirely.
        # Admin (role==admin) keeps full access (no chat restriction injected).
        scope = _inject_allowed_chat_ids(scope, current_user)
        # Run-lock: refuse if another run for the same thread is in flight.
        try:
            from database.models import AgentRun

            active = (
                db.query(AgentRun)
                .filter(
                    AgentRun.thread_id == thread_id,
                    AgentRun.id != run_id,
                    AgentRun.status.in_(["queued", "processing"]),
                )
                .first()
            )
            if active is not None:
                # Surface a soft block in the chat instead of stomping the other run.
                blocked_payload = {
                    "message": (
                        "В этом треде уже выполняется другой запрос. Подождите окончания "
                        "или отмените его — потом повторите."
                    ),
                    "cards": [
                        {
                            "type": "warning",
                            "title": "Запрос отклонён",
                            "body": f"Активный run: {active.id}",
                        }
                    ],
                    "tool_results": [],
                    "navigation_targets": [],
                    "requires_confirmation": False,
                    "confirmation_payload": None,
                    "ui_action": None,
                }
                create_message(
                    db,
                    thread_id=thread_id,
                    run_id=run_id,
                    role="assistant",
                    message_type="warning",
                    content=blocked_payload,
                )
                update_run(
                    db,
                    run_id=run_id,
                    status="failed",
                    progress={"step": "blocked", "percent": 100},
                    result=blocked_payload,
                    error_text="thread_busy",
                    requires_confirmation=False,
                )
                return blocked_payload
        except Exception:  # noqa: BLE001
            logger.debug("run-lock check failed", exc_info=True)

        create_run_event(
            db,
            run_id=run_id,
            event_type="planning_started",
            label="Понимаю запрос",
            status="running",
            payload={"query_text": user_text[:500]},
        )
        update_run(
            db,
            run_id=run_id,
            status="processing",
            progress={"step": "planning", "percent": 10},
        )

        if requested_tool:
            outcome = await self._run_requested_tool(
                db=db,
                thread_id=thread_id,
                run_id=run_id,
                current_user=current_user,
                scope=scope,
                tool_name=requested_tool,
                user_text=user_text,
            )
        elif not AI_AGENT_NATIVE_TOOLS:
            # Native tool-calling disabled by flag — surface explicit fallback.
            outcome = await self._provider_offline_fallback(
                db=db, run_id=run_id, user_text=user_text
            )
        elif not self.provider.enabled:
            outcome = await self._provider_offline_fallback(
                db=db, run_id=run_id, user_text=user_text
            )
        else:
            try:
                outcome = await self._run_native_loop(
                    db=db,
                    thread_id=thread_id,
                    run_id=run_id,
                    current_user=current_user,
                    scope=scope,
                    user_text=user_text,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Native tool-call loop failed")
                outcome = {
                    "message": f"AI недоступен: {exc}",
                    "cards": [
                        {
                            "type": "warning",
                            "title": "AI request failed",
                            "body": str(exc),
                        }
                    ],
                    "navigation_targets": [],
                    "tool_results": [],
                    "confirmation_payload": None,
                    "background_job": None,
                }

        confirmation_payload = outcome.get("confirmation_payload")
        background_job = outcome.get("background_job")
        requires_confirmation = bool(confirmation_payload)

        assistant_payload = {
            "message": outcome.get("message") or "Готово.",
            "cards": outcome.get("cards") or [],
            "tool_results": outcome.get("tool_results") or [],
            "navigation_targets": outcome.get("navigation_targets") or [],
            "requires_confirmation": requires_confirmation,
            "confirmation_payload": confirmation_payload,
            "ui_action": outcome.get("ui_action"),
        }

        create_message(
            db,
            thread_id=thread_id,
            run_id=run_id,
            role="assistant",
            message_type="text",
            content=assistant_payload,
        )

        if background_job:
            try:
                from workers.celery_worker import run_agent_monitored_chat_sync_audit_task

                create_run_event(
                    db,
                    run_id=run_id,
                    event_type="tool_progress",
                    label="Сверяю чеки",
                    status="running",
                    payload={"background": True, **background_job},
                )
                update_run(
                    db,
                    run_id=run_id,
                    status="processing",
                    progress={
                        "step": "background_running",
                        "percent": 15,
                        "tool_name": str(background_job.get("job_type") or ""),
                        "mode": "background",
                    },
                    result=assistant_payload,
                    requires_confirmation=False,
                )
                run_agent_monitored_chat_sync_audit_task.delay(
                    json.dumps(
                        {
                            "thread_id": str(thread_id),
                            "run_id": str(run_id),
                            "current_user": current_user,
                            "scope": scope or {},
                            "payload": background_job.get("payload") or {},
                        },
                        ensure_ascii=False,
                    )
                )
                return assistant_payload
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to schedule background audit")
                assistant_payload["message"] = f"Не удалось запустить фоновую сверку: {exc}"
                assistant_payload["cards"] = [
                    {
                        "type": "warning",
                        "title": "Фоновая сверка не запущена",
                        "body": str(exc),
                    }
                ]
                update_run(
                    db,
                    run_id=run_id,
                    status="failed",
                    progress={"step": "failed", "percent": 100},
                    result=assistant_payload,
                    error_text=str(exc),
                    requires_confirmation=False,
                )
                create_run_event(
                    db,
                    run_id=run_id,
                    event_type="failed",
                    label="Фоновая сверка не запущена",
                    status="failed",
                    payload={"error": str(exc)},
                )
                return assistant_payload

        final_status = "awaiting_confirmation" if requires_confirmation else "completed"
        create_run_event(
            db,
            run_id=run_id,
            event_type="awaiting_confirmation" if requires_confirmation else "completed",
            label="Готовлю действия" if requires_confirmation else "Готово",
            status="running" if requires_confirmation else "completed",
            payload={"requires_confirmation": requires_confirmation},
        )
        update_run(
            db,
            run_id=run_id,
            status=final_status,
            progress={"step": "completed", "percent": 100},
            result=assistant_payload,
            requires_confirmation=requires_confirmation,
        )
        return assistant_payload


# Keep TOOL_DESCRIPTIONS importable from this module for any external users.
__all__ = ["AgentOrchestrator", "TOOL_DESCRIPTIONS", "SYSTEM_PROMPT_NATIVE", "get_orchestrator"]


_orchestrator_singleton: Optional["AgentOrchestrator"] = None


def get_orchestrator() -> "AgentOrchestrator":
    """Process-wide orchestrator singleton (provider is itself a singleton)."""
    global _orchestrator_singleton
    if _orchestrator_singleton is None:
        _orchestrator_singleton = AgentOrchestrator()
    return _orchestrator_singleton
