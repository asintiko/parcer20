import type { AgentLocateResult, AgentNotification } from '../services/api';

const TOOL_LABELS: Record<string, string> = {
    transaction_analytics: 'Анализ транзакций',
    app_mapping: 'Сопоставление',
    data_verification: 'Проверка данных',
    bot_reconciliation: 'Сверка с Telegram',
    table_search_and_navigate: 'Переход к данным',
    db_inspector: 'Состояние системы',
    duplicate_detector: 'Поиск дублей',
    processing_errors_analyzer: 'Ошибки обработки',
    source_health_check: 'Состояние источников',
    monitored_chat_sync_audit: 'Аудит мониторинга чеков',
    telegram_cache_search: 'Поиск по Telegram кешу',
    message_to_transaction_trace: 'Трассировка сообщения',
    failed_receipt_investigator: 'Разбор проблемного чека',
    duplicate_merge_preview: 'Кандидаты на объединение',
    receipt_reparse_preview: 'Повторный разбор чека',
    monitor_config_inspector: 'Настройки мониторинга',
    report_publish_tool: 'Публикация отчета',
    report_builder: 'Формирование отчета',
    fix_plan_builder: 'План действий',
};

const STATUS_LABELS: Record<string, string> = {
    queued: 'В очереди',
    processing: 'Выполняется',
    awaiting_confirmation: 'Ждет подтверждения',
    completed: 'Завершено',
    failed: 'Ошибка',
    cancelled: 'Отменено',
};

const SUMMARY_KEY_LABELS: Record<string, string> = {
    total_transactions: 'Всего транзакций',
    unmapped_transactions: 'Без приложения',
    failed_parse_tasks: 'Ошибки парсинга',
    pending_mapping_suggestions: 'Ожидают сопоставления',
    pending_duplicate_suggestions: 'Подозрение на дубли',
    pending_reconciliation_suggestions: 'Ожидают сверки',
    transactions: 'Транзакций',
    failed_receipt_tasks: 'Ошибок обработки',
    period_label: 'Период',
    total_operations: 'Операций',
    direction: 'Тип расчета',
    currency: 'Валюта',
    count: 'Количество',
    total: 'Сумма',
    title: 'Название',
    chat_title: 'Источник',
    loaded_count: 'Загружено',
    history_status: 'Статус истории',
    estimated_candidates: 'Кандидатов',
    checked_chats: 'Проверено чатов',
    total_issues: 'Проблем',
    SYNCED: 'Успешно сверены',
    MISSING_IN_DB: 'Не попали в таблицу',
    FAILED_PARSE: 'Ошибки разбора',
    DUPLICATE: 'Дубликаты',
    ORPHANED_IN_DB: 'Без сообщения в кеше',
    CURSOR_STALE: 'Синхронизация отстает',
    CACHE_GAP: 'Пробелы в кеше',
    PENDING_PROCESSING: 'Еще обрабатываются',
};

const NOTIFICATION_TITLES: Record<string, string> = {
    weekly_report_ready: 'Недельный отчет готов',
    personal_report_ready: 'Личный отчет готов',
};

export function formatToolLabel(toolName?: string | null): string {
    if (!toolName) return 'ИИ-агент';
    return TOOL_LABELS[toolName] || toolName;
}

export function formatRunStatus(status?: string | null): string {
    if (!status) return 'Выполняется';
    return STATUS_LABELS[status] || status;
}

export function formatRunStep(step?: string | null, toolName?: string | null): string {
    const normalized = String(step || '').trim().toLowerCase();
    if (normalized === 'queued') return 'Запрос поставлен в очередь';
    if (normalized === 'planning') return 'Понимаю запрос';
    if (normalized === 'tool_execution') return `Выполняю: ${formatToolLabel(toolName)}`;
    if (normalized === 'confirming') return 'Применяю подтвержденное действие';
    if (normalized === 'background_running') return 'Сверяю чеки';
    if (normalized === 'scan_chunk') return 'Проверяю очередную часть данных';
    if (normalized === 'chat_complete') return 'Перехожу к следующему источнику';
    if (normalized === 'confirmed') return 'Подтверждение получено';
    if (normalized === 'completed') return 'Ответ готов';
    if (normalized === 'failed') return 'Во время обработки возникла ошибка';
    return formatToolLabel(toolName);
}

export function formatRunEventLabel(eventType?: string | null, label?: string | null, toolName?: string | null): string {
    const normalized = String(eventType || '').trim().toLowerCase();
    if (normalized === 'planning_started') return 'Понимаю запрос';
    if (normalized === 'tool_selected') return label || `Выбран инструмент: ${formatToolLabel(toolName)}`;
    if (normalized === 'tool_started') return label || `Запускаю: ${formatToolLabel(toolName)}`;
    if (normalized === 'tool_progress') return label || (toolName === 'monitored_chat_sync_audit' ? 'Сверяю чеки' : 'Проверяю данные');
    if (normalized === 'tool_finished') return label || 'Шаг завершен';
    if (normalized === 'awaiting_confirmation') return 'Жду подтверждения';
    if (normalized === 'completed') return 'Готово';
    if (normalized === 'failed') return 'Ошибка выполнения';
    return label || formatToolLabel(toolName);
}

export function humanizeSummaryKey(key: string): string {
    return SUMMARY_KEY_LABELS[key] || key.replace(/_/g, ' ');
}

export function formatNotificationTitle(notification: AgentNotification): string {
    return NOTIFICATION_TITLES[notification.type] || 'Уведомление агента';
}

export function formatNotificationBody(notification: AgentNotification): string {
    const payload = notification.payload || {};
    if (typeof payload.title === 'string' && payload.title.trim()) {
        return payload.title.trim();
    }
    if (payload.summary && typeof payload.summary === 'object') {
        const summary = payload.summary as Record<string, any>;
        const firstKey = Object.keys(summary)[0];
        if (firstKey) {
            return `${humanizeSummaryKey(firstKey)}: ${String(summary[firstKey])}`;
        }
    }
    return notification.scope === 'team' ? 'Командное обновление готово.' : 'Личное обновление готово.';
}

export function formatNavigationLabel(target?: AgentLocateResult | null): string {
    if (!target) return 'Открыть';
    if (target.route === '/automation') return 'Открыть Автоматизацию';
    if (target.focus_mode === 'filter') return 'Открыть операции';
    if (Array.isArray(target.row_ids) && target.row_ids.length > 1) return 'Показать операции';
    if (target.row_id) return 'Показать в таблице';
    return 'Открыть в таблице';
}

export function prettyJson(value: unknown): string {
    try {
        return JSON.stringify(value ?? {}, null, 2);
    } catch {
        return String(value ?? '');
    }
}
