/**
 * Main Application Component with Routing
 */
import { useState, useEffect, ComponentType, ReactNode, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BrowserRouter, HashRouter, Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { Menu } from 'lucide-react';
import { BurgerMenu } from './components/BurgerMenu';
import { AiAgentDrawer } from './components/AiAgentDrawer';
import { AiAgentLauncher } from './components/AiAgentLauncher';
import { ScopeGuard } from './components/ScopeGuard';
import { SyncStatus } from './components/SyncStatus';
import { useToast } from './components/Toast';
import { TransactionsPage } from './pages/TransactionsPage';
import { ReferencePage } from './pages/ReferencePage';
import { UserbotPage } from './pages/UserbotPage';
import { LogsPage } from './pages/LogsPage';
import { SettingsPage } from './pages/SettingsPage';
import { AuditPage } from './pages/AuditPage';
import { LoginPage } from './pages/LoginPage';
import { useAiAgent } from './contexts/AiAgentContext';
import { useAiAgentNotifications } from './hooks/useAiAgentNotifications';
import { useSettingsSubscription } from './hooks/useSettingsSubscription';
import { useScopeGuard } from './hooks/useScopeGuard';
import { ru } from './i18n/ru';
import { agentApi, API_BASE_URL, loadElectronSystemAccessStatus } from './services/api';
import { syncManager, type SyncSnapshot } from './services/syncManager';
import { useAuth } from './contexts/AuthContext';

function AppContent() {
    const [isMenuOpen, setIsMenuOpen] = useState(false);
    const [syncSnapshot, setSyncSnapshot] = useState<SyncSnapshot>({
        state: syncManager.getState(),
        statuses: syncManager.getStatuses(),
        backoffMs: syncManager.getBackoffMs(),
    });
    const location = useLocation();
    const { openAgent, isOpen: isAgentOpen } = useAiAgent();
    const { hasTab, firstAllowedRoute } = useAuth();
    const { showToast } = useToast();
    const { unreadCount } = useAiAgentNotifications();
    const [isBackendOnline, setIsBackendOnline] = useState(true);
    const launcherThreadsQuery = useQuery({
        queryKey: ['agent-launcher-state'],
        queryFn: () => agentApi.listThreads({ view: 'active' }),
        staleTime: 5000,
        refetchInterval: 5000,
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

    const getPageTitle = () => {
        switch (location.pathname) {
            case '/':
                return ru.nav.transactions;
            case '/reference':
                return ru.nav.reference;
            case '/automation':
                return 'AI-агент';
            case '/userbot':
                return ru.nav.telegramClient;
            case '/logs':
                return ru.nav.logs;
            case '/settings':
                return ru.nav.settings;
            case '/audit':
                return ru.nav.audit;
            default:
                return ru.nav.transactions;
        }
    };

    const guardRoute = (tab: string, element: ReactNode) => {
        if (hasTab(tab)) return element;
        return <Navigate to={firstAllowedRoute()} replace />;
    };

    return (
        <div className="h-screen w-full bg-bg flex flex-col overflow-hidden">
            <BurgerMenu isOpen={isMenuOpen} onClose={() => setIsMenuOpen(false)} />

            <header className="flex items-center h-14 px-4 bg-surface border-b border-border shadow-sm z-10 flex-shrink-0">
                <button
                    onClick={() => setIsMenuOpen(true)}
                    className="p-2 mr-4 rounded-lg hover:bg-surface-2 text-foreground-secondary transition-colors focus:outline-none focus:ring-2 focus:ring-primary"
                >
                    <Menu className="w-5 h-5" />
                </button>
                <h1 className="text-lg font-semibold text-foreground">{getPageTitle()}</h1>

                <div className="ml-auto flex items-center gap-3">
                    <div
                        className={`px-2.5 py-1 rounded-full text-xs font-medium border ${
                            isBackendOnline
                                ? 'bg-success/10 text-success border-success/30'
                                : 'bg-danger/10 text-danger border-danger/30'
                        }`}
                        title={isBackendOnline ? 'Backend доступен' : 'Backend недоступен'}
                    >
                        {isBackendOnline ? 'Сервер онлайн' : 'Сервер недоступен'}
                    </div>

                    <SyncStatus
                        state={syncIndicatorState}
                        lagRows={lagRows}
                        lastSyncAt={lastSyncAt}
                        tableStatuses={syncSnapshot.statuses}
                        onSync={() => {
                            void syncManager.runSyncCycle();
                        }}
                    />

                </div>
            </header>

            <div className="flex-1 min-h-0 overflow-hidden">
                <Routes>
                    <Route path="/" element={guardRoute('dashboard', <TransactionsPage />)} />
                    <Route path="/reference" element={guardRoute('reference', <ReferencePage />)} />
                    <Route
                        path="/automation"
                        element={<AutomationFallback onOpenAgent={() => openAgent({ systemMessage: 'Старый раздел заменён встроенным AI-агентом.' })} />}
                    />
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
                    <Route path="/settings" element={guardRoute('admin', <SettingsPage />)} />
                    <Route path="/audit" element={guardRoute('admin', <AuditPage />)} />
                    <Route path="*" element={<Navigate to={firstAllowedRoute()} replace />} />
                </Routes>
            </div>
            {!isAgentOpen ? (
                <AiAgentLauncher
                    unreadCount={unreadCount}
                    state={launcherState}
                    onClick={() => openAgent()}
                />
            ) : null}
            <AiAgentDrawer />
        </div>
    );
}

function AutomationFallback({ onOpenAgent }: { onOpenAgent: () => void }) {
    const navigate = useNavigate();
    const { firstAllowedRoute } = useAuth();

    useEffect(() => {
        onOpenAgent();
        navigate(firstAllowedRoute(), { replace: true });
    }, [firstAllowedRoute, navigate, onOpenAgent]);

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
