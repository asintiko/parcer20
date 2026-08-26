import React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { systemSettingsApi, securityApi, type SystemSettings } from '../services/api';
import { ru } from '../i18n/ru';

interface SystemSettingsPanelProps {
    showToast: (type: 'success' | 'error' | 'info', message: string) => void;
}

type ToggleKey = 'otp_enabled' | 'bot_control_enabled' | 'totp_2fa_enabled' | 'launch_gate_enabled';

const TOGGLE_LABELS: Record<ToggleKey, { title: string; on: string; off: string; description: string }> = {
    otp_enabled: {
        title: 'OTP по scope',
        on: 'Включено',
        off: 'Выключено',
        description: 'Запрос одноразового кода при доступе к чувствительным разделам.',
    },
    bot_control_enabled: {
        title: 'Управление ботами',
        on: 'Включено',
        off: 'Только чтение',
        description: 'Если выключено — операторы не могут запускать и останавливать ботов.',
    },
    totp_2fa_enabled: {
        title: 'Глобальная 2FA',
        on: 'Включено',
        off: 'Выключено',
        description: 'Принудительно включить 2FA для всех пользователей при следующем входе.',
    },
    launch_gate_enabled: {
        title: 'Gate запуска',
        on: 'Включено',
        off: 'Выключено',
        description: 'Дополнительная проверка перед запуском задач. Снижает риск случайного запуска.',
    },
};

export const SystemSettingsPanel: React.FC<SystemSettingsPanelProps> = ({ showToast }) => {
    const queryClient = useQueryClient();
    const settingsQuery = useQuery({
        queryKey: ['system-settings'],
        queryFn: systemSettingsApi.get,
    });

    const updateMutation = useMutation({
        mutationFn: (payload: Partial<SystemSettings>) => systemSettingsApi.update(payload),
        onSuccess: (_data, variables) => {
            showToast('success', ru.common.settingsUpdated);
            queryClient.invalidateQueries({ queryKey: ['system-settings'] });
            if (variables.otp_enabled !== undefined) {
                securityApi.clearScopeToken();
                queryClient.invalidateQueries({ queryKey: ['security-status'] });
                queryClient.invalidateQueries({ queryKey: ['transactions-init'] });
                queryClient.invalidateQueries({ queryKey: ['security-scopes'] });
            }
        },
        onError: (err: any) =>
            showToast(
                'error',
                err?.response?.data?.detail || err?.message || ru.errors.updateError,
            ),
    });

    const settings = settingsQuery.data;
    if (settingsQuery.isLoading || !settings) {
        return (
            <div className="sp-card">
                <div className="sp-card-head">
                    <div>
                        <h2 className="sp-card-title">Системные тогглы</h2>
                        <div className="sp-card-sub">
                            Глобальные переключатели — влияют на всех пользователей.
                        </div>
                    </div>
                </div>
                <div className="sp-empty">
                    <div className="sp-empty-title">Загружаем…</div>
                    <div>{ru.common.loading}</div>
                </div>
            </div>
        );
    }

    const toggle = (key: ToggleKey) => {
        updateMutation.mutate({ [key]: !settings[key] } as Partial<SystemSettings>);
    };

    const meta = settings.updated_at
        ? `${settings.updated_at}${settings.updated_by ? ` · user #${settings.updated_by}` : ''}`
        : null;

    return (
        <div className="sp-card">
            <div className="sp-card-head">
                <div>
                    <h2 className="sp-card-title">Системные тогглы</h2>
                    <div className="sp-card-sub">
                        Глобальные переключатели — влияют на всех пользователей.
                    </div>
                </div>
                {meta ? (
                    <span className="sp-chip sp-chip-mono" title="Последнее обновление">обновлено · {meta}</span>
                ) : null}
            </div>
            <div className="sp-card-body">
                {(Object.keys(TOGGLE_LABELS) as ToggleKey[]).map((key) => {
                    const isOn = Boolean(settings[key]);
                    const label = TOGGLE_LABELS[key];
                    return (
                        <div key={key} className="sp-card-row">
                            <div>
                                <div className="sp-row-label">{label.title}</div>
                                <div className="sp-row-hint">{label.description}</div>
                            </div>
                            <div className="sp-row-control">
                                <label className="sp-toggle">
                                    <input
                                        type="checkbox"
                                        checked={isOn}
                                        disabled={updateMutation.isPending}
                                        onChange={() => toggle(key)}
                                    />
                                    <span className="sp-toggle-track" />
                                    <span className="sp-toggle-label">
                                        {isOn ? label.on : label.off}
                                    </span>
                                </label>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};
