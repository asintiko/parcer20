/**
 * Automation Page Component
 * AI-powered transaction analysis and application mapping
 */
import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { automationApi } from '../services/api';
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
    AlertCircle
} from 'lucide-react';

export function AutomationPage() {
    const [analysisConfig, setAnalysisConfig] = useState({
        limit: 100,
        only_unmapped: true,
        currency_filter: '',
    });
    const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
    const [selectedSuggestions, setSelectedSuggestions] = useState<string[]>([]);
    const [filterConfidence, setFilterConfidence] = useState(0.0);

    // Start analysis mutation
    const startAnalysisMutation = useMutation({
        mutationFn: () => automationApi.analyzeTransactions(analysisConfig),
        onSuccess: (data) => {
            setActiveTaskId(data.task_id);
        },
    });

    // Poll task status
    const { data: taskStatus } = useQuery({
        queryKey: ['analyzeStatus', activeTaskId],
        queryFn: () => automationApi.getAnalyzeStatus(activeTaskId!),
        enabled: !!activeTaskId,
        refetchInterval: (query) => {
            if (!query.state.data) return false;
            return query.state.data.status === 'processing' || query.state.data.status === 'started' ? 2000 : false;
        },
    });
    // Reset task if it was not found (e.g., after backend restart)
    useEffect(() => {
        if (taskStatus?.status === 'not_found' && activeTaskId) {
            setActiveTaskId(null);
        }
    }, [taskStatus?.status, activeTaskId]);

    // Fetch suggestions
    const { data: suggestions, refetch: refetchSuggestions } = useQuery({
        queryKey: ['suggestions', activeTaskId, filterConfidence],
        queryFn: () => automationApi.getSuggestions({
            task_id: activeTaskId || undefined,
            confidence_min: filterConfidence,
            status: 'pending',
        }),
        enabled: !!activeTaskId && taskStatus?.status === 'completed',
    });

    // Apply suggestion mutation
    const applySuggestionMutation = useMutation({
        mutationFn: (suggestionId: string) => automationApi.applySuggestion(suggestionId),
        onSuccess: () => {
            refetchSuggestions();
        },
    });

    // Reject suggestion mutation
    const rejectSuggestionMutation = useMutation({
        mutationFn: (suggestionId: string) => automationApi.rejectSuggestion(suggestionId),
        onSuccess: () => {
            refetchSuggestions();
        },
    });

    // Batch apply mutation
    const batchApplyMutation = useMutation({
        mutationFn: (suggestionIds: string[]) => automationApi.batchApplySuggestions(suggestionIds),
        onSuccess: () => {
            setSelectedSuggestions([]);
            refetchSuggestions();
        },
    });

    const handleStartAnalysis = () => {
        startAnalysisMutation.mutate();
    };

    const handleToggleSelection = (suggestionId: string) => {
        setSelectedSuggestions(prev =>
            prev.includes(suggestionId)
                ? prev.filter(id => id !== suggestionId)
                : [...prev, suggestionId]
        );
    };

    const handleSelectAll = () => {
        if (!suggestions) return;
        if (selectedSuggestions.length === suggestions.length) {
            setSelectedSuggestions([]);
        } else {
            setSelectedSuggestions(suggestions.map(s => s.id));
        }
    };

    const getConfidenceColor = (confidence: number) => {
        if (confidence >= 0.8) return 'text-success bg-success-light border-success/30';
        if (confidence >= 0.5) return 'text-warning bg-warning-light border-warning/30';
        return 'text-danger bg-danger-light border-danger/30';
    };

    const getConfidenceIcon = (confidence: number) => {
        if (confidence >= 0.8) return <TrendingUp className="w-4 h-4" />;
        if (confidence >= 0.5) return <AlertCircle className="w-4 h-4" />;
        return <TrendingDown className="w-4 h-4" />;
    };

    return (
        <div className="h-full flex flex-col bg-bg">
            <div className="flex-1 overflow-auto p-6">
                <div className="max-w-7xl mx-auto space-y-6">

                    {/* Header */}
                    <div className="bg-surface rounded-lg shadow-sm border border-border p-6">
                        <div className="flex items-center gap-3 mb-4">
                            <div className="p-2 bg-gradient-to-br from-primary to-primary-dark rounded-lg">
                                <Bot className="w-6 h-6 text-foreground-inverse" />
                            </div>
                            <div>
                                <h1 className="text-2xl font-bold text-foreground">AI Автоматизация</h1>
                                <p className="text-sm text-foreground-secondary">Интеллектуальный анализ транзакций и сопоставление приложений</p>
                            </div>
                        </div>

                        {/* Analysis Configuration */}
                        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-4">
                            <div>
                                <label className="block text-sm font-medium text-foreground mb-2">
                                    Лимит транзакций
                                </label>
                                <input
                                    type="number"
                                    min="1"
                                    max="1000"
                                    value={analysisConfig.limit}
                                    onChange={(e) => setAnalysisConfig({ ...analysisConfig, limit: parseInt(e.target.value) })}
                                    className="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent bg-surface text-foreground"
                                    disabled={taskStatus?.status === 'processing'}
                                />
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-foreground mb-2">
                                    Валюта
                                </label>
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
                                    <span className="text-sm font-medium text-foreground">
                                        Только неопределенные
                                    </span>
                                </label>
                            </div>

                            <div className="flex items-end">
                                <button
                                    onClick={handleStartAnalysis}
                                    disabled={taskStatus?.status === 'processing' || startAnalysisMutation.isPending}
                                    className="w-full px-4 py-2 bg-gradient-to-r from-primary to-primary-dark text-foreground-inverse font-medium rounded-lg hover:from-primary-hover hover:to-primary transition-all shadow-md disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 focus:outline-none focus:ring-2 focus:ring-primary"
                                >
                                    {taskStatus?.status === 'processing' ? (
                                        <>
                                            <Loader2 className="w-4 h-4 animate-spin" />
                                            Анализ...
                                        </>
                                    ) : (
                                        <>
                                            <Play className="w-4 h-4" />
                                            Запустить анализ
                                        </>
                                    )}
                                </button>
                            </div>
                        </div>

                        {/* Progress Bar */}
                        {taskStatus && (taskStatus.status === 'processing' || taskStatus.status === 'started') && (
                            <div className="mt-4">
                                <div className="flex justify-between items-center mb-2">
                                    <span className="text-sm font-medium text-foreground">
                                        Прогресс: {taskStatus.progress.processed} / {taskStatus.progress.total}
                                    </span>
                                    <span className="text-sm font-bold text-primary">
                                        {taskStatus.progress.percent}%
                                    </span>
                                </div>
                                <div className="w-full bg-surface-2 rounded-full h-3 overflow-hidden">
                                    <div
                                        className="h-full bg-gradient-to-r from-primary to-primary-dark transition-all duration-500 ease-out"
                                        style={{ width: `${taskStatus.progress.percent}%` }}
                                    />
                                </div>
                            </div>
                        )}

                        {/* Results Summary */}
                        {taskStatus?.status === 'completed' && taskStatus.results && (
                            <div className="mt-4 grid grid-cols-3 gap-4">
                                <div className="bg-info-light border border-info/30 rounded-lg p-4">
                                    <div className="flex items-center justify-between">
                                        <div>
                                            <p className="text-sm text-info font-medium">Всего рекомендаций</p>
                                            <p className="text-2xl font-bold text-info">{taskStatus.results.suggestions_count}</p>
                                        </div>
                                        <Sparkles className="w-8 h-8 text-info" />
                                    </div>
                                </div>
                                <div className="bg-success-light border border-success/30 rounded-lg p-4">
                                    <div className="flex items-center justify-between">
                                        <div>
                                            <p className="text-sm text-success font-medium">Высокая точность</p>
                                            <p className="text-2xl font-bold text-success">{taskStatus.results.high_confidence}</p>
                                        </div>
                                        <TrendingUp className="w-8 h-8 text-success" />
                                    </div>
                                </div>
                                <div className="bg-warning-light border border-warning/30 rounded-lg p-4">
                                    <div className="flex items-center justify-between">
                                        <div>
                                            <p className="text-sm text-warning font-medium">Низкая точность</p>
                                            <p className="text-2xl font-bold text-warning">{taskStatus.results.low_confidence}</p>
                                        </div>
                                        <TrendingDown className="w-8 h-8 text-warning" />
                                    </div>
                                </div>
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
                                            <input
                                                type="range"
                                                min="0"
                                                max="1"
                                                step="0.1"
                                                value={filterConfidence}
                                                onChange={(e) => setFilterConfidence(parseFloat(e.target.value))}
                                                className="w-32"
                                            />
                                            <span className="text-sm font-medium text-foreground w-12">
                                                {(filterConfidence * 100).toFixed(0)}%
                                            </span>
                                        </div>
                                        {selectedSuggestions.length > 0 && (
                                            <button
                                                onClick={() => batchApplyMutation.mutate(selectedSuggestions)}
                                                disabled={batchApplyMutation.isPending}
                                                className="px-4 py-2 bg-success text-foreground-inverse text-sm font-medium rounded-lg hover:bg-success-hover transition-colors flex items-center gap-2 focus:outline-none focus:ring-2 focus:ring-success"
                                            >
                                                <Check className="w-4 h-4" />
                                                Применить выбранные ({selectedSuggestions.length})
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
                                        {suggestions.map((suggestion) => (
                                            <tr key={suggestion.id} className="hover:bg-table-row-hover transition-colors">
                                                <td className="px-4 py-3">
                                                    <input
                                                        type="checkbox"
                                                        checked={selectedSuggestions.includes(suggestion.id)}
                                                        onChange={() => handleToggleSelection(suggestion.id)}
                                                        className="w-4 h-4 text-primary border-border rounded focus:ring-primary"
                                                    />
                                                </td>
                                                <td className="px-4 py-3">
                                                    <div className="text-sm font-medium text-foreground">{suggestion.operator_raw}</div>
                                                </td>
                                                <td className="px-4 py-3">
                                                    <div className="text-sm text-foreground-secondary">
                                                        {suggestion.current_application || <span className="italic text-foreground-muted">Нет</span>}
                                                    </div>
                                                </td>
                                                <td className="px-4 py-3">
                                                    <div className="flex items-center gap-2">
                                                        <span className="text-sm font-medium text-foreground">{suggestion.suggested_application}</span>
                                                        {suggestion.is_new_application && (
                                                            <span className="px-2 py-0.5 text-xs font-medium bg-primary-light text-primary rounded-full">
                                                                Новое
                                                            </span>
                                                        )}
                                                    </div>
                                                </td>
                                                <td className="px-4 py-3">
                                                    <div className="flex justify-center">
                                                        {suggestion.is_p2p ? (
                                                            <span className="px-2 py-1 text-xs font-medium bg-info-light text-info rounded-full">
                                                                P2P
                                                            </span>
                                                        ) : (
                                                            <span className="px-2 py-1 text-xs font-medium bg-surface-2 text-foreground-secondary rounded-full">
                                                                Услуга
                                                            </span>
                                                        )}
                                                    </div>
                                                </td>
                                                <td className="px-4 py-3">
                                                    <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium ${getConfidenceColor(suggestion.confidence)}`}>
                                                        {getConfidenceIcon(suggestion.confidence)}
                                                        {(suggestion.confidence * 100).toFixed(0)}%
                                                    </div>
                                                </td>
                                                <td className="px-4 py-3">
                                                    <div className="text-sm text-foreground-secondary max-w-xs truncate" title={suggestion.reasoning}>
                                                        {suggestion.reasoning}
                                                    </div>
                                                </td>
                                                <td className="px-4 py-3">
                                                    <div className="flex items-center justify-center gap-2">
                                                        <button
                                                            onClick={() => applySuggestionMutation.mutate(suggestion.id)}
                                                            disabled={applySuggestionMutation.isPending}
                                                            className="p-1.5 text-success hover:bg-success-light rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-success"
                                                            title="Применить"
                                                        >
                                                            <CheckCircle2 className="w-5 h-5" />
                                                        </button>
                                                        <button
                                                            onClick={() => rejectSuggestionMutation.mutate(suggestion.id)}
                                                            disabled={rejectSuggestionMutation.isPending}
                                                            className="p-1.5 text-danger hover:bg-danger-light rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-danger"
                                                            title="Отклонить"
                                                        >
                                                            <XCircle className="w-5 h-5" />
                                                        </button>
                                                    </div>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}

                    {/* Empty State */}
                    {taskStatus?.status === 'completed' && (!suggestions || suggestions.length === 0) && (
                        <div className="bg-surface rounded-lg shadow-sm border border-border p-12 text-center">
                            <div className="max-w-md mx-auto">
                                <div className="w-16 h-16 bg-surface-2 rounded-full flex items-center justify-center mx-auto mb-4">
                                    <CheckCircle2 className="w-8 h-8 text-foreground-muted" />
                                </div>
                                <h3 className="text-lg font-semibold text-foreground mb-2">Рекомендаций не найдено</h3>
                                <p className="text-sm text-foreground-secondary">
                                    Все транзакции уже имеют корректные сопоставления приложений или не соответствуют критериям фильтрации.
                                </p>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
