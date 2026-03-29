import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertCircle, CheckCircle, Send } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { TwoFactorSetup } from '../components/TwoFactorSetup';
import { QRLoginPanel } from '../components/QRLoginPanel';

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

    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [twoFactorCode, setTwoFactorCode] = useState('');
    const [tempToken, setTempToken] = useState<string | null>(null);
    const [requiresSetup, setRequiresSetup] = useState(false);
    const [step, setStep] = useState<'credentials' | 'two_factor'>('credentials');
    const [status, setStatus] = useState<'idle' | 'loading' | 'authenticating' | 'error'>('idle');
    const [error, setError] = useState<string | null>(null);
    const [attemptsLeft, setAttemptsLeft] = useState<number | null>(null);

    const lockHint = useMemo(() => {
        if (attemptsLeft === null) return null;
        if (attemptsLeft <= 0) return 'Лимит попыток исчерпан';
        return `Осталось попыток: ${attemptsLeft}`;
    }, [attemptsLeft]);

    const handleLogin = async (e: React.FormEvent) => {
        e.preventDefault();
        setStatus('loading');
        setError(null);
        setAttemptsLeft(null);

        try {
            const user = await login(username.trim(), password);
            setStatus('authenticating');
            const target = resolveFirstRoute(user.allowed_tabs || [], user.role);
            navigate(target, { replace: true });
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
            navigate(target, { replace: true });
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

    return (
        <div className="min-h-screen w-full flex items-center justify-center bg-bg p-4">
            <div className="w-full max-w-md p-6">
                <div className="text-center mb-8">
                    <div className="inline-flex items-center justify-center w-16 h-16 bg-primary rounded-2xl mb-4">
                        <Send className="w-8 h-8 text-foreground-inverse" />
                    </div>
                    <h1 className="text-3xl font-semibold tracking-wide text-foreground mb-2">PARCER 2.0</h1>
                    <p className="text-foreground-secondary">Персональный вход</p>
                </div>

                <div className="bg-surface rounded-2xl shadow-xl p-8 border border-border space-y-6">
                    {step === 'credentials' ? (
                        <form onSubmit={handleLogin} className="space-y-4">
                            <div>
                                <label className="block text-sm text-foreground-secondary mb-2">Логин</label>
                                <input
                                    value={username}
                                    onChange={(e) => setUsername(e.target.value)}
                                    className="w-full px-3 py-2 rounded-lg border border-border bg-input-bg text-input-text"
                                    placeholder="username"
                                    autoComplete="username"
                                />
                            </div>
                            <div>
                                <label className="block text-sm text-foreground-secondary mb-2">Пароль</label>
                                <input
                                    type="password"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    className="w-full px-3 py-2 rounded-lg border border-border bg-input-bg text-input-text"
                                    placeholder="password"
                                    autoComplete="current-password"
                                />
                            </div>

                            {status === 'error' && error ? (
                                <div className="text-sm text-danger flex items-center gap-2">
                                    <AlertCircle className="w-4 h-4" />
                                    <span>{error}</span>
                                </div>
                            ) : null}
                            {lockHint ? <div className="text-xs text-foreground-muted">{lockHint}</div> : null}

                            <button
                                type="submit"
                                disabled={status === 'loading' || !username.trim() || !password}
                                className="w-full px-4 py-2 rounded-lg bg-primary text-foreground-inverse hover:bg-primary-hover disabled:opacity-60"
                            >
                                {status === 'loading' ? 'Вход...' : 'Войти'}
                            </button>
                        </form>
                    ) : (
                        <form onSubmit={handleLogin2fa} className="space-y-4">
                            <div className="text-sm text-foreground-secondary">Введите код из приложения-аутентификатора.</div>
                            {requiresSetup ? (
                                <TwoFactorSetup
                                    tempToken={tempToken}
                                    onCompleted={() => {
                                        setRequiresSetup(false);
                                        setError(null);
                                    }}
                                />
                            ) : null}
                            <input
                                value={twoFactorCode}
                                onChange={(e) => setTwoFactorCode(e.target.value)}
                                className="w-full px-3 py-2 rounded-lg border border-border bg-input-bg text-input-text"
                                placeholder="123456"
                                autoComplete="one-time-code"
                            />
                            {status === 'error' && error ? (
                                <div className="text-sm text-danger flex items-center gap-2">
                                    <AlertCircle className="w-4 h-4" />
                                    <span>{error}</span>
                                </div>
                            ) : null}
                            <div className="flex gap-2">
                                <button
                                    type="button"
                                    onClick={() => {
                                        setStep('credentials');
                                        setTwoFactorCode('');
                                        setTempToken(null);
                                        setRequiresSetup(false);
                                        setError(null);
                                        setStatus('idle');
                                    }}
                                    className="flex-1 px-4 py-2 rounded-lg border border-border bg-surface hover:bg-surface-2"
                                >
                                    Назад
                                </button>
                                <button
                                    type="submit"
                                    disabled={status === 'loading' || !tempToken || !twoFactorCode.trim() || requiresSetup}
                                    className="flex-1 px-4 py-2 rounded-lg bg-primary text-foreground-inverse hover:bg-primary-hover disabled:opacity-60"
                                >
                                    {status === 'loading' ? 'Проверка...' : 'Подтвердить'}
                                </button>
                            </div>
                        </form>
                    )}

                    {status === 'authenticating' ? (
                        <div className="flex items-center gap-2 text-success text-sm">
                            <CheckCircle className="w-4 h-4" />
                            <span>Успешный вход</span>
                        </div>
                    ) : null}

                    {step === 'credentials' && status !== 'authenticating' && (
                        <>
                            <div className="flex items-center gap-3">
                                <div className="flex-1 h-px bg-border" />
                                <span className="text-xs text-foreground-muted">или</span>
                                <div className="flex-1 h-px bg-border" />
                            </div>
                            <QRLoginPanel
                                onSuccess={(user) => {
                                    setStatus('authenticating');
                                    const target = resolveFirstRoute(user?.allowed_tabs || [], user?.role || '');
                                    navigate(target, { replace: true });
                                }}
                            />
                        </>
                    )}
                </div>
            </div>
        </div>
    );
};
