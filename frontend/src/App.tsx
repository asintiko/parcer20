/**
 * Main Application Component with Routing
 */
import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, useLocation, useNavigate } from 'react-router-dom';
import { Menu, Loader2, CheckCircle2 } from 'lucide-react';
import { BurgerMenu } from './components/BurgerMenu';
import { TransactionsPage } from './pages/TransactionsPage';
import { ReferencePage } from './pages/ReferencePage';
import { AutomationPage } from './pages/AutomationPage';
import { UserbotPage } from './pages/UserbotPage';
import { LogsPage } from './pages/LogsPage';
import { useAutomationStatus } from './hooks/useAutomationStatus';

const LAST_PAGE_KEY = 'last_visited_page';

function AppContent() {
    const [isMenuOpen, setIsMenuOpen] = useState(false);
    const location = useLocation();
    const navigate = useNavigate();
    const { isRunning, isCompleted, taskStatus } = useAutomationStatus();

    // Restore last page on mount
    useEffect(() => {
        const lastPage = localStorage.getItem(LAST_PAGE_KEY);
        if (lastPage && lastPage !== '/' && location.pathname === '/') {
            navigate(lastPage, { replace: true });
        }
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    // Save current page to localStorage
    useEffect(() => {
        localStorage.setItem(LAST_PAGE_KEY, location.pathname);
    }, [location.pathname]);

    const getPageTitle = () => {
        switch (location.pathname) {
            case '/':
                return 'Транзакции';
            case '/reference':
                return 'Справочник операторов';
            case '/automation':
                return 'Автоматизация';
            case '/userbot':
                return 'Telegram Bots';
            case '/logs':
                return 'Логи';
            default:
                return 'Транзакции';
        }
    };

    return (
        <div className="h-screen w-full bg-bg flex flex-col">
            <BurgerMenu isOpen={isMenuOpen} onClose={() => setIsMenuOpen(false)} />

            {/* Top Header */}
            <header className="flex items-center h-14 px-4 bg-surface border-b border-border shadow-sm z-10 flex-shrink-0">
                <button
                    onClick={() => setIsMenuOpen(true)}
                    className="p-2 mr-4 rounded-lg hover:bg-surface-2 text-foreground-secondary transition-colors focus:outline-none focus:ring-2 focus:ring-primary"
                >
                    <Menu className="w-5 h-5" />
                </button>
                <h1 className="text-lg font-semibold text-foreground">{getPageTitle()}</h1>

                {/* Background Automation Status Indicator */}
                {isRunning && location.pathname !== '/automation' && (
                    <button
                        type="button"
                        onClick={() => navigate('/automation')}
                        className="ml-4 flex items-center gap-2 px-3 py-1.5 bg-primary/10 hover:bg-primary/20 border border-primary/30 rounded-lg transition-colors"
                        title="Перейти к автоматизации"
                    >
                        <Loader2 className="w-4 h-4 text-primary animate-spin" />
                        <span className="text-sm text-primary font-medium">AI работает</span>
                        {taskStatus?.progress && (
                            <span className="text-xs text-primary/70">
                                {taskStatus.progress.processed}/{taskStatus.progress.total}
                            </span>
                        )}
                    </button>
                )}

                {isCompleted && location.pathname !== '/automation' && (
                    <button
                        type="button"
                        onClick={() => navigate('/automation')}
                        className="ml-4 flex items-center gap-2 px-3 py-1.5 bg-success/10 hover:bg-success/20 border border-success/30 rounded-lg transition-colors"
                        title="Перейти к автоматизации"
                    >
                        <CheckCircle2 className="w-4 h-4 text-success" />
                        <span className="text-sm text-success font-medium">AI завершен</span>
                        {taskStatus?.results?.suggestions_count !== undefined && (
                            <span className="text-xs text-success/70">
                                {taskStatus.results.suggestions_count} предложений
                            </span>
                        )}
                    </button>
                )}
            </header>

            {/* Main Content */}
            <div className="flex-1 overflow-hidden">
                <Routes>
                    <Route path="/" element={<TransactionsPage />} />
                    <Route path="/reference" element={<ReferencePage />} />
                    <Route path="/automation" element={<AutomationPage />} />
                    <Route path="/userbot" element={<UserbotPage />} />
                    <Route path="/logs" element={<LogsPage />} />
                </Routes>
            </div>
        </div>
    );
}

function App() {
    return (
        <BrowserRouter>
            <AppContent />
        </BrowserRouter>
    );
}

export default App;
