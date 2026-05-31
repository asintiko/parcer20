import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
    AlertCircle,
    ArrowLeft,
    ArrowRight,
    Eye,
    EyeOff,
    KeyRound,
    Lock,
    User,
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { TwoFactorSetup } from '../components/TwoFactorSetup';
import { QRLoginPanel } from '../components/QRLoginPanel';
import { StaggerChildren, StaggerItem } from '../components/motion/StaggerChildren';
import '../styles/login.css';

const routeByTab: Record<string, string> = {
    dashboard: '/',
    reference: '/reference',
    automation: '/automation',
    userbot: '/userbot',
    logs: '/logs',
    admin: '/settings',
};

const orderedTabs = ['dashboard', 'reference', 'automation', 'userbot', 'logs', 'admin'];

const resolveFirstRoute = (tabs: string[], role: string): string => {
    if (role === 'admin') return '/';
    const allowed = new Set(tabs || []);
    for (const tab of orderedTabs) {
        if (allowed.has(tab) && routeByTab[tab]) {
            return routeByTab[tab];
        }
    }
    return '/';
};

export const LoginPage: React.FC = () => {
    const navigate = useNavigate();
    const { login, login2fa } = useAuth();

    const [username, setUsername] = useState('admin');
    const [password, setPassword] = useState('admin');
    const [showPassword, setShowPassword] = useState(false);
    const [remember, setRemember] = useState(true);
    const [twoFactorCode, setTwoFactorCode] = useState('');
    const [tempToken, setTempToken] = useState<string | null>(null);
    const [requiresSetup, setRequiresSetup] = useState(false);
    const [step, setStep] = useState<'credentials' | 'two_factor'>('credentials');
    const [status, setStatus] = useState<'idle' | 'loading' | 'authenticating' | 'error'>('idle');
    const [error, setError] = useState<string | null>(null);
    const [attemptsLeft, setAttemptsLeft] = useState<number | null>(null);
    const otpInputRef = useRef<HTMLInputElement | null>(null);
    const otpAutoSubmittedRef = useRef(false);

    const liveStatus = useMemo(() => {
        if (status === 'loading') return 'Проверяем учётные данные';
        if (status === 'authenticating') return 'Готово, выполняется переход';
        if (status === 'error' && error) return error;
        return '';
    }, [status, error]);

    const lockHint = useMemo(() => {
        if (attemptsLeft === null) return null;
        if (attemptsLeft <= 0) return 'Лимит попыток исчерпан';
        return `Осталось попыток: ${attemptsLeft}`;
    }, [attemptsLeft]);

    useEffect(() => {
        const onKey = (event: KeyboardEvent) => {
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                document.querySelector<HTMLButtonElement>('.lp-submit')?.click();
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, []);

    // Auto-focus OTP when step changes
    useEffect(() => {
        if (step === 'two_factor' && !requiresSetup) {
            otpAutoSubmittedRef.current = false;
            const t = window.setTimeout(() => otpInputRef.current?.focus(), 80);
            return () => window.clearTimeout(t);
        }
        return;
    }, [step, requiresSetup]);

    // Auto-submit when 6 digits entered
    useEffect(() => {
        if (step !== 'two_factor' || requiresSetup) return;
        if (twoFactorCode.length === 6 && !otpAutoSubmittedRef.current && tempToken && status === 'idle') {
            otpAutoSubmittedRef.current = true;
            handleLogin2fa({ preventDefault: () => {} } as React.FormEvent);
        }
        if (twoFactorCode.length < 6) {
            otpAutoSubmittedRef.current = false;
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [twoFactorCode, step, requiresSetup, tempToken, status]);

    const handleLogin = async (e: React.FormEvent) => {
        e.preventDefault();
        setStatus('loading');
        setError(null);
        setAttemptsLeft(null);

        try {
            const user = await login(username.trim(), password);
            setStatus('authenticating');
            const target = resolveFirstRoute(user.allowed_tabs || [], user.role);
            setTimeout(() => navigate(target, { replace: true }), 480);
        } catch (err: any) {
            if (err?.code === 'requires_2fa') {
                setStatus('idle');
                setStep('two_factor');
                setTempToken(err?.temp_token || null);
                setRequiresSetup(Boolean(err?.requires_2fa_setup));
                setError(null);
                return;
            }
            setStatus('error');
            const code = err?.code || err?.response?.data?.error;
            const detail = err?.response?.data;
            setAttemptsLeft(detail?.attempts_left ?? err?.attempts_left ?? null);
            if (code === 'locked') {
                const seconds = detail?.locked_seconds ?? err?.locked_seconds;
                setError(seconds ? `Пользователь временно заблокирован (${seconds} сек)` : 'Пользователь временно заблокирован');
                return;
            }
            if (code === 'inactive_user') {
                setError('Пользователь отключен администратором');
                return;
            }
            setError('Неверный логин или пароль');
        }
    };

    const handleLogin2fa = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!tempToken || !twoFactorCode.trim()) return;
        setStatus('loading');
        setError(null);
        try {
            const user = await login2fa(tempToken, twoFactorCode.trim());
            setStatus('authenticating');
            const target = resolveFirstRoute(user.allowed_tabs || [], user.role);
            setTimeout(() => navigate(target, { replace: true }), 480);
        } catch (err: any) {
            setStatus('error');
            const detail = err?.response?.data?.detail;
            if (typeof detail === 'object' && detail?.locked_seconds) {
                setError(`Слишком много попыток. Повторите через ${detail.locked_seconds} сек`);
            } else if (typeof detail === 'string') {
                setError(detail === 'requires_2fa_setup' ? 'Сначала завершите настройку 2FA' : detail);
            } else {
                setError('Неверный 2FA код');
            }
        }
    };

    const renderSubmit = (label: string, _disabled: boolean) => {
        if (status === 'authenticating') {
            return (
                <span className="lp-success">
                    <svg className="lp-success-tick" viewBox="0 0 24 24" fill="none" aria-hidden>
                        <path
                            d="M5 12.5l4.2 4.2L19 7"
                            stroke="currentColor"
                            strokeWidth="2.4"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                        />
                    </svg>
                    Готово
                </span>
            );
        }
        if (status === 'loading') {
            return (
                <span className="lp-success">
                    <span className="lp-spinner" aria-hidden />
                    Проверяем…
                </span>
            );
        }
        return (
            <span className="lp-success">
                {label}
                <ArrowRight size={16} className="lp-submit-arrow" aria-hidden />
            </span>
        );
    };

    return (
        <div className="lp-shell">
            {/* Hero — editorial */}
            <aside className="lp-hero" aria-label="О продукте Receipt Parcer">
                <div className="lp-hero-top">
                    <div className="lp-brand">
                        <span className="lp-brand-dot" />
                        Receipt Parcer
                        <span className="lp-brand-meta">v{__APP_VERSION__}</span>
                    </div>
                </div>

                <StaggerChildren className="lp-hero-inner" as="div">
                    <StaggerItem as="h2" className="lp-headline">
                        Тихий рабочий стол<br />
                        для <em>каждого чека</em>.
                    </StaggerItem>
                    <StaggerItem as="p" className="lp-sub">
                        Сюда стекаются операции из чатов, ботов и SMS — и ровными строками
                        складываются в один аккуратный реестр. Без шума, без украшений.
                    </StaggerItem>

                    <StaggerItem className="lp-hero-foot">
                        <div className="lp-bullet-row">
                            <span className="lp-bullet-num">01</span>
                            <div>
                                <div className="lp-bullet-title">Источники в одной ленте</div>
                                <div className="lp-bullet-sub">Telegram, SMS, ручной ввод — единый поток с историей и аудитом.</div>
                            </div>
                        </div>
                        <div className="lp-bullet-row">
                            <span className="lp-bullet-num">02</span>
                            <div>
                                <div className="lp-bullet-title">Парсер с подсказками</div>
                                <div className="lp-bullet-sub">Каждая операция уже разобрана: оператор, валюта, источник, метод.</div>
                            </div>
                        </div>
                        <div className="lp-bullet-row">
                            <span className="lp-bullet-num">03</span>
                            <div>
                                <div className="lp-bullet-title">Контроль доступа</div>
                                <div className="lp-bullet-sub">Роли, scope-токены, заблокированные периоды и журнал входов.</div>
                            </div>
                        </div>
                    </StaggerItem>
                </StaggerChildren>
            </aside>

            {/* Form */}
            <main className="lp-form-side">
                <div className="lp-form-wrap">
                    <div className="lp-mobile-brand">
                        <div className="lp-mark">
                            <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden>
                                <path
                                    d="M6 3.2h9.5a3 3 0 0 1 3 3v14.6l-3-1.6-3 1.6-3-1.6-3 1.6V6.2a3 3 0 0 1 3-3z"
                                    fill="none"
                                    stroke="currentColor"
                                    strokeWidth="1.5"
                                    strokeLinejoin="round"
                                />
                                <path d="M9 8.5h6M9 12h6M9 15.5h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                            </svg>
                        </div>
                        <div className="lp-mobile-brand-name">Receipt Parcer</div>
                    </div>

                    <header className="lp-form-header">
                        {step === 'credentials' ? (
                            <>
                                <h1 className="lp-form-title">С возвращением.</h1>
                                <p className="lp-form-subtitle">
                                    Введите <span className="lp-emph">логин и пароль</span>, чтобы продолжить работу.
                                </p>
                            </>
                        ) : (
                            <>
                                <h1 className="lp-form-title">Шестизначный код.</h1>
                                <p className="lp-form-subtitle">
                                    Откройте приложение-аутентификатор и введите код за <span className="lp-emph">30 секунд</span>.
                                </p>
                            </>
                        )}
                    </header>

                    {step === 'credentials' ? (
                        <form onSubmit={handleLogin} className="lp-fields" noValidate>
                            <div className="lp-field">
                                <div className="lp-field-label">
                                    <span>Логин</span>
                                </div>
                                <div className={`lp-input-wrap ${error ? 'has-error' : ''}`}>
                                    <User size={16} className="lp-input-icon" aria-hidden />
                                    <input
                                        className="lp-input"
                                        value={username}
                                        onChange={(e) => setUsername(e.target.value)}
                                        placeholder="username"
                                        autoComplete="username"
                                        aria-label="Логин"
                                    />
                                </div>
                            </div>

                            <div className="lp-field">
                                <div className="lp-field-label">
                                    <span>Пароль</span>
                                    <a className="lp-link" href="#" onClick={(e) => e.preventDefault()}>
                                        Забыли?
                                    </a>
                                </div>
                                <div className={`lp-input-wrap ${error ? 'has-error' : ''}`}>
                                    <Lock size={16} className="lp-input-icon" aria-hidden />
                                    <input
                                        className="lp-input"
                                        type={showPassword ? 'text' : 'password'}
                                        value={password}
                                        onChange={(e) => setPassword(e.target.value)}
                                        placeholder="••••••••"
                                        autoComplete="current-password"
                                        aria-label="Пароль"
                                    />
                                    <button
                                        type="button"
                                        className="lp-input-trailing"
                                        onClick={() => setShowPassword((v) => !v)}
                                        aria-label={showPassword ? 'Скрыть пароль' : 'Показать пароль'}
                                    >
                                        {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
                                    </button>
                                </div>
                            </div>

                            <div className="lp-field lp-meta-row">
                                <label className="lp-checkbox">
                                    <input
                                        type="checkbox"
                                        checked={remember}
                                        onChange={(e) => setRemember(e.target.checked)}
                                    />
                                    <span className="lp-checkbox-box">
                                        <svg viewBox="0 0 16 16" aria-hidden>
                                            <path d="M3 8.4l3.2 3.1L13 4.5" />
                                        </svg>
                                    </span>
                                    Запомнить меня
                                </label>
                            </div>

                            {status === 'error' && error ? (
                                <div className="lp-error" role="alert">
                                    <AlertCircle size={16} aria-hidden />
                                    <div>
                                        <div>{error}</div>
                                        {lockHint ? (
                                            <div className="lp-error-meta">{lockHint}</div>
                                        ) : null}
                                    </div>
                                </div>
                            ) : null}

                            <div className="lp-field">
                                <button
                                    type="submit"
                                    className="lp-submit"
                                    disabled={status === 'loading' || status === 'authenticating' || !username.trim() || !password}
                                >
                                    <span className="lp-submit-content">
                                        {renderSubmit('Войти', false)}
                                    </span>
                                </button>
                            </div>

                            <div className="lp-divider">или сканируйте QR</div>

                            <QRLoginPanel
                                onSuccess={(user) => {
                                    setStatus('authenticating');
                                    const target = resolveFirstRoute(user?.allowed_tabs || [], user?.role || '');
                                    setTimeout(() => navigate(target, { replace: true }), 380);
                                }}
                            />
                        </form>
                    ) : (
                        <form onSubmit={handleLogin2fa} className="lp-fields" noValidate>
                            {requiresSetup ? (
                                <TwoFactorSetup
                                    tempToken={tempToken}
                                    onCompleted={() => {
                                        setRequiresSetup(false);
                                        setError(null);
                                    }}
                                />
                            ) : null}

                            <div className="lp-field">
                                <div className="lp-field-label">
                                    <span>Код подтверждения</span>
                                    <span className="lp-field-counter">{twoFactorCode.length}/6</span>
                                </div>
                                <div className={`lp-input-wrap ${error ? 'has-error' : ''}`}>
                                    <KeyRound size={16} className="lp-input-icon" aria-hidden />
                                    <input
                                        ref={otpInputRef}
                                        className="lp-input lp-input-otp"
                                        value={twoFactorCode}
                                        onChange={(e) => setTwoFactorCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                                        placeholder="000000"
                                        inputMode="numeric"
                                        autoComplete="one-time-code"
                                        aria-label="2FA код"
                                        aria-invalid={Boolean(error)}
                                    />
                                </div>
                            </div>

                            {status === 'error' && error ? (
                                <div className="lp-error" role="alert">
                                    <AlertCircle size={16} aria-hidden />
                                    <span>{error}</span>
                                </div>
                            ) : null}

                            <div className="lp-field lp-field-actions">
                                <button
                                    type="button"
                                    className="lp-back-btn"
                                    onClick={() => {
                                        setStep('credentials');
                                        setTwoFactorCode('');
                                        setTempToken(null);
                                        setRequiresSetup(false);
                                        setError(null);
                                        setStatus('idle');
                                    }}
                                >
                                    <ArrowLeft size={15} />
                                    Назад
                                </button>
                                <button
                                    type="submit"
                                    className="lp-submit"
                                    disabled={status === 'loading' || status === 'authenticating' || !tempToken || !twoFactorCode.trim() || requiresSetup}
                                >
                                    <span className="lp-submit-content">
                                        {renderSubmit('Подтвердить', false)}
                                    </span>
                                </button>
                            </div>
                        </form>
                    )}

                    <div className="lp-footer">
                        <div className="lp-footer-meta">
                            <span>
                                Нажмите <kbd>⌘</kbd>+<kbd>↵</kbd> чтобы войти быстрее.
                            </span>
                            <span className="lp-footer-version">v{__APP_VERSION__}</span>
                        </div>
                    </div>

                    {/* SR live region for status announcements */}
                    <div className="lp-live" role="status" aria-live="polite" aria-atomic="true">
                        {liveStatus}
                    </div>
                </div>
            </main>
        </div>
    );
};
