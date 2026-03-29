import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { periodsApi } from '../services/api';

interface PeriodsManagerProps {
    showToast: (type: 'success' | 'error' | 'info', message: string) => void;
}

export const PeriodsManager: React.FC<PeriodsManagerProps> = ({ showToast }) => {
    const queryClient = useQueryClient();
    const [dateFrom, setDateFrom] = useState('');
    const [dateTo, setDateTo] = useState('');
    const [reason, setReason] = useState('');

    const isInvalidRange = Boolean(dateFrom && dateTo && dateFrom > dateTo);

    const periodsQuery = useQuery({
        queryKey: ['periods-all'],
        queryFn: () => periodsApi.list(false),
    });

    const createMutation = useMutation({
        mutationFn: () => periodsApi.create({ date_from: dateFrom, date_to: dateTo, reason: reason || undefined }),
        onSuccess: () => {
            setDateFrom('');
            setDateTo('');
            setReason('');
            showToast('success', 'Период добавлен');
            queryClient.invalidateQueries({ queryKey: ['periods-all'] });
        },
        onError: (err: any) => showToast('error', err?.response?.data?.detail || err?.message || 'Ошибка добавления'),
    });

    const deactivateMutation = useMutation({
        mutationFn: (id: number) => periodsApi.deactivate(id),
        onSuccess: () => {
            showToast('success', 'Период деактивирован');
            queryClient.invalidateQueries({ queryKey: ['periods-all'] });
        },
        onError: (err: any) => showToast('error', err?.response?.data?.detail || err?.message || 'Ошибка деактивации'),
    });

    return (
        <section className="border border-border rounded-lg bg-surface p-4 space-y-3">
            <h2 className="text-lg font-semibold text-foreground">Блокировки периодов</h2>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
                <input
                    type="date"
                    value={dateFrom}
                    onChange={(e) => setDateFrom(e.target.value)}
                    placeholder="Дата начала"
                    className="px-3 py-2 border border-border rounded-md bg-input-bg text-input-text"
                />
                <input
                    type="date"
                    value={dateTo}
                    onChange={(e) => setDateTo(e.target.value)}
                    placeholder="Дата конца"
                    className="px-3 py-2 border border-border rounded-md bg-input-bg text-input-text"
                />
                <input
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="Причина блокировки"
                    className="px-3 py-2 border border-border rounded-md bg-input-bg text-input-text"
                />
                <button
                    type="button"
                    onClick={() => createMutation.mutate()}
                    disabled={createMutation.isPending || !dateFrom || !dateTo || isInvalidRange}
                    className="px-3 py-2 rounded-md border border-primary text-primary hover:bg-primary/10 disabled:opacity-60"
                >
                    Добавить
                </button>
            </div>
            {isInvalidRange ? (
                <div className="text-xs text-danger">Дата начала должна быть раньше или равна дате окончания.</div>
            ) : null}

            <div className="overflow-auto border border-border rounded-md">
                <table className="w-full text-sm">
                    <thead className="bg-surface-2">
                        <tr>
                            <th className="text-left px-3 py-2">ID</th>
                            <th className="text-left px-3 py-2">Период</th>
                            <th className="text-left px-3 py-2">Причина</th>
                            <th className="text-left px-3 py-2">Статус</th>
                            <th className="text-left px-3 py-2">Действие</th>
                        </tr>
                    </thead>
                    <tbody>
                        {(periodsQuery.data || []).map((row) => (
                            <tr key={row.id} className="border-t border-border">
                                <td className="px-3 py-2">{row.id}</td>
                                <td className="px-3 py-2">{row.date_from} .. {row.date_to}</td>
                                <td className="px-3 py-2">{row.reason || '-'}</td>
                                <td className="px-3 py-2">{row.is_active ? 'Активен' : 'Снят'}</td>
                                <td className="px-3 py-2">
                                    {row.is_active ? (
                                        <button
                                            type="button"
                                            onClick={() => deactivateMutation.mutate(row.id)}
                                            className="px-2 py-1 text-xs rounded border border-danger/40 text-danger hover:bg-danger/10"
                                        >
                                            Деактивировать
                                        </button>
                                    ) : (
                                        <span className="text-xs text-foreground-muted">—</span>
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </section>
    );
};
