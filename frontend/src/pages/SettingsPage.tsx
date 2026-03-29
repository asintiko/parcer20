import React, { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { adminApi, type AdminCreateUserPayload, type AdminUpdateUserPayload, securityApi } from '../services/api';
import { useUpdater } from '../hooks/useUpdater';
import { useToast } from '../components/Toast';
import { ForbiddenPeriodsEditor, type ForbiddenPeriod } from '../components/ForbiddenPeriodsEditor';
import { PeriodsManager } from '../components/PeriodsManager';
import { SystemSettingsPanel } from '../components/SystemSettingsPanel';
import { SessionsManager } from '../components/SessionsManager';
import { Button, Input } from '../components/ui';
import { useAuth } from '../contexts/AuthContext';

const TAB_OPTIONS = [
    { key: 'dashboard', label: 'Дашборд' },
    { key: 'reference', label: 'Справочник' },
    { key: 'automation', label: 'Автоматизация' },
    { key: 'userbot', label: 'Telegram Bots' },
    { key: 'logs', label: 'Логи' },
    { key: 'admin', label: 'Admin' },
] as const;

const ALL_TAB_KEYS = TAB_OPTIONS.map((tab) => tab.key);
const OPERATOR_TAB_KEYS = ALL_TAB_KEYS.filter((key) => key !== 'admin');
const OPERATOR_TAB_SET = new Set<string>(OPERATOR_TAB_KEYS);

type UserFormState = {
    id: number | null;
    username: string;
    password: string;
    role: 'admin' | 'operator';
    display_name: string;
    is_active: boolean;
    allowed_tabs: string[];
    allowed_folders: number[];
    forbidden_periods: ForbiddenPeriod[];
    can_toggle_sources: boolean;
    force_2fa: boolean;
    session_ttl_days: number;
    telegram_id: string;
    telegram_username: string;
};

type UserFormErrors = Partial<
    Record<'username' | 'password' | 'display_name' | 'allowed_tabs' | 'session_ttl_days', string>
>;

const emptyForm = (): UserFormState => ({
    id: null,
    username: '',
    password: '',
    role: 'operator',
    display_name: '',
    is_active: true,
    allowed_tabs: ['dashboard'],
    allowed_folders: [],
    forbidden_periods: [],
    can_toggle_sources: false,
    force_2fa: false,
    session_ttl_days: 7,
    telegram_id: '',
    telegram_username: '',
});

export const SettingsPage: React.FC = () => {
    const { isElectron, status, version, error, progress, check, download, install } = useUpdater();
    const { logout } = useAuth();
    const { showToast } = useToast();
    const queryClient = useQueryClient();
    const [form, setForm] = useState<UserFormState>(emptyForm());
    const [formErrors, setFormErrors] = useState<UserFormErrors>({});
    const [isEditorOpen, setIsEditorOpen] = useState(false);
    const [logoutLoading, setLogoutLoading] = useState(false);
    const isAdminRole = form.role === 'admin';

    useEffect(() => {
        setForm((prev) => {
            if (prev.role === 'admin') {
                const allTabs = [...ALL_TAB_KEYS];
                const same =
                    prev.allowed_tabs.length === allTabs.length &&
                    allTabs.every((tab) => prev.allowed_tabs.includes(tab));
                if (same) return prev;
                return { ...prev, allowed_tabs: allTabs };
            }
            const normalized = prev.allowed_tabs.filter((tab) => OPERATOR_TAB_SET.has(tab));
            if (!normalized.includes('dashboard')) {
                normalized.unshift('dashboard');
            }
            const unique = Array.from(new Set(normalized));
            const same =
                prev.allowed_tabs.length === unique.length &&
                unique.every((tab) => prev.allowed_tabs.includes(tab));
            if (same) return prev;
            return { ...prev, allowed_tabs: unique };
        });
    }, [form.role]);

    const validateForm = (state: UserFormState): UserFormErrors => {
        const errors: UserFormErrors = {};
        const username = state.username.trim();
        if (state.id === null) {
            if (!username) {
                errors.username = 'Логин обязателен';
            } else if (!/^[a-zA-Z0-9_.-]{3,50}$/.test(username)) {
                errors.username = 'Логин: 3-50 символов, только a-z A-Z 0-9 . _ -';
            }
            const password = state.password || '';
            const strongPassword =
                password.length >= 8 &&
                /[a-z]/.test(password) &&
                /[A-Z]/.test(password) &&
                /\d/.test(password) &&
                /[^A-Za-z0-9]/.test(password);
            if (!password) {
                errors.password = 'Пароль обязателен';
            } else if (!strongPassword) {
                errors.password = 'Минимум 8 символов: A-Z, a-z, 0-9 и спецсимвол';
            }
        }
        if (!state.display_name.trim()) {
            errors.display_name = 'Отображаемое имя обязательно';
        }
        if (!state.allowed_tabs.length) {
            errors.allowed_tabs = 'Выберите хотя бы одну вкладку';
        }
        if (!Number.isFinite(state.session_ttl_days) || state.session_ttl_days < 1 || state.session_ttl_days > 90) {
            errors.session_ttl_days = 'TTL сессии должен быть от 1 до 90 дней';
        }
        return errors;
    };

    const usersQuery = useQuery({
        queryKey: ['admin-users'],
        queryFn: () => adminApi.listUsers(true),
    });

    const scopesQuery = useQuery({
        queryKey: ['security-scopes-light'],
        queryFn: securityApi.listScopes,
    });

    const saveUserMutation = useMutation({
        mutationFn: async () => {
            const payloadBase = {
                role: form.role,
                display_name: form.display_name,
                is_active: form.is_active,
                allowed_tabs: form.allowed_tabs,
                allowed_folders: form.allowed_folders,
                allowed_sources: [],
                forbidden_periods: form.forbidden_periods.filter((row) => row.from && row.to),
                can_toggle_sources: form.can_toggle_sources,
                force_2fa: form.force_2fa,
                session_ttl_days: form.session_ttl_days,
            };

            if (form.id === null) {
                if (!form.username.trim() || !form.password) {
                    throw new Error('Для создания нужны username и password');
                }
                const tgId = form.telegram_id.trim() ? parseInt(form.telegram_id.trim(), 10) : undefined;
                const tgUsername = form.telegram_username.trim().replace(/^@/, '') || undefined;
                const payload: AdminCreateUserPayload = {
                    username: form.username.trim(),
                    password: form.password,
                    ...payloadBase,
                    ...(tgId && Number.isFinite(tgId) ? { telegram_id: tgId } : {}),
                    ...(tgUsername ? { telegram_username: tgUsername } : {}),
                };
                return adminApi.createUser(payload);
            }

            const payload: AdminUpdateUserPayload = payloadBase;
            return adminApi.updateUser(form.id, payload);
        },
        onSuccess: () => {
            showToast('success', form.id === null ? 'Пользователь создан' : 'Пользователь обновлен');
            setIsEditorOpen(false);
            setForm(emptyForm());
            setFormErrors({});
            queryClient.invalidateQueries({ queryKey: ['admin-users'] });
        },
        onError: (err: any) => {
            const detail = err?.response?.data?.detail;
            const map: Record<string, string> = {
                weak_password: 'Слабый пароль: мин. 8 символов, заглавная + строчная + цифра + спецсимвол',
                username_exists: 'Пользователь с таким логином уже существует',
                invalid_username: 'Некорректный логин',
                invalid_password: 'Пароль не задан',
                invalid_role: 'Некорректная роль',
                telegram_id_already_linked: 'Этот Telegram ID уже привязан к другому пользователю',
            };
            showToast('error', map[detail] || detail || err?.message || 'Ошибка сохранения');
        },
    });

    const resetPasswordMutation = useMutation({
        mutationFn: async (userId: number) => {
            const newPassword = window.prompt(
                'Новый пароль:\n(мин. 8 символов, заглавная + строчная + цифра + спецсимвол)',
            );
            if (!newPassword) {
                throw new Error('Отмена');
            }
            return adminApi.resetPassword(userId, newPassword);
        },
        onSuccess: () => {
            showToast('success', 'Пароль сброшен');
            queryClient.invalidateQueries({ queryKey: ['admin-users'] });
        },
        onError: (err: any) => {
            if (err?.message === 'Отмена') return;
            const detail = err?.response?.data?.detail;
            if (detail === 'weak_password') {
                showToast('error', 'Слабый пароль: мин. 8 символов, заглавная + строчная + цифра + спецсимвол');
                return;
            }
            showToast('error', detail || 'Не удалось сбросить пароль');
        },
    });

    const reset2faMutation = useMutation({
        mutationFn: (userId: number) => adminApi.reset2fa(userId),
        onSuccess: () => {
            showToast('success', '2FA сброшена');
            queryClient.invalidateQueries({ queryKey: ['admin-users'] });
        },
        onError: (err: any) => {
            showToast('error', err?.response?.data?.detail || 'Не удалось сбросить 2FA');
        },
    });

    const force2faMutation = useMutation({
        mutationFn: ({ userId, force }: { userId: number; force: boolean }) => adminApi.force2fa(userId, force),
        onSuccess: () => {
            showToast('success', 'Флаг force_2fa обновлен');
            queryClient.invalidateQueries({ queryKey: ['admin-users'] });
        },
        onError: (err: any) => {
            showToast('error', err?.response?.data?.detail || 'Не удалось обновить force_2fa');
        },
    });

    const unlockMutation = useMutation({
        mutationFn: (userId: number) => adminApi.unlockUser(userId),
        onSuccess: () => {
            showToast('success', 'Пользователь разблокирован');
            queryClient.invalidateQueries({ queryKey: ['admin-users'] });
        },
        onError: (err: any) => {
            showToast('error', err?.response?.data?.detail || 'Ошибка разблокировки');
        },
    });

    const deactivateMutation = useMutation({
        mutationFn: (userId: number) => adminApi.deactivateUser(userId),
        onSuccess: () => {
            showToast('success', 'Пользователь деактивирован');
            queryClient.invalidateQueries({ queryKey: ['admin-users'] });
        },
        onError: (err: any) => {
            showToast('error', err?.response?.data?.detail || 'Ошибка деактивации');
        },
    });

    const activateMutation = useMutation({
        mutationFn: (userId: number) => adminApi.updateUser(userId, { is_active: true }),
        onSuccess: () => {
            showToast('success', 'Пользователь активирован');
            queryClient.invalidateQueries({ queryKey: ['admin-users'] });
        },
        onError: (err: any) => {
            showToast('error', err?.response?.data?.detail || 'Ошибка активации');
        },
    });

    const linkTelegramMutation = useMutation({
        mutationFn: async (userId: number) => {
            const input = window.prompt('Введите Telegram ID пользователя:');
            if (!input) throw new Error('Отмена');
            const tgId = Number(input.trim());
            if (!Number.isFinite(tgId) || tgId <= 0) throw new Error('Некорректный Telegram ID');
            const username = window.prompt('Telegram @username (без @, необязательно):') || undefined;
            return adminApi.linkTelegram(userId, tgId, username?.replace(/^@/, ''));
        },
        onSuccess: () => {
            showToast('success', 'Telegram привязан');
            queryClient.invalidateQueries({ queryKey: ['admin-users'] });
        },
        onError: (err: any) => {
            if (err?.message === 'Отмена') return;
            const detail = err?.response?.data?.detail;
            if (detail === 'telegram_id_already_linked') {
                showToast('error', 'Этот Telegram ID уже привязан к другому пользователю');
                return;
            }
            showToast('error', detail || err?.message || 'Ошибка привязки Telegram');
        },
    });

    const unlinkTelegramMutation = useMutation({
        mutationFn: (userId: number) => adminApi.unlinkTelegram(userId),
        onSuccess: () => {
            showToast('success', 'Telegram отвязан');
            queryClient.invalidateQueries({ queryKey: ['admin-users'] });
        },
        onError: (err: any) => {
            showToast('error', err?.response?.data?.detail || 'Ошибка отвязки Telegram');
        },
    });

    const renderUpdateStatus = () => {
        switch (status) {
            case 'checking':
                return 'Проверка обновлений...';
            case 'available':
                return 'Найдена новая версия.';
            case 'not-available':
                return 'Установлена последняя версия.';
            case 'downloading':
                return `Скачивание... ${progress?.percent ? Math.round(progress.percent) + '%' : ''}`;
            case 'downloaded':
                return 'Обновление скачано. Можно установить.';
            case 'error':
                return error || 'Ошибка обновления.';
            default:
                return 'Готово.';
        }
    };

    const scopesById = useMemo(() => {
        const map = new Map<number, string>();
        for (const scope of scopesQuery.data || []) {
            map.set(scope.id, scope.name);
        }
        return map;
    }, [scopesQuery.data]);

    const openCreate = () => {
        setForm(emptyForm());
        setFormErrors({});
        setIsEditorOpen(true);
    };

    const openEdit = (user: any) => {
        setForm({
            id: user.id,
            username: user.username,
            password: '',
            role: user.role,
            display_name: user.display_name || user.username,
            is_active: user.is_active,
            allowed_tabs: user.allowed_tabs || ['dashboard'],
            allowed_folders: user.allowed_folders || [],
            forbidden_periods: user.forbidden_periods || [],
            can_toggle_sources: Boolean(user.can_toggle_sources),
            force_2fa: Boolean(user.force_2fa),
            session_ttl_days: Number(user.session_ttl_days || 7),
            telegram_id: user.telegram_id ? String(user.telegram_id) : '',
            telegram_username: user.telegram_username || '',
        });
        setFormErrors({});
        setIsEditorOpen(true);
    };

    const setFormField = <K extends keyof UserFormState>(key: K, value: UserFormState[K]) => {
        setForm((prev) => ({ ...prev, [key]: value }));
        setFormErrors((prev) => {
            const next = { ...prev };
            if (key in next) delete next[key as keyof UserFormErrors];
            return next;
        });
    };

    const handleLogout = async () => {
        setLogoutLoading(true);
        try {
            await logout();
            showToast('success', 'Вы вышли из аккаунта');
        } catch {
            showToast('error', 'Не удалось завершить сессию');
        } finally {
            setLogoutLoading(false);
        }
    };

    return (
        <div className="h-full overflow-y-auto settings-page text-foreground">
            <div className="p-6 space-y-6 max-w-6xl mx-auto pb-10">
                <div className="flex items-center justify-between gap-3">
                    <h1 className="text-xl font-semibold text-foreground">Настройки</h1>
                    <Button variant="secondary" onClick={handleLogout} disabled={logoutLoading}>
                        {logoutLoading ? 'Выход...' : 'Выйти из аккаунта'}
                    </Button>
                </div>

                <section className="border border-border rounded-lg bg-surface p-4 space-y-3">
                    <h2 className="text-lg font-semibold text-foreground">Обновления приложения</h2>
                    <div className="text-sm text-foreground-secondary">
                        {isElectron ? 'Работаем в desktop-режиме Electron.' : 'Запущено в браузере — автообновления недоступны.'}
                    </div>
                    <div className="text-sm text-foreground">
                        Текущая версия: <span className="font-mono">{version || '—'}</span>
                    </div>
                    <div className="text-sm text-foreground">{renderUpdateStatus()}</div>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={check}
                            disabled={!isElectron || status === 'checking'}
                            className="px-3 py-2 text-sm rounded-md border border-border bg-surface hover:bg-surface-2 disabled:opacity-50"
                        >
                            Проверить обновления
                        </button>
                        <button
                            onClick={download}
                            disabled={!isElectron || status !== 'available'}
                            className="px-3 py-2 text-sm rounded-md border border-border bg-surface hover:bg-surface-2 disabled:opacity-50"
                        >
                            Скачать
                        </button>
                        <button
                            onClick={install}
                            disabled={!isElectron || status !== 'downloaded'}
                            className="px-3 py-2 text-sm rounded-md border border-primary text-primary hover:bg-primary/10 disabled:opacity-50"
                        >
                            Установить и перезапустить
                        </button>
                    </div>
                </section>

                <SystemSettingsPanel showToast={showToast} />
                <PeriodsManager showToast={showToast} />
                <SessionsManager showToast={showToast} />

                <section className="border border-border rounded-lg bg-surface p-4 space-y-4">
                    <div className="flex items-center justify-between">
                        <h2 className="text-lg font-semibold text-foreground">Пользователи и роли</h2>
                        <button
                            onClick={openCreate}
                            className="px-3 py-2 text-sm rounded-md border border-primary text-primary hover:bg-primary/10"
                        >
                            Добавить пользователя
                        </button>
                    </div>

                    <div className="overflow-auto border border-border rounded-md">
                        <table className="w-full text-sm">
                            <thead className="bg-surface-2">
                                <tr>
                                    <th className="text-left px-3 py-2 whitespace-nowrap">Логин</th>
                                    <th className="text-left px-3 py-2 whitespace-nowrap">Роль</th>
                                    <th className="text-left px-3 py-2 whitespace-nowrap">Вкладки</th>
                                    <th className="text-left px-3 py-2 whitespace-nowrap">Папки</th>
                                    <th className="text-left px-3 py-2 whitespace-nowrap">TTL</th>
                                    <th className="text-left px-3 py-2 whitespace-nowrap">2FA</th>
                                    <th className="text-left px-3 py-2 whitespace-nowrap">Telegram</th>
                                    <th className="text-left px-3 py-2 whitespace-nowrap">Статус</th>
                                    <th className="text-left px-3 py-2 whitespace-nowrap">Действия</th>
                                </tr>
                            </thead>
                            <tbody>
                                {(usersQuery.data || []).map((user) => (
                                    <tr key={user.id} className="border-t border-border align-top">
                                        <td className="px-3 py-2">
                                            <div className="font-medium">{user.username}</div>
                                            <div className="text-xs text-foreground-muted">{user.display_name}</div>
                                        </td>
                                        <td className="px-3 py-2">{user.role}</td>
                                        <td className="px-3 py-2 text-xs">{(user.allowed_tabs || []).join(', ') || '—'}</td>
                                        <td className="px-3 py-2 text-xs">
                                            {(user.allowed_folders || []).map((id) => scopesById.get(id) || `#${id}`).join(', ') || '—'}
                                        </td>
                                        <td className="px-3 py-2 text-xs">{user.session_ttl_days || 7} дн.</td>
                                        <td className="px-3 py-2 text-xs">
                                            {user.totp_enabled ? 'Включена' : 'Отключена'}{user.force_2fa ? ' / Принуд.' : ''}
                                        </td>
                                        <td className="px-3 py-2 text-xs">
                                            {user.telegram_id ? (
                                                <div>
                                                    <span className="font-mono">{user.telegram_id}</span>
                                                    {user.telegram_username && <div className="text-foreground-muted">@{user.telegram_username}</div>}
                                                </div>
                                            ) : '—'}
                                        </td>
                                        <td className="px-3 py-2 text-xs">{user.is_active ? 'Активен' : 'Отключен'}</td>
                                        <td className="px-3 py-2">
                                            <div className="flex flex-wrap gap-2">
                                                <button onClick={() => openEdit(user)} className="px-2 py-1 text-xs rounded border border-border hover:bg-surface-2" title="Редактировать">Редакт.</button>
                                                <button onClick={() => resetPasswordMutation.mutate(user.id)} className="px-2 py-1 text-xs rounded border border-border hover:bg-surface-2">Сброс пароля</button>
                                                <button onClick={() => reset2faMutation.mutate(user.id)} className="px-2 py-1 text-xs rounded border border-border hover:bg-surface-2">Сброс 2FA</button>
                                                <button
                                                    onClick={() => force2faMutation.mutate({ userId: user.id, force: !user.force_2fa })}
                                                    className="px-2 py-1 text-xs rounded border border-border hover:bg-surface-2"
                                                >
                                                    {user.force_2fa ? 'Снять 2FA' : 'Навязать 2FA'}
                                                </button>
                                                <button onClick={() => unlockMutation.mutate(user.id)} className="px-2 py-1 text-xs rounded border border-border hover:bg-surface-2" title="Разблокировать">Разблок.</button>
                                                {user.telegram_id ? (
                                                    <button onClick={() => unlinkTelegramMutation.mutate(user.id)} className="px-2 py-1 text-xs rounded border border-border hover:bg-surface-2">Отвязать TG</button>
                                                ) : (
                                                    <button onClick={() => linkTelegramMutation.mutate(user.id)} className="px-2 py-1 text-xs rounded border border-border hover:bg-surface-2">Привязать TG</button>
                                                )}
                                                {user.is_active ? (
                                                    <button onClick={() => deactivateMutation.mutate(user.id)} className="px-2 py-1 text-xs rounded border border-danger/50 text-danger hover:bg-danger/10" title="Отключить">Откл.</button>
                                                ) : (
                                                    <button onClick={() => activateMutation.mutate(user.id)} className="px-2 py-1 text-xs rounded border border-success/50 text-success hover:bg-success/10">Вкл.</button>
                                                )}
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>

                    {isEditorOpen && (
                        <div className="border border-border rounded-md p-4 space-y-3 bg-surface-2">
                            <h3 className="font-medium text-foreground">{form.id === null ? 'Новый пользователь' : `Редактирование #${form.id}`}</h3>

                            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                                <Input
                                    value={form.username}
                                    onChange={(e) => setFormField('username', e.target.value)}
                                    label="Логин"
                                    disabled={form.id !== null}
                                    error={formErrors.username || null}
                                    containerClassName="md:col-span-1"
                                />
                                <div>
                                    <Input
                                        type="password"
                                        value={form.password}
                                        onChange={(e) => setFormField('password', e.target.value)}
                                        label="Пароль"
                                        placeholder={form.id === null ? '' : 'Только через "Сброс пароля"'}
                                        disabled={form.id !== null}
                                        error={formErrors.password || null}
                                    />
                                    {form.id === null && (
                                        <div className="text-[11px] text-foreground-muted mt-1">A-Z, a-z, 0-9, спецсимвол, мин. 8</div>
                                    )}
                                </div>
                                <Input
                                    value={form.display_name}
                                    onChange={(e) => setFormField('display_name', e.target.value)}
                                    label="Отображаемое имя"
                                    error={formErrors.display_name || null}
                                />
                            </div>

                            {form.id === null && (
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                                    <Input
                                        value={form.telegram_id}
                                        onChange={(e) => setFormField('telegram_id', e.target.value.replace(/\D/g, ''))}
                                        label="Telegram ID (необязательно)"
                                        placeholder="123456789"
                                        inputMode="numeric"
                                    />
                                    <Input
                                        value={form.telegram_username}
                                        onChange={(e) => setFormField('telegram_username', e.target.value.replace(/^@/, ''))}
                                        label="Telegram @username (необязательно)"
                                        placeholder="username (без @)"
                                    />
                                </div>
                            )}

                            <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
                                <select
                                    value={form.role}
                                    onChange={(e) => setFormField('role', e.target.value as 'admin' | 'operator')}
                                    className="input-base settings-native-select"
                                >
                                    <option value="operator">operator</option>
                                    <option value="admin">admin</option>
                                </select>

                                <Input
                                    type="number"
                                    value={String(form.session_ttl_days)}
                                    onChange={(e) => {
                                        const raw = Number(e.target.value);
                                        setFormField('session_ttl_days', Number.isFinite(raw) ? raw : 7);
                                    }}
                                    label="TTL сессии (дней)"
                                    min={1}
                                    max={90}
                                    error={formErrors.session_ttl_days || null}
                                />

                                <label className="flex items-center gap-2 text-sm">
                                    <input
                                        type="checkbox"
                                        checked={form.is_active}
                                        onChange={(e) => setFormField('is_active', e.target.checked)}
                                    />
                                    Активен
                                </label>

                                <label className="flex items-center gap-2 text-sm">
                                    <input
                                        type="checkbox"
                                        checked={form.can_toggle_sources}
                                        onChange={(e) => setFormField('can_toggle_sources', e.target.checked)}
                                    />
                                    Переключение источников
                                </label>
                                <label className="flex items-center gap-2 text-sm">
                                    <input
                                        type="checkbox"
                                        checked={form.force_2fa}
                                        onChange={(e) => setFormField('force_2fa', e.target.checked)}
                                    />
                                    Обязательная 2FA
                                </label>
                            </div>

                            <div>
                                <div className="text-sm text-foreground-secondary mb-2">Разрешенные вкладки</div>
                                {isAdminRole ? (
                                    <div className="mb-2 text-xs text-foreground-muted">
                                        Для роли <span className="font-semibold">admin</span> всегда включен полный доступ ко всем вкладкам.
                                        Изменение списка вкладок доступно для роли <span className="font-semibold">operator</span>.
                                    </div>
                                ) : null}
                                <div className="flex flex-wrap gap-3">
                                    {TAB_OPTIONS.map((tab) => (
                                        <label key={tab.key} className="flex items-center gap-2 text-sm">
                                            <input
                                                type="checkbox"
                                                checked={form.allowed_tabs.includes(tab.key)}
                                                disabled={isAdminRole}
                                                onChange={(e) => {
                                                    setForm((prev) => {
                                                        const next = new Set(prev.allowed_tabs);
                                                        if (e.target.checked) next.add(tab.key);
                                                        else next.delete(tab.key);
                                                        return { ...prev, allowed_tabs: Array.from(next) };
                                                    });
                                                    setFormErrors((prev) => {
                                                        const next = { ...prev };
                                                        delete next.allowed_tabs;
                                                        return next;
                                                    });
                                                }}
                                            />
                                            {tab.label}
                                        </label>
                                    ))}
                                </div>
                                {formErrors.allowed_tabs ? <p className="mt-1 text-xs text-danger">{formErrors.allowed_tabs}</p> : null}
                            </div>

                            <div>
                                <div className="text-sm text-foreground-secondary mb-2">Разрешенные папки (scopes)</div>
                                <div className="flex flex-wrap gap-3">
                                    {(scopesQuery.data || []).map((scope) => (
                                        <label key={scope.id} className="flex items-center gap-2 text-sm">
                                            <input
                                                type="checkbox"
                                                checked={form.allowed_folders.includes(scope.id)}
                                                onChange={(e) => {
                                                    setForm((prev) => {
                                                        const next = new Set(prev.allowed_folders);
                                                        if (e.target.checked) next.add(scope.id);
                                                        else next.delete(scope.id);
                                                        return { ...prev, allowed_folders: Array.from(next) };
                                                    });
                                                }}
                                            />
                                            {scope.name}
                                        </label>
                                    ))}
                                </div>
                            </div>

                            <div>
                                <div className="text-sm text-foreground-secondary mb-2">Запрещённые периоды</div>
                                <ForbiddenPeriodsEditor
                                    value={form.forbidden_periods}
                                    onChange={(rows) => setForm((prev) => ({ ...prev, forbidden_periods: rows }))}
                                />
                            </div>

                            <div className="flex items-center gap-2">
                                <Button
                                    onClick={() => {
                                        const validationErrors = validateForm(form);
                                        setFormErrors(validationErrors);
                                        if (Object.keys(validationErrors).length > 0) {
                                            const firstError =
                                                Object.values(validationErrors).find((message) => Boolean(message)) ||
                                                'Проверьте поля формы';
                                            showToast('error', firstError);
                                            return;
                                        }
                                        saveUserMutation.mutate();
                                    }}
                                    disabled={saveUserMutation.isPending}
                                >
                                    {saveUserMutation.isPending ? 'Сохраняем...' : 'Сохранить'}
                                </Button>
                                <Button
                                    onClick={() => {
                                        setIsEditorOpen(false);
                                        setForm(emptyForm());
                                        setFormErrors({});
                                    }}
                                    variant="secondary"
                                >
                                    Отмена
                                </Button>
                            </div>
                        </div>
                    )}
                </section>
            </div>
        </div>
    );
};
