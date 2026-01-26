/**
 * Logs Page - страница логов обработки чеков
 */
import { useState, useEffect, useCallback } from 'react';
import { AlertCircle, CheckCircle2, Clock, Copy, RefreshCw, Search, Filter, ChevronLeft, ChevronRight } from 'lucide-react';

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
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                        {loading ? (
                            <tr>
                                <td colSpan={6} className="px-4 py-8 text-center text-foreground-secondary">
                                    <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2" />
                                    Загрузка...
                                </td>
                            </tr>
                        ) : logs.length === 0 ? (
                            <tr>
                                <td colSpan={6} className="px-4 py-8 text-center text-foreground-secondary">
                                    Нет данных для отображения
                                </td>
                            </tr>
                        ) : (
                            logs.map((log) => (
                                <tr key={log.id} className="hover:bg-surface-2/50 transition-colors">
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
                                        {log.amount ? `${Number(log.amount).toLocaleString()} UZS` : '—'}
                                    </td>
                                    <td className="px-4 py-3 text-sm text-error max-w-[300px] truncate" title={log.error || ''}>
                                        {log.error || '—'}
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
        </div>
    );
};
