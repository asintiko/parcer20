import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, X, AlertCircle, Users as UsersIcon, Check } from 'lucide-react';
import { periodsApi, adminApi, type AdminUser } from '../services/api';

interface PeriodsManagerProps {
    showToast: (type: 'success' | 'error' | 'info', message: string) => void;
}

export const PeriodsManager: React.FC<PeriodsManagerProps> = ({ showToast }) => {
    const queryClient = useQueryClient();
    const [dateFrom, setDateFrom] = useState('');
    const [dateTo, setDateTo] = useState('');
    const [reason, setReason] = useState('');
    const [exclusionEditFor, setExclusionEditFor] = useState<number | null>(null);
    const [draftExclusions, setDraftExclusions] = useState<number[]>([]);

    const isInvalidRange = Boolean(dateFrom && dateTo && dateFrom > dateTo);

    const periodsQuery = useQuery({
        queryKey: ['periods-all'],
        queryFn: () => periodsApi.list(false),
    });

    const usersQuery = useQuery({
        queryKey: ['admin-users'],
        queryFn: () => adminApi.listUsers(),
    });
    const users: AdminUser[] = usersQuery.data || [];
    const userById = useMemo(() => {
        const m = new Map<number, AdminUser>();
        users.forEach((u) => m.set(u.id, u));
        return m;
    }, [users]);

    const createMutation = useMutation({
        mutationFn: () =>
            periodsApi.create({
                date_from: dateFrom,
                date_to: dateTo,
                reason: reason || undefined,
            }),
        onSuccess: () => {
            setDateFrom('');
            setDateTo('');
            setReason('');
            showToast('success', 'Период добавлен');
            queryClient.invalidateQueries({ queryKey: ['periods-all'] });
        },
        onError: (err: any) =>
            showToast(
                'error',
                err?.response?.data?.detail || err?.message || 'Ошибка добавления',
            ),
    });

    const deactivateMutation = useMutation({
        mutationFn: (id: number) => periodsApi.deactivate(id),
        onSuccess: () => {
            showToast('success', 'Период деактивирован');
            queryClient.invalidateQueries({ queryKey: ['periods-all'] });
        },
        onError: (err: any) =>
            showToast(
                'error',
                err?.response?.data?.detail || err?.message || 'Ошибка деактивации',
            ),
    });

    const updateExclusionsMutation = useMutation({
        mutationFn: ({ id, ids }: { id: number; ids: number[] }) =>
            periodsApi.update(id, { excluded_user_ids: ids }),
        onSuccess: () => {
            showToast('success', 'Исключения обновлены');
            queryClient.invalidateQueries({ queryKey: ['periods-all'] });
            setExclusionEditFor(null);
        },
        onError: (err: any) =>
            showToast(
                'error',
                err?.response?.data?.detail || err?.message || 'Ошибка сохранения исключений',
            ),
    });

    const rows = periodsQuery.data || [];
    const activeCount = rows.filter((r) => r.is_active).length;
    const canSubmit = !!dateFrom && !!dateTo && !isInvalidRange && !createMutation.isPending;

    const startEditExclusions = (row: { id: number; excluded_user_ids?: number[] }) => {
        setDraftExclusions(row.excluded_user_ids || []);
        setExclusionEditFor(row.id);
    };

    return (
        <div className="sp-card">
            <div className="sp-card-head">
                <div>
                    <h2 className="sp-card-title">Заблокированные периоды</h2>
                    <div className="sp-card-sub">
                        Запрет правок транзакций в указанных диапазонах. Можно исключить отдельных пользователей.
                    </div>
                </div>
                {rows.length > 0 ? (
                    <span className="sp-chip sp-chip-mono">
                        активных · {activeCount} / {rows.length}
                    </span>
                ) : null}
            </div>

            <div className="sp-card-body">
                <div className="sp-grid-form">
                    <div>
                        <label className="sp-row-hint sp-form-label">Дата начала</label>
                        <input
                            type="date"
                            value={dateFrom}
                            onChange={(e) => setDateFrom(e.target.value)}
                            className="sp-input is-mono"
                        />
                    </div>
                    <div>
                        <label className="sp-row-hint sp-form-label">Дата конца</label>
                        <input
                            type="date"
                            value={dateTo}
                            onChange={(e) => setDateTo(e.target.value)}
                            className="sp-input is-mono"
                        />
                    </div>
                    <div>
                        <label className="sp-row-hint sp-form-label">Причина</label>
                        <input
                            type="text"
                            value={reason}
                            onChange={(e) => setReason(e.target.value)}
                            placeholder="Например: закрытие квартала"
                            className="sp-input"
                        />
                    </div>
                    <div className="sp-form-action">
                        <button
                            type="button"
                            className="sp-btn sp-btn-primary"
                            onClick={() => createMutation.mutate()}
                            disabled={!canSubmit}
                        >
                            <Plus size={13} />
                            Добавить
                        </button>
                    </div>
                </div>
                {isInvalidRange ? (
                    <div className="sp-error" style={{ marginTop: -4 }}>
                        <AlertCircle size={13} />
                        <span>Дата начала должна быть раньше или равна дате окончания.</span>
                    </div>
                ) : null}
            </div>

            {periodsQuery.isLoading ? (
                <div className="sp-empty">
                    <div className="sp-empty-title">Загружаем периоды…</div>
                </div>
            ) : rows.length > 0 ? (
                <div className="sp-table-wrap">
                    <table className="sp-table">
                        <thead>
                            <tr>
                                <th style={{ width: 56 }}>ID</th>
                                <th>Период</th>
                                <th>Причина</th>
                                <th>Исключения</th>
                                <th>Статус</th>
                                <th className="sp-cell-actions">Действие</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((row) => {
                                const excluded = row.excluded_user_ids || [];
                                const isEditing = exclusionEditFor === row.id;
                                return (
                                    <React.Fragment key={row.id}>
                                        <tr>
                                            <td className="sp-cell-mono">#{row.id}</td>
                                            <td>
                                                <span className="sp-cell-mono">
                                                    {row.date_from} … {row.date_to}
                                                </span>
                                            </td>
                                            <td>{row.reason || <span className="sp-chip">—</span>}</td>
                                            <td>
                                                <button
                                                    type="button"
                                                    className="sp-btn sp-btn-sm sp-btn-ghost"
                                                    onClick={() => isEditing
                                                        ? setExclusionEditFor(null)
                                                        : startEditExclusions(row)}
                                                    title="Редактировать исключения"
                                                >
                                                    <UsersIcon size={12} />
                                                    {excluded.length > 0
                                                        ? `${excluded.length} ${excluded.length === 1 ? 'юзер' : 'юзеров'}`
                                                        : 'нет'}
                                                </button>
                                            </td>
                                            <td>
                                                {row.is_active ? (
                                                    <span className="sp-pill is-warning">
                                                        <span className="sp-pill-dot" />
                                                        активен
                                                    </span>
                                                ) : (
                                                    <span className="sp-pill">снят</span>
                                                )}
                                            </td>
                                            <td className="sp-cell-actions">
                                                {row.is_active ? (
                                                    <button
                                                        type="button"
                                                        className="sp-btn sp-btn-sm sp-btn-danger"
                                                        onClick={() => deactivateMutation.mutate(row.id)}
                                                        disabled={deactivateMutation.isPending}
                                                    >
                                                        <X size={12} />
                                                        Снять
                                                    </button>
                                                ) : (
                                                    <span className="sp-chip">—</span>
                                                )}
                                            </td>
                                        </tr>
                                        {isEditing ? (
                                            <tr className="sp-row-expanded">
                                                <td colSpan={6}>
                                                    <div className="sp-row-expanded-body">
                                                        <div className="sp-row-hint" style={{ marginBottom: 6 }}>
                                                            Выберите пользователей, для которых период не действует:
                                                        </div>
                                                        <div className="sp-chipgrid">
                                                            {users.map((u) => {
                                                                const checked = draftExclusions.includes(u.id);
                                                                return (
                                                                    <label
                                                                        key={u.id}
                                                                        className={['sp-chip-toggle', checked ? 'is-active' : ''].filter(Boolean).join(' ')}
                                                                    >
                                                                        <input
                                                                            type="checkbox"
                                                                            checked={checked}
                                                                            onChange={(e) => {
                                                                                setDraftExclusions((prev) =>
                                                                                    e.target.checked
                                                                                        ? [...prev, u.id]
                                                                                        : prev.filter((id) => id !== u.id)
                                                                                );
                                                                            }}
                                                                        />
                                                                        {checked ? <Check size={11} /> : null}
                                                                        {u.display_name || u.username}
                                                                        <span className="sp-cell-mono" style={{ opacity: 0.6, marginLeft: 4 }}>
                                                                            @{u.username}
                                                                        </span>
                                                                    </label>
                                                                );
                                                            })}
                                                        </div>
                                                        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                                                            <button
                                                                type="button"
                                                                className="sp-btn sp-btn-sm sp-btn-primary"
                                                                onClick={() => updateExclusionsMutation.mutate({
                                                                    id: row.id,
                                                                    ids: draftExclusions,
                                                                })}
                                                                disabled={updateExclusionsMutation.isPending}
                                                            >
                                                                {updateExclusionsMutation.isPending ? (
                                                                    <>
                                                                        <span className="sp-btn-spinner" />
                                                                        Сохраняем
                                                                    </>
                                                                ) : 'Сохранить'}
                                                            </button>
                                                            <button
                                                                type="button"
                                                                className="sp-btn sp-btn-sm"
                                                                onClick={() => setExclusionEditFor(null)}
                                                                disabled={updateExclusionsMutation.isPending}
                                                            >
                                                                Отмена
                                                            </button>
                                                            {excluded.length > 0 ? (
                                                                <button
                                                                    type="button"
                                                                    className="sp-btn sp-btn-sm sp-btn-ghost"
                                                                    onClick={() => setDraftExclusions([])}
                                                                    disabled={updateExclusionsMutation.isPending}
                                                                    style={{ marginLeft: 'auto' }}
                                                                >
                                                                    Очистить
                                                                </button>
                                                            ) : null}
                                                        </div>
                                                        {draftExclusions.length > 0 ? (
                                                            <div className="sp-row-hint" style={{ marginTop: 6 }}>
                                                                Текущая выборка: {draftExclusions.length} {draftExclusions.length === 1 ? 'юзер' : 'юзеров'}
                                                                {draftExclusions.length <= 4 ? ` · ${draftExclusions.map((id) => userById.get(id)?.username || `#${id}`).join(', ')}` : ''}
                                                            </div>
                                                        ) : null}
                                                    </div>
                                                </td>
                                            </tr>
                                        ) : null}
                                    </React.Fragment>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            ) : (
                <div className="sp-empty">
                    <div className="sp-empty-title">Периодов пока нет</div>
                    <div>Добавьте первый период через форму выше.</div>
                </div>
            )}
        </div>
    );
};
