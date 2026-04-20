import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { auditApi } from '../services/api';

export const AuditPage: React.FC = () => {
    const [action, setAction] = useState('');
    const [userId, setUserId] = useState('');
    const [dateFrom, setDateFrom] = useState('');
    const [dateTo, setDateTo] = useState('');
    const [page, setPage] = useState(0);
    const limit = 200;

    const auditQuery = useQuery({
        queryKey: ['audit-records', action, userId, dateFrom, dateTo, page],
        queryFn: () =>
            auditApi.list({
                action: action.trim() || undefined,
                user_id: userId.trim() ? Number(userId) : undefined,
                date_from: dateFrom.trim() || undefined,
                date_to: dateTo.trim() || undefined,
                limit,
                offset: page * limit,
            }),
    });

    return (
        <div className="h-full overflow-y-auto p-6 space-y-4">
            <h1 className="text-xl font-semibold text-foreground">Аудит безопасности</h1>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-2 border border-border rounded-lg bg-surface p-3">
                <input
                    value={action}
                    onChange={(e) => {
                        setAction(e.target.value);
                        setPage(0);
                    }}
                    placeholder="Действие"
                    className="px-3 py-2 border border-border rounded-md bg-input-bg text-input-text"
                />
                <input
                    value={userId}
                    onChange={(e) => {
                        setUserId(e.target.value);
                        setPage(0);
                    }}
                    placeholder="ID пользователя"
                    className="px-3 py-2 border border-border rounded-md bg-input-bg text-input-text"
                />
                <input
                    value={dateFrom}
                    onChange={(e) => {
                        setDateFrom(e.target.value);
                        setPage(0);
                    }}
                    placeholder="Дата от (ГГГГ-ММ-ДД)"
                    className="px-3 py-2 border border-border rounded-md bg-input-bg text-input-text"
                />
                <input
                    value={dateTo}
                    onChange={(e) => {
                        setDateTo(e.target.value);
                        setPage(0);
                    }}
                    placeholder="Дата до (ГГГГ-ММ-ДД)"
                    className="px-3 py-2 border border-border rounded-md bg-input-bg text-input-text"
                />
            </div>

            <div className="border border-border rounded-lg bg-surface overflow-auto">
                <table className="w-full text-sm">
                    <thead className="bg-surface-2">
                        <tr>
                            <th className="text-left px-3 py-2">Время</th>
                            <th className="text-left px-3 py-2">Действие</th>
                            <th className="text-left px-3 py-2">Результат</th>
                            <th className="text-left px-3 py-2">Пользователь</th>
                            <th className="text-left px-3 py-2">IP</th>
                            <th className="text-left px-3 py-2">Детали</th>
                        </tr>
                    </thead>
                    <tbody>
                        {(auditQuery.data || []).map((row) => (
                            <tr key={row.id} className="border-t border-border align-top">
                                <td className="px-3 py-2 text-xs">{row.created_at || '-'}</td>
                                <td className="px-3 py-2">{row.action}</td>
                                <td className="px-3 py-2">{row.success ? 'OK' : 'Ошибка'}</td>
                                <td className="px-3 py-2">{row.user_id ?? '-'}</td>
                                <td className="px-3 py-2">{row.ip_address || '-'}</td>
                                <td className="px-3 py-2 text-xs font-mono whitespace-pre-wrap break-words">
                                    {row.details ? JSON.stringify(row.details, null, 2) : '-'}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                {!auditQuery.isLoading && (auditQuery.data || []).length === 0 ? (
                    <div className="px-3 py-8 text-sm text-foreground-secondary">Нет записей по текущим фильтрам.</div>
                ) : null}
            </div>

            <div className="flex items-center gap-2">
                <button
                    type="button"
                    onClick={() => setPage((prev) => Math.max(0, prev - 1))}
                    disabled={page === 0 || auditQuery.isFetching}
                    className="px-3 py-2 rounded-md border border-border bg-surface hover:bg-surface-2 disabled:opacity-50"
                >
                    Назад
                </button>
                <button
                    type="button"
                    onClick={() => setPage((prev) => prev + 1)}
                    disabled={(auditQuery.data || []).length < limit || auditQuery.isFetching}
                    className="px-3 py-2 rounded-md border border-border bg-surface hover:bg-surface-2 disabled:opacity-50"
                >
                    Далее
                </button>
                <div className="text-xs text-foreground-secondary">Страница: {page + 1}</div>
            </div>
        </div>
    );
};
