from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from config.ai_models import AI_MAX_TOOL_CALLS_PER_REQUEST, DEEPSEEK_TEXT_MODEL
from services.ai_agent.session_service import create_message, create_run_event, update_run
from services.ai_agent.tool_registry import TOOL_DESCRIPTIONS, execute_tool
from services.ai_provider import get_text_ai_provider

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    def __init__(self) -> None:
        self.provider = get_text_ai_provider()

    @staticmethod
    def _looks_like_analytics_request(text: str) -> bool:
        lowered = (text or "").lower()
        metric_tokens = ["сколько", "сумма", "сумму", "итог", "потра", "расход", "списан", "поступ", "зачис", "оборот"]
        period_tokens = ["с ", "по ", "сегодня", "вчера", "месяц", "феврал", "январ", "март", "апрел", "май", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр"]
        return any(token in lowered for token in metric_tokens) and any(token in lowered for token in period_tokens)

    @staticmethod
    def _extract_analytics_arguments(text: str) -> Dict[str, Any]:
        lowered = (text or "").lower()
        direction = "spent"
        if any(token in lowered for token in ["получ", "поступ", "зачис", "пришло"]):
            direction = "received"
        elif any(token in lowered for token in ["оборот", "всего прошло", "движение"]):
            direction = "turnover"
        currency = None
        if " usd" in lowered or lowered.endswith("usd") or "доллар" in lowered:
            currency = "USD"
        elif " uzs" in lowered or "сум" in lowered:
            currency = "UZS"
        return {
            "query_text": text,
            "direction": direction,
            "currency": currency,
        }

    @staticmethod
    def _is_explicit_report_request(text: str) -> bool:
        lowered = (text or "").lower()
        return any(token in lowered for token in ["weekly report", "weekly", "сделай отчет", "собери сводку", "сформируй отчет", "отчет"])

    @staticmethod
    def _is_generic_reply(text: Optional[str]) -> bool:
        normalized = str(text or "").strip().lower()
        if not normalized:
            return True
        generic_tokens = [
            "запускаю выбранный инструмент",
            "готовлю ответ",
            "ai planning fallback",
            "запускаю эвристически",
            "сейчас запущу",
            "запущу инструмент",
        ]
        return any(token in normalized for token in generic_tokens)

    def _heuristic_tool_calls(self, text: str) -> List[Dict[str, Any]]:
        lowered = (text or "").lower()
        calls: List[Dict[str, Any]] = []
        if any(token in lowered for token in ["проверь всё", "проверь все", "сверь все чеки", "сверь всё", "полный аудит", "audit all"]):
            return [{"name": "monitored_chat_sync_audit", "arguments": {"query_text": text}}]
        if self._is_explicit_report_request(text):
            return [{"name": "report_builder", "arguments": {}}]
        if self._looks_like_analytics_request(text):
            return [{"name": "transaction_analytics", "arguments": self._extract_analytics_arguments(text)}]
        if any(token in lowered for token in ["почему чек", "не попал в таблиц", "разбери чек", "investigate failed", "failed receipt"]):
            calls.append({"name": "failed_receipt_investigator", "arguments": {"query_text": text}})
        if any(token in lowered for token in ["trace", "трасс", "отследи сообщение", "message trace"]):
            calls.append({"name": "message_to_transaction_trace", "arguments": {"query_text": text}})
        if any(token in lowered for token in ["кеш", "cache", "сообщени", "найди в чате", "найди сообщение"]):
            calls.append({"name": "telegram_cache_search", "arguments": {"query_text": text}})
        if any(token in lowered for token in ["синх", "monitor audit", "мониторинг чеков", "missing in db", "пропущен"]):
            calls.append({"name": "monitored_chat_sync_audit", "arguments": {"query_text": text}})
        if any(token in lowered for token in ["mapping", "размет", "приложен"]):
            calls.append({"name": "app_mapping", "arguments": {}})
        if any(token in lowered for token in ["verify", "вериф", "проверь чек", "ошибк парс"]):
            calls.append({"name": "data_verification", "arguments": {}})
        if any(token in lowered for token in ["reconcile", "сверк", "telegram history", "истор"]):
            calls.append({"name": "bot_reconciliation", "arguments": {}})
        if any(token in lowered for token in ["duplicate merge", "preview дубл", "объедин", "дублик preview"]):
            calls.append({"name": "duplicate_merge_preview", "arguments": {}})
        if any(token in lowered for token in ["reparse", "повторно разоб", "перепарс"]):
            calls.append({"name": "receipt_reparse_preview", "arguments": {"query_text": text}})
        if any(token in lowered for token in ["config monitor", "настройки монитор", "inspect monitor"]):
            calls.append({"name": "monitor_config_inspector", "arguments": {}})
        if any(token in lowered for token in ["publish report", "опубликуй отчет", "командный отчет"]):
            calls.append({"name": "report_publish_tool", "arguments": {}})
        if any(token in lowered for token in ["report", "отчет", "weekly"]):
            calls.append({"name": "report_builder", "arguments": {}})
        if any(token in lowered for token in ["найди", "open transaction", "открой транзакц", "locate"]):
            tx_match = re.search(r"#?(\d{1,12})", lowered)
            calls.append({
                "name": "table_search_and_navigate",
                "arguments": {"transaction_id": int(tx_match.group(1)) if tx_match else None, "search": text},
            })
        if any(token in lowered for token in ["диагност", "inspect", "состояние бд"]):
            calls.append({"name": "db_inspector", "arguments": {}})
        if any(token in lowered for token in ["дублик", "duplicate"]):
            calls.append({"name": "duplicate_detector", "arguments": {}})
        if any(token in lowered for token in ["ошибк", "failed parse"]):
            calls.append({"name": "processing_errors_analyzer", "arguments": {}})
        if any(token in lowered for token in ["источник", "source health", "чат"]):
            calls.append({"name": "source_health_check", "arguments": {}})
        if not calls:
            calls.append({"name": "fix_plan_builder", "arguments": {}})
        return calls[: max(1, int(AI_MAX_TOOL_CALLS_PER_REQUEST))]

    @staticmethod
    def _tool_progress_label(tool_name: str, progress: Dict[str, Any]) -> str:
        step = str(progress.get("step") or "").strip().lower()
        if tool_name == "transaction_analytics":
            return "Проверяю данные"
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
            return max(0, min(100, int(progress.get("percent") if progress.get("percent") is not None else default_percent)))
        except Exception:
            return default_percent

    @staticmethod
    def _run_event_status(progress: Dict[str, Any]) -> str:
        if progress.get("failed"):
            return "failed"
        if progress.get("completed"):
            return "completed"
        return "running"

    async def _plan(self, text: str, requested_tool: Optional[str] = None) -> Dict[str, Any]:
        if requested_tool:
            return {
                "reply": "Запускаю выбранный инструмент.",
                "tool_calls": [{"name": requested_tool, "arguments": {}}],
                "requires_confirmation": False,
            }

        heuristic_calls = self._heuristic_tool_calls(text)
        if heuristic_calls and heuristic_calls[0]["name"] == "transaction_analytics":
            return {
                "reply": "Считаю итог за период.",
                "tool_calls": heuristic_calls,
                "requires_confirmation": False,
            }

        if not self.provider.enabled:
            return {
                "reply": "AI planning fallback: запускаю эвристически подобранные инструменты.",
                "tool_calls": heuristic_calls,
                "requires_confirmation": False,
            }

        tool_list = "\n".join(f"- {name}: {desc}" for name, desc in TOOL_DESCRIPTIONS.items())
        system_prompt = (
            "Ты встроенный ИИ-агент Parcer 2.0. "
            "Определи, какие инструменты нужно вызвать для ответа пользователю. "
            "Верни JSON с ключами reply, tool_calls, requires_confirmation. "
            "tool_calls — массив объектов {name, arguments}. "
            "Не придумывай инструменты вне списка. Максимум инструментов за запрос: "
            f"{AI_MAX_TOOL_CALLS_PER_REQUEST}. "
            "Для вопросов о сумме расходов, поступлений, обороте и итогах за период выбирай transaction_analytics, "
            "а не report_builder и не db_inspector. "
            "report_builder используй только если пользователь явно просит отчет или сводку.\n"
            f"Доступные инструменты:\n{tool_list}"
        )
        payload = await self.provider.complete_json(
            model=DEEPSEEK_TEXT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            max_tokens=900,
        )
        tool_calls = payload.get("tool_calls") if isinstance(payload.get("tool_calls"), list) else []
        normalized_calls = []
        for item in tool_calls[: max(1, int(AI_MAX_TOOL_CALLS_PER_REQUEST))]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
            normalized_calls.append({"name": name, "arguments": arguments})
        if not normalized_calls:
            normalized_calls = heuristic_calls
        return {
            "reply": str(payload.get("reply") or "Готовлю ответ."),
            "tool_calls": normalized_calls,
            "requires_confirmation": bool(payload.get("requires_confirmation", False)),
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
        create_run_event(
            db,
            run_id=run_id,
            event_type="planning_started",
            label="Понимаю запрос",
            status="running",
            payload={"query_text": user_text[:500]},
        )
        update_run(db, run_id=run_id, status="processing", progress={"step": "planning", "percent": 10})
        plan = await self._plan(user_text, requested_tool=requested_tool)
        tool_results: List[Dict[str, Any]] = []
        navigation_targets: List[Dict[str, Any]] = []
        cards: List[Dict[str, Any]] = []
        confirmation_payload: Optional[Dict[str, Any]] = None
        background_job: Optional[Dict[str, Any]] = None

        for index, tool_call in enumerate(plan.get("tool_calls", []), start=1):
            tool_name = str(tool_call.get("name") or "").strip()
            arguments = tool_call.get("arguments") if isinstance(tool_call.get("arguments"), dict) else {}
            arguments = {
                **arguments,
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
                payload={"tool_name": tool_name, "arguments": arguments},
            )
            update_run(
                db,
                run_id=run_id,
                status="processing",
                progress={
                    "step": "tool_execution",
                    "percent": min(95, 10 + index * 20),
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

            def progress_callback(progress: Dict[str, Any]) -> None:
                percent = self._progress_percent(progress, min(95, 10 + index * 20))
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

            result = await execute_tool(
                tool_name,
                db=db,
                current_user=current_user,
                scope=scope,
                arguments=arguments,
                progress_callback=progress_callback,
            )
            tool_results.append({"name": tool_name, "result": result})
            cards.extend(result.get("cards") or [])
            navigation_targets.extend(result.get("navigation_targets") or [])
            if not confirmation_payload and isinstance(result.get("confirmation_payload"), dict):
                confirmation_payload = result.get("confirmation_payload")
            if not background_job and isinstance(result.get("background_job"), dict):
                background_job = result.get("background_job")
            create_run_event(
                db,
                run_id=run_id,
                event_type="tool_finished",
                label="Готово",
                status="completed",
                payload={"tool_name": tool_name, "summary": result.get("summary")},
            )

        primary_result = next(
            (item.get("result") for item in tool_results if isinstance(item.get("result"), dict)),
            {},
        ) or {}
        final_message = str(plan.get("reply") or "").strip()
        if self._is_generic_reply(final_message):
            final_message = str(primary_result.get("assistant_message") or primary_result.get("summary") or "Готово.").strip()
        elif primary_result.get("assistant_message") and len(tool_results) == 1:
            final_message = str(primary_result.get("assistant_message") or final_message)

        requires_confirmation = bool(plan.get("requires_confirmation", False) or confirmation_payload)
        assistant_payload = {
            "message": final_message or "Готово.",
            "cards": cards,
            "tool_results": tool_results,
            "navigation_targets": navigation_targets,
            "requires_confirmation": requires_confirmation,
            "confirmation_payload": confirmation_payload,
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

        final_status = "awaiting_confirmation" if assistant_payload["requires_confirmation"] else "completed"
        create_run_event(
            db,
            run_id=run_id,
            event_type="awaiting_confirmation" if assistant_payload["requires_confirmation"] else "completed",
            label="Готовлю действия" if assistant_payload["requires_confirmation"] else "Готово",
            status="completed" if not assistant_payload["requires_confirmation"] else "running",
            payload={"requires_confirmation": assistant_payload["requires_confirmation"]},
        )
        update_run(
            db,
            run_id=run_id,
            status=final_status,
            progress={"step": "completed", "percent": 100},
            result=assistant_payload,
            requires_confirmation=assistant_payload["requires_confirmation"],
        )
        return assistant_payload
