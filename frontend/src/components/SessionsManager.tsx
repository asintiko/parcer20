import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { RefreshCw, Power, Globe, Smartphone, QrCode, Send, Check, Info } from 'lucide-react';
import { sessionsApi, type ActiveSession } from '../services/api';
import { Dialog } from './motion/Dialog';

interface SessionsManagerProps {
    showToast: (type: 'success' | 'error' | 'info', message: string) => void;
}

const formatDate = (iso?: string | null): string => {
    if (!iso) return '—';
    try {
        const d = new Date(iso);
        return d.toLocaleString('ru-RU', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });
    } catch {
        return iso;
    }
};

const TOKEN_KIND_META: Record<
    string,
    { label: string; icon: React.ComponentType<any> }
> = {
    access: { label: 'Веб', icon: Globe },
    app: { label: 'Приложение', icon: Smartphone },
    qr: { label: 'QR-вход', icon: QrCode },
    telegram: { label: 'Telegram', icon: Send },
};

export const SessionsManager: React.FC<SessionsManagerProps> = ({ showToast }) => {
    const queryClient = useQueryClient();
    const currentSessionId = sessionsApi.getCurrentSessionId();
    const [detailFor, setDetailFor] = useState<ActiveSession | null>(null);

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
            showToast(
                'error',
                err?.response?.data?.detail || 'Не удалось завершить сессию',
            );
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
            showToast(
                'error',
                err?.response?.data?.detail || err?.message || 'Ошибка завершения сессий',
            );
        },
    });

    const sessions = sessionsQuery.data || [];
    const otherSessionsCount = sessions.filter((s) => s.session_id !== currentSessionId).length;

    return (
        <div className="sp-card">
            <div className="sp-card-head">
                <div>
                    <h2 className="sp-card-title">Активные сессии</h2>
                    <div className="sp-card-sub">
                        Все живые токены команды. Авто-обновление каждые 15с.
                        {sessions.length > 0 ? (
                            <> · всего <b>{sessions.length}</b>{otherSessionsCount > 0 ? <>, чужих <b>{otherSessionsCount}</b></> : null}</>
                        ) : null}
                    </div>
                </div>
                <div style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
                    {otherSessionsCount > 0 ? (
                        <button
                            type="button"
                            className="sp-btn sp-btn-sm sp-btn-danger"
                            onClick={() => killAllMutation.mutate()}
                            disabled={killAllMutation.isPending}
                        >
                            {killAllMutation.isPending ? (
                                <>
                                    <span className="sp-btn-spinner" />
                                    Завершаем
                                </>
                            ) : (
                                <>
                                    <Power size={12} />
                                    Завершить все ({otherSessionsCount})
                                </>
                            )}
                        </button>
                    ) : null}
                    <button
                        type="button"
                        className="sp-btn sp-btn-sm"
                        onClick={() =>
                            queryClient.invalidateQueries({ queryKey: ['admin-sessions'] })
                        }
                        disabled={sessionsQuery.isFetching}
                    >
                        <RefreshCw
                            size={12}
                            className={sessionsQuery.isFetching ? 'sp-rotating' : ''}
                        />
                        Обновить
                    </button>
                </div>
            </div>

            {sessionsQuery.isLoading ? (
                <div className="sp-empty">
                    <div className="sp-empty-title">Загружаем сессии…</div>
                    <div>Опрашиваем активные токены команды.</div>
                </div>
            ) : sessions.length === 0 ? (
                <div className="sp-empty">
                    <div className="sp-empty-title">Нет активных сессий</div>
                    <div>Если вы вошли в систему — это странно. Попробуйте обновить.</div>
                </div>
            ) : (
                <div className="sp-table-wrap">
                    <table className="sp-table">
                        <thead>
                            <tr>
                                <th>ID сессии</th>
                                <th>Тип</th>
                                <th>Пользователь</th>
                                <th>IP</th>
                                <th>Создана</th>
                                <th>Активность</th>
                                <th>Истекает</th>
                                <th className="sp-cell-actions">Действие</th>
                            </tr>
                        </thead>
                        <tbody>
                            {sessions.map((s) => {
                                const isCurrent = s.session_id === currentSessionId;
                                const meta = TOKEN_KIND_META[s.token_kind];
                                const Icon = meta?.icon;
                                return (
                                    <tr
                                        key={s.session_id}
                                        className={isCurrent ? 'is-selected' : ''}
                                    >
                                        <td>
                                            <span className="sp-cell-mono">
                                                {s.session_id.slice(0, 12)}…
                                            </span>
                                            {isCurrent ? (
                                                <span
                                                    className="sp-pill is-accent"
                                                    style={{ marginLeft: 6 }}
                                                >
                                                    <Check size={10} />
                                                    текущая
                                                </span>
                                            ) : null}
                                        </td>
                                        <td>
                                            <span className="sp-chip">
                                                {Icon ? <Icon size={11} /> : null}
                                                {meta?.label || s.token_kind}
                                            </span>
                                        </td>
                                        <td>
                                            {s.subject || '—'}
                                            {s.user_id ? (
                                                <span className="sp-cell-mono" style={{ marginLeft: 4 }}>
                                                    #{s.user_id}
                                                </span>
                                            ) : null}
                                        </td>
                                        <td>
                                            <span className="sp-cell-mono">
                                                {s.ip_address || '—'}
                                            </span>
                                        </td>
                                        <td>
                                            <span className="sp-cell-mono">
                                                {formatDate(s.created_at)}
                                            </span>
                                        </td>
                                        <td>
                                            <span className="sp-cell-mono">
                                                {formatDate(s.last_activity_at)}
                                            </span>
                                        </td>
                                        <td>
                                            <span className="sp-cell-mono">
                                                {formatDate(s.expires_at)}
                                            </span>
                                        </td>
                                        <td className="sp-cell-actions">
                                            <button
                                                type="button"
                                                className="sp-btn sp-btn-sm sp-btn-icon"
                                                onClick={() => setDetailFor(s)}
                                                title="Детали"
                                                aria-label="Подробнее о сессии"
                                                style={{ marginRight: 4 }}
                                            >
                                                <Info size={12} />
                                            </button>
                                            {isCurrent ? (
                                                <span className="sp-chip">текущая</span>
                                            ) : (
                                                <button
                                                    type="button"
                                                    className="sp-btn sp-btn-sm sp-btn-danger"
                                                    onClick={() => killMutation.mutate(s.session_id)}
                                                    disabled={killMutation.isPending}
                                                >
                                                    <Power size={12} />
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
            <SessionDetailDialog
                session={detailFor}
                isCurrent={detailFor?.session_id === currentSessionId}
                onClose={() => setDetailFor(null)}
                onKill={(sid) => {
                    killMutation.mutate(sid);
                    setDetailFor(null);
                }}
            />
        </div>
    );
};

const SessionDetailDialog: React.FC<{
    session: ActiveSession | null;
    isCurrent: boolean;
    onClose: () => void;
    onKill: (sessionId: string) => void;
}> = ({ session, isCurrent, onClose, onKill }) => {
    if (!session) return null;
    const meta = TOKEN_KIND_META[session.token_kind];
    const Icon = meta?.icon;

    const rows: { label: string; value: React.ReactNode }[] = [
        { label: 'Session ID', value: <span className="sp-cell-mono" style={{ wordBreak: 'break-all' }}>{session.session_id}</span> },
        { label: 'Тип', value: (
            <span className="sp-chip">
                {Icon ? <Icon size={11} /> : null}
                {meta?.label || session.token_kind}
            </span>
        ) },
        { label: 'Пользователь', value: session.subject || '—' },
        { label: 'User ID', value: session.user_id ? <span className="sp-cell-mono">#{session.user_id}</span> : '—' },
        { label: 'IP-адрес', value: <span className="sp-cell-mono">{session.ip_address || '—'}</span> },
        { label: 'Создана', value: <span className="sp-cell-mono">{formatDate(session.created_at)}</span> },
        { label: 'Активность', value: <span className="sp-cell-mono">{formatDate(session.last_activity_at)}</span> },
        { label: 'Истекает', value: <span className="sp-cell-mono">{formatDate(session.expires_at)}</span> },
    ];

    return (
        <Dialog
            open={Boolean(session)}
            onClose={onClose}
            title={
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span aria-hidden style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        width: 28, height: 28,
                        borderRadius: 4,
                        background: 'var(--surface-2)',
                        color: 'var(--text)',
                    }}>
                        {Icon ? <Icon size={15} /> : <Info size={15} />}
                    </span>
                    <h3 className="sp-sheet-title">Сессия {session.session_id.slice(0, 8)}…</h3>
                    {isCurrent ? <span className="sp-pill is-accent" style={{ marginLeft: 'auto' }}>текущая</span> : null}
                </div>
            }
            description="Полная информация о сессии. Все поля доступны в одну строку без обрезания."
            width={560}
            footer={
                <>
                    <span className="sp-spacer" />
                    <button type="button" className="sp-btn" onClick={onClose}>Закрыть</button>
                    {!isCurrent ? (
                        <button
                            type="button"
                            className="sp-btn sp-btn-danger"
                            onClick={() => onKill(session.session_id)}
                        >
                            <Power size={12} />
                            Завершить сессию
                        </button>
                    ) : null}
                </>
            }
        >
            <div className="sp-session-detail">
                {rows.map((r) => (
                    <div key={r.label} className="sp-detail-row">
                        <span className="sp-detail-label">{r.label}</span>
                        <span className="sp-detail-value">{r.value}</span>
                    </div>
                ))}
            </div>
        </Dialog>
    );
};
