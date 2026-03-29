import React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { sessionsApi } from '../services/api';

interface SessionsManagerProps {
    showToast: (type: 'success' | 'error' | 'info', message: string) => void;
}

const formatDate = (iso?: string | null): string => {
    if (!iso) return '—';
    try {
        const d = new Date(iso);
        return d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch {
        return iso;
    }
};

const TOKEN_KIND_LABELS: Record<string, string> = {
    access: 'Веб',
    app: 'Приложение',
    qr: 'QR-вход',
    telegram: 'Telegram',
};

export const SessionsManager: React.FC<SessionsManagerProps> = ({ showToast }) => {
    const queryClient = useQueryClient();

    const currentSessionId = sessionsApi.getCurrentSessionId();

    const sessionsQuery = useQuery({
        queryKey: ['admin-sessions'],
        queryFn: () => sessionsApi.list(),
        refetchInterval: 15_000,
    });

    const killMutation = useMutation({
        mutationFn: (sessionId: string) => sessionsApi.kill(sessionId),
        onSuccess: (_data, sessionId) => {
            showToast('success', `Сессия ${sessionId.slice(0, 8)}… завершена`);
            queryClient.invalidateQueries({ queryKey: ['admin-sessions'] });
        },
        onError: (err: any) => {
            showToast('error', err?.response?.data?.detail || 'Не удалось завершить сессию');
        },
    });

    const killAllMutation = useMutation({
        mutationFn: () => {
            if (!currentSessionId) throw new Error('Не удалось определить текущую сессию');
            return sessionsApi.killAllExceptCurrent(currentSessionId);
        },
        onSuccess: (data) => {
            showToast('success', `Завершено сессий: ${data.killed}`);
            queryClient.invalidateQueries({ queryKey: ['admin-sessions'] });
        },
        onError: (err: any) => {
            showToast('error', err?.response?.data?.detail || err?.message || 'Ошибка завершения сессий');
        },
    });

    const sessions = sessionsQuery.data || [];
    const otherSessionsCount = sessions.filter((s) => s.session_id !== currentSessionId).length;

    return (
        <section className="border border-border rounded-lg bg-surface p-4 space-y-3">
            <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-foreground">Активные сессии</h2>
                <div className="flex items-center gap-2">
                    {otherSessionsCount > 0 && (
                        <button
                            type="button"
                            onClick={() => killAllMutation.mutate()}
                            disabled={killAllMutation.isPending}
                            className="px-2 py-1 text-xs rounded border border-danger/40 text-danger hover:bg-danger/10 disabled:opacity-50"
                        >
                            {killAllMutation.isPending ? 'Завершаем...' : `Завершить все кроме текущей (${otherSessionsCount})`}
                        </button>
                    )}
                    <span className="text-xs text-foreground-muted">Авто-обновление: 15 сек</span>
                    <button
                        type="button"
                        onClick={() => queryClient.invalidateQueries({ queryKey: ['admin-sessions'] })}
                        disabled={sessionsQuery.isFetching}
                        className="px-2 py-1 text-xs rounded border border-border hover:bg-surface-2 disabled:opacity-50"
                    >
                        {sessionsQuery.isFetching ? 'Загрузка...' : 'Обновить'}
                    </button>
                </div>
            </div>

            {sessions.length === 0 ? (
                <div className="text-sm text-foreground-muted py-2">Нет активных сессий</div>
            ) : (
                <div className="overflow-auto border border-border rounded-md">
                    <table className="w-full text-sm">
                        <thead className="bg-surface-2">
                            <tr>
                                <th className="text-left px-3 py-2 whitespace-nowrap">ID сессии</th>
                                <th className="text-left px-3 py-2 whitespace-nowrap">Тип</th>
                                <th className="text-left px-3 py-2 whitespace-nowrap">Пользователь</th>
                                <th className="text-left px-3 py-2 whitespace-nowrap">IP</th>
                                <th className="text-left px-3 py-2 whitespace-nowrap">Создана</th>
                                <th className="text-left px-3 py-2 whitespace-nowrap">Активность</th>
                                <th className="text-left px-3 py-2 whitespace-nowrap">Истекает</th>
                                <th className="text-left px-3 py-2 whitespace-nowrap">Действие</th>
                            </tr>
                        </thead>
                        <tbody>
                            {sessions.map((s) => {
                                const isCurrent = s.session_id === currentSessionId;
                                return (
                                    <tr
                                        key={s.session_id}
                                        className={`border-t border-border align-top ${isCurrent ? 'bg-primary/5 ring-1 ring-inset ring-primary/20' : ''}`}
                                    >
                                        <td className="px-3 py-2 font-mono text-xs">
                                            {s.session_id.slice(0, 12)}…
                                            {isCurrent && (
                                                <span className="ml-1 px-1.5 py-0.5 rounded-full bg-primary/15 text-primary text-[10px] font-medium">
                                                    текущая
                                                </span>
                                            )}
                                        </td>
                                        <td className="px-3 py-2 text-xs">{TOKEN_KIND_LABELS[s.token_kind] || s.token_kind}</td>
                                        <td className="px-3 py-2 text-xs">
                                            {s.subject || '—'}
                                            {s.user_id ? ` (#${s.user_id})` : ''}
                                        </td>
                                        <td className="px-3 py-2 text-xs">{s.ip_address || '—'}</td>
                                        <td className="px-3 py-2 text-xs">{formatDate(s.created_at)}</td>
                                        <td className="px-3 py-2 text-xs">{formatDate(s.last_activity_at)}</td>
                                        <td className="px-3 py-2 text-xs">{formatDate(s.expires_at)}</td>
                                        <td className="px-3 py-2">
                                            {isCurrent ? (
                                                <span className="text-xs text-foreground-muted">—</span>
                                            ) : (
                                                <button
                                                    type="button"
                                                    onClick={() => killMutation.mutate(s.session_id)}
                                                    disabled={killMutation.isPending}
                                                    className="px-2 py-1 text-xs rounded border border-danger/40 text-danger hover:bg-danger/10 disabled:opacity-50"
                                                >
                                                    Завершить
                                                </button>
                                            )}
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            )}
        </section>
    );
};
