import React, { useState } from 'react';
import { twoFactorApi } from '../services/api';

type SetupPayload = {
    secret: string;
    otpauth_uri: string;
    qr_code_base64: string;
    backup_codes: string[];
};

interface TwoFactorSetupProps {
    tempToken?: string | null;
    onCompleted: () => void;
}

export const TwoFactorSetup: React.FC<TwoFactorSetupProps> = ({ tempToken, onCompleted }) => {
    const [setup, setSetup] = useState<SetupPayload | null>(null);
    const [code, setCode] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [done, setDone] = useState(false);

    const handleStart = async () => {
        setLoading(true);
        setError(null);
        try {
            const payload = await twoFactorApi.setup(tempToken || undefined);
            setSetup(payload);
        } catch (err: any) {
            setError(err?.response?.data?.detail || err?.message || 'Не удалось начать настройку 2FA');
        } finally {
            setLoading(false);
        }
    };

    const handleConfirm = async () => {
        if (!code.trim()) return;
        setLoading(true);
        setError(null);
        try {
            const result = await twoFactorApi.confirm(code.trim(), tempToken || undefined);
            if (!result?.ok) {
                throw new Error('Неверный код подтверждения');
            }
            setDone(true);
            onCompleted();
        } catch (err: any) {
            const detail = err?.response?.data?.detail;
            const detailError = typeof detail === 'object' ? detail?.error : null;
            setError(detailError || detail || err?.message || 'Не удалось подтвердить 2FA');
        } finally {
            setLoading(false);
        }
    };

    if (done) {
        return <div className="text-sm text-success">2FA успешно включена. Теперь введите код для входа.</div>;
    }

    return (
        <div className="space-y-3 rounded-lg border border-border bg-surface-2 p-4">
            <div className="text-sm font-medium text-foreground">Обязательная настройка 2FA</div>

            {!setup ? (
                <button
                    type="button"
                    onClick={handleStart}
                    disabled={loading}
                    className="px-3 py-2 rounded-md border border-primary text-primary hover:bg-primary/10 disabled:opacity-60"
                >
                    {loading ? 'Готовим QR...' : 'Начать настройку'}
                </button>
            ) : (
                <div className="space-y-3">
                    <img
                        src={`data:image/png;base64,${setup.qr_code_base64}`}
                        alt="TOTP QR"
                        className="w-44 h-44 rounded-md border border-border bg-white p-2"
                    />
                    <div className="text-xs text-foreground-secondary break-all">
                        Secret: <span className="font-mono">{setup.secret}</span>
                    </div>
                    <div className="text-xs text-foreground-secondary">
                        Backup codes: {setup.backup_codes.join(', ')}
                    </div>
                    <div className="flex gap-2">
                        <input
                            value={code}
                            onChange={(e) => setCode(e.target.value)}
                            placeholder="Код из приложения"
                            className="flex-1 px-3 py-2 rounded-md border border-border bg-input-bg text-input-text"
                        />
                        <button
                            type="button"
                            onClick={handleConfirm}
                            disabled={loading || !code.trim()}
                            className="px-3 py-2 rounded-md bg-primary text-foreground-inverse hover:bg-primary-hover disabled:opacity-60"
                        >
                            Подтвердить
                        </button>
                    </div>
                </div>
            )}

            {error ? <div className="text-xs text-danger">{error}</div> : null}
        </div>
    );
};
