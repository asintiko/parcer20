import React, { useCallback, useEffect, useRef, useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { Loader2, RefreshCcw, Smartphone } from 'lucide-react';
import { authApi } from '../services/api';
import { useAuth } from '../contexts/AuthContext';

interface QRLoginPanelProps {
    onSuccess: (user: any) => void;
}

const QR_POLL_INTERVAL = 2000;
const QR_REFRESH_BEFORE_EXPIRE = 30; // seconds

export const QRLoginPanel: React.FC<QRLoginPanelProps> = ({ onSuccess }) => {
    const { loginWithTokens } = useAuth();
    const [sessionId, setSessionId] = useState<string | null>(null);
    const [qrUrl, setQrUrl] = useState<string | null>(null);
    const [expiresAt, setExpiresAt] = useState<number | null>(null);
    const [secondsLeft, setSecondsLeft] = useState(0);
    const [status, setStatus] = useState<'idle' | 'loading' | 'active' | 'expired' | 'error'>('idle');
    const [error, setError] = useState<string | null>(null);
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const mountedRef = useRef(true);

    const generateQR = useCallback(async () => {
        setStatus('loading');
        setError(null);
        try {
            const result = await authApi.qrGenerate();
            if (!mountedRef.current) return;
            setSessionId(result.session_id);
            setQrUrl(result.qr_url);
            setExpiresAt(Date.now() + result.expires_in * 1000);
            setSecondsLeft(result.expires_in);
            setStatus('active');
        } catch (err: any) {
            if (!mountedRef.current) return;
            setStatus('error');
            setError(err?.response?.data?.detail || 'Не удалось создать QR');
        }
    }, []);

    // Poll for confirmation
    useEffect(() => {
        if (status !== 'active' || !sessionId) return;

        pollRef.current = setInterval(async () => {
            try {
                const result = await authApi.qrStatus(sessionId);
                if (!mountedRef.current) return;

                if (result.status === 'confirmed' && result.token) {
                    setStatus('idle');
                    if (pollRef.current) clearInterval(pollRef.current);
                    const user = await loginWithTokens(
                        result.token,
                        result.scope_token,
                        result.refresh_token,
                        result.user,
                    );
                    onSuccess(user);
                } else if (result.status === 'expired') {
                    setStatus('expired');
                    if (pollRef.current) clearInterval(pollRef.current);
                }
            } catch {
                // ignore polling errors
            }
        }, QR_POLL_INTERVAL);

        return () => {
            if (pollRef.current) clearInterval(pollRef.current);
        };
    }, [status, sessionId, loginWithTokens, onSuccess]);

    // Countdown timer
    useEffect(() => {
        if (!expiresAt || status !== 'active') return;
        const timer = setInterval(() => {
            const left = Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000));
            setSecondsLeft(left);
            if (left <= 0) {
                setStatus('expired');
            }
        }, 1000);
        return () => clearInterval(timer);
    }, [expiresAt, status]);

    // Auto-refresh before expiry
    useEffect(() => {
        if (status === 'active' && secondsLeft > 0 && secondsLeft <= QR_REFRESH_BEFORE_EXPIRE) {
            // Don't auto-refresh, just let it expire and show refresh button
        }
    }, [status, secondsLeft]);

    useEffect(() => {
        mountedRef.current = true;
        return () => {
            mountedRef.current = false;
        };
    }, []);

    if (status === 'idle') {
        return (
            <button
                type="button"
                onClick={generateQR}
                className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg border border-border bg-surface hover:bg-surface-2 transition-colors"
            >
                <Smartphone className="w-4 h-4" />
                <span>Войти через Telegram</span>
            </button>
        );
    }

    if (status === 'loading') {
        return (
            <div className="flex items-center justify-center py-6">
                <Loader2 className="w-6 h-6 animate-spin text-primary" />
            </div>
        );
    }

    if (status === 'error') {
        return (
            <div className="space-y-3 text-center">
                <div className="text-sm text-danger">{error}</div>
                <button
                    type="button"
                    onClick={generateQR}
                    className="px-4 py-2 rounded-lg border border-border bg-surface hover:bg-surface-2"
                >
                    Повторить
                </button>
            </div>
        );
    }

    return (
        <div className="space-y-4 text-center">
            <p className="text-sm text-foreground-secondary">
                Отсканируйте QR-код в Telegram
            </p>

            {qrUrl && status === 'active' ? (
                <div className="inline-block p-3 bg-white rounded-lg">
                    <QRCodeSVG value={qrUrl} size={192} />
                </div>
            ) : null}

            <div className="text-xs text-foreground-muted">
                {status === 'expired' ? (
                    <div className="space-y-2">
                        <span>QR-код истек</span>
                        <br />
                        <button
                            type="button"
                            onClick={generateQR}
                            className="inline-flex items-center gap-1 px-3 py-1 rounded border border-border bg-surface hover:bg-surface-2"
                        >
                            <RefreshCcw className="w-3 h-3" />
                            Обновить
                        </button>
                    </div>
                ) : (
                    `Действует: ${Math.floor(secondsLeft / 60)}:${String(secondsLeft % 60).padStart(2, '0')}`
                )}
            </div>
        </div>
    );
};
