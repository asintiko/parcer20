/**
 * Logs Page - страница логов обработки чеков
 * С автообновлением и детальным просмотром записей
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { AlertCircle, CheckCircle2, Clock, Copy, RefreshCw, Search, Filter, ChevronLeft, ChevronRight, X, Play, Pause, Eye } from 'lucide-react';

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

const API_BASE = (import.meta as any).env?.VITE_API_URL || 'http://localhost:8000';
const AUTO_REFRESH_INTERVAL = 10000; // 10 seconds

export const LogsPage = () => {
    const [logs, setLogs] = useState<LogEntry[]>([]);
    const [stats, setStats] = useState<LogStats | null>(null);
    const [loading, setLoading] = useState(true);
    const [page, setPage] = useState(1);
    const [total, setTotal] = useState(0);
    const [pageSize] = useState(50);
    const [statusFilter, setStatusFilter] = useState<string>('');
    const [searchQuery, setSearchQuery] = useState('');
    const [duplicatesOnly, setDuplicatesOnly] = useState(false);
    const [autoRefresh, setAutoRefresh] = useState(false);
    const [selectedLog, setSelectedLog] = useState<LogEntry | null>(null);
    const autoRefreshRef = useRef<ReturnType<typeof setInterval> | null>(null);

    const getAuthHeaders = () => {
        const token = localStorage.getItem('token');
        return {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
        };
    };

    const fetchStats = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/api/logs/stats`, {
                headers: getAuthHeaders(),
            });
            if (res.ok) {
                const data = await res.json();
                setStats(data);
            }
        } catch (err) {
            console.error('Failed to fetch stats:', err);
        }
    }, []);

    const fetchLogs = useCallback(async () => {
        setLoading(true);
        try {
            const params = new URLSearchParams({
                page: String(page),
                page_size: String(pageSize),
            });
            if (statusFilter) params.append('status', statusFilter);
            if (searchQuery) params.append('search', searchQuery);
            if (duplicatesOnly) params.append('duplicates_only', 'true');

            const res = await fetch(`${API_BASE}/api/logs?${params}`, {
                headers: getAuthHeaders(),
            });
            if (res.ok) {
                const data: LogsResponse = await res.json();
                setLogs(data.items);
                setTotal(data.total);
            }
        } catch (err) {
            console.error('Failed to fetch logs:', err);
        } finally {
            setLoading(false);
        }
    }, [page, pageSize, statusFilter, searchQuery, duplicatesOnly]);

    // Auto-refresh effect
    useEffect(() => {
        if (autoRefresh && !selectedLog) {
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
            if (autoRefreshRef.current) {
                clearInterval(autoRefreshRef.current);
            }
        };
    }, [autoRefresh, selectedLog, fetchLogs, fetchStats]);

    useEffect(() => {
        fetchStats();
    }, [fetchStats]);

    useEffect(() => {
        fetchLogs();
    }, [fetchLogs]);

    const totalPages = Math.ceil(total / pageSize);

    const getStatusIcon = (status: string, isDuplicate: boolean) => {
        if (isDuplicate) {
            return <Copy className="w-4 h-4 text-warning" />;
        }
        switch (status) {
            case 'done':
                return <CheckCircle2 className="w-4 h-4 text-success" />;
            case 'failed':
                return <AlertCircle className="w-4 h-4 text-error" />;
            case 'processing':
            case 'queued':
                return <Clock className="w-4 h-4 text-primary animate-pulse" />;
            default:
                return <Clock className="w-4 h-4 text-foreground-secondary" />;
        }
    };

    const getStatusBadge = (status: string, isDuplicate: boolean) => {
        if (isDuplicate) {
            return (
                <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-warning/10 text-warning border border-warning/20">
                    {getStatusIcon(status, isDuplicate)}
                    Дубликат
                </span>
            );
        }
        const styles: Record<string, string> = {
            done: 'bg-success/10 text-success border-success/20',
            failed: 'bg-error/10 text-error border-error/20',
            processing: 'bg-primary/10 text-primary border-primary/20',
            queued: 'bg-foreground-secondary/10 text-foreground-secondary border-foreground-secondary/20',
        };
        const labels: Record<string, string> = {
            done: 'Успешно',
            failed: 'Ошибка',
            processing: 'В процессе',
            queued: 'В очереди',
        };
        return (
            <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border ${styles[status] || styles.queued}`}>
                {getStatusIcon(status, isDuplicate)}
                {labels[status] || status}
            </span>
        );
    };

    const formatDate = (dateStr: string) => {
        const date = new Date(dateStr);
        return date.toLocaleString('ru-RU', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });
    };

    return (
        <div className="h-full flex flex-col bg-bg">
            {/* Stats Cards */}
            <div className="p-4 border-b border-border">
                <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                    <div className="bg-surface rounded-xl p-4 border border-border">
                        <div className="text-2xl font-bold text-foreground">{stats?.total || 0}</div>
                        <div className="text-sm text-foreground-secondary">Всего</div>
                    </div>
                    <div className="bg-surface rounded-xl p-4 border border-success/20">
                        <div className="text-2xl font-bold text-success">{stats?.success || 0}</div>
                        <div className="text-sm text-foreground-secondary">Успешно</div>
                    </div>
                    <div className="bg-surface rounded-xl p-4 border border-error/20">
                        <div className="text-2xl font-bold text-error">{stats?.failed || 0}</div>
                        <div className="text-sm text-foreground-secondary">Ошибок</div>
                    </div>
                    <div className="bg-surface rounded-xl p-4 border border-warning/20">
                        <div className="text-2xl font-bold text-warning">{stats?.duplicates || 0}</div>
                        <div className="text-sm text-foreground-secondary">Дубликатов</div>
                    </div>
                    <div className="bg-surface rounded-xl p-4 border border-primary/20">
                        <div className="text-2xl font-bold text-primary">{stats?.processing || 0}</div>
                        <div className="text-sm text-foreground-secondary">В процессе</div>
                    </div>
                </div>
            </div>

            {/* Filters */}
            <div className="p-4 border-b border-border flex flex-wrap gap-3 items-center">
                <div className="relative flex-1 min-w-[200px] max-w-md">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-foreground-secondary" />
                    <input
                        type="text"
                        placeholder="Поиск по ошибке..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        className="w-full pl-10 pr-4 py-2 bg-surface border border-border rounded-lg text-foreground placeholder:text-foreground-secondary focus:outline-none focus:ring-2 focus:ring-primary/50"
                    />
                </div>

                <div className="flex items-center gap-2">
                    <Filter className="w-4 h-4 text-foreground-secondary" />
                    <select
                        value={statusFilter}
                        onChange={(e) => setStatusFilter(e.target.value)}
                        className="bg-surface border border-border rounded-lg px-3 py-2 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
                    >
                        <option value="">Все статусы</option>
                        <option value="done">Успешно</option>
                        <option value="failed">Ошибка</option>
                        <option value="processing">В процессе</option>
                        <option value="queued">В очереди</option>
                    </select>
                </div>

                <label className="flex items-center gap-2 cursor-pointer">
                    <input
                        type="checkbox"
                        checked={duplicatesOnly}
                        onChange={(e) => setDuplicatesOnly(e.target.checked)}
                        className="w-4 h-4 rounded border-border text-primary focus:ring-primary/50"
                    />
                    <span className="text-sm text-foreground">Только дубликаты</span>
                </label>

                {/* Auto-refresh toggle */}
                <button
                    onClick={() => setAutoRefresh(!autoRefresh)}
                    className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
                        autoRefresh
                            ? 'bg-success/20 text-success border border-success/30'
                            : 'bg-surface border border-border text-foreground hover:bg-surface-2'
                    }`}
                    title={autoRefresh ? 'Остановить автообновление' : 'Включить автообновление (10 сек)'}
                >
                    {autoRefresh ? (
                        <>
                            <Pause className="w-4 h-4" />
                            <span className="text-sm">Авто</span>
                            <span className="w-2 h-2 rounded-full bg-success animate-pulse" />
                        </>
                    ) : (
                        <>
                            <Play className="w-4 h-4" />
                            <span className="text-sm">Авто</span>
                        </>
                    )}
                </button>

                <button
                    onClick={() => { fetchLogs(); fetchStats(); }}
                    className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
                >
                    <RefreshCw className="w-4 h-4" />
                    Обновить
                </button>
            </div>

            {/* Table */}
            <div className="flex-1 overflow-auto">
                <table className="w-full">
                    <thead className="bg-surface-2 sticky top-0">
                        <tr>
                            <th className="px-4 py-3 text-left text-xs font-medium text-foreground-secondary uppercase tracking-wider">Дата</th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-foreground-secondary uppercase tracking-wider">Чат / Сообщение</th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-foreground-secondary uppercase tracking-wider">Статус</th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-foreground-secondary uppercase tracking-wider">Оператор</th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-foreground-secondary uppercase tracking-wider">Сумма</th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-foreground-secondary uppercase tracking-wider">Ошибка</th>
                            <th className="px-4 py-3 text-center text-xs font-medium text-foreground-secondary uppercase tracking-wider w-16">
                                <span className="sr-only">Действия</span>
                            </th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                        {loading ? (
                            <tr>
                                <td colSpan={7} className="px-4 py-8 text-center text-foreground-secondary">
                                    <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2" />
                                    Загрузка...
                                </td>
                            </tr>
                        ) : logs.length === 0 ? (
                            <tr>
                                <td colSpan={7} className="px-4 py-8 text-center text-foreground-secondary">
                                    Нет данных для отображения
                                </td>
                            </tr>
                        ) : (
                            logs.map((log) => (
                                <tr
                                    key={log.id}
                                    className="hover:bg-surface-2/50 transition-colors cursor-pointer"
                                    onClick={() => setSelectedLog(log)}
                                >
                                    <td className="px-4 py-3 text-sm text-foreground whitespace-nowrap">
                                        {formatDate(log.created_at)}
                                    </td>
                                    <td className="px-4 py-3 text-sm text-foreground-secondary">
                                        <div className="font-mono text-xs">
                                            {log.chat_id} / {log.message_id}
                                        </div>
                                    </td>
                                    <td className="px-4 py-3">
                                        {getStatusBadge(log.status, log.is_duplicate)}
                                    </td>
                                    <td className="px-4 py-3 text-sm text-foreground max-w-[200px] truncate" title={log.operator_raw || ''}>
                                        {log.operator_raw || '—'}
                                    </td>
                                    <td className="px-4 py-3 text-sm text-foreground whitespace-nowrap">
                                        {log.amount ? `${Number(log.amount).toLocaleString()} ${log.currency || 'UZS'}` : '—'}
                                    </td>
                                    <td className="px-4 py-3 text-sm text-error max-w-[300px] truncate" title={log.error || ''}>
                                        {log.error || '—'}
                                    </td>
                                    <td className="px-4 py-3 text-center">
                                        <button
                                            type="button"
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                setSelectedLog(log);
                                            }}
                                            className="p-1.5 rounded-lg hover:bg-surface-2 text-foreground-secondary hover:text-foreground transition-colors"
                                            title="Подробнее"
                                        >
                                            <Eye className="w-4 h-4" />
                                        </button>
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
                <div className="p-4 border-t border-border flex items-center justify-between">
                    <div className="text-sm text-foreground-secondary">
                        Показано {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} из {total}
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => setPage((p) => Math.max(1, p - 1))}
                            disabled={page === 1}
                            className="p-2 rounded-lg border border-border hover:bg-surface-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                            <ChevronLeft className="w-4 h-4" />
                        </button>
                        <span className="px-4 py-2 text-sm text-foreground">
                            {page} / {totalPages}
                        </span>
                        <button
                            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                            disabled={page === totalPages}
                            className="p-2 rounded-lg border border-border hover:bg-surface-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                            <ChevronRight className="w-4 h-4" />
                        </button>
                    </div>
                </div>
            )}

            {/* Detail Modal */}
            {selectedLog && (
                <LogDetailModal log={selectedLog} onClose={() => setSelectedLog(null)} />
            )}
        </div>
    );
};

// Detail Modal Component
const LogDetailModal: React.FC<{ log: LogEntry; onClose: () => void }> = ({ log, onClose }) => {
    const formatDate = (dateStr: string | null) => {
        if (!dateStr) return '—';
        const date = new Date(dateStr);
        return date.toLocaleString('ru-RU', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
        });
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
            <div className="bg-surface w-full max-w-2xl max-h-[90vh] rounded-lg border border-border shadow-xl flex flex-col">
                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-border">
                    <h3 className="text-lg font-semibold text-foreground">
                        Детали записи #{log.id}
                    </h3>
                    <button
                        type="button"
                        onClick={onClose}
                        className="p-2 rounded-lg hover:bg-surface-2 text-foreground-secondary hover:text-foreground transition-colors"
                        title="Закрыть"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>

                {/* Content */}
                <div className="flex-1 overflow-auto p-6 space-y-4">
                    {/* Info Grid */}
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="text-xs text-foreground-secondary uppercase tracking-wider">Task ID</label>
                            <div className="font-mono text-sm text-foreground mt-1">{log.task_id}</div>
                        </div>
                        <div>
                            <label className="text-xs text-foreground-secondary uppercase tracking-wider">Статус</label>
                            <div className="mt-1">
                                {log.is_duplicate ? (
                                    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-warning/10 text-warning border border-warning/20">
                                        <Copy className="w-3 h-3" />
                                        Дубликат
                                    </span>
                                ) : (
                                    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border ${
                                        log.status === 'done' ? 'bg-success/10 text-success border-success/20' :
                                        log.status === 'failed' ? 'bg-error/10 text-error border-error/20' :
                                        'bg-primary/10 text-primary border-primary/20'
                                    }`}>
                                        {log.status === 'done' && <CheckCircle2 className="w-3 h-3" />}
                                        {log.status === 'failed' && <AlertCircle className="w-3 h-3" />}
                                        {['processing', 'queued'].includes(log.status) && <Clock className="w-3 h-3" />}
                                        {log.status}
                                    </span>
                                )}
                            </div>
                        </div>
                        <div>
                            <label className="text-xs text-foreground-secondary uppercase tracking-wider">Chat ID</label>
                            <div className="font-mono text-sm text-foreground mt-1">{log.chat_id}</div>
                        </div>
                        <div>
                            <label className="text-xs text-foreground-secondary uppercase tracking-wider">Message ID</label>
                            <div className="font-mono text-sm text-foreground mt-1">{log.message_id}</div>
                        </div>
                        <div>
                            <label className="text-xs text-foreground-secondary uppercase tracking-wider">Transaction ID</label>
                            <div className="font-mono text-sm text-foreground mt-1">{log.transaction_id || '—'}</div>
                        </div>
                        <div>
                            <label className="text-xs text-foreground-secondary uppercase tracking-wider">Fingerprint</label>
                            <div className="font-mono text-xs text-foreground mt-1 truncate" title={log.fingerprint || ''}>
                                {log.fingerprint ? log.fingerprint.substring(0, 16) + '...' : '—'}
                            </div>
                        </div>
                        <div>
                            <label className="text-xs text-foreground-secondary uppercase tracking-wider">Создано</label>
                            <div className="text-sm text-foreground mt-1">{formatDate(log.created_at)}</div>
                        </div>
                        <div>
                            <label className="text-xs text-foreground-secondary uppercase tracking-wider">Обновлено</label>
                            <div className="text-sm text-foreground mt-1">{formatDate(log.updated_at)}</div>
                        </div>
                        <div>
                            <label className="text-xs text-foreground-secondary uppercase tracking-wider">Оператор</label>
                            <div className="text-sm text-foreground mt-1">{log.operator_raw || '—'}</div>
                        </div>
                        <div>
                            <label className="text-xs text-foreground-secondary uppercase tracking-wider">Сумма</label>
                            <div className="text-sm text-foreground mt-1">
                                {log.amount ? `${Number(log.amount).toLocaleString()} ${log.currency || 'UZS'}` : '—'}
                            </div>
                        </div>
                    </div>

                    {/* Error */}
                    {log.error && (
                        <div>
                            <label className="text-xs text-foreground-secondary uppercase tracking-wider">Ошибка</label>
                            <div className="mt-2 p-3 bg-error/10 border border-error/20 rounded-lg">
                                <pre className="text-sm text-error whitespace-pre-wrap font-mono">{log.error}</pre>
                            </div>
                        </div>
                    )}

                    {/* Raw Message */}
                    {log.raw_message && (
                        <div>
                            <label className="text-xs text-foreground-secondary uppercase tracking-wider">Исходное сообщение</label>
                            <div className="mt-2 p-3 bg-surface-2 border border-border rounded-lg max-h-[200px] overflow-auto">
                                <pre className="text-sm text-foreground whitespace-pre-wrap font-mono">{log.raw_message}</pre>
                            </div>
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="flex justify-end px-6 py-4 border-t border-border bg-surface-2">
                    <button
                        type="button"
                        onClick={onClose}
                        className="px-4 py-2 rounded-lg bg-primary text-white hover:bg-primary/90 transition-colors"
                    >
                        Закрыть
                    </button>
                </div>
            </div>
        </div>
    );
};
