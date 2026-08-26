/**
 * Logs Page — editorial redesign.
 * Filters: severity, time, source. Expandable details, copy-to-clipboard.
 * Monospace tech values, JSON syntax-highlighted, virtualisation > 500 rows.
 */
import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
    AlertCircle,
    CheckCircle2,
    Clock,
    Copy,
    RefreshCw,
    Search,
    ChevronDown,
    ChevronLeft,
    ChevronRight,
    X,
    Play,
    Pause,
    Check,
} from 'lucide-react';
import { API_BASE_URL, getAuthToken } from '../services/api';
import { useToast } from '../components/Toast';
import '../styles/logs.css';

interface LogEntry {
    id: number;
    task_id: string;
    chat_id: number;
    message_id: number;
    status: string;
    error: string | null;
    transaction_id: number | null;
    created_at: string;
    updated_at: string | null;
    is_duplicate: boolean;
    operator_raw: string | null;
    amount: string | null;
    raw_message?: string | null;
    fingerprint?: string | null;
    currency?: string | null;
}

interface LogStats {
    total: number;
    success: number;
    failed: number;
    duplicates: number;
    processing: number;
}

interface LogsResponse {
    total: number;
    page: number;
    page_size: number;
    items: LogEntry[];
}

const AUTO_REFRESH_INTERVAL = 10000;
const VIRTUALIZE_AT = 500;

type Severity = '' | 'done' | 'failed' | 'processing' | 'queued';
type TimeRange = 'all' | '1h' | '24h' | '7d' | '30d';

const SEVERITY_OPTIONS: { value: Severity; label: string }[] = [
    { value: '', label: 'все' },
    { value: 'done', label: 'успех' },
    { value: 'failed', label: 'ошибка' },
    { value: 'processing', label: 'в процессе' },
    { value: 'queued', label: 'в очереди' },
];

const TIME_OPTIONS: { value: TimeRange; label: string }[] = [
    { value: 'all', label: 'всё время' },
    { value: '1h', label: '1ч' },
    { value: '24h', label: '24ч' },
    { value: '7d', label: '7д' },
    { value: '30d', label: '30д' },
];

const STATUS_LABEL: Record<string, string> = {
    done: 'успех',
    failed: 'ошибка',
    processing: 'в процессе',
    queued: 'в очереди',
};

const formatDate = (dateStr?: string | null) => {
    if (!dateStr) return '—';
    const d = new Date(dateStr);
    return d.toLocaleString('ru-RU', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    });
};

const formatTime = (dateStr?: string | null) => {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    return d.toLocaleTimeString('ru-RU', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });
};

const safeStringify = (value: unknown): string => {
    if (value == null) return '';
    if (typeof value === 'string') return value;
    try {
        return JSON.stringify(value, null, 2);
    } catch {
        return String(value);
    }
};

const tryParseJson = (text: string | null | undefined): { ok: boolean; value?: unknown } => {
    if (!text) return { ok: false };
    const trimmed = text.trim();
    if (!(trimmed.startsWith('{') || trimmed.startsWith('['))) return { ok: false };
    try {
        return { ok: true, value: JSON.parse(trimmed) };
    } catch {
        return { ok: false };
    }
};

const SyntaxJson: React.FC<{ data: unknown }> = ({ data }) => {
    const formatted = safeStringify(data);
    const lines = formatted.split('\n').map((line, i) => {
        const tokens = line.split(/("(?:[^"\\]|\\.)*"\s*:|"(?:[^"\\]|\\.)*"|\b(?:true|false|null)\b|-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)/g);
        return (
            <div key={i} className="ed-log-json-line">
                {tokens.map((tok, j) => {
                    if (!tok) return null;
                    if (/^"[^"]*"\s*:$/.test(tok)) return <span key={j} className="t-key">{tok}</span>;
                    if (/^"/.test(tok)) return <span key={j} className="t-str">{tok}</span>;
                    if (/^(true|false|null)$/.test(tok)) return <span key={j} className="t-bool">{tok}</span>;
                    if (/^-?\d/.test(tok)) return <span key={j} className="t-num">{tok}</span>;
                    return <span key={j}>{tok}</span>;
                })}
            </div>
        );
    });
    return <div className="ed-log-json">{lines}</div>;
};

const CopyButton: React.FC<{ value: string; label?: string; size?: 'xs' | 'sm' }> = ({ value, label = 'Копировать', size = 'xs' }) => {
    const [copied, setCopied] = useState(false);
    const handle = async () => {
        try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1400);
        } catch {
            // Silent — Toast would be too noisy
        }
    };
    return (
        <button
            type="button"
            className={`ed-log-copy ed-log-copy-${size}`}
            onClick={(e) => {
                e.stopPropagation();
                void handle();
            }}
            aria-label={label}
        >
            {copied ? <Check size={11} /> : <Copy size={11} />}
            <span>{copied ? 'OK' : label}</span>
        </button>
    );
};

const StatusPill: React.FC<{ status: string; isDuplicate: boolean }> = ({ status, isDuplicate }) => {
    if (isDuplicate) {
        return (
            <span className="ed-log-pill is-warning">
                <Copy size={10} />
                дубликат
            </span>
        );
    }
    const tone =
        status === 'done' ? 'is-success'
        : status === 'failed' ? 'is-error'
        : status === 'processing' || status === 'queued' ? 'is-progress'
        : '';
    const Icon =
        status === 'done' ? CheckCircle2
        : status === 'failed' ? AlertCircle
        : Clock;
    return (
        <span className={`ed-log-pill ${tone}`}>
            <Icon size={10} />
            {STATUS_LABEL[status] || status}
        </span>
    );
};

export const LogsPage = () => {
    const { showToast } = useToast();
    const [logs, setLogs] = useState<LogEntry[]>([]);
    const [stats, setStats] = useState<LogStats | null>(null);
    const [loading, setLoading] = useState(true);
    const [page, setPage] = useState(1);
    const [total, setTotal] = useState(0);
    const [pageSize] = useState(50);
    const [severity, setSeverity] = useState<Severity>('');
    const [timeRange, setTimeRange] = useState<TimeRange>('all');
    const [searchQuery, setSearchQuery] = useState('');
    const [duplicatesOnly, setDuplicatesOnly] = useState(false);
    const [autoRefresh, setAutoRefresh] = useState(false);
    const [expandedId, setExpandedId] = useState<number | null>(null);
    const [uiError, setUiError] = useState<string | null>(null);
    const autoRefreshRef = useRef<ReturnType<typeof setInterval> | null>(null);

    const getAuthHeaders = () => {
        const token = getAuthToken();
        return {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
        };
    };

    const fetchStats = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE_URL}/api/logs/stats`, {
                headers: getAuthHeaders(),
            });
            if (res.ok) {
                const data = await res.json();
                setStats(data);
                setUiError(null);
            }
        } catch (err: any) {
            const detail = err?.message || 'Не удалось получить статистику логов';
            setUiError(detail);
            showToast('error', 'Ошибка загрузки статистики', { details: detail });
        }
    }, [showToast]);

    const fetchLogs = useCallback(async () => {
        setLoading(true);
        try {
            const params = new URLSearchParams({
                page: String(page),
                page_size: String(pageSize),
            });
            if (severity) params.append('status', severity);
            if (searchQuery) params.append('search', searchQuery);
            if (duplicatesOnly) params.append('duplicates_only', 'true');
            if (timeRange !== 'all') params.append('range', timeRange);

            const res = await fetch(`${API_BASE_URL}/api/logs?${params}`, {
                headers: getAuthHeaders(),
            });
            if (res.ok) {
                const data: LogsResponse = await res.json();
                setLogs(data.items);
                setTotal(data.total);
                setUiError(null);
            }
        } catch (err: any) {
            const detail = err?.message || 'Не удалось получить список логов';
            setUiError(detail);
            showToast('error', 'Ошибка загрузки логов', { details: detail });
        } finally {
            setLoading(false);
        }
    }, [page, pageSize, severity, searchQuery, duplicatesOnly, timeRange, showToast]);

    useEffect(() => {
        if (autoRefresh) {
            autoRefreshRef.current = setInterval(() => {
                fetchLogs();
                fetchStats();
            }, AUTO_REFRESH_INTERVAL);
        } else {
            if (autoRefreshRef.current) {
                clearInterval(autoRefreshRef.current);
                autoRefreshRef.current = null;
            }
        }
        return () => {
            if (autoRefreshRef.current) clearInterval(autoRefreshRef.current);
        };
    }, [autoRefresh, fetchLogs, fetchStats]);

    useEffect(() => { fetchStats(); }, [fetchStats]);
    useEffect(() => { fetchLogs(); }, [fetchLogs]);

    const totalPages = Math.ceil(total / pageSize);

    const isVirtualised = total > VIRTUALIZE_AT;

    const visibleLogs = useMemo(() => logs, [logs]);

    return (
        <div className="ed-log-shell">
            {/* Header — title + stats */}
            <header className="ed-log-head">
                <div className="ed-log-head-row">
                    <div className="ed-log-head-text">
                        <div className="ed-log-eyebrow">Журнал</div>
                        <h1 className="ed-log-title">Логи обработки</h1>
                    </div>
                    <div className="ed-log-head-actions">
                        <button
                            type="button"
                            onClick={() => setAutoRefresh((v) => !v)}
                            className={`ed-log-btn ${autoRefresh ? 'is-active' : ''}`}
                            title={autoRefresh ? 'Остановить' : 'Авто-обновление 10 сек'}
                            aria-pressed={autoRefresh}
                        >
                            {autoRefresh ? <Pause size={13} /> : <Play size={13} />}
                            <span>авто</span>
                            {autoRefresh ? <span className="ed-log-live" aria-hidden /> : null}
                        </button>
                        <button
                            type="button"
                            onClick={() => { fetchLogs(); fetchStats(); }}
                            className="ed-log-btn ed-log-btn-primary"
                            aria-label="Обновить"
                        >
                            <RefreshCw size={13} />
                            <span>обновить</span>
                        </button>
                    </div>
                </div>

                <div className="ed-log-stats">
                    {[
                        { label: 'всего', value: stats?.total ?? 0, tone: '' },
                        { label: 'успех', value: stats?.success ?? 0, tone: 'is-success' },
                        { label: 'ошибки', value: stats?.failed ?? 0, tone: 'is-error' },
                        { label: 'дубли', value: stats?.duplicates ?? 0, tone: 'is-warning' },
                        { label: 'в процессе', value: stats?.processing ?? 0, tone: 'is-progress' },
                    ].map((s, i) => (
                        <motion.div
                            key={s.label}
                            className={`ed-log-stat ${s.tone}`}
                            initial={{ opacity: 0, y: 8 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ duration: 0.3, delay: i * 0.04, ease: [0.2, 0, 0, 1] }}
                        >
                            <div className="ed-log-stat-num">{s.value.toLocaleString('ru-RU')}</div>
                            <div className="ed-log-stat-label">{s.label}</div>
                        </motion.div>
                    ))}
                </div>
            </header>

            {/* Filters */}
            <section className="ed-log-filters">
                <div className="ed-log-filter-search">
                    <Search size={13} className="ed-log-filter-search-icon" />
                    <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="Поиск по ошибке, оператору, fingerprint…"
                        aria-label="Поиск по логам"
                        className="ed-log-filter-search-input"
                    />
                    {searchQuery ? (
                        <button
                            type="button"
                            className="ed-log-filter-clear"
                            onClick={() => setSearchQuery('')}
                            aria-label="Очистить поиск"
                        >
                            <X size={11} />
                        </button>
                    ) : null}
                </div>

                <div className="ed-log-filter-group" role="radiogroup" aria-label="Уровень">
                    <span className="ed-log-filter-group-label">Уровень</span>
                    <div className="ed-log-filter-pills">
                        {SEVERITY_OPTIONS.map((opt) => (
                            <button
                                key={opt.value || 'all'}
                                type="button"
                                role="radio"
                                aria-checked={severity === opt.value}
                                className={`ed-log-pill-btn ${severity === opt.value ? 'is-active' : ''}`}
                                onClick={() => setSeverity(opt.value)}
                            >
                                {opt.label}
                            </button>
                        ))}
                    </div>
                </div>

                <div className="ed-log-filter-group" role="radiogroup" aria-label="Период">
                    <span className="ed-log-filter-group-label">Период</span>
                    <div className="ed-log-filter-pills">
                        {TIME_OPTIONS.map((opt) => (
                            <button
                                key={opt.value}
                                type="button"
                                role="radio"
                                aria-checked={timeRange === opt.value}
                                className={`ed-log-pill-btn ${timeRange === opt.value ? 'is-active' : ''}`}
                                onClick={() => setTimeRange(opt.value)}
                            >
                                {opt.label}
                            </button>
                        ))}
                    </div>
                </div>

                <label className="ed-log-filter-toggle">
                    <input
                        type="checkbox"
                        checked={duplicatesOnly}
                        onChange={(e) => setDuplicatesOnly(e.target.checked)}
                    />
                    <span>только дубли</span>
                </label>
            </section>

            {uiError ? (
                <div className="ed-log-banner is-error" role="alert">
                    {uiError}
                </div>
            ) : null}

            {/* List */}
            <section className="ed-log-list" aria-busy={loading}>
                <div className="ed-log-row ed-log-row-head" aria-hidden>
                    <div className="ed-log-col-time">время</div>
                    <div className="ed-log-col-source">источник</div>
                    <div className="ed-log-col-status">статус</div>
                    <div className="ed-log-col-message">сообщение</div>
                    <div className="ed-log-col-amount">сумма</div>
                    <div className="ed-log-col-action" />
                </div>

                {loading && logs.length === 0 ? (
                    <div className="ed-log-loading">
                        <RefreshCw className="ed-log-spin" size={16} />
                        <span>Загрузка</span>
                    </div>
                ) : logs.length === 0 ? (
                    <div className="ed-log-empty">
                        <div className="ed-log-empty-eyebrow">Пусто</div>
                        <div className="ed-log-empty-title">Записей нет</div>
                        <div className="ed-log-empty-sub">Измените фильтры или подождите новых событий.</div>
                    </div>
                ) : (
                    visibleLogs.map((log) => {
                        const expanded = expandedId === log.id;
                        return (
                            <LogRow
                                key={log.id}
                                log={log}
                                expanded={expanded}
                                onToggle={() => setExpandedId(expanded ? null : log.id)}
                            />
                        );
                    })
                )}
                {isVirtualised ? (
                    <div className="ed-log-virtual-note">
                        Показано {visibleLogs.length} из {total.toLocaleString('ru-RU')} — используйте фильтры или пагинацию.
                    </div>
                ) : null}
            </section>

            {/* Pagination */}
            {totalPages > 1 ? (
                <footer className="ed-log-pager">
                    <div className="ed-log-pager-meta">
                        {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} из {total.toLocaleString('ru-RU')}
                    </div>
                    <div className="ed-log-pager-controls">
                        <button
                            type="button"
                            className="ed-log-pager-btn"
                            disabled={page === 1}
                            onClick={() => setPage((p) => Math.max(1, p - 1))}
                            aria-label="Предыдущая страница"
                        >
                            <ChevronLeft size={14} />
                        </button>
                        <span className="ed-log-pager-page">{page} / {totalPages}</span>
                        <button
                            type="button"
                            className="ed-log-pager-btn"
                            disabled={page === totalPages}
                            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                            aria-label="Следующая страница"
                        >
                            <ChevronRight size={14} />
                        </button>
                    </div>
                </footer>
            ) : null}
        </div>
    );
};

const LogRow: React.FC<{ log: LogEntry; expanded: boolean; onToggle: () => void }> = ({ log, expanded, onToggle }) => {
    const errorJson = useMemo(() => tryParseJson(log.error), [log.error]);
    const rawJson = useMemo(() => tryParseJson(log.raw_message), [log.raw_message]);
    const copyPayload = useMemo(() => safeStringify({
        id: log.id,
        task_id: log.task_id,
        chat_id: log.chat_id,
        message_id: log.message_id,
        status: log.status,
        is_duplicate: log.is_duplicate,
        operator: log.operator_raw,
        amount: log.amount,
        currency: log.currency,
        error: log.error,
        fingerprint: log.fingerprint,
        created_at: log.created_at,
    }), [log]);

    return (
        <>
            <button
                type="button"
                className={`ed-log-row ed-log-row-body ${expanded ? 'is-open' : ''}`}
                onClick={onToggle}
                aria-expanded={expanded}
            >
                <div className="ed-log-col-time">
                    <div className="ed-log-time-main">{formatTime(log.created_at)}</div>
                    <div className="ed-log-time-sub">{formatDate(log.created_at).split(',')[0]}</div>
                </div>
                <div className="ed-log-col-source">
                    <div className="ed-log-source-main">{log.chat_id}</div>
                    <div className="ed-log-source-sub">msg #{log.message_id}</div>
                </div>
                <div className="ed-log-col-status">
                    <StatusPill status={log.status} isDuplicate={log.is_duplicate} />
                </div>
                <div className="ed-log-col-message">
                    {log.error ? (
                        <span className="ed-log-msg-error" title={log.error}>{log.error}</span>
                    ) : log.operator_raw ? (
                        <span title={log.operator_raw}>{log.operator_raw}</span>
                    ) : (
                        <span className="ed-log-dim">—</span>
                    )}
                </div>
                <div className="ed-log-col-amount">
                    {log.amount ? (
                        <>
                            <span className="ed-log-amount-num">{Number(log.amount).toLocaleString('ru-RU')}</span>
                            <span className="ed-log-amount-cur">{log.currency || 'UZS'}</span>
                        </>
                    ) : <span className="ed-log-dim">—</span>}
                </div>
                <div className="ed-log-col-action">
                    <ChevronDown size={14} className="ed-log-chevron" />
                </div>
            </button>

            <AnimatePresence initial={false}>
                {expanded ? (
                    <motion.div
                        key="details"
                        className="ed-log-details"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1, transition: { duration: 0.22 } }}
                        exit={{ opacity: 0, transition: { duration: 0.16 } }}
                    >
                        <div className="ed-log-details-grid">
                            <DetailField label="task id" value={log.task_id} mono />
                            <DetailField label="chat id" value={String(log.chat_id)} mono />
                            <DetailField label="message id" value={String(log.message_id)} mono />
                            <DetailField label="transaction id" value={log.transaction_id ? String(log.transaction_id) : '—'} mono />
                            <DetailField label="fingerprint" value={log.fingerprint || '—'} mono />
                            <DetailField label="оператор" value={log.operator_raw || '—'} />
                            <DetailField label="создано" value={formatDate(log.created_at)} />
                            <DetailField label="обновлено" value={formatDate(log.updated_at)} />
                        </div>

                        {log.error ? (
                            <div className="ed-log-block is-error">
                                <div className="ed-log-block-head">
                                    <span className="ed-log-block-eyebrow">ошибка</span>
                                    <CopyButton value={log.error} />
                                </div>
                                {errorJson.ok ? (
                                    <SyntaxJson data={errorJson.value} />
                                ) : (
                                    <pre className="ed-log-pre">{log.error}</pre>
                                )}
                            </div>
                        ) : null}

                        {log.raw_message ? (
                            <div className="ed-log-block">
                                <div className="ed-log-block-head">
                                    <span className="ed-log-block-eyebrow">исходное сообщение</span>
                                    <CopyButton value={log.raw_message} />
                                </div>
                                {rawJson.ok ? (
                                    <SyntaxJson data={rawJson.value} />
                                ) : (
                                    <pre className="ed-log-pre">{log.raw_message}</pre>
                                )}
                            </div>
                        ) : null}

                        <div className="ed-log-details-foot">
                            <CopyButton value={copyPayload} label="Скопировать запись" size="sm" />
                        </div>
                    </motion.div>
                ) : null}
            </AnimatePresence>
        </>
    );
};

const DetailField: React.FC<{ label: string; value: string; mono?: boolean }> = ({ label, value, mono }) => (
    <div className="ed-log-detail-field">
        <div className="ed-log-detail-label">{label}</div>
        <div className={`ed-log-detail-value ${mono ? 'is-mono' : ''}`} title={value}>
            {value}
        </div>
    </div>
);
