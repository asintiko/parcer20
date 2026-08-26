import React, { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
    User as UserIcon,
    Shield,
    Palette,
    Users,
    FolderLock,
    CalendarOff,
    SlidersHorizontal,
    Download,
    Activity,
    LogOut,
    Search,
    Plus,
    RefreshCw,
    Check,
    Sun,
    Moon,
    Monitor,
} from 'lucide-react';
import { adminApi } from '../services/api';
import { useUpdater } from '../hooks/useUpdater';
import { useToast } from '../components/Toast';
import { PeriodsManager } from '../components/PeriodsManager';
import { SystemSettingsPanel } from '../components/SystemSettingsPanel';
import { SessionsManager } from '../components/SessionsManager';
import { UserEditorSheet, type UserEditorMode, type AdminUserLike } from '../components/UserEditorSheet';
import { UserRowMenu } from '../components/UserRowMenu';
import { AccessMatrixPanel } from '../components/AccessMatrixPanel';
import { TwoFactorPanel } from '../components/TwoFactorPanel';
import { PromptModal } from '../components/PromptModal';
import { ConfirmDialog } from '../components/motion/ConfirmDialog';
import { useAuth } from '../contexts/AuthContext';
import { useTheme } from '../contexts/ThemeContext';
import '../styles/settings.css';

type SectionKey =
    | 'profile'
    | 'security'
    | 'appearance'
    | 'users'
    | 'access'
    | 'periods'
    | 'system'
    | 'updates'
    | 'sessions';

type GroupKey = 'personal' | 'team' | 'system';

type SectionDef = {
    key: SectionKey;
    label: string;
    icon: React.ComponentType<any>;
    group: GroupKey;
    adminOnly?: boolean;
    description?: string;
};

const SECTIONS: SectionDef[] = [
    { key: 'profile', label: 'Профиль', icon: UserIcon, group: 'personal',
      description: 'Имя, контакты, выход из аккаунта.' },
    { key: 'security', label: 'Безопасность', icon: Shield, group: 'personal',
      description: '2FA, активные сессии, история входов.' },
    { key: 'appearance', label: 'Внешний вид', icon: Palette, group: 'personal',
      description: 'Тема и плотность интерфейса.' },
    { key: 'users', label: 'Пользователи', icon: Users, group: 'team', adminOnly: true,
      description: 'Создание и управление учётными записями команды.' },
    { key: 'access', label: 'Доступы и папки', icon: FolderLock, group: 'team', adminOnly: true,
      description: 'Системные тогглы, влияющие на права.' },
    { key: 'periods', label: 'Заблокир. периоды', icon: CalendarOff, group: 'team', adminOnly: true,
      description: 'Запрет редактирования транзакций в указанных датах.' },
    { key: 'system', label: 'Системные', icon: SlidersHorizontal, group: 'system', adminOnly: true,
      description: 'OTP, бот, 2FA, gate запуска.' },
    { key: 'updates', label: 'Обновления', icon: Download, group: 'system',
      description: 'Версии и автообновление desktop-приложения.' },
    { key: 'sessions', label: 'Сессии', icon: Activity, group: 'system', adminOnly: true,
      description: 'Активные сессии всех пользователей.' },
];

const GROUP_LABEL: Record<GroupKey, string> = {
    personal: 'Личное',
    team: 'Команда',
    system: 'Система',
};

const PROMPT_PASSWORD_HINT = 'Минимум 8 символов: A-Z, a-z, 0-9, спецсимвол';
const validateStrongPassword = (v: string): string | null => {
    const p = v || '';
    const strong =
        p.length >= 8 && /[a-z]/.test(p) && /[A-Z]/.test(p) && /\d/.test(p) && /[^A-Za-z0-9]/.test(p);
    if (!p) return 'Пароль обязателен';
    if (!strong) return PROMPT_PASSWORD_HINT;
    return null;
};

const validateTelegramId = (v: string): string | null => {
    const n = Number(v.trim());
    if (!Number.isFinite(n) || n <= 0) return 'Telegram ID должен быть положительным числом';
    return null;
};

export const SettingsPage: React.FC = () => {
    const { user, logout, hasTab } = useAuth();
    const { showToast } = useToast();
    const queryClient = useQueryClient();
    const { isDark, theme, setTheme } = useTheme();

    const isAdmin = user?.role === 'admin';
    const visibleSections = useMemo(
        () => SECTIONS.filter((s) => !s.adminOnly || isAdmin),
        [isAdmin],
    );

    // Section selection from URL hash so deep-links survive
    const initialSection = (): SectionKey => {
        const raw = (window.location.hash || '').replace('#', '') as SectionKey;
        return visibleSections.some((s) => s.key === raw) ? raw : visibleSections[0]?.key || 'profile';
    };
    const [active, setActive] = useState<SectionKey>(initialSection);

    useEffect(() => {
        const handler = () => {
            const raw = (window.location.hash || '').replace('#', '') as SectionKey;
            if (visibleSections.some((s) => s.key === raw)) setActive(raw);
        };
        window.addEventListener('hashchange', handler);
        return () => window.removeEventListener('hashchange', handler);
    }, [visibleSections]);

    const goSection = (k: SectionKey) => {
        setActive(k);
        if (window.location.hash.replace('#', '') !== k) {
            window.history.replaceState(null, '', `#${k}`);
        }
    };

    // Logout
    const [logoutLoading, setLogoutLoading] = useState(false);
    const [logoutOpen, setLogoutOpen] = useState(false);
    const handleLogoutConfirm = async () => {
        setLogoutOpen(false);
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
    const handleLogout = () => setLogoutOpen(true);

    // ───── Users management ─────
    const usersQuery = useQuery({
        queryKey: ['admin-users'],
        queryFn: () => adminApi.listUsers(true),
        enabled: isAdmin,
    });

    const [userSearch, setUserSearch] = useState('');
    const [userRoleFilter, setUserRoleFilter] = useState<'all' | 'admin' | 'operator'>('all');
    const [editorMode, setEditorMode] = useState<UserEditorMode | null>(null);
    const [openMenuFor, setOpenMenuFor] = useState<number | null>(null);

    const filteredUsers = useMemo(() => {
        const list = usersQuery.data || [];
        const q = userSearch.trim().toLowerCase();
        return list.filter((u) => {
            if (userRoleFilter !== 'all' && u.role !== userRoleFilter) return false;
            if (!q) return true;
            return (
                u.username.toLowerCase().includes(q) ||
                (u.display_name || '').toLowerCase().includes(q) ||
                (u.telegram_username || '').toLowerCase().includes(q)
            );
        });
    }, [usersQuery.data, userSearch, userRoleFilter]);

    // ───── User row mutations ─────

    // ───── User row mutations ─────
    const resetPasswordMutation = useMutation({
        mutationFn: ({ userId, password }: { userId: number; password: string }) =>
            adminApi.resetPassword(userId, password),
        onSuccess: () => {
            showToast('success', 'Пароль сброшен');
            queryClient.invalidateQueries({ queryKey: ['admin-users'] });
            setPromptState(null);
        },
        onError: (err: any) => {
            const detail = err?.response?.data?.detail;
            if (detail === 'weak_password') {
                setPromptState((prev) => prev ? { ...prev, serverError: PROMPT_PASSWORD_HINT } : prev);
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
        onError: (err: any) => showToast('error', err?.response?.data?.detail || 'Не удалось сбросить 2FA'),
    });

    const force2faMutation = useMutation({
        mutationFn: ({ userId, force }: { userId: number; force: boolean }) =>
            adminApi.force2fa(userId, force),
        onSuccess: () => {
            showToast('success', 'Флаг force_2fa обновлён');
            queryClient.invalidateQueries({ queryKey: ['admin-users'] });
        },
        onError: (err: any) => showToast('error', err?.response?.data?.detail || 'Не удалось обновить'),
    });

    const unlockMutation = useMutation({
        mutationFn: (userId: number) => adminApi.unlockUser(userId),
        onSuccess: () => {
            showToast('success', 'Пользователь разблокирован');
            queryClient.invalidateQueries({ queryKey: ['admin-users'] });
        },
        onError: (err: any) => showToast('error', err?.response?.data?.detail || 'Ошибка разблокировки'),
    });

    const deactivateMutation = useMutation({
        mutationFn: (userId: number) => adminApi.deactivateUser(userId),
        onSuccess: () => {
            showToast('success', 'Пользователь деактивирован');
            queryClient.invalidateQueries({ queryKey: ['admin-users'] });
        },
        onError: (err: any) => showToast('error', err?.response?.data?.detail || 'Ошибка'),
    });

    const activateMutation = useMutation({
        mutationFn: (userId: number) => adminApi.updateUser(userId, { is_active: true }),
        onSuccess: () => {
            showToast('success', 'Пользователь активирован');
            queryClient.invalidateQueries({ queryKey: ['admin-users'] });
        },
        onError: (err: any) => showToast('error', err?.response?.data?.detail || 'Ошибка'),
    });

    const linkTelegramMutation = useMutation({
        mutationFn: ({ userId, telegram_id, telegram_username }: { userId: number; telegram_id: number; telegram_username?: string }) =>
            adminApi.linkTelegram(userId, telegram_id, telegram_username),
        onSuccess: () => {
            showToast('success', 'Telegram привязан');
            queryClient.invalidateQueries({ queryKey: ['admin-users'] });
            setPromptState(null);
        },
        onError: (err: any) => {
            const detail = err?.response?.data?.detail;
            if (detail === 'telegram_id_already_linked') {
                setPromptState((prev) => prev ? { ...prev, serverError: 'Этот Telegram ID уже привязан к другому пользователю' } : prev);
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
        onError: (err: any) => showToast('error', err?.response?.data?.detail || 'Ошибка отвязки'),
    });

    // ───── Prompts (replace window.prompt) ─────
    type PromptState = {
        kind: 'reset-password' | 'link-telegram-id' | 'link-telegram-username';
        userId: number;
        username: string;
        title: string;
        description?: React.ReactNode;
        label?: string;
        placeholder?: string;
        confirmLabel?: string;
        inputType?: 'text' | 'password' | 'numeric';
        validate?: (v: string) => string | null;
        serverError?: string | null;
        // for 2-step telegram link, carry partial state
        telegramId?: number;
    } | null;
    const [promptState, setPromptState] = useState<PromptState>(null);

    const openResetPassword = (u: AdminUserLike) =>
        setPromptState({
            kind: 'reset-password',
            userId: u.id,
            username: u.username,
            title: `Сбросить пароль: ${u.username}`,
            description: 'Новый пароль будет передан пользователю вне приложения.',
            label: 'Новый пароль',
            placeholder: '••••••••',
            confirmLabel: 'Сбросить',
            inputType: 'password',
            validate: validateStrongPassword,
        });

    const openLinkTelegram = (u: AdminUserLike) =>
        setPromptState({
            kind: 'link-telegram-id',
            userId: u.id,
            username: u.username,
            title: `Привязать Telegram: ${u.username}`,
            description: 'Шаг 1 из 2 — Telegram ID пользователя.',
            label: 'Telegram ID',
            placeholder: '123456789',
            confirmLabel: 'Далее',
            inputType: 'numeric',
            validate: validateTelegramId,
        });

    const handlePromptSubmit = (raw: string) => {
        if (!promptState) return;
        const value = raw.trim();
        if (promptState.kind === 'reset-password') {
            resetPasswordMutation.mutate({ userId: promptState.userId, password: raw });
        } else if (promptState.kind === 'link-telegram-id') {
            const tgId = Number(value);
            setPromptState({
                kind: 'link-telegram-username',
                userId: promptState.userId,
                username: promptState.username,
                title: `Привязать Telegram: ${promptState.username}`,
                description: 'Шаг 2 из 2 — @username (необязательно, можно оставить пустым).',
                label: 'Telegram @username',
                placeholder: 'username',
                confirmLabel: 'Привязать',
                inputType: 'text',
                telegramId: tgId,
            });
        } else if (promptState.kind === 'link-telegram-username') {
            const tgU = value.replace(/^@/, '') || undefined;
            linkTelegramMutation.mutate({
                userId: promptState.userId,
                telegram_id: promptState.telegramId!,
                telegram_username: tgU,
            });
        }
    };

    // ───── Updater ─────
    const updater = useUpdater();
    const renderUpdateStatus = () => {
        switch (updater.status) {
            case 'checking': return 'Проверка обновлений…';
            case 'available': return 'Найдена новая версия.';
            case 'not-available': return 'Установлена последняя версия.';
            case 'downloading': return `Скачивание… ${updater.progress?.percent ? Math.round(updater.progress.percent) + '%' : ''}`;
            case 'downloaded': return 'Обновление скачано. Можно установить.';
            case 'error': return updater.error || 'Ошибка обновления.';
            default: return 'Готово.';
        }
    };

    const updaterPill = (): { label: string; mod: string } => {
        switch (updater.status) {
            case 'available': return { label: 'есть обновление', mod: 'is-warning' };
            case 'downloading': return { label: 'загрузка', mod: 'is-warning' };
            case 'downloaded': return { label: 'готово к установке', mod: 'is-success' };
            case 'not-available': return { label: 'актуально', mod: 'is-success' };
            case 'error': return { label: 'ошибка', mod: 'is-danger' };
            case 'checking': return { label: 'проверка', mod: '' };
            default: return { label: 'готово', mod: '' };
        }
    };

    // ───── User identity hero ─────
    const initials = useMemo(() => {
        const src = user?.display_name?.trim() || user?.username?.trim() || '?';
        const parts = src.split(/\s+/).filter(Boolean);
        if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
        return src.slice(0, 2).toUpperCase();
    }, [user]);

    // ───── Keyboard shortcuts (admin) ─────
    useEffect(() => {
        if (!isAdmin) return;
        const onKey = (e: KeyboardEvent) => {
            if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
            if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k' && active === 'users') {
                e.preventDefault();
                document.getElementById('sp-user-search')?.focus();
            }
            if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'n' && active === 'users') {
                e.preventDefault();
                setEditorMode({ kind: 'create' });
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [isAdmin, active]);

    const renderProfile = () => (
        <div className="sp-page">
            <header className="sp-page-head">
                <div>
                    <h1 className="sp-page-title">Профиль</h1>
                    <p className="sp-page-sub">
                        Информация о вашей учётной записи и кнопка выхода. Логин и пароль может изменить только администратор.
                    </p>
                </div>
            </header>

            <div className="sp-profile-hero">
                <div className="sp-avatar lg" aria-hidden>{initials}</div>
                <div className="sp-profile-meta">
                    <div className="sp-profile-name">{user?.display_name || user?.username || '—'}</div>
                    <div className="sp-profile-sub">
                        <span className={`sp-pill ${user?.role === 'admin' ? 'is-accent' : ''}`}>
                            {user?.role || '—'}
                        </span>
                        <span className="sp-chip sp-chip-mono">@{user?.username}</span>
                        {user?.totp_enabled ? (
                            <span className="sp-pill is-success"><span className="sp-pill-dot" />2FA</span>
                        ) : (
                            <span className="sp-pill is-warning"><span className="sp-pill-dot" />2FA отключена</span>
                        )}
                    </div>
                </div>
                <div className="sp-profile-actions">
                    <button
                        type="button"
                        className="sp-btn sp-btn-danger"
                        onClick={handleLogout}
                        disabled={logoutLoading}
                    >
                        {logoutLoading ? (
                            <><span className="sp-btn-spinner" />Выход…</>
                        ) : (
                            <><LogOut size={13} />Выйти</>
                        )}
                    </button>
                </div>
            </div>

            <div className="sp-card">
                <div className="sp-card-head">
                    <div>
                        <h2 className="sp-card-title">Учётная запись</h2>
                        <div className="sp-card-sub">Эти поля управляются администратором.</div>
                    </div>
                </div>
                <div className="sp-card-body">
                    <div className="sp-card-row">
                        <div>
                            <div className="sp-row-label">Логин</div>
                            <div className="sp-row-hint">Используется для входа в систему.</div>
                        </div>
                        <div className="sp-row-control">
                            <input value={user?.username || ''} disabled className="sp-input is-mono" />
                        </div>
                    </div>
                    <div className="sp-card-row">
                        <div>
                            <div className="sp-row-label">Отображаемое имя</div>
                            <div className="sp-row-hint">Видно в шапке и в логах действий.</div>
                        </div>
                        <div className="sp-row-control">
                            <input value={user?.display_name || ''} disabled className="sp-input" />
                        </div>
                    </div>
                    <div className="sp-card-row">
                        <div>
                            <div className="sp-row-label">Роль</div>
                            <div className="sp-row-hint">Определяет, какие разделы доступны.</div>
                        </div>
                        <div className="sp-row-control">
                            <span className={`sp-pill ${user?.role === 'admin' ? 'is-accent' : ''}`} style={{ alignSelf: 'flex-start' }}>
                                {user?.role || '—'}
                            </span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );

    const renderAppearance = () => {
        const themeMap: Record<typeof theme, string> = {
            light: 'светлая',
            dark: 'тёмная',
            system: 'системная',
        } as const;
        return (
        <div className="sp-page">
            <header className="sp-page-head">
                <div>
                    <h1 className="sp-page-title">Внешний вид</h1>
                    <p className="sp-page-sub">Тема интерфейса. Системный режим следует за настройкой ОС.</p>
                </div>
            </header>

            <div className="sp-card">
                <div className="sp-card-head">
                    <div>
                        <h2 className="sp-card-title">Тема</h2>
                        <div className="sp-card-sub">
                            Сейчас активна <b>{themeMap[theme]}</b>
                            {theme === 'system' ? ` · фактически ${isDark ? 'тёмная' : 'светлая'}` : ''}
                        </div>
                    </div>
                </div>
                <div className="sp-card-body">
                    <div className="sp-chipgrid">
                        {([
                            { key: 'light', label: 'Светлая', Icon: Sun },
                            { key: 'dark', label: 'Тёмная', Icon: Moon },
                            { key: 'system', label: 'Системная', Icon: Monitor },
                        ] as const).map(({ key, label, Icon }) => (
                            <button
                                key={key}
                                type="button"
                                className={['sp-chip-toggle', theme === key ? 'is-active' : ''].filter(Boolean).join(' ')}
                                onClick={() => setTheme(key)}
                                aria-pressed={theme === key}
                            >
                                <Icon size={12} />
                                {label}
                                {theme === key ? <Check size={11} /> : null}
                            </button>
                        ))}
                    </div>
                </div>
            </div>
        </div>
        );
    };

    const renderSecurity = () => (
        <div className="sp-page">
            <header className="sp-page-head">
                <div>
                    <h1 className="sp-page-title">Безопасность</h1>
                    <p className="sp-page-sub">Двухфакторная аутентификация и активные сессии текущего пользователя.</p>
                </div>
            </header>

            <TwoFactorPanel
                forceLocked={Boolean(user?.force_2fa)}
                onSuccess={(msg) => showToast('success', msg)}
                onError={(msg) => showToast('error', msg)}
            />
        </div>
    );

    const renderUpdates = () => {
        const pill = updaterPill();
        return (
        <div className="sp-page">
            <header className="sp-page-head">
                <div>
                    <h1 className="sp-page-title">Обновления</h1>
                    <p className="sp-page-sub">
                        {updater.isElectron
                            ? 'Desktop-режим Electron, автообновления доступны.'
                            : 'Запущено в браузере — автообновления недоступны.'}
                    </p>
                </div>
            </header>

            <div className="sp-card">
                <div className="sp-card-head">
                    <div>
                        <h2 className="sp-card-title">Версия приложения</h2>
                        <div className="sp-card-sub">
                            <span className="sp-chip sp-chip-mono">{updater.version || '—'}</span>
                        </div>
                    </div>
                    {updater.isElectron ? (
                        <span className={`sp-pill ${pill.mod}`.trim()}>
                            <span className="sp-pill-dot" />
                            {pill.label}
                        </span>
                    ) : null}
                </div>
                <div className="sp-card-body">
                    <div className="sp-update">
                        <div className="sp-update-status">
                            {updater.status === 'downloading' || updater.status === 'checking' ? (
                                <RefreshCw size={14} className="sp-rotating" />
                            ) : null}
                            <span>{renderUpdateStatus()}</span>
                        </div>
                        <div style={{ display: 'inline-flex', gap: 8 }}>
                            <button
                                onClick={updater.check}
                                disabled={!updater.isElectron || updater.status === 'checking'}
                                className="sp-btn"
                            >
                                <RefreshCw size={13} />
                                Проверить
                            </button>
                            <button
                                onClick={updater.download}
                                disabled={!updater.isElectron || updater.status !== 'available'}
                                className="sp-btn"
                            >
                                <Download size={13} />
                                Скачать
                            </button>
                            <button
                                onClick={updater.install}
                                disabled={!updater.isElectron || updater.status !== 'downloaded'}
                                className="sp-btn sp-btn-primary"
                            >
                                Установить и перезапустить
                            </button>
                        </div>
                    </div>
                    {updater.status === 'downloading' && updater.progress?.percent ? (
                        <div className="sp-progress" aria-label="Прогресс загрузки">
                            <div
                                className="sp-progress-bar"
                                style={{ transform: `scaleX(${Math.max(0, Math.min(1, updater.progress.percent / 100))})` }}
                            />
                        </div>
                    ) : null}
                    {!updater.isElectron ? (
                        <div className="sp-row-hint">
                            Чтобы получать автоматические обновления, откройте десктоп-версию TBSparcer.
                        </div>
                    ) : null}
                </div>
            </div>
        </div>
        );
    };

    const renderSystem = () => (
        <div className="sp-page">
            <header className="sp-page-head">
                <div>
                    <h1 className="sp-page-title">Системные настройки</h1>
                    <p className="sp-page-sub">Глобальные тогглы, влияющие на все учётные записи.</p>
                </div>
            </header>
            <SystemSettingsPanel showToast={showToast} />
        </div>
    );

    const renderPeriods = () => (
        <div className="sp-page">
            <header className="sp-page-head">
                <div>
                    <h1 className="sp-page-title">Заблокированные периоды</h1>
                    <p className="sp-page-sub">
                        Запрет на любые правки транзакций в указанных диапазонах. Применяется ко всем пользователям.
                    </p>
                </div>
            </header>
            <PeriodsManager showToast={showToast} />
        </div>
    );

    const renderSessions = () => (
        <div className="sp-page">
            <header className="sp-page-head">
                <div>
                    <h1 className="sp-page-title">Активные сессии</h1>
                    <p className="sp-page-sub">Все активные токены и устройства команды.</p>
                </div>
            </header>
            <SessionsManager showToast={showToast} />
        </div>
    );

    const renderAccess = () => (
        <div className="sp-page">
            <header className="sp-page-head">
                <div>
                    <h1 className="sp-page-title">Доступы и папки</h1>
                    <p className="sp-page-sub">
                        Матрица «пользователь × папка». Изменения применяются сразу.
                    </p>
                </div>
            </header>
            <AccessMatrixPanel
                onSuccess={(msg) => showToast('success', msg)}
                onError={(msg) => showToast('error', msg)}
            />
        </div>
    );

    const renderUsers = () => (
        <div className="sp-page">
            <header className="sp-page-head">
                <div>
                    <h1 className="sp-page-title">Пользователи</h1>
                    <p className="sp-page-sub">
                        Создание учётных записей, изменение ролей, доступов и принудительной 2FA.
                    </p>
                </div>
                <button
                    type="button"
                    className="sp-btn sp-btn-primary"
                    onClick={() => setEditorMode({ kind: 'create' })}
                >
                    <Plus size={13} />
                    Добавить
                    <span className="sp-kbd">⌘N</span>
                </button>
            </header>

            <div className="sp-card">
                <div className="sp-card-head">
                    <div>
                        <h2 className="sp-card-title">Учётные записи</h2>
                        <div className="sp-card-sub">
                            Кликните по строке, чтобы открыть карточку и изменить роль или доступы.
                        </div>
                    </div>
                    <span className="sp-chip sp-chip-mono">
                        всего · {(usersQuery.data || []).length}
                    </span>
                </div>
                <div className="sp-toolbar">
                    <div className="sp-toolbar-search">
                        <div className="sp-input-wrap">
                            <Search size={14} className="sp-input-icon" />
                            <input
                                id="sp-user-search"
                                type="text"
                                value={userSearch}
                                onChange={(e) => setUserSearch(e.target.value)}
                                placeholder="Поиск по логину или имени"
                                className="sp-input"
                            />
                            <span className="sp-input-trail" style={{ pointerEvents: 'none' }}>⌘K</span>
                        </div>
                    </div>
                    <select
                        value={userRoleFilter}
                        onChange={(e) => setUserRoleFilter(e.target.value as 'all' | 'admin' | 'operator')}
                        className="sp-select"
                        style={{ width: 'auto', minWidth: 140 }}
                    >
                        <option value="all">Все роли</option>
                        <option value="admin">Только admin</option>
                        <option value="operator">Только operator</option>
                    </select>
                    <span className="sp-toolbar-spacer" />
                    <span className="sp-toolbar-meta">
                        {filteredUsers.length} из {(usersQuery.data || []).length}
                    </span>
                </div>

                {usersQuery.isLoading ? (
                    <div className="sp-empty">
                        <div className="sp-empty-title">Загружаем пользователей…</div>
                    </div>
                ) : filteredUsers.length === 0 ? (
                    (usersQuery.data || []).length === 0 ? (
                        <div className="sp-empty">
                            <div className="sp-empty-title">Пока нет пользователей</div>
                            <div>Создайте первую учётную запись через кнопку «Добавить».</div>
                        </div>
                    ) : (
                        <div className="sp-empty">
                            <div className="sp-empty-title">Никого не найдено</div>
                            <div>Попробуйте изменить запрос или фильтр.</div>
                        </div>
                    )
                ) : (
                    <div className="sp-table-wrap">
                        <table className="sp-table">
                            <thead>
                                <tr>
                                    <th>Пользователь</th>
                                    <th>Роль</th>
                                    <th>Вкладки</th>
                                    <th>2FA</th>
                                    <th>Telegram</th>
                                    <th>Статус</th>
                                    <th className="sp-cell-actions">Действия</th>
                                </tr>
                            </thead>
                            <tbody>
                                {filteredUsers.map((u) => {
                                    const tabsCount = (u.allowed_tabs || []).length;
                                    const status = !u.is_active ? 'disabled' : 'active';
                                    return (
                                        <tr key={u.id}>
                                            <td>
                                                <button
                                                    className="sp-row-edit"
                                                    onClick={() => setEditorMode({ kind: 'edit', user: u as AdminUserLike })}
                                                    title="Открыть карточку"
                                                >
                                                    <div className="sp-avatar" aria-hidden style={{ width: 24, height: 24, fontSize: 10, borderRadius: 6 }}>
                                                        {(u.display_name || u.username).slice(0, 2).toUpperCase()}
                                                    </div>
                                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 }}>
                                                        <span className="sp-cell-strong">{u.display_name || u.username}</span>
                                                        <span className="sp-cell-mono">@{u.username}</span>
                                                    </div>
                                                </button>
                                            </td>
                                            <td>
                                                <span className={`sp-pill ${u.role === 'admin' ? 'is-accent' : ''}`}>
                                                    {u.role}
                                                </span>
                                            </td>
                                            <td>
                                                {u.role === 'admin' ? (
                                                    <span className="sp-chip">все ({tabsCount})</span>
                                                ) : (
                                                    <span className="sp-chip">{tabsCount}</span>
                                                )}
                                            </td>
                                            <td>
                                                {u.totp_enabled ? (
                                                    <span className="sp-pill is-success">включена</span>
                                                ) : u.force_2fa ? (
                                                    <span className="sp-pill is-warning">принудит.</span>
                                                ) : (
                                                    <span className="sp-chip">—</span>
                                                )}
                                            </td>
                                            <td>
                                                {u.telegram_id ? (
                                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                                                        <span className="sp-cell-mono">{u.telegram_id}</span>
                                                        {u.telegram_username ? (
                                                            <span className="sp-cell-mono" style={{ color: 'var(--sp-ink-soft)' }}>
                                                                @{u.telegram_username}
                                                            </span>
                                                        ) : null}
                                                    </div>
                                                ) : (
                                                    <span className="sp-chip">—</span>
                                                )}
                                            </td>
                                            <td>
                                                <span className={`sp-pill ${status === 'active' ? 'is-success' : 'is-danger'}`}>
                                                    <span className="sp-pill-dot" />
                                                    {status === 'active' ? 'активен' : 'отключён'}
                                                </span>
                                            </td>
                                            <td className="sp-cell-actions">
                                                <div style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                                                    <button
                                                        type="button"
                                                        className="sp-btn sp-btn-sm"
                                                        onClick={() => setEditorMode({ kind: 'edit', user: u as AdminUserLike })}
                                                    >
                                                        Открыть
                                                    </button>
                                                    <UserRowMenu
                                                        user={u as AdminUserLike}
                                                        open={openMenuFor === u.id}
                                                        onToggle={() => setOpenMenuFor((prev) => (prev === u.id ? null : u.id))}
                                                        onClose={() => setOpenMenuFor(null)}
                                                        onResetPassword={(user) => openResetPassword(user)}
                                                        onReset2fa={(id) => reset2faMutation.mutate(id)}
                                                        onForce2fa={(id, force) => force2faMutation.mutate({ userId: id, force })}
                                                        onUnlock={(id) => unlockMutation.mutate(id)}
                                                        onLinkTelegram={(user) => openLinkTelegram(user)}
                                                        onUnlinkTelegram={(id) => unlinkTelegramMutation.mutate(id)}
                                                        onActivate={(id) => activateMutation.mutate(id)}
                                                        onDeactivate={(id) => deactivateMutation.mutate(id)}
                                                    />
                                                </div>
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </div>
    );

    const renderActiveSection = () => {
        switch (active) {
            case 'profile': return renderProfile();
            case 'security': return renderSecurity();
            case 'appearance': return renderAppearance();
            case 'users': return isAdmin ? renderUsers() : renderProfile();
            case 'access': return isAdmin ? renderAccess() : renderProfile();
            case 'periods': return isAdmin ? renderPeriods() : renderProfile();
            case 'system': return isAdmin ? renderSystem() : renderProfile();
            case 'updates': return renderUpdates();
            case 'sessions': return isAdmin ? renderSessions() : renderProfile();
            default: return renderProfile();
        }
    };

    const activeSection = visibleSections.find((s) => s.key === active) || visibleSections[0];

    // suppress unused warnings for parts of public API we don't render
    void hasTab;

    return (
        <div className="sp-shell">
            {/* Sidebar */}
            <aside className="sp-sidebar" aria-label="Разделы настроек">
                {(['personal', 'team', 'system'] as GroupKey[]).map((group) => {
                    const items = visibleSections.filter((s) => s.group === group);
                    if (!items.length) return null;
                    return (
                        <div key={group} className="sp-nav-group">
                            <div className="sp-nav-label">{GROUP_LABEL[group]}</div>
                            {items.map((s) => {
                                const Icon = s.icon;
                                return (
                                    <button
                                        key={s.key}
                                        type="button"
                                        className={['sp-nav-item', active === s.key ? 'is-active' : ''].filter(Boolean).join(' ')}
                                        onClick={() => goSection(s.key)}
                                        aria-current={active === s.key ? 'page' : undefined}
                                    >
                                        <Icon size={14} className="sp-nav-icon" />
                                        {s.label}
                                        {s.key === 'users' && usersQuery.data ? (
                                            <span className="sp-nav-badge">{usersQuery.data.length}</span>
                                        ) : null}
                                    </button>
                                );
                            })}
                        </div>
                    );
                })}

                <span className="sp-nav-spacer" />

                <div className="sp-nav-footer">
                    <div className="sp-nav-user">
                        <div className="sp-avatar" aria-hidden>{initials}</div>
                        <div className="sp-nav-user-meta">
                            <span className="sp-nav-user-name">{user?.display_name || user?.username || '—'}</span>
                            <span className="sp-nav-user-role">{user?.role || ''}</span>
                        </div>
                    </div>
                </div>
            </aside>

            {/* Main */}
            <main className="sp-main">
                <div className="sp-topbar">
                    <span className="sp-topbar-path">
                        settings <span style={{ opacity: 0.5 }}>/</span>
                        <span className="sp-current">{activeSection?.label}</span>
                    </span>
                    <span className="sp-topbar-spacer" />
                    {active === 'users' && isAdmin ? (
                        <span className="sp-kbd-group">
                            <span className="sp-kbd">⌘K</span><span>поиск</span>
                            <span style={{ marginLeft: 8 }} />
                            <span className="sp-kbd">⌘N</span><span>новый</span>
                        </span>
                    ) : null}
                </div>

                <div className="sp-content">
                    {renderActiveSection()}
                </div>
            </main>

            {isAdmin ? (
                <UserEditorSheet
                    open={editorMode !== null}
                    mode={editorMode}
                    onClose={() => setEditorMode(null)}
                    onSuccess={(action) =>
                        showToast('success', action === 'created' ? 'Пользователь создан' : 'Пользователь обновлён')
                    }
                    onError={(msg) => showToast('error', msg)}
                />
            ) : null}

            {promptState ? (
                <PromptModal
                    open
                    title={promptState.title}
                    description={promptState.description}
                    label={promptState.label}
                    placeholder={promptState.placeholder}
                    confirmLabel={promptState.confirmLabel}
                    inputType={promptState.inputType}
                    validate={promptState.validate}
                    serverError={promptState.serverError}
                    submitting={resetPasswordMutation.isPending || linkTelegramMutation.isPending}
                    onClose={() => setPromptState(null)}
                    onSubmit={handlePromptSubmit}
                />
            ) : null}

            <ConfirmDialog
                open={logoutOpen}
                title="Выйти из аккаунта?"
                description="Активная сессия будет завершена, на других устройствах вход сохранится."
                confirmLabel="Выйти"
                cancelLabel="Остаться"
                tone="danger"
                onConfirm={handleLogoutConfirm}
                onClose={() => setLogoutOpen(false)}
            />
        </div>
    );
};
