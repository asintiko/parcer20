import React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { systemSettingsApi, securityApi, type SystemSettings } from '../services/api';
import { ru } from '../i18n/ru';

interface SystemSettingsPanelProps {
    showToast: (type: 'success' | 'error' | 'info', message: string) => void;
}

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
            // When OTP toggled — invalidate scope token caches and refresh security queries
            if (variables.otp_enabled !== undefined) {
                securityApi.clearScopeToken();
                queryClient.invalidateQueries({ queryKey: ['security-status'] });
                queryClient.invalidateQueries({ queryKey: ['transactions-init'] });
                queryClient.invalidateQueries({ queryKey: ['security-scopes'] });
            }
        },
        onError: (err: any) => showToast('error', err?.response?.data?.detail || err?.message || ru.errors.updateError),
    });

    const settings = settingsQuery.data;
    if (!settings) {
        return (
            <section className="border border-border rounded-lg bg-surface p-4">
                <h2 className="text-lg font-semibold text-foreground">{ru.security.systemToggles}</h2>
                <div className="text-sm text-foreground-secondary mt-2">{ru.common.loading}</div>
            </section>
        );
    }

    const makeToggle = (key: keyof Pick<SystemSettings, 'otp_enabled' | 'bot_control_enabled' | 'totp_2fa_enabled' | 'launch_gate_enabled'>) => {
        updateMutation.mutate({ [key]: !settings[key] } as Partial<SystemSettings>);
    };

    return (
        <section className="border border-border rounded-lg bg-surface p-4 space-y-3">
            <h2 className="text-lg font-semibold text-foreground">{ru.security.systemToggles}</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                <button
                    type="button"
                    onClick={() => makeToggle('otp_enabled')}
                    disabled={updateMutation.isPending}
                    className="px-3 py-2 rounded-md border border-border bg-surface hover:bg-surface-2 text-left"
                >
                    {ru.security.otpByScope}: <b>{settings.otp_enabled ? ru.common.on : ru.common.off}</b>
                </button>
                <button
                    type="button"
                    onClick={() => makeToggle('bot_control_enabled')}
                    disabled={updateMutation.isPending}
                    className="px-3 py-2 rounded-md border border-border bg-surface hover:bg-surface-2 text-left"
                >
                    {ru.security.botControl}: <b>{settings.bot_control_enabled ? ru.common.on : ru.security.botReadOnly}</b>
                </button>
                <button
                    type="button"
                    onClick={() => makeToggle('totp_2fa_enabled')}
                    disabled={updateMutation.isPending}
                    className="px-3 py-2 rounded-md border border-border bg-surface hover:bg-surface-2 text-left"
                >
                    {ru.security.globalTotp}: <b>{settings.totp_2fa_enabled ? ru.common.on : ru.common.off}</b>
                </button>
                <button
                    type="button"
                    onClick={() => makeToggle('launch_gate_enabled')}
                    disabled={updateMutation.isPending}
                    className="px-3 py-2 rounded-md border border-border bg-surface hover:bg-surface-2 text-left"
                >
                    {ru.security.launchGateToggle}: <b>{settings.launch_gate_enabled ? ru.common.on : ru.common.off}</b>
                </button>
            </div>
            <div className="text-xs text-foreground-muted">
                {ru.common.updated}: {settings.updated_at || '-'} {settings.updated_by ? `(user #${settings.updated_by})` : ''}
            </div>
        </section>
    );
};
