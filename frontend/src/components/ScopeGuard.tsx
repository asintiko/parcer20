import { ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { securityApi } from '../services/api';
import { ru } from '../i18n/ru';
import { useAuth } from '../contexts/AuthContext';

type ScopeGuardProps = {
    children: ReactNode;
    action?: 'sources' | 'transactions';
};

export function ScopeGuard({ children, action = 'sources' }: ScopeGuardProps) {
    const { user } = useAuth();
    const queryClient = useQueryClient();
    const [otpCode, setOtpCode] = useState('');
    const [otpScopeId, setOtpScopeId] = useState<number | null>(null);
    const [otpExpiresAt, setOtpExpiresAt] = useState<number | null>(null);
    const [otpSecondsLeft, setOtpSecondsLeft] = useState<number>(0);
    const autoRequestKeyRef = useRef<string | null>(null);
    const isAdmin = user?.role === 'admin';

    const statusQuery = useQuery({
        queryKey: ['security-status'],
        queryFn: securityApi.getStatus,
        refetchInterval: 30000,
    });

    const scopesEnabled = Boolean(statusQuery.data?.scopes_enabled);
    const scopesQuery = useQuery({
        queryKey: ['security-scopes'],
        queryFn: securityApi.listScopes,
        enabled: statusQuery.isSuccess && scopesEnabled,
        refetchInterval: 30000,
    });

    const hasAccess = useMemo(() => {
        if (isAdmin) return true;
        if (!statusQuery.data) return false;
        if (!statusQuery.data.scopes_enabled) return true;
        const scope = statusQuery.data?.current_scope;
        if (!scope) return false;
        return action === 'sources' ? Boolean(scope.allow_sources) : Boolean(scope.allow_transactions);
    }, [statusQuery.data, action, isAdmin]);

    const statusErrorDetail = (statusQuery.error as any)?.response?.data?.detail;
    const statusErrorText =
        typeof statusErrorDetail === 'string'
            ? statusErrorDetail
            : statusErrorDetail?.error
                ? String(statusErrorDetail.error)
                : ru.scope.securityStatusUnavailable;
    const scopesErrorDetail = (scopesQuery.error as any)?.response?.data?.detail;
    const scopesErrorText =
        typeof scopesErrorDetail === 'string'
            ? scopesErrorDetail
            : scopesErrorDetail?.error
                ? String(scopesErrorDetail.error)
                : 'ошибка запроса';

    const targetScope = useMemo(() => {
        const scopes = (scopesQuery.data || []).filter((scope) => {
            if (!scope.is_active) return false;
            return action === 'sources' ? scope.allow_sources : scope.allow_transactions;
        });
        return scopes[0] || null;
    }, [scopesQuery.data, action]);

    const requestCodeMutation = useMutation({
        mutationFn: async (scopeId: number) => securityApi.requestScopeCode(scopeId),
        onSuccess: async (response, scopeId) => {
            // Global OTP may be disabled: backend returns scoped token immediately.
            // In this case we should refresh status and open section without code input UI.
            if (response?.otp_skipped && response?.token) {
                setOtpScopeId(null);
                setOtpCode('');
                setOtpExpiresAt(null);
                setOtpSecondsLeft(0);
                autoRequestKeyRef.current = null;
                await Promise.all([
                    queryClient.invalidateQueries({ queryKey: ['security-status'] }),
                    queryClient.invalidateQueries({ queryKey: ['security-scopes'] }),
                ]);
                return;
            }
            const seconds = Math.max(0, Number(response.expires_in) || 0);
            setOtpScopeId(scopeId);
            setOtpCode('');
            setOtpSecondsLeft(seconds);
            setOtpExpiresAt(Date.now() + seconds * 1000);
        },
    });

    const verifyCodeMutation = useMutation({
        mutationFn: async (payload: { scopeId: number; code: string }) =>
            securityApi.verifyScopeCode({
                scope_id: payload.scopeId,
                code: payload.code.trim(),
            }),
        onSuccess: async () => {
            setOtpCode('');
            setOtpScopeId(null);
            setOtpExpiresAt(null);
            setOtpSecondsLeft(0);
            await Promise.all([
                queryClient.invalidateQueries({ queryKey: ['security-status'] }),
                queryClient.invalidateQueries({ queryKey: ['security-scopes'] }),
            ]);
        },
    });

    useEffect(() => {
        if (!otpExpiresAt) return;
        const timer = window.setInterval(() => {
            const left = Math.max(0, Math.ceil((otpExpiresAt - Date.now()) / 1000));
            setOtpSecondsLeft(left);
            if (left <= 0) {
                setOtpExpiresAt(null);
            }
        }, 1000);
        return () => window.clearInterval(timer);
    }, [otpExpiresAt]);

    useEffect(() => {
        if (!statusQuery.isSuccess || !scopesEnabled || hasAccess || !targetScope) {
            autoRequestKeyRef.current = null;
            return;
        }
        if (requestCodeMutation.isPending) {
            return;
        }
        if (otpScopeId === targetScope.id && otpSecondsLeft > 0) {
            return;
        }
        const autoKey = `${action}:${targetScope.id}`;
        if (autoRequestKeyRef.current === autoKey) {
            return;
        }
        autoRequestKeyRef.current = autoKey;
        requestCodeMutation.mutate(targetScope.id);
    }, [
        action,
        hasAccess,
        otpScopeId,
        otpSecondsLeft,
        requestCodeMutation.isPending,
        requestCodeMutation.mutate,
        scopesEnabled,
        statusQuery.isSuccess,
        targetScope,
    ]);

    if (hasAccess) {
        return <>{children}</>;
    }

    if (statusQuery.isLoading || (statusQuery.isFetching && !statusQuery.data)) {
        return (
            <div className="h-full w-full flex items-center justify-center text-foreground-secondary">
                {ru.scope.checkingAccess}
            </div>
        );
    }

    if (statusQuery.isError && !statusQuery.data) {
        return (
            <div className="h-full w-full p-6 bg-bg text-foreground">
                <div className="max-w-xl mx-auto bg-surface border border-danger/40 rounded-lg p-6 space-y-3">
                    <h2 className="text-xl font-semibold text-danger">Доступ временно ограничен</h2>
                    <p className="text-sm text-foreground-secondary">
                        Не удалось проверить статус безопасности. До успешной проверки раздел остаётся закрыт.
                    </p>
                    <div className="text-xs text-danger">{statusErrorText}</div>
                </div>
            </div>
        );
    }

    return (
        <div className="h-full w-full p-6 bg-bg text-foreground">
            <div className="max-w-xl mx-auto bg-surface border border-border rounded-lg p-6 space-y-4">
                <h2 className="text-xl font-semibold">
                    {action === 'sources' ? ru.scope.accessClosed : ru.scope.accessRestricted}
                </h2>
                <p className="text-sm text-foreground-secondary">
                    {ru.scope.otpRequired}
                </p>

                {scopesQuery.isError ? (
                    <div className="text-sm text-danger">
                        Не удалось загрузить список доступов: {scopesErrorText}.
                    </div>
                ) : !targetScope ? (
                    <div className="text-sm text-danger">
                        {ru.scope.noActiveScopeForSources}
                    </div>
                ) : (
                    <div className="space-y-3">
                        <button
                            type="button"
                            className="px-3 py-2 rounded-lg border border-primary/40 bg-primary/10 hover:bg-primary/20 disabled:opacity-50"
                            disabled={requestCodeMutation.isPending}
                            onClick={() => requestCodeMutation.mutate(targetScope.id)}
                        >
                            {requestCodeMutation.isPending ? ru.scope.requesting : `${ru.scope.requestOtp} (${targetScope.name})`}
                        </button>

                        {otpScopeId ? (
                            <div className="space-y-2">
                                <form
                                    onSubmit={(e) => {
                                        e.preventDefault();
                                        const cleanCode = otpCode.replace(/\D/g, '');
                                        if (cleanCode.length < 4 || verifyCodeMutation.isPending) return;
                                        verifyCodeMutation.mutate({ scopeId: otpScopeId, code: cleanCode });
                                    }}
                                    className="space-y-2"
                                >
                                    <input
                                        type="text"
                                        value={otpCode}
                                        maxLength={6}
                                        onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, ''))}
                                        placeholder={ru.scope.enterCodePlaceholder}
                                        className="w-full px-3 py-2 rounded-lg border border-border bg-bg"
                                        autoFocus
                                        inputMode="numeric"
                                    />
                                    <div className="text-xs text-foreground-secondary">
                                        {otpSecondsLeft > 0 ? `${ru.scope.codeValidFor}: ${otpSecondsLeft}с` : ru.scope.codeExpired}
                                    </div>
                                    <button
                                        type="submit"
                                        className="px-3 py-2 rounded-lg border border-success/40 bg-success/10 hover:bg-success/20 disabled:opacity-50"
                                        disabled={otpCode.trim().length < 4 || verifyCodeMutation.isPending}
                                    >
                                        {verifyCodeMutation.isPending ? ru.scope.verifying : ru.scope.verifyCode}
                                    </button>
                                </form>
                            </div>
                        ) : null}

                        {requestCodeMutation.isError ? (
                            <div className="text-xs text-danger">
                                {(requestCodeMutation.error as any)?.response?.data?.detail || 'Не удалось запросить OTP-код'}
                            </div>
                        ) : null}
                        {verifyCodeMutation.isError ? (
                            <div className="text-xs text-danger">
                                {(verifyCodeMutation.error as any)?.response?.data?.detail || 'Неверный OTP-код'}
                            </div>
                        ) : null}
                    </div>
                )}
            </div>
        </div>
    );
}
