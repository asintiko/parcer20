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
    verify_receipt_parse: 'Сверка чека',
    auto_describe_operators: 'Описание операторов',
    set_operator_description: 'Запись описания',
    list_operator_descriptions: 'Список описаний',
    rollback_operator_descriptions: 'Откат описаний',
};

const TOOL_PURPOSE: Record<string, string> = {
    transaction_analytics: 'Считаю сводку по транзакциям',
    app_mapping: 'Сопоставляю операторов с приложениями',
    data_verification: 'Проверяю корректность данных',
    bot_reconciliation: 'Сверяю транзакции с Telegram',
    table_search_and_navigate: 'Ищу нужные строки и готовлю переход',
    db_inspector: 'Смотрю состояние системы',
    duplicate_detector: 'Ищу повторяющиеся операции',
    processing_errors_analyzer: 'Разбираю ошибки обработки чеков',
    source_health_check: 'Проверяю состояние источников',
    monitored_chat_sync_audit: 'Сверяю чеки из мониторинга',
    telegram_cache_search: 'Ищу сообщения в кеше Telegram',
    message_to_transaction_trace: 'Прослеживаю путь от сообщения к транзакции',
    failed_receipt_investigator: 'Разбираюсь, почему чек не обработался',
    duplicate_merge_preview: 'Готовлю кандидатов на объединение',
    receipt_reparse_preview: 'Перепроверяю распознавание чека',
    monitor_config_inspector: 'Смотрю настройки мониторинга',
    report_publish_tool: 'Публикую готовый отчет',
    report_builder: 'Собираю отчет по данным',
    fix_plan_builder: 'Составляю план исправлений',
    verify_receipt_parse: 'Сверяю распознанный чек с исходным сообщением',
    auto_describe_operators: 'Ищу в интернете и подписываю операторов',
    set_operator_description: 'Записываю описание оператора',
    list_operator_descriptions: 'Собираю список описаний операторов',
    rollback_operator_descriptions: 'Откатываю записанные описания',
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

export function formatToolPurpose(toolName?: string | null): string {
    if (!toolName) return '';
    return TOOL_PURPOSE[toolName] || '';
}

export function formatRunStatus(status?: string | null): string {
    if (!status) return 'Выполняется';
    return STATUS_LABELS[status] || status;
}

const WEB_READING_PREFIX = '🌐 Читаю в интернете';

/** True when a payload describes the live "reading the web" step. */
export function isWebSearchPayload(
    payload?: Record<string, any> | null,
    label?: string | null,
): boolean {
    if (payload && typeof payload === 'object') {
        const step = String(payload.step || '').trim().toLowerCase();
        if (step === 'web_search') return true;
    }
    if (typeof label === 'string' && label.trim().startsWith('🌐')) return true;
    return false;
}

/** Live "🌐 Читаю в интернете: <operator>" line, operator drawn from payload. */
export function formatWebSearchLabel(payload?: Record<string, any> | null): string {
    const operator =
        payload && typeof payload === 'object'
            ? String(payload.operator || payload.query || payload.term || '').trim()
            : '';
    return operator ? `${WEB_READING_PREFIX}: ${operator}` : `${WEB_READING_PREFIX}…`;
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
    if (normalized === 'web_search') return `${WEB_READING_PREFIX}…`;
    if (normalized === 'describe_operator') return 'Подписываю оператора';
    if (normalized === 'write_description') return 'Записываю описание';
    return formatToolLabel(toolName);
}

export function formatRunEventLabel(
    eventType?: string | null,
    label?: string | null,
    toolName?: string | null,
    payload?: Record<string, any> | null,
): string {
    const normalized = String(eventType || '').trim().toLowerCase();
    if (isWebSearchPayload(payload, label)) {
        return label && label.trim().startsWith('🌐') ? label : formatWebSearchLabel(payload);
    }
    if (normalized === 'planning_started') return 'Понимаю запрос';
    if (normalized === 'tool_selected') return label || `Выбран инструмент: ${formatToolLabel(toolName)}`;
    if (normalized === 'tool_started') return label || `Запускаю: ${formatToolLabel(toolName)}`;
    if (normalized === 'tool_progress') {
        if (label) return label;
        if (toolName === 'monitored_chat_sync_audit') return 'Сверяю чеки';
        if (toolName === 'auto_describe_operators') return 'Подписываю операторов';
        return 'Проверяю данные';
    }
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
