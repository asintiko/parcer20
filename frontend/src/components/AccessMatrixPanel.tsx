import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { adminApi, securityApi } from '../services/api';

/**
 * Inline access matrix: rows = users, columns = folders/scopes.
 * Toggle cells write through to admin.updateUser(id, { allowed_folders }).
 */

type Scope = { id: number; name: string };
type AdminUserLite = {
    id: number;
    username: string;
    role: 'admin' | 'operator';
    display_name?: string | null;
    allowed_folders?: number[];
    is_active?: boolean;
};

export interface AccessMatrixPanelProps {
    onSuccess: (msg: string) => void;
    onError: (msg: string) => void;
}

export const AccessMatrixPanel: React.FC<AccessMatrixPanelProps> = ({ onSuccess, onError }) => {
    const queryClient = useQueryClient();
    const [search, setSearch] = useState('');

    const usersQuery = useQuery({ queryKey: ['admin-users'], queryFn: () => adminApi.listUsers() });
    const scopesQuery = useQuery({ queryKey: ['security-scopes-light'], queryFn: () => securityApi.listScopes() });

    const users = (usersQuery.data || []) as AdminUserLite[];
    const scopes = (scopesQuery.data || []) as Scope[];

    const filteredUsers = useMemo(() => {
        const q = search.trim().toLowerCase();
        if (!q) return users;
        return users.filter((u) =>
            u.username.toLowerCase().includes(q) ||
            (u.display_name || '').toLowerCase().includes(q)
        );
    }, [users, search]);

    const toggleMutation = useMutation({
        mutationFn: async ({ user, folderId, on }: { user: AdminUserLite; folderId: number; on: boolean }) => {
            const next = new Set(user.allowed_folders || []);
            if (on) next.add(folderId); else next.delete(folderId);
            return adminApi.updateUser(user.id, {
                allowed_folders: Array.from(next),
            });
        },
        onSuccess: (_data, variables) => {
            queryClient.invalidateQueries({ queryKey: ['admin-users'] });
            onSuccess(`Доступ к папке для @${variables.user.username} обновлён`);
        },
        onError: (err: any) => {
            onError(err?.response?.data?.detail || err?.message || 'Не удалось обновить доступ');
        },
    });

    const isLoading = usersQuery.isLoading || scopesQuery.isLoading;

    if (isLoading) {
        return (
            <div className="sp-empty">
                <div className="sp-empty-title">Загружаем матрицу…</div>
                <div>Получаем список пользователей и папок.</div>
            </div>
        );
    }

    if (!scopes.length) {
        return (
            <div className="sp-empty">
                <div className="sp-empty-title">Нет настроенных папок</div>
                <div>Создайте папки в системе, чтобы управлять доступами.</div>
            </div>
        );
    }

    if (!users.length) {
        return (
            <div className="sp-empty">
                <div className="sp-empty-title">Нет пользователей</div>
                <div>Добавьте операторов в разделе «Пользователи».</div>
            </div>
        );
    }

    return (
        <div className="sp-card">
            <div className="sp-card-head">
                <div>
                    <h2 className="sp-card-title">Матрица доступа</h2>
                    <div className="sp-card-sub">
                        Рядом с пользователем — папки, к которым у него есть доступ.
                    </div>
                </div>
                <span className="sp-chip sp-chip-mono" title="Папок в системе">
                    {scopes.length} {scopes.length === 1 ? 'папка' : 'папок'}
                </span>
            </div>
            <div className="sp-toolbar">
                <div className="sp-toolbar-search">
                    <div className="sp-input-wrap">
                        <Search size={14} className="sp-input-icon" />
                        <input
                            type="text"
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            placeholder="Поиск пользователя"
                            className="sp-input"
                        />
                    </div>
                </div>
                <span className="sp-toolbar-spacer" />
                <span className="sp-toolbar-meta">
                    {filteredUsers.length} из {users.length}
                </span>
            </div>

            <div className="sp-table-wrap">
                {filteredUsers.length === 0 ? (
                    <div className="sp-empty">
                        <div className="sp-empty-title">Никого не найдено</div>
                        <div>Попробуйте изменить запрос.</div>
                    </div>
                ) : (
                    <table className="sp-table sp-access-matrix">
                    <thead>
                        <tr>
                            <th>Пользователь</th>
                            {scopes.map((s) => (
                                <th key={s.id} className="sp-cell-center" title={s.name}>
                                    {s.name}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {filteredUsers.map((u) => {
                            const isAdmin = u.role === 'admin';
                            return (
                                <tr key={u.id}>
                                    <td>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                            <div className="sp-avatar" aria-hidden style={{ width: 24, height: 24, fontSize: 10, borderRadius: 6 }}>
                                                {(u.display_name || u.username).slice(0, 2).toUpperCase()}
                                            </div>
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 }}>
                                                <span className="sp-cell-strong">{u.display_name || u.username}</span>
                                                <span className="sp-cell-mono">@{u.username}</span>
                                            </div>
                                            {isAdmin ? (
                                                <span className="sp-pill is-accent" style={{ marginLeft: 'auto' }}>admin</span>
                                            ) : null}
                                        </div>
                                    </td>
                                    {scopes.map((s) => {
                                        const checked = isAdmin || (u.allowed_folders || []).includes(s.id);
                                        return (
                                            <td key={s.id} className="sp-cell-center">
                                                <label
                                                    className={[
                                                        'sp-matrix-cell',
                                                        checked ? 'is-checked' : '',
                                                        isAdmin ? 'is-disabled' : '',
                                                    ].filter(Boolean).join(' ')}
                                                    title={isAdmin ? 'admin: полный доступ' : `${s.name}: ${checked ? 'есть' : 'нет'}`}
                                                >
                                                    <input
                                                        type="checkbox"
                                                        checked={checked}
                                                        disabled={isAdmin || toggleMutation.isPending}
                                                        onChange={(e) => {
                                                            if (isAdmin) return;
                                                            toggleMutation.mutate({
                                                                user: u,
                                                                folderId: s.id,
                                                                on: e.target.checked,
                                                            });
                                                        }}
                                                    />
                                                </label>
                                            </td>
                                        );
                                    })}
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
                )}
            </div>

            <div className="sp-card-body compact" style={{ borderTop: '1px solid var(--sp-border)' }}>
                <div className="sp-row-hint">
                    Изменения сохраняются мгновенно. Admin-пользователи всегда видят все папки.
                </div>
            </div>
        </div>
    );
};
