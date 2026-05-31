import { FormEvent, useEffect, useMemo, useState } from 'react';
import { securityApi } from '../services/api';

type LaunchGateProps = {
    onUnlocked: () => void;
};

export function LaunchGate({ onUnlocked }: LaunchGateProps) {
    const [loading, setLoading] = useState(true);
    const [password, setPassword] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [lockedUntil, setLockedUntil] = useState<string | null>(null);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [clockTs, setClockTs] = useState(Date.now());
    const [shake, setShake] = useState(false);

    useEffect(() => {
        let cancelled = false;
        const load = async () => {
            try {
                const status = await securityApi.getLaunchStatus();
                if (cancelled) return;
                if (!status.password_set) {
                    onUnlocked();
                    return;
                }
                setLockedUntil(status.locked_until || null);
            } catch (err: any) {
                if (cancelled) return;
                setError(err?.response?.data?.detail || 'Не удалось проверить статус запуска');
            } finally {
                if (!cancelled) setLoading(false);
            }
        };
        load();
        return () => {
            cancelled = true;
        };
    }, [onUnlocked]);

    useEffect(() => {
        const timer = window.setInterval(() => setClockTs(Date.now()), 1000);
        return () => window.clearInterval(timer);
    }, []);

    useEffect(() => {
        if (!shake) return;
        const timer = window.setTimeout(() => setShake(false), 360);
        return () => window.clearTimeout(timer);
    }, [shake]);

    const lockRemaining = useMemo(() => {
        if (!lockedUntil) return null;
        const ms = new Date(lockedUntil).getTime() - Date.now();
        if (ms <= 0) return null;
        const mins = Math.floor(ms / 60000);
        const secs = Math.floor((ms % 60000) / 1000);
        return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    }, [lockedUntil, clockTs]);

    const submit = async (e: FormEvent) => {
        e.preventDefault();
        if (!password.trim() || isSubmitting) return;
        setIsSubmitting(true);
        setError(null);
        try {
            const result = await securityApi.verifyLaunch(password.trim());
            if (result.verified) {
                onUnlocked();
                return;
            }
            if (result.locked && result.locked_until) {
                setLockedUntil(result.locked_until);
                setError('Слишком много попыток. Доступ временно заблокирован.');
            } else {
                setShake(false);
                requestAnimationFrame(() => setShake(true));
                setError(`Неверный пароль${typeof result.attempts_left === 'number' ? ` (осталось: ${result.attempts_left})` : ''}`);
            }
        } catch (err: any) {
            setShake(false);
            requestAnimationFrame(() => setShake(true));
            setError(err?.response?.data?.detail || 'Ошибка проверки пароля');
        } finally {
            setIsSubmitting(false);
        }
    };

    if (loading) {
        return <div className="h-screen w-full bg-bg flex items-center justify-center text-foreground">Проверка доступа...</div>;
    }

    return (
        <div className="h-screen w-full bg-[#111827] text-white flex items-center justify-center px-6">
            <form onSubmit={submit} className="w-full max-w-md rounded-xl border border-white/10 bg-black/40 p-8 backdrop-blur">
                <h1 className="text-2xl font-semibold mb-2">TBSparcer</h1>
                <p className="text-sm text-white/70 mb-6">Введите пароль для запуска приложения</p>
                <input
                    type="password"
                    value={password}
                    autoFocus
                    disabled={Boolean(lockRemaining)}
                    onChange={(e) => setPassword(e.target.value)}
                    className={`w-full px-4 py-3 rounded-md bg-black/30 border border-white/20 focus:outline-none focus:ring-2 focus:ring-info ${shake ? 'animate-shake border-danger focus:ring-danger' : ''}`}
                    placeholder="Пароль"
                />
                {lockRemaining && <div className="mt-3 text-sm text-warning">Блокировка: {lockRemaining}</div>}
                {error && <div className="mt-3 text-sm text-danger">{error}</div>}
                <button
                    type="submit"
                    disabled={isSubmitting || Boolean(lockRemaining)}
                    className="mt-6 w-full py-3 rounded-md bg-primary hover:bg-primary-hover disabled:opacity-50"
                >
                    {isSubmitting ? 'Проверка...' : 'Войти'}
                </button>
            </form>
        </div>
    );
}
