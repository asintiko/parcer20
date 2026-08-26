/**
 * Automation Page Component
 * AI-powered transaction analysis, application mapping, and data verification
 */
import { Fragment, useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { automationApi, telegramClientApi } from '../services/api';
import type {
    VerificationSuggestion,
    ReconciliationItem,
    ReconciliationSummary,
    ChatSyncStatusItem,
} from '../services/api';
import {
    Bot,
    Play,
    CheckCircle2,
    XCircle,
    Loader2,
    TrendingUp,
    TrendingDown,
    Check,
    Sparkles,
    AlertCircle,
    ShieldCheck,
    ArrowRight,
    Search,
    Calendar,
    RefreshCw,
    FileSearch,
    Link2,
    Unlink,
    AlertOctagon,
    Zap,
} from 'lucide-react';
import { EmptyState } from '../components/ui';

type TabType = 'mapping' | 'verification' | 'reconciliation';

export function AutomationPage() {
    const [activeTab, setActiveTab] = useState<TabType>(() => {
        return (localStorage.getItem('automation_active_tab') as TabType) || 'mapping';
    });

    useEffect(() => {
        localStorage.setItem('automation_active_tab', activeTab);
    }, [activeTab]);

    return (
        <div className="h-full flex flex-col bg-bg">
            <div className="flex-1 overflow-auto p-6">
                <div className="max-w-7xl mx-auto space-y-6">
                    {/* Page Header */}
                    <div className="flex items-center gap-3">
                        <div className="p-2 bg-gradient-to-br from-primary to-primary-dark rounded-lg">
                            <Bot className="w-6 h-6 text-foreground-inverse" />
                        </div>
                        <div>
                            <h1 className="text-2xl font-bold text-foreground">AI Автоматизация</h1>
                            <p className="text-sm text-foreground-secondary">Интеллектуальный анализ и сверка транзакций</p>
                        </div>
                    </div>

                    {/* Tabs */}
                    <div className="flex gap-1 bg-surface-2 p-1 rounded-lg w-fit">
                        <button
                            onClick={() => setActiveTab('mapping')}
                            className={`px-4 py-2 text-sm font-medium rounded-md transition-all flex items-center gap-2 ${
                                activeTab === 'mapping'
                                    ? 'bg-surface text-foreground shadow-sm'
                                    : 'text-foreground-secondary hover:text-foreground'
                            }`}
                        >
                            <Sparkles className="w-4 h-4" />
                            Сопоставление
                        </button>
                        <button
                            onClick={() => setActiveTab('verification')}
                            className={`px-4 py-2 text-sm font-medium rounded-md transition-all flex items-center gap-2 ${
                                activeTab === 'verification'
                                    ? 'bg-surface text-foreground shadow-sm'
                                    : 'text-foreground-secondary hover:text-foreground'
                            }`}
                        >
                            <ShieldCheck className="w-4 h-4" />
                            Сверка данных
                        </button>
                        <button
                            onClick={() => setActiveTab('reconciliation')}
                            className={`px-4 py-2 text-sm font-medium rounded-md transition-all flex items-center gap-2 ${
                                activeTab === 'reconciliation'
                                    ? 'bg-surface text-foreground shadow-sm'
                                    : 'text-foreground-secondary hover:text-foreground'
                            }`}
                        >
                            <FileSearch className="w-4 h-4" />
                            Сверка с ботами
                        </button>
                    </div>

                    {activeTab === 'mapping' && <MappingTab />}
                    {activeTab === 'verification' && <VerificationTab />}
                    {activeTab === 'reconciliation' && <ReconciliationTab />}
                </div>
            </div>
        </div>
    );
}

/* ─────────────────────────────────────────── */
/*  Tab 1: Application Mapping (existing)      */
/* ─────────────────────────────────────────── */
function MappingTab() {
    const [analysisConfig, setAnalysisConfig] = useState({
        limit: 100,
        only_unmapped: true,
        currency_filter: '',
    });
    const [activeTaskId, setActiveTaskId] = useState<string | null>(() => {
        return localStorage.getItem('automation_task_id') || null;
    });
    const [selectedSuggestions, setSelectedSuggestions] = useState<string[]>([]);
    const [filterConfidence, setFilterConfidence] = useState(0.0);

    useEffect(() => {
        if (activeTaskId) {
            localStorage.setItem('automation_task_id', activeTaskId);
        } else {
            localStorage.removeItem('automation_task_id');
        }
    }, [activeTaskId]);

    const startAnalysisMutation = useMutation({
        mutationFn: () => automationApi.analyzeTransactions(analysisConfig),
        onSuccess: (data) => setActiveTaskId(data.task_id),
    });

    const { data: taskStatus } = useQuery({
        queryKey: ['analyzeStatus', activeTaskId],
        queryFn: () => automationApi.getAnalyzeStatus(activeTaskId!),
        enabled: !!activeTaskId,
        refetchInterval: (query) => {
            if (!query.state.data) return false;
            return query.state.data.status === 'processing' || query.state.data.status === 'started' ? 2000 : false;
        },
    });

    useEffect(() => {
        if (taskStatus?.status === 'not_found' && activeTaskId) setActiveTaskId(null);
    }, [taskStatus?.status, activeTaskId]);

    const { data: suggestions, refetch: refetchSuggestions } = useQuery({
        queryKey: ['suggestions', activeTaskId, filterConfidence],
        queryFn: () => automationApi.getSuggestions({
            task_id: activeTaskId || undefined,
            confidence_min: filterConfidence,
            status: 'pending',
        }),
        enabled: !!activeTaskId && taskStatus?.status === 'completed',
    });

    const applySuggestionMutation = useMutation({
        mutationFn: (id: string) => automationApi.applySuggestion(id),
        onSuccess: () => refetchSuggestions(),
    });

    const rejectSuggestionMutation = useMutation({
        mutationFn: (id: string) => automationApi.rejectSuggestion(id),
        onSuccess: () => refetchSuggestions(),
    });

    const batchApplyMutation = useMutation({
        mutationFn: (ids: string[]) => automationApi.batchApplySuggestions(ids),
        onSuccess: () => { setSelectedSuggestions([]); refetchSuggestions(); },
    });

    const handleToggleSelection = (id: string) => {
        setSelectedSuggestions(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
    };
    const handleSelectAll = () => {
        if (!suggestions) return;
        setSelectedSuggestions(selectedSuggestions.length === suggestions.length ? [] : suggestions.map(s => s.id));
    };

    const groupedSuggestions = useMemo(() => {
        const source = suggestions || [];
        const groups = new Map<string, typeof source>();
        for (const item of source) {
            const key = String(item.operator_raw || 'Без оператора').trim() || 'Без оператора';
            const bucket = groups.get(key) || [];
            bucket.push(item);
            groups.set(key, bucket);
        }
        return Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b, 'ru'));
    }, [suggestions]);

    const getConfidenceColor = (c: number) => {
        if (c >= 0.8) return 'text-success bg-success-light border-success/30';
        if (c >= 0.5) return 'text-warning bg-warning-light border-warning/30';
        return 'text-danger bg-danger-light border-danger/30';
    };
    const getConfidenceIcon = (c: number) => {
        if (c >= 0.8) return <TrendingUp className="w-4 h-4" />;
        if (c >= 0.5) return <AlertCircle className="w-4 h-4" />;
        return <TrendingDown className="w-4 h-4" />;
    };

    return (
        <>
            {/* Config Card */}
            <div className="bg-surface rounded-lg shadow-sm border border-border p-6">
                <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-4">
                    <div>
                        <label className="block text-sm font-medium text-foreground mb-2">Лимит транзакций</label>
                        <input
                            type="number" min="1" max="1000"
                            value={analysisConfig.limit}
                            onChange={(e) => setAnalysisConfig({ ...analysisConfig, limit: parseInt(e.target.value) })}
                            className="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent bg-surface text-foreground"
                            disabled={taskStatus?.status === 'processing'}
                        />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-foreground mb-2">Валюта</label>
                        <select
                            value={analysisConfig.currency_filter}
                            onChange={(e) => setAnalysisConfig({ ...analysisConfig, currency_filter: e.target.value })}
                            className="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent bg-surface text-foreground"
                            disabled={taskStatus?.status === 'processing'}
                        >
                            <option value="">Все</option>
                            <option value="UZS">UZS</option>
                            <option value="USD">USD</option>
                        </select>
                    </div>
                    <div className="flex items-end">
                        <label className="flex items-center gap-2 cursor-pointer">
                            <input
                                type="checkbox"
                                checked={analysisConfig.only_unmapped}
                                onChange={(e) => setAnalysisConfig({ ...analysisConfig, only_unmapped: e.target.checked })}
                                className="w-4 h-4 text-primary border-border rounded focus:ring-primary"
                                disabled={taskStatus?.status === 'processing'}
                            />
                            <span className="text-sm font-medium text-foreground">Только неопределенные</span>
                        </label>
                    </div>
                    <div className="flex items-end">
                        <button
                            onClick={() => startAnalysisMutation.mutate()}
                            disabled={taskStatus?.status === 'processing' || startAnalysisMutation.isPending}
                            className="w-full px-4 py-2 bg-gradient-to-r from-primary to-primary-dark text-foreground-inverse font-medium rounded-lg hover:from-primary-hover hover:to-primary transition-all shadow-md disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 focus:outline-none focus:ring-2 focus:ring-primary"
                        >
                            {taskStatus?.status === 'processing' ? (
                                <><Loader2 className="w-4 h-4 animate-spin" />Анализ...</>
                            ) : (
                                <><Play className="w-4 h-4" />Запустить анализ</>
                            )}
                        </button>
                    </div>
                </div>

                <ProgressBar status={taskStatus} />

                {taskStatus?.status === 'completed' && taskStatus.results && (
                    <div className="mt-4 grid grid-cols-3 gap-4">
                        <StatCard label="Всего рекомендаций" value={taskStatus.results.suggestions_count} color="info" icon={<Sparkles className="w-8 h-8 text-info" />} />
                        <StatCard label="Высокая точность" value={taskStatus.results.high_confidence} color="success" icon={<TrendingUp className="w-8 h-8 text-success" />} />
                        <StatCard label="Низкая точность" value={taskStatus.results.low_confidence} color="warning" icon={<TrendingDown className="w-8 h-8 text-warning" />} />
                    </div>
                )}
            </div>

            {/* Suggestions Table */}
            {suggestions && suggestions.length > 0 && (
                <div className="bg-surface rounded-lg shadow-sm border border-border">
                    <div className="p-4 border-b border-border">
                        <div className="flex items-center justify-between">
                            <h2 className="text-lg font-semibold text-foreground">Рекомендации ИИ</h2>
                            <div className="flex items-center gap-4">
                                <div className="flex items-center gap-2">
                                    <label className="text-sm text-foreground-secondary">Мин. точность:</label>
                                    <input type="range" min="0" max="1" step="0.1" value={filterConfidence} onChange={(e) => setFilterConfidence(parseFloat(e.target.value))} className="w-32" />
                                    <span className="text-sm font-medium text-foreground w-12">{(filterConfidence * 100).toFixed(0)}%</span>
                                </div>
                                {selectedSuggestions.length > 0 && (
                                    <button onClick={() => batchApplyMutation.mutate(selectedSuggestions)} disabled={batchApplyMutation.isPending}
                                        className="px-4 py-2 bg-success text-foreground-inverse text-sm font-medium rounded-lg hover:bg-success-hover transition-colors flex items-center gap-2 focus:outline-none focus:ring-2 focus:ring-success">
                                        <Check className="w-4 h-4" />Применить выбранные ({selectedSuggestions.length})
                                    </button>
                                )}
                            </div>
                        </div>
                    </div>
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead className="bg-table-header border-b border-table-border">
                                <tr>
                                    <th className="px-4 py-3 text-left">
                                        <input
                                            type="checkbox"
                                            checked={suggestions.length > 0 && selectedSuggestions.length === suggestions.length}
                                            onChange={handleSelectAll}
                                            className="w-4 h-4 text-primary border-border rounded focus:ring-primary"
                                            aria-label="Выбрать все рекомендации"
                                        />
                                    </th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-foreground-secondary uppercase">Оператор</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-foreground-secondary uppercase">Текущее</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-foreground-secondary uppercase">Рекомендация</th>
                                    <th className="px-4 py-3 text-center text-xs font-semibold text-foreground-secondary uppercase">P2P</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-foreground-secondary uppercase">Точность</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-foreground-secondary uppercase">Обоснование</th>
                                    <th className="px-4 py-3 text-center text-xs font-semibold text-foreground-secondary uppercase">Действия</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-border">
                                {groupedSuggestions.map(([operatorName, rows]) => (
                                    <Fragment key={operatorName}>
                                        <tr className="bg-surface-2/60">
                                            <td colSpan={8} className="px-4 py-2 text-xs font-semibold text-foreground-secondary">
                                                Оператор: {operatorName} ({rows.length})
                                            </td>
                                        </tr>
                                        {rows.map((s) => (
                                            <tr key={s.id} className="hover:bg-table-row-hover transition-colors">
                                                <td className="px-4 py-3">
                                                    <input
                                                        type="checkbox"
                                                        checked={selectedSuggestions.includes(s.id)}
                                                        onChange={() => handleToggleSelection(s.id)}
                                                        className="w-4 h-4 text-primary border-border rounded focus:ring-primary"
                                                        aria-label={`Выбрать рекомендацию ${s.id}`}
                                                    />
                                                </td>
                                                <td className="px-4 py-3"><div className="text-sm font-medium text-foreground">{s.operator_raw}</div></td>
                                                <td className="px-4 py-3"><div className="text-sm text-foreground-secondary">{s.current_application || <span className="italic text-foreground-muted">Нет</span>}</div></td>
                                                <td className="px-4 py-3">
                                                    <div className="flex items-center gap-2">
                                                        <span className="text-sm font-medium text-foreground">{s.suggested_application}</span>
                                                        {s.is_new_application && <span className="px-2 py-0.5 text-xs font-medium bg-primary-light text-primary rounded-full">Новое</span>}
                                                    </div>
                                                </td>
                                                <td className="px-4 py-3">
                                                    <div className="flex justify-center">
                                                        {s.is_p2p
                                                            ? <span className="px-2 py-1 text-xs font-medium bg-info-light text-info rounded-full" title="Перевод между картами">P2P</span>
                                                            : <span className="px-2 py-1 text-xs font-medium bg-surface-2 text-foreground-secondary rounded-full">Услуга</span>
                                                        }
                                                    </div>
                                                </td>
                                                <td className="px-4 py-3">
                                                    <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium ${getConfidenceColor(s.confidence)}`}>
                                                        {getConfidenceIcon(s.confidence)}{(s.confidence * 100).toFixed(0)}%
                                                    </div>
                                                </td>
                                                <td className="px-4 py-3"><div className="text-sm text-foreground-secondary max-w-xs truncate" title={s.reasoning}>{s.reasoning}</div></td>
                                                <td className="px-4 py-3">
                                                    <div className="flex items-center justify-center gap-2">
                                                        <button
                                                            onClick={() => applySuggestionMutation.mutate(s.id)}
                                                            disabled={applySuggestionMutation.isPending}
                                                            className="p-1.5 text-success hover:bg-success-light rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-success"
                                                            title="Применить"
                                                            aria-label={`Применить рекомендацию ${s.id}`}
                                                        >
                                                            <CheckCircle2 className="w-5 h-5" />
                                                        </button>
                                                        <button
                                                            onClick={() => rejectSuggestionMutation.mutate(s.id)}
                                                            disabled={rejectSuggestionMutation.isPending}
                                                            className="p-1.5 text-danger hover:bg-danger-light rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-danger"
                                                            title="Отклонить"
                                                            aria-label={`Отклонить рекомендацию ${s.id}`}
                                                        >
                                                            <XCircle className="w-5 h-5" />
                                                        </button>
                                                    </div>
                                                </td>
                                            </tr>
                                        ))}
                                    </Fragment>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {taskStatus?.status === 'completed' && (!suggestions || suggestions.length === 0) && (
                <EmptyState icon={<CheckCircle2 className="w-8 h-8 text-foreground-muted" />} title="Рекомендаций не найдено" description="Все транзакции уже имеют корректные сопоставления приложений или не соответствуют критериям фильтрации." />
            )}
        </>
    );
}

/* ─────────────────────────────────────────── */
/*  Tab 2: Data Verification (new)             */
/* ─────────────────────────────────────────── */
function VerificationTab() {
    const [verifyConfig, setVerifyConfig] = useState({ limit: 50, date_from: '', date_to: '' });
    const [activeTaskId, setActiveTaskId] = useState<string | null>(() => {
        return localStorage.getItem('verification_task_id') || null;
    });
    const [selectedSuggestions, setSelectedSuggestions] = useState<string[]>([]);
    const [filterConfidence, setFilterConfidence] = useState(0.0);

    useEffect(() => {
        if (activeTaskId) localStorage.setItem('verification_task_id', activeTaskId);
        else localStorage.removeItem('verification_task_id');
    }, [activeTaskId]);

    const startVerifyMutation = useMutation({
        mutationFn: () => automationApi.verifyTransactions({
            limit: verifyConfig.limit,
            date_from: verifyConfig.date_from || undefined,
            date_to: verifyConfig.date_to || undefined,
        }),
        onSuccess: (data) => setActiveTaskId(data.task_id),
    });

    const { data: taskStatus } = useQuery({
        queryKey: ['verifyStatus', activeTaskId],
        queryFn: () => automationApi.getVerifyStatus(activeTaskId!),
        enabled: !!activeTaskId,
        refetchInterval: (query) => {
            if (!query.state.data) return false;
            return query.state.data.status === 'processing' || query.state.data.status === 'started' ? 2000 : false;
        },
    });

    useEffect(() => {
        if (taskStatus?.status === 'not_found' && activeTaskId) setActiveTaskId(null);
    }, [taskStatus?.status, activeTaskId]);

    const { data: suggestions, refetch: refetchSuggestions } = useQuery({
        queryKey: ['verificationSuggestions', activeTaskId, filterConfidence],
        queryFn: () => automationApi.getVerificationSuggestions({
            task_id: activeTaskId || undefined,
            confidence_min: filterConfidence,
            status: 'pending',
        }),
        enabled: !!activeTaskId && taskStatus?.status === 'completed',
    });

    const applyMutation = useMutation({
        mutationFn: (id: string) => automationApi.applyVerificationSuggestion(id),
        onSuccess: () => refetchSuggestions(),
    });

    const rejectMutation = useMutation({
        mutationFn: (id: string) => automationApi.rejectVerificationSuggestion(id),
        onSuccess: () => refetchSuggestions(),
    });

    const batchApplyMutation = useMutation({
        mutationFn: (ids: string[]) => automationApi.batchApplyVerificationSuggestions(ids),
        onSuccess: () => { setSelectedSuggestions([]); refetchSuggestions(); },
    });

    const handleToggle = (id: string) => {
        setSelectedSuggestions(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
    };
    const handleSelectAll = () => {
        if (!suggestions) return;
        setSelectedSuggestions(selectedSuggestions.length === suggestions.length ? [] : suggestions.map(s => s.id));
    };

    const getConfidenceColor = (c: number) => {
        if (c >= 0.8) return 'text-success bg-success-light border-success/30';
        if (c >= 0.5) return 'text-warning bg-warning-light border-warning/30';
        return 'text-danger bg-danger-light border-danger/30';
    };

    return (
        <>
            {/* Config Card */}
            <div className="bg-surface rounded-lg shadow-sm border border-border p-6">
                <div className="flex items-center gap-2 mb-4">
                    <ShieldCheck className="w-5 h-5 text-primary" />
                    <h2 className="text-lg font-semibold text-foreground">Сверка исходных данных</h2>
                </div>
                <p className="text-sm text-foreground-secondary mb-4">
                    AI сравнит исходный текст чеков с распарсенными данными в таблице и найдёт ошибки в дате, сумме, операторе и других полях.
                </p>

                <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-4">
                    <div>
                        <label className="block text-sm font-medium text-foreground mb-2">Лимит транзакций</label>
                        <input
                            type="number" min="1" max="500"
                            value={verifyConfig.limit}
                            onChange={(e) => setVerifyConfig({ ...verifyConfig, limit: parseInt(e.target.value) || 50 })}
                            className="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent bg-surface text-foreground"
                            disabled={taskStatus?.status === 'processing'}
                        />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-foreground mb-2 flex items-center gap-1">
                            <Calendar className="w-3.5 h-3.5" />Дата с
                        </label>
                        <input
                            type="date"
                            value={verifyConfig.date_from}
                            onChange={(e) => setVerifyConfig({ ...verifyConfig, date_from: e.target.value })}
                            className="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent bg-surface text-foreground"
                            disabled={taskStatus?.status === 'processing'}
                        />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-foreground mb-2 flex items-center gap-1">
                            <Calendar className="w-3.5 h-3.5" />Дата по
                        </label>
                        <input
                            type="date"
                            value={verifyConfig.date_to}
                            onChange={(e) => setVerifyConfig({ ...verifyConfig, date_to: e.target.value })}
                            className="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent bg-surface text-foreground"
                            disabled={taskStatus?.status === 'processing'}
                        />
                    </div>
                    <div className="flex items-end">
                        <button
                            onClick={() => startVerifyMutation.mutate()}
                            disabled={taskStatus?.status === 'processing' || startVerifyMutation.isPending}
                            className="w-full px-4 py-2 bg-gradient-to-r from-primary to-primary-dark text-foreground-inverse font-medium rounded-lg hover:from-primary-hover hover:to-primary transition-all shadow-md disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 focus:outline-none focus:ring-2 focus:ring-primary"
                        >
                            {taskStatus?.status === 'processing' ? (
                                <><Loader2 className="w-4 h-4 animate-spin" />Сверка...</>
                            ) : (
                                <><Search className="w-4 h-4" />Запустить сверку</>
                            )}
                        </button>
                    </div>
                </div>

                <ProgressBar status={taskStatus} />

                {taskStatus?.status === 'completed' && taskStatus.results && (
                    <div className="mt-4 grid grid-cols-3 gap-4">
                        <StatCard
                            label="Проверено транзакций"
                            value={(taskStatus.results as any).total_verified}
                            color="info"
                            icon={<ShieldCheck className="w-8 h-8 text-info" />}
                        />
                        <StatCard
                            label="С ошибками"
                            value={(taskStatus.results as any).transactions_with_errors}
                            color="danger"
                            icon={<AlertCircle className="w-8 h-8 text-danger" />}
                        />
                        <StatCard
                            label="Всего исправлений"
                            value={(taskStatus.results as any).total_corrections}
                            color="warning"
                            icon={<Sparkles className="w-8 h-8 text-warning" />}
                        />
                    </div>
                )}
            </div>

            {/* Verification Suggestions Table */}
            {suggestions && suggestions.length > 0 && (
                <div className="bg-surface rounded-lg shadow-sm border border-border">
                    <div className="p-4 border-b border-border">
                        <div className="flex items-center justify-between">
                            <h2 className="text-lg font-semibold text-foreground">Найденные ошибки</h2>
                            <div className="flex items-center gap-4">
                                <div className="flex items-center gap-2">
                                    <label className="text-sm text-foreground-secondary">Мин. точность:</label>
                                    <input type="range" min="0" max="1" step="0.1" value={filterConfidence} onChange={(e) => setFilterConfidence(parseFloat(e.target.value))} className="w-32" />
                                    <span className="text-sm font-medium text-foreground w-12">{(filterConfidence * 100).toFixed(0)}%</span>
                                </div>
                                {selectedSuggestions.length > 0 && (
                                    <button onClick={() => batchApplyMutation.mutate(selectedSuggestions)} disabled={batchApplyMutation.isPending}
                                        className="px-4 py-2 bg-success text-foreground-inverse text-sm font-medium rounded-lg hover:bg-success-hover transition-colors flex items-center gap-2 focus:outline-none focus:ring-2 focus:ring-success">
                                        <Check className="w-4 h-4" />Исправить выбранные ({selectedSuggestions.length})
                                    </button>
                                )}
                            </div>
                        </div>
                    </div>
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead className="bg-table-header border-b border-table-border">
                                <tr>
                                    <th className="px-4 py-3 text-left">
                                        <input
                                            type="checkbox"
                                            checked={suggestions.length > 0 && selectedSuggestions.length === suggestions.length}
                                            onChange={handleSelectAll}
                                            className="w-4 h-4 text-primary border-border rounded focus:ring-primary"
                                            aria-label="Выбрать все исправления"
                                        />
                                    </th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-foreground-secondary uppercase">ID</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-foreground-secondary uppercase">Поле</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-foreground-secondary uppercase">Текущее значение</th>
                                    <th className="px-4 py-3 text-center text-xs font-semibold text-foreground-secondary uppercase"></th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-foreground-secondary uppercase">Предложенное</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-foreground-secondary uppercase">Точность</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-foreground-secondary uppercase">Причина</th>
                                    <th className="px-4 py-3 text-center text-xs font-semibold text-foreground-secondary uppercase">Действия</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-border">
                                {suggestions.map((s: VerificationSuggestion) => (
                                    <tr key={s.id} className="hover:bg-table-row-hover transition-colors">
                                        <td className="px-4 py-3">
                                            <input
                                                type="checkbox"
                                                checked={selectedSuggestions.includes(s.id)}
                                                onChange={() => handleToggle(s.id)}
                                                className="w-4 h-4 text-primary border-border rounded focus:ring-primary"
                                                aria-label={`Выбрать исправление ${s.id}`}
                                            />
                                        </td>
                                        <td className="px-4 py-3">
                                            <span className="text-xs font-mono text-foreground-secondary">#{s.transaction_id}</span>
                                        </td>
                                        <td className="px-4 py-3">
                                            <span className="inline-flex px-2 py-1 text-xs font-medium bg-surface-2 text-foreground rounded-md">
                                                {s.field_label}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3">
                                            <span className="text-sm text-danger line-through">
                                                {s.current_value || <span className="italic text-foreground-muted">пусто</span>}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3 text-center">
                                            <ArrowRight className="w-4 h-4 text-foreground-muted mx-auto" />
                                        </td>
                                        <td className="px-4 py-3">
                                            <span className="text-sm font-medium text-success">
                                                {s.suggested_value || <span className="italic text-foreground-muted">пусто</span>}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3">
                                            <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium ${getConfidenceColor(s.confidence)}`}>
                                                {(s.confidence * 100).toFixed(0)}%
                                            </div>
                                        </td>
                                        <td className="px-4 py-3">
                                            <div className="text-sm text-foreground-secondary max-w-xs truncate" title={s.reasoning || ''}>
                                                {s.reasoning}
                                            </div>
                                        </td>
                                        <td className="px-4 py-3">
                                            <div className="flex items-center justify-center gap-2">
                                                <button onClick={() => applyMutation.mutate(s.id)} disabled={applyMutation.isPending} className="p-1.5 text-success hover:bg-success-light rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-success" title="Исправить"><CheckCircle2 className="w-5 h-5" /></button>
                                                <button onClick={() => rejectMutation.mutate(s.id)} disabled={rejectMutation.isPending} className="p-1.5 text-danger hover:bg-danger-light rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-danger" title="Отклонить"><XCircle className="w-5 h-5" /></button>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {taskStatus?.status === 'completed' && (!suggestions || suggestions.length === 0) && (
                <EmptyState icon={<ShieldCheck className="w-8 h-8 text-foreground-muted" />} title="Ошибок не найдено" description="Все проверенные транзакции корректно распарсены — данные совпадают с исходными чеками." />
            )}
        </>
    );
}

/* ─────────────────────────────────────────── */
/*  Tab 3: Reconciliation with bots            */
/* ─────────────────────────────────────────── */

type ReconcileCategory = 'all' | 'MATCHED' | 'MISSING_IN_DB' | 'FAILED_PARSE' | 'ORPHANED_IN_DB';

function ReconciliationTab() {
    const [config, setConfig] = useState({
        period_start: '',
        period_end: '',
        bot_chat_ids: [] as number[],
        auto_parse: false,
        source: 'local' as 'local' | 'tdlib',
    });
    const [activeTaskId, setActiveTaskId] = useState<string | null>(() =>
        localStorage.getItem('reconciliation_task_id') || null,
    );
    const [categoryFilter, setCategoryFilter] = useState<ReconcileCategory>('all');
    const autoParseRefreshTimersRef = useRef<number[]>([]);

    useEffect(() => {
        if (activeTaskId) localStorage.setItem('reconciliation_task_id', activeTaskId);
        else localStorage.removeItem('reconciliation_task_id');
    }, [activeTaskId]);

    // Load available chats (bots)
    const { data: chatsData } = useQuery({
        queryKey: ['reconciliation-chats'],
        queryFn: () => telegramClientApi.getChats({ chat_types: 'bot', limit: 200 }),
    });

    const botChats = chatsData?.items ?? [];

    // Sync status for selected chats
    const { data: syncStatuses, refetch: refetchSync } = useQuery({
        queryKey: ['reconciliation-sync-status', config.bot_chat_ids],
        queryFn: () => automationApi.getChatSyncStatuses(config.bot_chat_ids),
        enabled: config.bot_chat_ids.length > 0,
        refetchInterval: 10000,
    });

    // Task status polling
    const { data: taskStatus } = useQuery({
        queryKey: ['reconcileStatus', activeTaskId],
        queryFn: () => automationApi.getReconcileStatus(activeTaskId!),
        enabled: !!activeTaskId,
        refetchInterval: (query) => {
            if (!query.state.data) return false;
            return query.state.data.status === 'processing' ? 2000 : false;
        },
    });

    // Results
    const { data: resultsData, refetch: refetchResults } = useQuery({
        queryKey: ['reconcileResults', activeTaskId, categoryFilter],
        queryFn: () =>
            automationApi.getReconcileResults(activeTaskId!, {
                category: categoryFilter === 'all' ? undefined : categoryFilter,
                limit: 500,
            }),
        enabled: !!activeTaskId && taskStatus?.status === 'completed',
    });

    useEffect(() => {
        if (taskStatus?.status === 'not_found' && activeTaskId) setActiveTaskId(null);
    }, [taskStatus?.status, activeTaskId]);

    const scheduleResultsRefresh = useCallback(() => {
        autoParseRefreshTimersRef.current.forEach((timerId) => window.clearTimeout(timerId));
        autoParseRefreshTimersRef.current = [];

        // Parsing runs in background workers, so refresh results with delay.
        [5000, 12000, 25000].forEach((delayMs) => {
            const timerId = window.setTimeout(() => {
                refetchResults();
                refetchSync();
            }, delayMs);
            autoParseRefreshTimersRef.current.push(timerId);
        });
    }, [refetchResults, refetchSync]);

    useEffect(() => {
        return () => {
            autoParseRefreshTimersRef.current.forEach((timerId) => window.clearTimeout(timerId));
            autoParseRefreshTimersRef.current = [];
        };
    }, []);

    // Start mutation
    const startMutation = useMutation({
        mutationFn: () =>
            automationApi.reconcileStart({
                period_start: config.period_start,
                period_end: config.period_end,
                bot_chat_ids: config.bot_chat_ids,
                auto_parse: config.auto_parse,
                source: config.source,
            }),
        onSuccess: (data) => {
            setActiveTaskId(data.task_id);
            setCategoryFilter('all');
        },
    });

    // Auto-parse mutation
    const autoParseMutation = useMutation({
        mutationFn: () => automationApi.autoParseReconciliation(activeTaskId!),
        onSuccess: () => {
            refetchResults();
            scheduleResultsRefresh();
        },
    });

    // Sync a specific chat
    const syncChatMutation = useMutation({
        mutationFn: (chatId: number) => telegramClientApi.startHistoryLoad(chatId),
        onSuccess: () => refetchSync(),
    });

    const toggleChat = useCallback(
        (chatId: number) => {
            setConfig((prev) => ({
                ...prev,
                bot_chat_ids: prev.bot_chat_ids.includes(chatId)
                    ? prev.bot_chat_ids.filter((id) => id !== chatId)
                    : [...prev.bot_chat_ids, chatId],
            }));
        },
        [],
    );

    const summary: ReconciliationSummary | null = resultsData?.summary ?? null;
    const items: ReconciliationItem[] = resultsData?.items ?? [];
    const isProcessing = taskStatus?.status === 'processing';
    const isCompleted = taskStatus?.status === 'completed';

    const canStart =
        config.period_start &&
        config.period_end &&
        config.bot_chat_ids.length > 0 &&
        !isProcessing &&
        !startMutation.isPending;

    // Lookup chat titles
    const chatTitleMap = new Map(botChats.map((c) => [c.chat_id, c.title]));
    // Lookup sync statuses
    const syncMap = new Map((syncStatuses ?? []).map((s) => [s.chat_id, s]));

    const getCategoryBadge = (cat: string) => {
        switch (cat) {
            case 'MATCHED':
                return (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-success/15 text-success">
                        <Link2 className="w-3 h-3" />Совпадение
                    </span>
                );
            case 'MISSING_IN_DB':
                return (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-danger/15 text-danger">
                        <Unlink className="w-3 h-3" />Не распарсен
                    </span>
                );
            case 'FAILED_PARSE':
                return (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-warning/15 text-warning">
                        <AlertCircle className="w-3 h-3" />Ошибка парсинга
                    </span>
                );
            case 'ORPHANED_IN_DB':
                return (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-info/15 text-info">
                        <AlertOctagon className="w-3 h-3" />Осиротевший
                    </span>
                );
            default:
                return <span className="text-xs text-foreground-secondary">{cat}</span>;
        }
    };

    const getSyncBadge = (status: ChatSyncStatusItem | undefined) => {
        if (!status || status.status === 'not_started') {
            return <span className="text-xs text-warning">Не синхронизирован</span>;
        }
        if (status.status === 'loading') {
            return (
                <span className="inline-flex items-center gap-1 text-xs text-info">
                    <Loader2 className="w-3 h-3 animate-spin" />Синхронизация...
                </span>
            );
        }
        if (status.status === 'completed') {
            return (
                <span className="text-xs text-success">
                    Синхронизирован ({status.loaded_count.toLocaleString()} сообщ.)
                </span>
            );
        }
        if (status.status === 'error') {
            return <span className="text-xs text-danger">Ошибка синхронизации</span>;
        }
        return <span className="text-xs text-foreground-secondary">{status.status}</span>;
    };

    const formatDate = (d: string | null) => {
        if (!d) return '—';
        try {
            return new Date(d).toLocaleString('ru-RU', {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
            });
        } catch {
            return d;
        }
    };

    const missingCount = (summary?.missing_in_db ?? 0) + (summary?.failed_parse ?? 0);

    return (
        <>
            {/* Config Card */}
            <div className="bg-surface rounded-lg shadow-sm border border-border p-6">
                <div className="flex items-center gap-2 mb-4">
                    <FileSearch className="w-5 h-5 text-primary" />
                    <h2 className="text-lg font-semibold text-foreground">Сверка с ботами</h2>
                </div>
                <p className="text-sm text-foreground-secondary mb-4">
                    Сравнение синхронизированной истории чатов с распарсенными транзакциями. Находит пропущенные чеки и осиротевшие записи.
                </p>

                {/* Date range */}
                <div className="grid grid-cols-1 md:grid-cols-5 gap-4 mb-4">
                    <div>
                        <label className="block text-sm font-medium text-foreground mb-2 flex items-center gap-1">
                            <Calendar className="w-3.5 h-3.5" />Период с
                        </label>
                        <input
                            type="date"
                            value={config.period_start}
                            onChange={(e) => setConfig({ ...config, period_start: e.target.value })}
                            className="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent bg-surface text-foreground"
                            disabled={isProcessing}
                        />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-foreground mb-2 flex items-center gap-1">
                            <Calendar className="w-3.5 h-3.5" />Период по
                        </label>
                        <input
                            type="date"
                            value={config.period_end}
                            onChange={(e) => setConfig({ ...config, period_end: e.target.value })}
                            className="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent bg-surface text-foreground"
                            disabled={isProcessing}
                        />
                    </div>
                    <div className="flex items-end">
                        <label className="flex items-center gap-2 cursor-pointer">
                            <input
                                type="checkbox"
                                checked={config.auto_parse}
                                onChange={(e) => setConfig({ ...config, auto_parse: e.target.checked })}
                                className="w-4 h-4 text-primary border-border rounded focus:ring-primary"
                                disabled={isProcessing}
                            />
                            <span className="text-sm font-medium text-foreground">Авто-парсинг пропущенных</span>
                        </label>
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-foreground mb-2">Источник данных</label>
                        <select
                            value={config.source}
                            onChange={(e) => setConfig({ ...config, source: e.target.value as 'local' | 'tdlib' })}
                            className="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent bg-surface text-foreground"
                            disabled={isProcessing}
                            aria-label="Источник данных для сверки"
                        >
                            <option value="local">Локальная история (PostgreSQL)</option>
                            <option value="tdlib">TDLib (fallback)</option>
                        </select>
                    </div>
                    <div className="flex items-end">
                        <button
                            onClick={() => startMutation.mutate()}
                            disabled={!canStart}
                            className="w-full px-4 py-2 bg-gradient-to-r from-primary to-primary-dark text-foreground-inverse font-medium rounded-lg hover:from-primary-hover hover:to-primary transition-all shadow-md disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 focus:outline-none focus:ring-2 focus:ring-primary"
                        >
                            {isProcessing ? (
                                <><Loader2 className="w-4 h-4 animate-spin" />Сверка...</>
                            ) : (
                                <><FileSearch className="w-4 h-4" />Начать сверку</>
                            )}
                        </button>
                    </div>
                </div>

                {/* Chat selection */}
                <div className="mb-4">
                    <label className="block text-sm font-medium text-foreground mb-2">
                        Чаты для сверки ({config.bot_chat_ids.length} выбрано)
                    </label>
                    <div className="max-h-48 overflow-y-auto border border-border rounded-lg divide-y divide-border">
                        {botChats.length === 0 && (
                            <div className="p-3 text-sm text-foreground-muted text-center">
                                Нет доступных ботов
                            </div>
                        )}
                        {botChats.map((chat) => {
                            const isChecked = config.bot_chat_ids.includes(chat.chat_id);
                            const syncStatus = syncMap.get(chat.chat_id);
                            const needsSync = !syncStatus || syncStatus.status === 'not_started' || syncStatus.status === 'error';
                            return (
                                <div
                                    key={chat.chat_id}
                                    className={`flex items-center gap-3 px-3 py-2 hover:bg-surface-2/50 transition-colors ${
                                        isChecked ? 'bg-primary/5' : ''
                                    }`}
                                >
                                    <input
                                        type="checkbox"
                                        checked={isChecked}
                                        onChange={() => toggleChat(chat.chat_id)}
                                        className="w-4 h-4 text-primary border-border rounded focus:ring-primary flex-shrink-0"
                                        disabled={isProcessing}
                                        aria-label={`Выбрать чат ${chat.title}`}
                                    />
                                    <div className="flex-1 min-w-0">
                                        <div className="text-sm font-medium text-foreground truncate">{chat.title}</div>
                                        <div className="flex items-center gap-2 mt-0.5">
                                            {getSyncBadge(syncStatus)}
                                        </div>
                                    </div>
                                    {needsSync && (
                                        <button
                                            type="button"
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                syncChatMutation.mutate(chat.chat_id);
                                            }}
                                            disabled={syncChatMutation.isPending}
                                            className="px-2 py-1 text-xs rounded-md border border-border text-foreground-secondary hover:bg-surface-2 disabled:opacity-50 flex items-center gap-1"
                                        >
                                            <RefreshCw className="w-3 h-3" />
                                            Синхронизировать
                                        </button>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </div>

                {/* Progress bar */}
                {isProcessing && taskStatus?.progress && (
                    <div className="mt-4">
                        <div className="flex justify-between items-center mb-2">
                            <span className="text-sm font-medium text-foreground">
                                {taskStatus.progress.step === 'loading_messages' && 'Загрузка сообщений...'}
                                {taskStatus.progress.step === 'matching' && 'Сопоставление...'}
                                {taskStatus.progress.step === 'classifying' && 'Классификация...'}
                                {taskStatus.progress.step === 'orphan_check' && 'Поиск осиротевших...'}
                                {taskStatus.progress.step === 'auto_parsing' && 'Авто-парсинг...'}
                                {taskStatus.progress.step === 'done' && 'Готово'}
                                {!taskStatus.progress.step && 'Обработка...'}
                            </span>
                            <span className="text-sm font-bold text-primary">
                                {taskStatus.progress.percent ?? 0}%
                            </span>
                        </div>
                        <div className="w-full bg-surface-2 rounded-full h-3 overflow-hidden">
                            <div
                                className="h-full bg-gradient-to-r from-primary to-primary-dark transition-all duration-500 ease-out"
                                style={{ width: `${taskStatus.progress.percent ?? 0}%` }}
                            />
                        </div>
                    </div>
                )}

                {/* Summary stat cards */}
                {isCompleted && summary && (
                    <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-4">
                        <StatCard
                            label="Совпадения"
                            value={summary.matched}
                            color="success"
                            icon={<Link2 className="w-8 h-8 text-success" />}
                        />
                        <StatCard
                            label="Не распарсены"
                            value={summary.missing_in_db}
                            color="danger"
                            icon={<Unlink className="w-8 h-8 text-danger" />}
                        />
                        <StatCard
                            label="Ошибки парсинга"
                            value={summary.failed_parse}
                            color="warning"
                            icon={<AlertCircle className="w-8 h-8 text-warning" />}
                        />
                        <StatCard
                            label="Осиротевшие"
                            value={summary.orphaned_in_db}
                            color="info"
                            icon={<AlertOctagon className="w-8 h-8 text-info" />}
                        />
                    </div>
                )}

                {/* Sync warnings */}
                {startMutation.data?.sync_warnings && startMutation.data.sync_warnings.length > 0 && (
                    <div className="mt-3 p-3 rounded-md bg-warning/10 border border-warning/30 text-sm text-warning">
                        <div className="font-medium mb-1">Предупреждения синхронизации:</div>
                        {startMutation.data.sync_warnings.map((w, i) => (
                            <div key={i} className="text-xs">{w.message}</div>
                        ))}
                    </div>
                )}
            </div>

            {/* Results table */}
            {isCompleted && items.length > 0 && (
                <div className="bg-surface rounded-lg shadow-sm border border-border">
                    <div className="p-4 border-b border-border">
                        <div className="flex items-center justify-between flex-wrap gap-3">
                            <h2 className="text-lg font-semibold text-foreground">
                                Результаты сверки ({resultsData?.total_items ?? items.length})
                            </h2>
                            <div className="flex items-center gap-3 flex-wrap">
                                {/* Category filter */}
                                <div className="flex gap-1 bg-surface-2 p-0.5 rounded-md">
                                    {([
                                        ['all', 'Все'],
                                        ['MATCHED', 'Совпадения'],
                                        ['MISSING_IN_DB', 'Не распарсены'],
                                        ['FAILED_PARSE', 'Ошибки'],
                                        ['ORPHANED_IN_DB', 'Осиротевшие'],
                                    ] as [ReconcileCategory, string][]).map(([key, label]) => (
                                        <button
                                            key={key}
                                            onClick={() => setCategoryFilter(key)}
                                            className={`px-2.5 py-1 text-xs rounded-md transition-all ${
                                                categoryFilter === key
                                                    ? 'bg-surface text-foreground shadow-sm font-medium'
                                                    : 'text-foreground-secondary hover:text-foreground'
                                            }`}
                                        >
                                            {label}
                                        </button>
                                    ))}
                                </div>
                                {/* Bulk auto-parse */}
                                {missingCount > 0 && (
                                    <button
                                        onClick={() => autoParseMutation.mutate()}
                                        disabled={autoParseMutation.isPending}
                                        className="px-3 py-1.5 bg-primary/10 text-primary text-xs font-medium rounded-lg hover:bg-primary/20 transition-colors flex items-center gap-1.5 disabled:opacity-50"
                                    >
                                        {autoParseMutation.isPending ? (
                                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                        ) : (
                                            <Zap className="w-3.5 h-3.5" />
                                        )}
                                        Парсить все пропущенные
                                    </button>
                                )}
                            </div>
                        </div>
                        {autoParseMutation.isSuccess && autoParseMutation.data && (
                            <div className="mt-2 flex items-center gap-2 px-2 py-1.5 rounded-md bg-success/10 text-success text-xs">
                                <CheckCircle2 className="w-3.5 h-3.5 flex-shrink-0" />
                                <span>
                                    В очередь: {autoParseMutation.data.queued}, пропущено: {autoParseMutation.data.skipped}
                                    {autoParseMutation.data.errors > 0 && (
                                        <span className="text-danger">, ошибок: {autoParseMutation.data.errors}</span>
                                    )}
                                </span>
                            </div>
                        )}
                    </div>
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead className="bg-table-header border-b border-table-border">
                                <tr>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-foreground-secondary uppercase">Чат</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-foreground-secondary uppercase">Сообщение</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-foreground-secondary uppercase">Дата</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-foreground-secondary uppercase">Категория</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-foreground-secondary uppercase">Транзакция</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-border">
                                {items.map((item, idx) => (
                                    <tr key={`${item.chat_id}-${item.message_id}-${idx}`} className="hover:bg-table-row-hover transition-colors">
                                        <td className="px-4 py-3">
                                            <div className="text-sm text-foreground truncate max-w-[160px]">
                                                {chatTitleMap.get(item.chat_id) || `#${item.chat_id}`}
                                            </div>
                                        </td>
                                        <td className="px-4 py-3">
                                            <div className="text-xs font-mono text-foreground-secondary">#{item.message_id}</div>
                                            {item.text_preview && (
                                                <div className="text-xs text-foreground-muted truncate max-w-[250px]" title={item.text_preview}>
                                                    {item.text_preview}
                                                </div>
                                            )}
                                        </td>
                                        <td className="px-4 py-3">
                                            <div className="text-xs text-foreground-secondary whitespace-nowrap">
                                                {formatDate(item.message_date)}
                                            </div>
                                        </td>
                                        <td className="px-4 py-3">{getCategoryBadge(item.category)}</td>
                                        <td className="px-4 py-3">
                                            {item.transaction_id ? (
                                                <span className="text-xs font-mono text-foreground">#{item.transaction_id}</span>
                                            ) : (
                                                <span className="text-xs text-foreground-muted">—</span>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {isCompleted && (!items || items.length === 0) && (
                <EmptyState
                    icon={<FileSearch className="w-8 h-8 text-foreground-muted" />}
                    title="Нет результатов"
                    description="В выбранном периоде не найдено чеков-кандидатов в синхронизированных чатах."
                />
            )}
        </>
    );
}

/* ─────────────────────────────────────────── */
/*  Shared Components                          */
/* ─────────────────────────────────────────── */
function ProgressBar({ status }: { status: any }) {
    if (!status || (status.status !== 'processing' && status.status !== 'started')) return null;
    return (
        <div className="mt-4">
            <div className="flex justify-between items-center mb-2">
                <span className="text-sm font-medium text-foreground">
                    Прогресс: {status.progress.processed} / {status.progress.total}
                </span>
                <span className="text-sm font-bold text-primary">{status.progress.percent}%</span>
            </div>
            <div className="w-full bg-surface-2 rounded-full h-3 overflow-hidden">
                <div className="h-full bg-gradient-to-r from-primary to-primary-dark transition-all duration-500 ease-out" style={{ width: `${status.progress.percent}%` }} />
            </div>
        </div>
    );
}

function StatCard({ label, value, color, icon }: { label: string; value: number; color: string; icon: React.ReactNode }) {
    return (
        <div className={`bg-${color}-light border border-${color}/30 rounded-lg p-4`}>
            <div className="flex items-center justify-between">
                <div>
                    <p className={`text-sm text-${color} font-medium`}>{label}</p>
                    <p className={`text-2xl font-bold text-${color}`}>{value}</p>
                </div>
                {icon}
            </div>
        </div>
    );
}
