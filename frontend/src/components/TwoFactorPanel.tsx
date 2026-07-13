import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Shield, ShieldCheck, ShieldOff, AlertCircle, RefreshCw } from 'lucide-react';
import { twoFactorApi } from '../services/api';
import { Dialog } from './motion/Dialog';
import { ConfirmDialog } from './motion/ConfirmDialog';

/**
 * Self-service 2FA management.
 * - Status pill (enabled/disabled, force-locked).
 * - Toggle: setup flow (QR + verify) or disable confirm.
 * - Backup codes regeneration.
 */

export interface TwoFactorPanelProps {
    onSuccess: (msg: string) => void;
    onError: (msg: string) => void;
    forceLocked?: boolean; // force_2fa from current user
}

type SetupPayload = {
    secret: string;
    otpauth_uri: string;
    qr_code_base64: string;
    backup_codes: string[];
};

export const TwoFactorPanel: React.FC<TwoFactorPanelProps> = ({ onSuccess, onError, forceLocked }) => {
    const queryClient = useQueryClient();

    const statusQuery = useQuery({
        queryKey: ['2fa-status'],
        queryFn: twoFactorApi.getStatus,
    });

    const enabled = Boolean(statusQuery.data?.enabled);

    // Setup flow state
    const [setupOpen, setSetupOpen] = useState(false);
    const [setupPayload, setSetupPayload] = useState<SetupPayload | null>(null);
    const [code, setCode] = useState('');
    const [setupStep, setSetupStep] = useState<'init' | 'verify'>('init');

    // Disable flow state
    const [disableConfirmOpen, setDisableConfirmOpen] = useState(false);

    // Backup codes regen
    const [showBackup, setShowBackup] = useState<string[] | null>(null);

    const setupMutation = useMutation({
        mutationFn: () => twoFactorApi.setup(),
        onSuccess: (data) => {
            setSetupPayload(data);
            setSetupStep('verify');
        },
        onError: (err: any) => {
            onError(err?.response?.data?.detail || err?.message || 'Не удалось начать настройку');
            setSetupOpen(false);
        },
    });

    const confirmMutation = useMutation({
        mutationFn: () => twoFactorApi.confirm(code.trim()),
        onSuccess: (data) => {
            if (data.ok && data.enabled) {
                queryClient.invalidateQueries({ queryKey: ['2fa-status'] });
                onSuccess('Двухфакторная аутентификация включена');
                setSetupOpen(false);
                setSetupPayload(null);
                setCode('');
                setSetupStep('init');
            } else {
                onError('Неверный код подтверждения');
            }
        },
        onError: (err: any) => {
            onError(err?.response?.data?.detail || err?.message || 'Не удалось подтвердить код');
        },
    });

    const disableMutation = useMutation({
        mutationFn: () => twoFactorApi.disable(),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['2fa-status'] });
            onSuccess('Двухфакторная аутентификация отключена');
            setDisableConfirmOpen(false);
        },
        onError: (err: any) => {
            onError(err?.response?.data?.detail || err?.message || 'Не удалось отключить 2FA');
        },
    });

    const regenMutation = useMutation({
        mutationFn: () => twoFactorApi.regenerateBackupCodes(),
        onSuccess: (data) => {
            if (data.ok) {
                setShowBackup(data.backup_codes);
                onSuccess('Резервные коды обновлены');
            }
        },
        onError: (err: any) => {
            onError(err?.response?.data?.detail || err?.message || 'Не удалось сгенерировать коды');
        },
    });

    const handleStartSetup = () => {
        setCode('');
        setSetupStep('init');
        setSetupPayload(null);
        setSetupOpen(true);
        setupMutation.mutate();
    };

    return (
        <>
            <div className="sp-card">
                <div className="sp-card-head">
                    <div>
                        <h2 className="sp-card-title">Двухфакторная аутентификация</h2>
                        <div className="sp-card-sub">
                            {statusQuery.isLoading
                                ? 'Загружаем статус…'
                                : enabled
                                    ? 'Защищает аккаунт одноразовыми кодами из приложения-аутентификатора.'
                                    : 'Не настроена. Рекомендуется включить для защиты аккаунта.'}
                            {forceLocked ? ' · Принудительно администратором' : null}
                        </div>
                    </div>
                    {statusQuery.isLoading ? (
                        <span className="sp-pill"><span className="sp-pill-dot" />проверяем</span>
                    ) : (
                        <span className={`sp-pill ${enabled ? 'is-success' : 'is-warning'}`}>
                            <span className="sp-pill-dot" />
                            {enabled ? 'активна' : 'отключена'}
                        </span>
                    )}
                </div>

                <div className="sp-card-body">
                    <div className="sp-toggle-row" style={{ gap: 12 }}>
                        {enabled ? (
                            <>
                                <button
                                    type="button"
                                    className="sp-btn"
                                    onClick={() => regenMutation.mutate()}
                                    disabled={regenMutation.isPending}
                                >
                                    {regenMutation.isPending ? (
                                        <><span className="sp-btn-spinner" />Генерируем</>
                                    ) : (
                                        <><RefreshCw size={13} />Перегенерировать резервные коды</>
                                    )}
                                </button>
                                <button
                                    type="button"
                                    className="sp-btn sp-btn-danger"
                                    onClick={() => setDisableConfirmOpen(true)}
                                    disabled={forceLocked || disableMutation.isPending}
                                    title={forceLocked ? '2FA принудительна — отключение запрещено' : ''}
                                >
                                    {disableMutation.isPending ? (
                                        <><span className="sp-btn-spinner" />Отключаем</>
                                    ) : (
                                        <><ShieldOff size={13} />Отключить 2FA</>
                                    )}
                                </button>
                            </>
                        ) : (
                            <button
                                type="button"
                                className="sp-btn sp-btn-primary"
                                onClick={handleStartSetup}
                                disabled={setupMutation.isPending}
                            >
                                {setupMutation.isPending ? (
                                    <><span className="sp-btn-spinner" />Подготавливаем</>
                                ) : (
                                    <><ShieldCheck size={13} />Настроить 2FA</>
                                )}
                            </button>
                        )}
                    </div>
                </div>
            </div>

            {/* Setup dialog */}
            <Dialog
                open={setupOpen}
                onClose={() => {
                    if (confirmMutation.isPending || setupMutation.isPending) return;
                    setSetupOpen(false);
                    setSetupPayload(null);
                    setCode('');
                    setSetupStep('init');
                }}
                ariaLabel="Настройка 2FA"
                title={
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <span aria-hidden style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            width: 28, height: 28,
                            borderRadius: 4,
                            background: 'color-mix(in srgb, var(--success) 14%, transparent)',
                            color: 'var(--success)',
                        }}>
                            <Shield size={15} />
                        </span>
                        <h3 className="sp-sheet-title">Настройка 2FA</h3>
                    </div>
                }
                description={
                    setupStep === 'init'
                        ? 'Откройте Google Authenticator или 1Password — отсканируйте QR-код.'
                        : 'Введите 6-значный код из приложения для подтверждения.'
                }
                width={480}
                footer={
                    <>
                        <span className="sp-spacer" />
                        <button
                            type="button"
                            className="sp-btn"
                            onClick={() => {
                                setSetupOpen(false);
                                setSetupPayload(null);
                                setCode('');
                                setSetupStep('init');
                            }}
                            disabled={confirmMutation.isPending}
                        >
                            Отмена
                        </button>
                        {setupStep === 'verify' ? (
                            <button
                                type="button"
                                className="sp-btn sp-btn-primary"
                                onClick={() => confirmMutation.mutate()}
                                disabled={code.trim().length !== 6 || confirmMutation.isPending}
                            >
                                {confirmMutation.isPending ? (
                                    <>
                                        <span className="sp-btn-spinner" aria-hidden />
                                        Проверяем
                                    </>
                                ) : 'Подтвердить'}
                            </button>
                        ) : null}
                    </>
                }
            >
                {setupMutation.isPending && !setupPayload ? (
                    <div className="sp-row-hint" style={{ padding: '20px 0' }}>Готовим QR-код…</div>
                ) : setupPayload ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                        <div style={{ display: 'flex', justifyContent: 'center' }}>
                            <img
                                src={`data:image/png;base64,${setupPayload.qr_code_base64}`}
                                alt="QR-код для 2FA"
                                style={{
                                    width: 196, height: 196,
                                    border: '1px solid var(--sp-border)',
                                    borderRadius: 4,
                                    background: '#fff',
                                    padding: 8,
                                }}
                            />
                        </div>
                        <div className="sp-row-hint" style={{ textAlign: 'center' }}>
                            Или введите ключ вручную:
                        </div>
                        <div className="sp-chip sp-chip-mono" style={{
                            alignSelf: 'center',
                            fontSize: 12,
                            padding: '4px 10px',
                            wordBreak: 'break-all',
                            textAlign: 'center',
                        }}>
                            {setupPayload.secret}
                        </div>
                        <input
                            type="text"
                            value={code}
                            onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                            placeholder="000000"
                            inputMode="numeric"
                            autoComplete="one-time-code"
                            autoFocus
                            className="sp-input"
                            style={{
                                fontFamily: 'JetBrains Mono, ui-monospace, monospace',
                                letterSpacing: '0.4em',
                                textAlign: 'center',
                                fontSize: 18,
                            }}
                        />
                        <details>
                            <summary className="sp-row-hint" style={{ cursor: 'pointer' }}>
                                Резервные коды ({setupPayload.backup_codes.length})
                            </summary>
                            <div style={{
                                display: 'grid',
                                gridTemplateColumns: 'repeat(2, 1fr)',
                                gap: 6,
                                marginTop: 8,
                                fontFamily: 'JetBrains Mono, ui-monospace, monospace',
                                fontSize: 12,
                            }}>
                                {setupPayload.backup_codes.map((c) => (
                                    <span key={c} style={{
                                        padding: '4px 8px',
                                        background: 'var(--sp-surface-2)',
                                        borderRadius: 3,
                                        textAlign: 'center',
                                    }}>{c}</span>
                                ))}
                            </div>
                            <div className="sp-row-hint" style={{ marginTop: 6 }}>
                                Сохраните эти коды — они понадобятся при потере доступа к приложению.
                            </div>
                        </details>
                    </div>
                ) : (
                    <div className="sp-row-hint">
                        <AlertCircle size={13} /> Не удалось загрузить настройку. Попробуйте ещё раз.
                    </div>
                )}
            </Dialog>

            {/* Disable confirm */}
            <ConfirmDialog
                open={disableConfirmOpen}
                onClose={() => setDisableConfirmOpen(false)}
                onConfirm={() => disableMutation.mutate()}
                title="Отключить 2FA?"
                description="Аккаунт будет защищён только паролем. Это снизит безопасность."
                tone="danger"
                confirmLabel="Отключить"
            />

            {/* Backup codes regen result */}
            <Dialog
                open={Boolean(showBackup)}
                onClose={() => setShowBackup(null)}
                title="Новые резервные коды"
                description="Сохраните коды в надёжном месте. Старые коды больше не работают."
                width={400}
                footer={
                    <>
                        <span className="sp-spacer" />
                        <button
                            type="button"
                            className="sp-btn sp-btn-primary"
                            onClick={() => setShowBackup(null)}
                        >
                            Готово
                        </button>
                    </>
                }
            >
                {showBackup ? (
                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(2, 1fr)',
                        gap: 6,
                        fontFamily: 'JetBrains Mono, ui-monospace, monospace',
                        fontSize: 13,
                    }}>
                        {showBackup.map((c) => (
                            <span key={c} style={{
                                padding: '6px 10px',
                                background: 'var(--sp-surface-2)',
                                borderRadius: 4,
                                textAlign: 'center',
                            }}>{c}</span>
                        ))}
                    </div>
                ) : null}
            </Dialog>
        </>
    );
};
