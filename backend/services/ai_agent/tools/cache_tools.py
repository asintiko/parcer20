from __future__ import annotations

import re
from datetime import timedelta
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from config.ai_models import AI_AGENT_RECEIPT_GRACE_MINUTES
from database.models import DuplicateSuggestion, ReceiptProcessingTask
from services.ai_agent.report_service import generate_report
from services.incident_service import upsert_receipt_incident
from services.telegram_cache_service import TelegramCacheService


ToolResult = Dict[str, Any]
ProgressCallback = Callable[[Dict[str, Any]], None]
BACKGROUND_AUDIT_THRESHOLD = 2000
BACKGROUND_AUDIT_CHUNK_SIZE = 500


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace('Z', '+00:00')).replace(tzinfo=None)
    except Exception:
        return None


def _allowed_chat_ids(current_user: Dict[str, Any], requested_ids: Optional[Iterable[int]]) -> Optional[List[int]]:
    role = str((current_user or {}).get('role') or '').lower()
    allowed_sources = [int(item) for item in ((current_user or {}).get('allowed_sources') or []) if str(item).strip()]
    requested = [int(item) for item in (requested_ids or []) if item is not None]
    if role == 'admin' and not allowed_sources:
        return requested or None
    if not allowed_sources:
        return requested or None
    if not requested:
        return sorted(set(allowed_sources))
    filtered = [chat_id for chat_id in requested if chat_id in set(allowed_sources)]
    return sorted(set(filtered))


def _parse_chat_ids(args: Dict[str, Any]) -> Optional[List[int]]:
    raw_values = args.get('chat_ids') or args.get('source_chat_ids') or args.get('chat_id')
    if raw_values is None:
        return None
    values: List[Any]
    if isinstance(raw_values, list):
        values = raw_values
    else:
        values = str(raw_values).split(',')
    parsed: List[int] = []
    for item in values:
        try:
            parsed.append(int(str(item).strip()))
        except Exception:
            continue
    return sorted(set(parsed)) or None


def _progress(args: Dict[str, Any]) -> Optional[ProgressCallback]:
    callback = args.get('_progress_callback')
    return callback if callable(callback) else None


def _iso_date_label(value: Optional[datetime]) -> Optional[str]:
    return value.date().isoformat() if value else None


def _period_label(date_from: Optional[datetime], date_to: Optional[datetime]) -> str:
    if not date_from and not date_to:
        return 'весь доступный период'
    return f"{_iso_date_label(date_from) or '...'} - {_iso_date_label(date_to) or '...'}"


def _build_audit_navigation_target(
    *,
    row_id: Optional[int] = None,
    row_ids: Optional[List[int]] = None,
    column_id: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    highlight_seconds: int = 4,
) -> Dict[str, Any]:
    normalized_row_ids = [int(item) for item in (row_ids or []) if item is not None]
    return {
        'exists': True,
        'route': '/transactions',
        'row_id': int(row_id) if row_id is not None else (normalized_row_ids[0] if normalized_row_ids else None),
        'row_ids': normalized_row_ids or None,
        'column_id': column_id,
        'focus_mode': 'row' if row_id is not None or normalized_row_ids else 'filter',
        'suggested_filters': filters or {},
        'sort_hint': {'sort_by': 'transaction_date', 'sort_dir': 'desc'},
        'page_hint': 1,
        'highlight_seconds': int(highlight_seconds),
    }


def _build_navigation_target(issue: Dict[str, Any], *, date_from: Optional[datetime], date_to: Optional[datetime]) -> Optional[Dict[str, Any]]:
    chat_id = issue.get('chat_id')
    message_id = issue.get('message_id')
    tx_id = issue.get('transaction_id')
    if chat_id is None and tx_id is None:
        return None
    filters: Dict[str, Any] = {}
    if chat_id is not None:
        filters['source_chat_ids'] = [int(chat_id)]
    if date_from:
        filters['date_from'] = date_from.date().isoformat()
    if date_to:
        filters['date_to'] = date_to.date().isoformat()
    if issue.get('category') == 'FAILED_PARSE':
        filters['search'] = str(message_id or '')
    return _build_audit_navigation_target(
        row_id=int(tx_id) if tx_id is not None else None,
        column_id='raw_message' if issue.get('category') == 'FAILED_PARSE' else 'amount',
        filters=filters,
    )


def _build_trace_navigation(trace: Dict[str, Any]) -> List[Dict[str, Any]]:
    transaction = trace.get('transaction') or {}
    message = trace.get('message') or {}
    chat_id = transaction.get('source_chat_id') or message.get('chat_id')
    tx_id = transaction.get('id')
    if not tx_id and not chat_id:
        return []
    return [
        _build_audit_navigation_target(
            row_id=int(tx_id) if tx_id is not None else None,
            column_id='amount' if tx_id is not None else 'raw_message',
            filters={'source_chat_ids': [int(chat_id)]} if chat_id is not None else {},
        )
    ]


def _extract_trace_ids(args: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    direct_chat_id = args.get('chat_id')
    direct_message_id = args.get('message_id')
    if direct_chat_id is not None and direct_message_id is not None:
        try:
            return int(direct_chat_id), int(direct_message_id)
        except Exception:
            return None, None

    text = str(args.get('query_text') or args.get('search') or '').strip()
    match = re.search(r'(-?\d+)\D+(\d+)', text)
    if not match:
        return None, None
    try:
        return int(match.group(1)), int(match.group(2))
    except Exception:
        return None, None


def _build_monitored_chat_sync_audit_result(
    *,
    summary: Dict[str, Any],
    date_from: Optional[datetime],
    date_to: Optional[datetime],
    background: bool = False,
    estimated_candidates: Optional[int] = None,
) -> ToolResult:
    categories = summary.get('categories') or {}
    issues = summary.get('issues_preview') or summary.get('top_actionable_cases') or summary.get('issues') or []
    top_issues = list(issues[: min(10, len(issues))])
    actual_candidates = sum(int(item.get('total_candidates') or 0) for item in (summary.get('by_chat') or []))
    display_candidate_count = int(estimated_candidates) if estimated_candidates and int(estimated_candidates) > 0 else (actual_candidates if actual_candidates > 0 else None)
    navigation_targets = [
        target
        for target in (_build_navigation_target(item, date_from=date_from, date_to=date_to) for item in top_issues)
        if target
    ]
    period_label = _period_label(date_from, date_to)
    prefix = 'Запустил фоновую сверку' if background else 'Проверил мониторинг'
    assistant_message = (
        f"{prefix} за {period_label}. "
        f"Найдено проблем: {int(summary.get('total_issues') or 0)}. "
        f"Критичные категории: missing={int(categories.get('MISSING_IN_DB') or 0)}, "
        f"failed={int(categories.get('FAILED_PARSE') or 0)}, duplicate={int(categories.get('DUPLICATE') or 0)}."
    )
    payload = {
        'period_label': period_label,
        'checked_chats': int(summary.get('checked_chats') or 0),
        'total_issues': int(summary.get('total_issues') or 0),
        'categories': categories,
        'by_chat': (summary.get('by_chat') or [])[:50],
        'issues_preview': top_issues,
    }
    if display_candidate_count is not None:
        payload['estimated_candidates'] = int(display_candidate_count)
    compact_details = {
        'period_label': period_label,
        'checked_chats': int(summary.get('checked_chats') or 0),
        'total_issues': int(summary.get('total_issues') or 0),
        'categories': categories,
        'by_chat': (summary.get('by_chat') or [])[:25],
        'top_actionable_cases': top_issues,
    }
    if display_candidate_count is not None:
        compact_details['estimated_candidates'] = int(display_candidate_count)
    return {
        'summary': assistant_message,
        'assistant_message': assistant_message,
        'cards': [
            {
                'type': 'progress' if background else 'result',
                'title': 'Аудит мониторинга чеков',
                'body': (
                    f"Фоновая проверка запущена. Оценка candidate messages: {int(display_candidate_count)}."
                    if background and display_candidate_count is not None
                    else "Фоновая проверка запущена."
                    if background
                    else f"Проверено чатов: {int(summary.get('checked_chats') or 0)}. Проблем найдено: {int(summary.get('total_issues') or 0)}."
                ),
                'payload': payload,
                'details': compact_details,
            }
        ],
        'navigation_targets': navigation_targets,
    }


async def monitored_chat_sync_audit(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> ToolResult:
    service = TelegramCacheService(db)
    requested_chat_ids = _parse_chat_ids(args)
    chat_ids = _allowed_chat_ids(current_user, requested_chat_ids)
    date_from = _parse_datetime(args.get('date_from') or args.get('period_start'))
    date_to = _parse_datetime(args.get('date_to') or args.get('period_end'))
    progress_callback = _progress(args)
    grace_minutes = int(args.get('grace_minutes') or AI_AGENT_RECEIPT_GRACE_MINUTES)
    estimated_candidates = service.estimate_receipt_candidate_count(
        chat_ids=chat_ids,
        date_from=date_from,
        date_to=date_to,
    )

    if (date_from is None and date_to is None) or estimated_candidates > BACKGROUND_AUDIT_THRESHOLD:
        immediate_summary = {
            'categories': {},
            'issues': [],
            'by_chat': [],
            'total_issues': 0,
            'checked_chats': len(chat_ids or service.list_monitored_chat_ids(only_enabled=True)),
        }
        result = _build_monitored_chat_sync_audit_result(
            summary=immediate_summary,
            date_from=date_from,
            date_to=date_to,
            background=True,
            estimated_candidates=estimated_candidates,
        )
        result['background_job'] = {
            'job_type': 'monitored_chat_sync_audit',
            'payload': {
                'chat_ids': chat_ids,
                'date_from': date_from.isoformat() if date_from else None,
                'date_to': date_to.isoformat() if date_to else None,
                'grace_minutes': grace_minutes,
                'estimated_candidates': estimated_candidates,
                'chunk_size': BACKGROUND_AUDIT_CHUNK_SIZE,
            },
        }
        return result

    summary = service.audit_monitored_chats(
        chat_ids=chat_ids,
        date_from=date_from,
        date_to=date_to,
        grace_minutes=grace_minutes,
        progress_callback=progress_callback,
    )
    for issue in summary.get('issues') or []:
        category = str(issue.get('category') or '').upper()
        if category == 'SYNCED':
            continue
        incident_type = {
            'FAILED_PARSE': 'failed_parse',
            'MISSING_IN_DB': 'missing_in_db',
            'DUPLICATE': 'duplicate_without_row',
            'CURSOR_STALE': 'cursor_stale',
            'CACHE_GAP': 'cache_gap',
            'ORPHANED_IN_DB': 'manual_review',
        }.get(category, 'manual_review')
        upsert_receipt_incident(
            db,
            chat_id=int(issue.get('chat_id') or 0),
            message_id=int(issue.get('message_id')) if issue.get('message_id') is not None else None,
            transaction_id=int(issue.get('transaction_id')) if issue.get('transaction_id') is not None else None,
            task_id=int(issue.get('task_id')) if issue.get('task_id') is not None else None,
            incident_type=incident_type,
            severity='high' if category in {'FAILED_PARSE', 'MISSING_IN_DB', 'CURSOR_STALE', 'CACHE_GAP'} else 'medium',
            reason_code=category.lower(),
            reason_text=str(issue.get('summary') or ''),
            payload=issue,
            notify=bool(args.get('create_incidents', True)),
        )
    return _build_monitored_chat_sync_audit_result(summary=summary, date_from=date_from, date_to=date_to)


async def telegram_cache_search(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> ToolResult:
    service = TelegramCacheService(db)
    requested_chat_ids = _parse_chat_ids(args)
    chat_ids = _allowed_chat_ids(current_user, requested_chat_ids)
    results = service.search_messages(
        chat_ids=chat_ids,
        search=args.get('search') or args.get('query_text'),
        date_from=_parse_datetime(args.get('date_from')),
        date_to=_parse_datetime(args.get('date_to')),
        looks_like_receipt_only=bool(args.get('looks_like_receipt_only', False)),
        processing_status=args.get('processing_status'),
        duplicate_status=args.get('duplicate_status'),
        limit=int(args.get('limit') or 50),
    )
    assistant_message = f"Найдено сообщений в кеше: {len(results)}."
    return {
        'summary': assistant_message,
        'assistant_message': assistant_message,
        'cards': [
            {
                'type': 'result',
                'title': 'Поиск по Telegram кешу',
                'body': assistant_message,
                'payload': {
                    'count': len(results),
                    'messages': results[:10],
                },
                'details': results,
            }
        ],
    }


async def message_to_transaction_trace(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> ToolResult:
    chat_id, message_id = _extract_trace_ids(args)
    if chat_id is None or message_id is None:
        return {
            'summary': 'Нужны chat_id и message_id сообщения.',
            'assistant_message': 'Уточните chat_id и message_id сообщения, чтобы построить трассировку.',
            'cards': [{'type': 'warning', 'title': 'Недостаточно данных', 'body': 'Передайте chat_id и message_id сообщения.'}],
        }
    allowed_chat_ids = _allowed_chat_ids(current_user, [chat_id])
    if allowed_chat_ids == []:
        return {
            'summary': 'Нет доступа к источнику.',
            'assistant_message': 'У пользователя нет доступа к этому источнику.',
            'cards': [{'type': 'warning', 'title': 'Доступ ограничен', 'body': 'Этот источник недоступен по текущим правам.'}],
        }
    service = TelegramCacheService(db)
    trace = service.trace_message(chat_id=chat_id, message_id=message_id)
    return {
        'summary': trace.get('summary') or 'Трассировка готова.',
        'assistant_message': trace.get('summary') or 'Трассировка готова.',
        'cards': [
            {
                'type': 'result',
                'title': 'Трассировка сообщения',
                'body': trace.get('summary') or 'Связи по сообщению проверены.',
                'payload': {
                    'status': trace.get('status'),
                    'message': trace.get('message'),
                    'task': trace.get('task'),
                    'transaction': trace.get('transaction'),
                    'duplicate': trace.get('duplicate'),
                },
                'details': trace,
            }
        ],
        'navigation_targets': _build_trace_navigation(trace),
    }


async def failed_receipt_investigator(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> ToolResult:
    service = TelegramCacheService(db)
    chat_id, message_id = _extract_trace_ids(args)
    if chat_id is None or message_id is None:
        row = (
            db.query(ReceiptProcessingTask)
            .filter(ReceiptProcessingTask.status == 'failed')
            .order_by(ReceiptProcessingTask.updated_at.desc(), ReceiptProcessingTask.id.desc())
            .first()
        )
        if row is not None:
            chat_id, message_id = int(row.chat_id), int(row.message_id)
    if chat_id is None or message_id is None:
        return {
            'summary': 'Ошибки обработки не найдены.',
            'assistant_message': 'Сейчас нет сохраненных failed receipt tasks для расследования.',
            'cards': [{'type': 'result', 'title': 'Ошибки обработки', 'body': 'Свежих failed задач не найдено.'}],
        }
    trace = service.trace_message(chat_id=chat_id, message_id=message_id)
    return {
        'summary': trace.get('summary') or 'Проверка ошибки завершена.',
        'assistant_message': trace.get('summary') or 'Проверка ошибки завершена.',
        'cards': [
            {
                'type': 'result',
                'title': 'Разбор проблемного чека',
                'body': trace.get('summary') or 'Проверка выполнена.',
                'payload': {
                    'status': trace.get('status'),
                    'task': trace.get('task'),
                    'message': trace.get('message'),
                    'transaction': trace.get('transaction'),
                },
                'details': trace,
            }
        ],
        'navigation_targets': _build_trace_navigation(trace),
    }


async def duplicate_merge_preview(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> ToolResult:
    limit = max(1, min(int(args.get('limit') or 10), 50))
    rows = (
        db.query(DuplicateSuggestion)
        .filter(DuplicateSuggestion.status == 'pending')
        .order_by(DuplicateSuggestion.created_at.desc())
        .limit(limit)
        .all()
    )
    payload = [
        {
            'id': str(row.id),
            'primary_transaction_id': int(row.primary_transaction_id),
            'duplicate_transaction_id': int(row.duplicate_transaction_id),
            'confidence': row.confidence,
            'reasoning': row.reasoning,
        }
        for row in rows
    ]
    navigation_targets = []
    for row in rows[:5]:
        navigation_targets.append(
            _build_audit_navigation_target(
                row_id=int(row.primary_transaction_id),
                row_ids=[int(row.primary_transaction_id), int(row.duplicate_transaction_id)],
                column_id='amount',
                highlight_seconds=5,
            )
        )
    return {
        'summary': f'Подготовил preview по дублям: {len(payload)} кандидатов.',
        'assistant_message': f'Подготовил preview по дублям: {len(payload)} кандидатов. Автослияния не выполнялись.',
        'requires_confirmation': bool(payload),
        'confirmation_payload': {
            'action': 'merge_duplicates',
            'args': {'suggestion_ids': [str(item['id']) for item in payload]},
            'idempotency_key': f"merge_duplicates:{':'.join(str(item['id']) for item in payload)}",
        } if payload else None,
        'cards': [
            {
                'type': 'confirmation',
                'title': 'Preview объединения дублей',
                'body': f'Найдено кандидатов: {len(payload)}. Это только preview без изменений данных.',
                'payload': {'items': payload},
                'details': payload,
            }
        ],
        'navigation_targets': navigation_targets,
    }


async def receipt_reparse_preview(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> ToolResult:
    chat_id, message_id = _extract_trace_ids(args)
    if chat_id is None or message_id is None:
        row = (
            db.query(ReceiptProcessingTask)
            .filter(ReceiptProcessingTask.status == 'failed')
            .order_by(ReceiptProcessingTask.updated_at.desc(), ReceiptProcessingTask.id.desc())
            .first()
        )
        if row is not None:
            chat_id, message_id = int(row.chat_id), int(row.message_id)
    if chat_id is None or message_id is None:
        return {
            'summary': 'Нет кандидата для повторного разбора.',
            'assistant_message': 'Не нашел сообщения, для которого можно подготовить preview повторного разбора.',
            'cards': [{'type': 'warning', 'title': 'Нет данных', 'body': 'Сначала укажите chat_id/message_id или выберите failed чек.'}],
        }
    trace = TelegramCacheService(db).trace_message(chat_id=chat_id, message_id=message_id)
    return {
        'summary': 'Подготовил preview повторного разбора.',
        'assistant_message': 'Подготовил preview повторного разбора. Изменения еще не применялись.',
        'requires_confirmation': True,
        'confirmation_payload': {
            'action': 'reparse_receipt',
            'args': {'chat_id': chat_id, 'message_id': message_id},
            'idempotency_key': f'reparse_receipt:{chat_id}:{message_id}',
        },
        'cards': [
            {
                'type': 'confirmation',
                'title': 'Preview повторного разбора',
                'body': f'Сообщение {chat_id}/{message_id} готово к повторной обработке после подтверждения.',
                'payload': {
                    'chat_id': chat_id,
                    'message_id': message_id,
                    'current_status': trace.get('status'),
                },
                'details': trace,
            }
        ],
        'navigation_targets': _build_trace_navigation(trace),
    }


async def monitor_config_inspector(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> ToolResult:
    service = TelegramCacheService(db)
    chat_ids = _allowed_chat_ids(current_user, _parse_chat_ids(args))
    payload = service.monitored_chat_health(chat_ids)
    enabled_count = sum(1 for item in payload if item.get('enabled'))
    assistant_message = f'Проверил настройки мониторинга. Активных источников: {enabled_count}.'
    return {
        'summary': assistant_message,
        'assistant_message': assistant_message,
        'cards': [
            {
                'type': 'result',
                'title': 'Настройки мониторинга',
                'body': assistant_message,
                'payload': {'count': len(payload), 'enabled': enabled_count},
                'details': payload,
            }
        ],
    }


async def report_publish_tool(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> ToolResult:
    report = generate_report(
        db,
        created_by_user_id=int(current_user.get('id') or current_user.get('user_id') or 0),
        scope='team',
        publish_team_notification=False,
        publish_immediately=False,
    )
    compact_report = {
        'id': report.get('id'),
        'title': report.get('title'),
        'scope': report.get('scope'),
        'status': report.get('status'),
        'summary': report.get('summary') or {},
        'items_count': len(report.get('items') or []),
        'items_preview': (report.get('items') or [])[:10],
    }
    return {
        'summary': 'Подготовил preview командного отчета.',
        'assistant_message': 'Подготовил preview командного отчета. Публикация будет выполнена после подтверждения.',
        'requires_confirmation': True,
        'confirmation_payload': {
            'action': 'publish_report',
            'args': {'report_id': report.get('id')},
            'idempotency_key': f"publish_report:{report.get('id')}",
        },
        'cards': [
            {
                'type': 'confirmation',
                'title': report.get('title') or 'Командный отчет',
                'body': 'Отчет собран и готов к публикации в командные уведомления.',
                'payload': {
                    'report_id': report.get('id'),
                    'scope': report.get('scope'),
                    'status': report.get('status'),
                    'items': len(report.get('items') or []),
                },
                'details': compact_report,
            }
        ],
        'report_id': report.get('id'),
    }
