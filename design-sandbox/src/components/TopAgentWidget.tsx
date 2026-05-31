/**
 * Top Agent Analytics Widget
 * Displays hourly statistics and insights
 */
import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { analyticsApi } from '../services/api';
import { TrendingUp, Activity } from 'lucide-react';

export const TopAgentWidget: React.FC = () => {
    const { data, isLoading, error } = useQuery({
        queryKey: ['topAgent'],
        queryFn: analyticsApi.getTopAgent,
        refetchInterval: 5 * 60 * 1000, // Refresh every 5 minutes
    });

    if (isLoading) {
        return (
            <div className="bg-widget-bg border border-widget-border rounded-lg p-6">
                <div className="flex items-center gap-2 mb-4">
                    <Activity className="w-5 h-5 text-widget-text-accent" />
                    <h2 className="text-lg font-semibold text-foreground">Топ Агент (последний час)</h2>
                </div>
                <div className="text-foreground-secondary">Загрузка...</div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="bg-widget-bg border border-widget-border rounded-lg p-6">
                <div className="text-danger">Ошибка загрузки данных</div>
            </div>
        );
    }

    if (!data) return null;

    return (
        <div className="bg-widget-bg border border-widget-border rounded-lg p-6 shadow-sm">
            <div className="flex items-center gap-2 mb-4">
                <TrendingUp className="w-5 h-5 text-widget-text-accent" />
                <h2 className="text-lg font-semibold text-foreground">Топ Агент</h2>
                <span className="text-sm text-foreground-secondary ml-auto">Последний час</span>
            </div>

            {data.transaction_count === 0 ? (
                <div className="text-foreground-secondary text-sm">
                    Нет транзакций за последний час
                </div>
            ) : (
                <div className="space-y-4">
                    {/* Main Stats */}
                    <div className="grid grid-cols-2 gap-4">
                        <div className="bg-widget-accent-blue rounded-lg p-4">
                            <div className="text-sm text-foreground-secondary mb-1">Всего транзакций</div>
                            <div className="text-2xl font-bold text-widget-text-accent">
                                {data.transaction_count}
                            </div>
                        </div>
                        <div className="bg-widget-accent-green rounded-lg p-4">
                            <div className="text-sm text-foreground-secondary mb-1">Общий объем</div>
                            <div className="text-xl font-bold text-success font-mono">
                                {parseFloat(data.total_volume).toLocaleString('ru-RU', {
                                    minimumFractionDigits: 0,
                                    maximumFractionDigits: 0
                                })} UZS
                            </div>
                        </div>
                    </div>

                    {/* Top Application */}
                    {data.top_application && (
                        <div className="border-t border-border pt-4">
                            <div className="text-sm text-foreground-secondary mb-2">Наиболее активное приложение</div>
                            <div className="flex items-baseline gap-3">
                                <div className="text-xl font-semibold text-foreground">
                                    {data.top_application}
                                </div>
                                <div className="text-sm text-foreground-muted">
                                    {data.top_application_count} транз. • {parseFloat(data.top_application_volume).toLocaleString('ru-RU')} UZS
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Insight */}
                    <div className="bg-surface-2 rounded-lg p-4 border-l-4 border-primary">
                        <div className="text-sm text-foreground">
                            {data.insight}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};
