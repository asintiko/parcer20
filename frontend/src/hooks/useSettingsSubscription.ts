/**
 * Real-time subscription to system settings changes via WebSocket.
 * When OTP or other security settings change, immediately invalidates
 * relevant caches and notifies UI components.
 */
import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { API_BASE_URL, securityApi, getAuthToken } from '../services/api';
import { syncManager } from '../services/syncManager';

function buildWsUrl(): string {
    const base = API_BASE_URL.replace(/^http/, 'ws');
    const token = getAuthToken();
    return `${base}/api/tg/ws/tg${token ? `?token=${encodeURIComponent(token)}` : ''}`;
}

export function useSettingsSubscription(): void {
    const queryClient = useQueryClient();
    const wsRef = useRef<WebSocket | null>(null);
    const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const lastSyncUpdateTsRef = useRef<number>(0);

    useEffect(() => {
        let unmounted = false;

        function connect() {
            if (unmounted) return;
            const token = getAuthToken();
            if (!token) return; // Not authenticated

            try {
                const ws = new WebSocket(buildWsUrl());
                wsRef.current = ws;

                ws.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        if (data.type === 'settings-changed') {
                            const payload = data.payload || {};
                            // OTP toggled — clear all scope token caches
                            if (payload.otp_enabled !== undefined) {
                                securityApi.clearScopeToken();
                                queryClient.invalidateQueries({ queryKey: ['security-status'] });
                                queryClient.invalidateQueries({ queryKey: ['transactions-init'] });
                                queryClient.invalidateQueries({ queryKey: ['security-scopes'] });
                                window.dispatchEvent(
                                    new CustomEvent('otp-state-changed', {
                                        detail: { enabled: payload.otp_enabled },
                                    }),
                                );
                            }
                            // Any settings change — refresh system settings
                            queryClient.invalidateQueries({ queryKey: ['system-settings'] });
                            return;
                        }

                        if (data.type === 'locked-periods-changed') {
                            queryClient.invalidateQueries({ queryKey: ['locked-periods'] });
                            queryClient.invalidateQueries({ queryKey: ['transactions'] });
                            queryClient.invalidateQueries({ queryKey: ['transactions-init'] });
                            queryClient.invalidateQueries({ queryKey: ['transaction-years'] });
                            window.dispatchEvent(
                                new CustomEvent('locked-periods-changed', {
                                    detail: { payload: data.payload || {} },
                                }),
                            );
                            return;
                        }

                        if (data.type === 'sync-update') {
                            queryClient.invalidateQueries({ queryKey: ['transactions'] });
                            queryClient.invalidateQueries({ queryKey: ['transaction-years'] });
                            queryClient.invalidateQueries({ queryKey: ['transactions-init'] });
                            const nowTs = Date.now();
                            if (nowTs - lastSyncUpdateTsRef.current >= 1500) {
                                lastSyncUpdateTsRef.current = nowTs;
                                void syncManager.runSyncCycle();
                            }
                        }
                    } catch {
                        /* ignore parse errors */
                    }
                };

                ws.onclose = () => {
                    wsRef.current = null;
                    if (!unmounted) {
                        reconnectTimerRef.current = setTimeout(connect, 5000);
                    }
                };

                ws.onerror = () => {
                    ws.close();
                };
            } catch {
                if (!unmounted) {
                    reconnectTimerRef.current = setTimeout(connect, 5000);
                }
            }
        }

        connect();

        return () => {
            unmounted = true;
            if (reconnectTimerRef.current) {
                clearTimeout(reconnectTimerRef.current);
            }
            if (wsRef.current) {
                wsRef.current.close();
                wsRef.current = null;
            }
        };
    }, [queryClient]);
}
