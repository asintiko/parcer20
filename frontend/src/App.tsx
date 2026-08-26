/**
 * Main Application Component with Routing
 */
import { lazy, Suspense, useState, useEffect, ComponentType, ReactNode, useMemo, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BrowserRouter, HashRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import { AppShell } from './components/shell/AppShell';
import { AiAgentDrawer } from './components/AiAgentDrawer';
import { AiAgentLauncher } from './components/AiAgentLauncher';
import { ScopeGuard } from './components/ScopeGuard';
import { SyncStatus } from './components/SyncStatus';
import { useToast } from './components/Toast';
import { LoginPage } from './pages/LoginPage';
import { useAiAgent } from './contexts/AiAgentContext';
import { useAiAgentNotifications } from './hooks/useAiAgentNotifications';
import { useSettingsSubscription } from './hooks/useSettingsSubscription';
import { useScopeGuard } from './hooks/useScopeGuard';
import { ru } from './i18n/ru';
import { agentApi, API_BASE_URL, loadElectronSystemAccessStatus } from './services/api';
import { syncManager, type SyncSnapshot } from './services/syncManager';
import { useAuth } from './contexts/AuthContext';
import { useAnyOverlayOpen } from './utils/overlayStore';

const TransactionsPage = lazy(() => import('./pages/TransactionsPage').then((module) => ({ default: module.TransactionsPage })));
const ReferencePage = lazy(() => import('./pages/ReferencePage').then((module) => ({ default: module.ReferencePage })));
const UserbotPage = lazy(() => import('./pages/UserbotPage').then((module) => ({ default: module.UserbotPage })));
const LogsPage = lazy(() => import('./pages/LogsPage').then((module) => ({ default: module.LogsPage })));
const RoutinesPage = lazy(() => import('./pages/RoutinesPage').then((module) => ({ default: module.RoutinesPage })));
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((module) => ({ default: module.SettingsPage })));
const AuditPage = lazy(() => import('./pages/AuditPage').then((module) => ({ default: module.AuditPage })));

function RouteLoadingState() {
    return (
        <div className="flex min-h-[240px] items-center justify-center text-foreground-secondary" role="status">
            {ru.common.loading}
        </div>
    );
}

function AppContent() {
    const [syncSnapshot, setSyncSnapshot] = useState<SyncSnapshot>({
        state: syncManager.getState(),
        statuses: syncManager.getStatuses(),
        backoffMs: syncManager.getBackoffMs(),
    });
    const { openAgent, isOpen: isAgentOpen } = useAiAgent();
    const anyOverlayOpen = useAnyOverlayOpen();
    const { hasTab, firstAllowedRoute } = useAuth();
    const { showToast } = useToast();
    const { unreadCount } = useAiAgentNotifications();
    const [isBackendOnline, setIsBackendOnline] = useState(true);
    const launcherThreadsQuery = useQuery({
        queryKey: ['agent-launcher-state'],
        queryFn: () => agentApi.listThreads({ view: 'active' }),
        staleTime: 5000,
        // Event-driven via SSE invalidation. Only poll when the agent drawer is
        // open; while closed, keep a slow heartbeat so the launcher badge still
        // reflects running/unread state without hammering the backend.
        refetchInterval: isAgentOpen ? 8000 : 60000,
    });
    useSettingsSubscription();
    useScopeGuard();

    useEffect(() => syncManager.subscribe(setSyncSnapshot), []);

    useEffect(() => {
        let mounted = true;
        let timer: ReturnType<typeof setInterval> | null = null;

        const pingBackend = async () => {
            try {
                const response = await fetch(`${API_BASE_URL}/health`, {
                    method: 'GET',
                    cache: 'no-store',
                });
                if (!mounted) return;
                setIsBackendOnline(response.ok);
            } catch {
                if (!mounted) return;
                setIsBackendOnline(false);
            }
        };

        const handleOffline = () => setIsBackendOnline(false);
        const handleOnline = () => {
            void pingBackend();
        };

        window.addEventListener('offline', handleOffline);
        window.addEventListener('online', handleOnline);
        void pingBackend();
        timer = setInterval(() => {
            void pingBackend();
        }, 30000);

        return () => {
            mounted = false;
            if (timer) clearInterval(timer);
            window.removeEventListener('offline', handleOffline);
            window.removeEventListener('online', handleOnline);
        };
    }, []);

    useEffect(() => {
        const handler = (event: Event) => {
            const custom = event as CustomEvent<{ expected?: string; server?: string }>;
            const expected = custom.detail?.expected || 'unknown';
            const server = custom.detail?.server || 'unknown';
            showToast('warning', 'Версия сервера обновилась. Перезапустите клиент.', {
                details: `Сервер API: ${server}\nКлиент ожидает: ${expected}`,
                duration: 9000,
            });
        };
        window.addEventListener('api-version-mismatch', handler);
        return () => window.removeEventListener('api-version-mismatch', handler);
    }, [showToast]);

    const lastSyncAt = useMemo(() => {
        const candidates = syncSnapshot.statuses
            .map((item) => item.lastSyncAt)
            .filter((item): item is string => Boolean(item))
            .sort((a, b) => new Date(b).getTime() - new Date(a).getTime());
        return candidates[0] || null;
    }, [syncSnapshot.statuses]);

    const lagRows = useMemo(() => {
        const txStatus = syncSnapshot.statuses.find((item) => item.table === 'transactions');
        if (!txStatus) return 0;
        const lag = Number(txStatus.lagRows || 0);
        return lag > 0 ? lag : 0;
    }, [syncSnapshot.statuses]);

    const syncIndicatorState: 'idle' | 'syncing' | 'lagging' | 'error' = useMemo(() => {
        if (syncSnapshot.state === 'syncing') return 'syncing';
        if (syncSnapshot.state === 'error') return 'error';
        if (lagRows > 0) return 'lagging';
        return 'idle';
    }, [syncSnapshot.state, lagRows]);

    const launcherState = useMemo<'idle' | 'has_notifications' | 'thinking' | 'running' | 'error'>(() => {
        if (!isBackendOnline) return 'error';
        const threads = launcherThreadsQuery.data || [];
        if (threads.some((thread) => thread.latest_run_status === 'processing')) {
            return 'running';
        }
        if (
            threads.some((thread) =>
                thread.latest_run_status === 'queued' ||
                thread.latest_run_status === 'awaiting_confirmation',
            )
        ) {
            return 'thinking';
        }
        if (unreadCount > 0) return 'has_notifications';
        return 'idle';
    }, [isBackendOnline, launcherThreadsQuery.data, unreadCount]);

    const guardRoute = (tab: string, element: ReactNode) => {
        if (hasTab(tab)) return element;
        return <Navigate to={firstAllowedRoute()} replace />;
    };

    return (
        <AppShell
            rightSlot={(
                <>
                    <span
                        className={`rl-status-pill${isBackendOnline ? ' is-online' : ' is-offline'}`}
                        title={isBackendOnline ? 'Backend доступен' : 'Backend недоступен'}
                    >
                        <span className="rl-status-dot" />
                        {isBackendOnline ? 'онлайн' : 'офлайн'}
                    </span>
                    <SyncStatus
                        state={syncIndicatorState}
                        lagRows={lagRows}
                        lastSyncAt={lastSyncAt}
                        tableStatuses={syncSnapshot.statuses}
                        onSync={() => {
                            void syncManager.runSyncCycle();
                        }}
                    />
                </>
            )}
        >
            <Suspense fallback={<RouteLoadingState />}>
                <Routes>
                    <Route path="/" element={guardRoute('dashboard', <TransactionsPage />)} />
                    <Route path="/reference" element={guardRoute('reference', <ReferencePage />)} />
                    <Route
                        path="/userbot"
                        element={
                            guardRoute(
                                'userbot',
                                <ScopeGuard action="sources">
                                    <UserbotPage />
                                </ScopeGuard>
                            )
                        }
                    />
                    <Route path="/logs" element={guardRoute('logs', <LogsPage />)} />
                    <Route path="/routines" element={guardRoute('admin', <RoutinesPage />)} />
                    <Route path="/settings" element={guardRoute('admin', <SettingsPage />)} />
                    <Route path="/audit" element={guardRoute('admin', <AuditPage />)} />
                    <Route path="*" element={<Navigate to={firstAllowedRoute()} replace />} />
                </Routes>
            </Suspense>
            {!isAgentOpen && !anyOverlayOpen ? (
                <AiAgentLauncher
                    unreadCount={unreadCount}
                    state={launcherState}
                    onClick={() => openAgent()}
                />
            ) : null}
            <AiAgentDrawer />
            <AgentUiActionRouter />
        </AppShell>
    );
}

function AgentUiActionRouter() {
    const navigate = useNavigate();
    const { pendingUiAction, consumeUiAction } = useAiAgent();
    const lastTokenRef = useRef<number | null>(null);

    useEffect(() => {
        if (!pendingUiAction) return;
        if (lastTokenRef.current === pendingUiAction.token) return;

        if (pendingUiAction.kind === 'navigate_view') {
            const routeMap: Record<string, string> = {
                transactions: '/',
                dashboard: '/',
                monitored_chats: '/userbot',
                userbot: '/userbot',
                operators: '/reference',
                reference: '/reference',
                audit: '/audit',
                reports: '/audit',
                settings: '/settings',
                logs: '/logs',
            };
            const targetRoute =
                pendingUiAction.target?.route ||
                (pendingUiAction.target?.view ? routeMap[String(pendingUiAction.target.view).toLowerCase()] : null);
            if (targetRoute) {
                lastTokenRef.current = pendingUiAction.token;
                navigate(targetRoute);
                consumeUiAction();
            }
        }
    }, [pendingUiAction, navigate, consumeUiAction]);

    return null;
}

function App() {
    const { isAuthenticated, loading } = useAuth();

    const isElectron =
        typeof window !== 'undefined' &&
        (Boolean((window as any).electronAPI?.isElectron) ||
            navigator.userAgent.toLowerCase().includes('electron'));
    const [clientAccessLoading, setClientAccessLoading] = useState(isElectron);
    const [clientAccessStatus, setClientAccessStatus] = useState<any>(null);

    useEffect(() => {
        let mounted = true;
        if (!isElectron) {
            setClientAccessLoading(false);
            return () => {
                mounted = false;
            };
        }
        loadElectronSystemAccessStatus(true)
            .then((status) => {
                if (!mounted) return;
                setClientAccessStatus(status);
            })
            .finally(() => {
                if (mounted) {
                    setClientAccessLoading(false);
                }
            });
        return () => {
            mounted = false;
        };
    }, [isElectron]);

    const Router: ComponentType<{ children: ReactNode }> = isElectron ? HashRouter : BrowserRouter;

    if (isElectron && clientAccessLoading) {
        return (
            <div className="h-screen w-full bg-bg flex items-center justify-center text-foreground">
                {ru.common.checkingClientAccess}
            </div>
        );
    }

    if (isElectron && (!clientAccessStatus || !clientAccessStatus.ok)) {
        return (
            <div className="h-screen w-full bg-danger/10 flex items-center justify-center p-6">
                <div className="max-w-xl w-full bg-surface border border-danger/40 rounded-lg p-8">
                    <h2 className="text-2xl font-semibold text-danger text-center">{ru.common.accessBlocked}</h2>
                </div>
            </div>
        );
    }

    return (
        <Router>
            {loading ? (
                <div className="h-screen w-full flex items-center justify-center bg-bg text-foreground-secondary">
                    {ru.common.loading}
                </div>
            ) : isAuthenticated ? (
                <AppContent />
            ) : (
                <LoginPage />
            )}
        </Router>
    );
}

export default App;
