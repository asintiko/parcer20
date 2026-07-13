import React, { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertCircle, Check, KeyRound, Send } from 'lucide-react';
import { adminApi, securityApi, type AdminCreateUserPayload, type AdminUpdateUserPayload } from '../services/api';
import { ForbiddenPeriodsEditor, type ForbiddenPeriod } from './ForbiddenPeriodsEditor';
import { Dialog } from './motion/Dialog';
import { useShake } from '../hooks/useShake';

const TAB_OPTIONS = [
    { key: 'dashboard', label: 'Дашборд' },
    { key: 'reference', label: 'Справочник' },
    { key: 'userbot', label: 'Telegram Bots' },
    { key: 'logs', label: 'Логи' },
    { key: 'admin', label: 'Admin' },
] as const;

const ALL_TAB_KEYS = TAB_OPTIONS.map((t) => t.key);
const OPERATOR_TAB_SET = new Set<string>(ALL_TAB_KEYS.filter((k) => k !== 'admin'));

export type UserEditorMode =
    | { kind: 'create' }
    | { kind: 'edit'; user: AdminUserLike };

export type AdminUserLike = {
    id: number;
    username: string;
    role: 'admin' | 'operator';
    display_name?: string | null;
    is_active: boolean;
    allowed_tabs?: string[];
    allowed_folders?: number[];
    forbidden_periods?: ForbiddenPeriod[];
    can_toggle_sources?: boolean;
    force_2fa?: boolean;
    session_ttl_days?: number;
    telegram_id?: number | null;
    telegram_username?: string | null;
};

type FormState = {
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

type FormErrors = Partial<Record<
    'username' | 'password' | 'display_name' | 'allowed_tabs' | 'session_ttl_days',
    string
>>;

const emptyForm = (): FormState => ({
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

const ERR_MAP: Record<string, string> = {
    weak_password: 'Слабый пароль: мин. 8 символов, заглавная + строчная + цифра + спецсимвол',
    username_exists: 'Пользователь с таким логином уже существует',
    invalid_username: 'Некорректный логин',
    invalid_password: 'Пароль не задан',
    invalid_role: 'Некорректная роль',
    telegram_id_already_linked: 'Этот Telegram ID уже привязан к другому пользователю',
};

export interface UserEditorSheetProps {
    open: boolean;
    mode: UserEditorMode | null;
    onClose: () => void;
    onSuccess: (action: 'created' | 'updated') => void;
    onError: (message: string) => void;
}

export const UserEditorSheet: React.FC<UserEditorSheetProps> = ({ open, mode, onClose, onSuccess, onError }) => {
    const queryClient = useQueryClient();
    const [form, setForm] = useState<FormState>(emptyForm());
    const [errors, setErrors] = useState<FormErrors>({});
    const [shakeKey, fireShake] = useShake();

    const isCreate = mode?.kind === 'create';
    const editingUser = mode?.kind === 'edit' ? mode.user : null;

    const scopesQuery = useQuery({
        queryKey: ['security-scopes-light'],
        queryFn: securityApi.listScopes,
        enabled: open,
    });

    useEffect(() => {
        if (!open || !mode) return;
        if (mode.kind === 'create') {
            setForm(emptyForm());
            setErrors({});
        } else {
            const u = mode.user;
            setForm({
                username: u.username,
                password: '',
                role: u.role,
                display_name: u.display_name || u.username,
                is_active: u.is_active,
                allowed_tabs: u.allowed_tabs?.length ? u.allowed_tabs : ['dashboard'],
                allowed_folders: u.allowed_folders || [],
                forbidden_periods: u.forbidden_periods || [],
                can_toggle_sources: Boolean(u.can_toggle_sources),
                force_2fa: Boolean(u.force_2fa),
                session_ttl_days: Number(u.session_ttl_days || 7),
                telegram_id: u.telegram_id ? String(u.telegram_id) : '',
                telegram_username: u.telegram_username || '',
            });
            setErrors({});
        }
    }, [open, mode]);

    useEffect(() => {
        setForm((prev) => {
            if (prev.role === 'admin') {
                const all = [...ALL_TAB_KEYS];
                const same = prev.allowed_tabs.length === all.length && all.every((t) => prev.allowed_tabs.includes(t));
                return same ? prev : { ...prev, allowed_tabs: all };
            }
            const filtered = prev.allowed_tabs.filter((t) => OPERATOR_TAB_SET.has(t));
            if (!filtered.includes('dashboard')) filtered.unshift('dashboard');
            const unique = Array.from(new Set(filtered));
            const same = prev.allowed_tabs.length === unique.length && unique.every((t) => prev.allowed_tabs.includes(t));
            return same ? prev : { ...prev, allowed_tabs: unique };
        });
    }, [form.role]);

    useEffect(() => {
        if (!open) return;
        const onKey = (e: KeyboardEvent) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                document.querySelector<HTMLButtonElement>('[data-sheet-submit]')?.click();
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [open]);

    const validate = (s: FormState): FormErrors => {
        const e: FormErrors = {};
        if (isCreate) {
            const u = s.username.trim();
            if (!u) e.username = 'Логин обязателен';
            else if (!/^[a-zA-Z0-9_.-]{3,50}$/.test(u))
                e.username = 'Логин: 3-50 символов, только a-z A-Z 0-9 . _ -';
            const p = s.password || '';
            const strong =
                p.length >= 8 &&
                /[a-z]/.test(p) &&
                /[A-Z]/.test(p) &&
                /\d/.test(p) &&
                /[^A-Za-z0-9]/.test(p);
            if (!p) e.password = 'Пароль обязателен';
            else if (!strong) e.password = 'Минимум 8 символов: A-Z, a-z, 0-9 и спецсимвол';
        }
        if (!s.display_name.trim()) e.display_name = 'Отображаемое имя обязательно';
        if (!s.allowed_tabs.length) e.allowed_tabs = 'Выберите хотя бы одну вкладку';
        if (!Number.isFinite(s.session_ttl_days) || s.session_ttl_days < 1 || s.session_ttl_days > 90)
            e.session_ttl_days = 'TTL сессии должен быть от 1 до 90 дней';
        return e;
    };

    const saveMutation = useMutation({
        mutationFn: async () => {
            const base = {
                role: form.role,
                display_name: form.display_name,
                is_active: form.is_active,
                allowed_tabs: form.allowed_tabs,
                allowed_folders: form.allowed_folders,
                allowed_sources: [],
                forbidden_periods: form.forbidden_periods.filter((r) => r.from && r.to),
                can_toggle_sources: form.can_toggle_sources,
                force_2fa: form.force_2fa,
                session_ttl_days: form.session_ttl_days,
            };
            if (isCreate) {
                const tgId = form.telegram_id.trim() ? parseInt(form.telegram_id.trim(), 10) : undefined;
                const tgU = form.telegram_username.trim().replace(/^@/, '') || undefined;
                const payload: AdminCreateUserPayload = {
                    username: form.username.trim(),
                    password: form.password,
                    ...base,
                    ...(tgId && Number.isFinite(tgId) ? { telegram_id: tgId } : {}),
                    ...(tgU ? { telegram_username: tgU } : {}),
                };
                return adminApi.createUser(payload);
            }
            if (!editingUser) throw new Error('No user');
            const payload: AdminUpdateUserPayload = base;
            return adminApi.updateUser(editingUser.id, payload);
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['admin-users'] });
            onSuccess(isCreate ? 'created' : 'updated');
            onClose();
        },
        onError: (err: any) => {
            const detail = err?.response?.data?.detail;
            onError(ERR_MAP[detail] || detail || err?.message || 'Ошибка сохранения');
            fireShake();
        },
    });

    const setField = <K extends keyof FormState>(k: K, v: FormState[K]) => {
        setForm((prev) => ({ ...prev, [k]: v }));
        setErrors((prev) => {
            const next = { ...prev };
            if (k in next) delete next[k as keyof FormErrors];
            return next;
        });
    };

    const handleSubmit = () => {
        const errs = validate(form);
        setErrors(errs);
        if (Object.keys(errs).length) {
            const first = Object.values(errs).find((m) => m);
            if (first) onError(first);
            fireShake();
            return;
        }
        saveMutation.mutate();
    };

    const initials = useMemo(() => {
        const src = form.display_name?.trim() || form.username.trim() || '?';
        const parts = src.split(/\s+/).filter(Boolean);
        if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
        return src.slice(0, 2).toUpperCase();
    }, [form.display_name, form.username]);

    const isAdminRole = form.role === 'admin';

    return (
        <Dialog
            open={open && mode !== null}
            onClose={onClose}
            ariaLabel={isCreate ? 'Новый пользователь' : 'Редактирование пользователя'}
            title={isCreate ? 'Новый пользователь' : 'Редактирование'}
            description={
                isCreate ? (
                    'Логин и пароль фиксируются при создании.'
                ) : (
                    <span className="sp-identity-pills">
                        <span className="sp-chip sp-chip-mono">#{editingUser?.id}</span>
                        <span>{editingUser?.username}</span>
                    </span>
                )
            }
            width={720}
            footer={
                <>
                    <span className="sp-kbd-group sp-sheet-foot-meta">
                        <span className="sp-kbd">⌘</span>
                        <span className="sp-kbd">↵</span>
                        <span style={{ marginLeft: 4 }}>сохранить</span>
                    </span>
                    <span className="sp-spacer" />
                    <button
                        type="button"
                        className="sp-btn"
                        onClick={onClose}
                        disabled={saveMutation.isPending}
                    >
                        Отмена
                    </button>
                    <button
                        type="button"
                        data-sheet-submit
                        className="sp-btn sp-btn-primary"
                        onClick={handleSubmit}
                        disabled={saveMutation.isPending}
                    >
                        {saveMutation.isPending ? (
                            <>
                                <span className="sp-btn-spinner" aria-hidden />
                                Сохраняем
                            </>
                        ) : (
                            <>
                                <Send size={13} />
                                {isCreate ? 'Создать' : 'Сохранить'}
                            </>
                        )}
                    </button>
                </>
            }
        >
            {/* Identity preview — только для edit (для create вверху форма) */}
            {!isCreate ? (
                <div className="sp-section">
                    <div className="sp-identity-row">
                        <div className="sp-avatar lg" aria-hidden>{initials}</div>
                        <div className="sp-identity-meta">
                            <div className="sp-identity-name">
                                {form.display_name || form.username || 'Без имени'}
                            </div>
                            <div className="sp-identity-pills">
                                <span className={`sp-pill ${isAdminRole ? 'is-accent' : ''}`}>
                                    {isAdminRole ? 'admin' : 'operator'}
                                </span>
                                <span className={`sp-pill ${form.is_active ? 'is-success' : 'is-danger'}`}>
                                    <span className="sp-pill-dot" />
                                    {form.is_active ? 'активен' : 'отключён'}
                                </span>
                            </div>
                        </div>
                    </div>
                </div>
            ) : null}

            {/* Credentials */}
            {isCreate ? (
                <div className="sp-section">
                    <div className="sp-grid-2">
                        <div className="sp-field-stack">
                            <label className="sp-row-hint sp-form-label" htmlFor="ue-username">Логин</label>
                            <input
                                id="ue-username"
                                type="text"
                                value={form.username}
                                onChange={(e) => setField('username', e.target.value)}
                                placeholder="andrey_b"
                                autoComplete="off"
                                key={`username-${shakeKey}`}
                                className={['sp-input', errors.username ? 'has-error' : ''].filter(Boolean).join(' ')}
                                aria-invalid={Boolean(errors.username)}
                            />
                            {errors.username ? (
                                <div className="sp-error sp-field-error">
                                    <AlertCircle size={12} /><span>{errors.username}</span>
                                </div>
                            ) : null}
                        </div>
                        <div className="sp-field-stack">
                            <label className="sp-row-hint sp-form-label" htmlFor="ue-password">Пароль</label>
                            <input
                                id="ue-password"
                                type="password"
                                value={form.password}
                                onChange={(e) => setField('password', e.target.value)}
                                placeholder="••••••••"
                                autoComplete="new-password"
                                key={`password-${shakeKey}`}
                                className={['sp-input', errors.password ? 'has-error' : ''].filter(Boolean).join(' ')}
                                aria-invalid={Boolean(errors.password)}
                            />
                            {errors.password ? (
                                <div className="sp-error sp-field-error">
                                    <AlertCircle size={12} /><span>{errors.password}</span>
                                </div>
                            ) : (
                                <div className="sp-row-hint">8+ символов, A-Z, a-z, 0-9, спецсимвол</div>
                            )}
                        </div>
                    </div>
                </div>
            ) : null}

            {/* Profile + Role row */}
            <div className="sp-section">
                <div className="sp-grid-2">
                    <div className="sp-field-stack">
                        <label className="sp-row-hint sp-form-label" htmlFor="ue-display">Отображаемое имя</label>
                        <input
                            id="ue-display"
                            type="text"
                            value={form.display_name}
                            onChange={(e) => setField('display_name', e.target.value)}
                            placeholder="Андрей Бачинин"
                            key={`display-${shakeKey}`}
                            className={['sp-input', errors.display_name ? 'has-error' : ''].filter(Boolean).join(' ')}
                            aria-invalid={Boolean(errors.display_name)}
                        />
                        {errors.display_name ? (
                            <div className="sp-error sp-field-error">
                                <AlertCircle size={12} /><span>{errors.display_name}</span>
                            </div>
                        ) : null}
                    </div>
                    <div className="sp-field-stack">
                        <label className="sp-row-hint sp-form-label" htmlFor="ue-role">Роль</label>
                        <select
                            id="ue-role"
                            value={form.role}
                            onChange={(e) => setField('role', e.target.value as 'admin' | 'operator')}
                            className="sp-select"
                        >
                            <option value="operator">operator</option>
                            <option value="admin">admin</option>
                        </select>
                    </div>
                </div>
                <div className="sp-toggle-row">
                    <label className="sp-toggle">
                        <input
                            type="checkbox"
                            checked={form.is_active}
                            onChange={(e) => setField('is_active', e.target.checked)}
                        />
                        <span className="sp-toggle-track" />
                        <span className="sp-toggle-label">Активен</span>
                    </label>
                    <label className="sp-toggle">
                        <input
                            type="checkbox"
                            checked={form.force_2fa}
                            onChange={(e) => setField('force_2fa', e.target.checked)}
                        />
                        <span className="sp-toggle-track" />
                        <span className="sp-toggle-label">Обязательная 2FA</span>
                    </label>
                </div>
            </div>

            {/* Tabs */}
            <div className="sp-section">
                <div className="sp-section-head">
                    <div className="sp-section-title">Разрешённые вкладки</div>
                    {isAdminRole ? (
                        <span className="sp-row-hint">admin — полный доступ</span>
                    ) : null}
                </div>
                <div className="sp-chipgrid">
                    {TAB_OPTIONS.map((tab) => {
                        const checked = form.allowed_tabs.includes(tab.key);
                        return (
                            <label
                                key={tab.key}
                                className={[
                                    'sp-chip-toggle',
                                    checked ? 'is-active' : '',
                                    isAdminRole ? 'is-disabled' : '',
                                ].filter(Boolean).join(' ')}
                            >
                                <input
                                    type="checkbox"
                                    checked={checked}
                                    disabled={isAdminRole}
                                    onChange={(e) => {
                                        setForm((prev) => {
                                            const next = new Set(prev.allowed_tabs);
                                            if (e.target.checked) next.add(tab.key);
                                            else next.delete(tab.key);
                                            return { ...prev, allowed_tabs: Array.from(next) };
                                        });
                                        setErrors((prev) => {
                                            const n = { ...prev };
                                            delete n.allowed_tabs;
                                            return n;
                                        });
                                    }}
                                />
                                {checked ? <Check size={11} /> : null}
                                {tab.label}
                            </label>
                        );
                    })}
                </div>
                {errors.allowed_tabs ? (
                    <div className="sp-error">
                        <AlertCircle size={12} /><span>{errors.allowed_tabs}</span>
                    </div>
                ) : null}
            </div>

            {/* Advanced — collapsible */}
            <details className="sp-details">
                <summary className="sp-details-summary">Дополнительные настройки</summary>
                <div className="sp-details-body">
                    <div className="sp-grid-2">
                        <div className="sp-field-stack">
                            <label className="sp-row-hint sp-form-label" htmlFor="ue-ttl">TTL сессии (дней)</label>
                            <input
                                id="ue-ttl"
                                type="number"
                                min={1}
                                max={90}
                                value={String(form.session_ttl_days)}
                                onChange={(e) => {
                                    const n = Number(e.target.value);
                                    setField('session_ttl_days', Number.isFinite(n) ? n : 7);
                                }}
                                key={`ttl-${shakeKey}`}
                                className={['sp-input', errors.session_ttl_days ? 'has-error' : ''].filter(Boolean).join(' ')}
                                aria-invalid={Boolean(errors.session_ttl_days)}
                            />
                            {errors.session_ttl_days ? (
                                <div className="sp-error sp-field-error">
                                    <AlertCircle size={12} /><span>{errors.session_ttl_days}</span>
                                </div>
                            ) : null}
                        </div>
                        <label className="sp-toggle" style={{ alignSelf: 'end', marginBottom: 6 }}>
                            <input
                                type="checkbox"
                                checked={form.can_toggle_sources}
                                onChange={(e) => setField('can_toggle_sources', e.target.checked)}
                            />
                            <span className="sp-toggle-track" />
                            <span className="sp-toggle-label">Переключение источников</span>
                        </label>
                    </div>

                    {/* Telegram (только для create) */}
                    {isCreate ? (
                        <div className="sp-grid-2">
                            <div className="sp-field-stack">
                                <label className="sp-row-hint sp-form-label" htmlFor="ue-tgid">Telegram ID</label>
                                <input
                                    id="ue-tgid"
                                    type="text"
                                    value={form.telegram_id}
                                    onChange={(e) => setField('telegram_id', e.target.value.replace(/\D/g, ''))}
                                    placeholder="123456789"
                                    inputMode="numeric"
                                    className="sp-input is-mono"
                                />
                            </div>
                            <div className="sp-field-stack">
                                <label className="sp-row-hint sp-form-label" htmlFor="ue-tgu">@username</label>
                                <input
                                    id="ue-tgu"
                                    type="text"
                                    value={form.telegram_username}
                                    onChange={(e) => setField('telegram_username', e.target.value.replace(/^@/, ''))}
                                    placeholder="username"
                                    className="sp-input"
                                />
                            </div>
                        </div>
                    ) : null}

                    {/* Folders/scopes */}
                    {(scopesQuery.data && scopesQuery.data.length > 0) ? (
                        <div className="sp-field-stack">
                            <label className="sp-row-hint sp-form-label">Разрешённые папки</label>
                            <div className="sp-chipgrid">
                                {scopesQuery.data.map((scope) => {
                                    const checked = form.allowed_folders.includes(scope.id);
                                    return (
                                        <label
                                            key={scope.id}
                                            className={['sp-chip-toggle', checked ? 'is-active' : ''].filter(Boolean).join(' ')}
                                        >
                                            <input
                                                type="checkbox"
                                                checked={checked}
                                                onChange={(e) => {
                                                    setForm((prev) => {
                                                        const n = new Set(prev.allowed_folders);
                                                        if (e.target.checked) n.add(scope.id);
                                                        else n.delete(scope.id);
                                                        return { ...prev, allowed_folders: Array.from(n) };
                                                    });
                                                }}
                                            />
                                            {checked ? <Check size={11} /> : null}
                                            {scope.name}
                                        </label>
                                    );
                                })}
                            </div>
                        </div>
                    ) : null}

                    {/* Forbidden periods */}
                    <div className="sp-field-stack">
                        <label className="sp-row-hint sp-form-label">Запрещённые периоды</label>
                        <ForbiddenPeriodsEditor
                            value={form.forbidden_periods}
                            onChange={(rows) => setForm((prev) => ({ ...prev, forbidden_periods: rows }))}
                        />
                    </div>
                </div>
            </details>

            {/* Hint for edit mode */}
            {!isCreate ? (
                <div className="sp-card sp-edit-hint">
                    <div className="sp-card-body compact">
                        <KeyRound size={14} style={{ color: 'var(--sp-ink-soft)', flexShrink: 0 }} />
                        <div className="sp-row-hint" style={{ flex: 1 }}>
                            Пароль и логин нельзя редактировать. Используйте действия в строке таблицы.
                        </div>
                    </div>
                </div>
            ) : null}
        </Dialog>
    );
};
