import React from 'react';
import type { AgentLocateResult, AgentMessage, AgentReport, AgentRun } from '../services/api';
import { AiAgentToolCard } from './AiAgentToolCard';
import { AiAgentReportCard } from './AiAgentReportCard';
import { AiAgentConfirmationCard } from './AiAgentConfirmationCard';
import { formatNavigationLabel, humanizeSummaryKey, prettyJson } from '../utils/aiAgentDisplay';

interface AiAgentMessageProps {
    message: AgentMessage;
    latestRun: AgentRun | null;
    onNavigate: (target: AgentLocateResult) => void;
    onOpenReport: (reportId: string) => void;
    onConfirmRun: (runId: string) => void;
    confirmPending?: boolean;
}

export const AiAgentMessage: React.FC<AiAgentMessageProps> = ({
    message,
    latestRun,
    onNavigate,
    onOpenReport,
    onConfirmRun,
    confirmPending,
}) => {
    const isUser = message.role === 'user';
    const content = message.content || {};
    const cards = Array.isArray(content.cards) ? content.cards : [];
    const navigationTargets = Array.isArray(content.navigation_targets) ? content.navigation_targets : [];

    const DetailsDisclosure = ({ value }: { value: unknown }) => (
        <details className="mt-3 rounded-md border border-border/60 bg-surface px-2.5 py-2 text-xs text-foreground-secondary">
            <summary className="cursor-pointer select-none font-medium text-foreground">Показать детали</summary>
            <pre className="mt-2 whitespace-pre-wrap break-words">{prettyJson(value)}</pre>
        </details>
    );

    const KeyValueList = ({ payload }: { payload: Record<string, any> }) => {
        const entries = Object.entries(payload).filter(([, value]) => value !== null && value !== undefined && value !== '');
        if (!entries.length) return null;
        return (
            <div className="space-y-1 text-xs text-foreground-secondary">
                {entries.slice(0, 6).map(([key, value]) => (
                    <div key={key} className="flex items-center justify-between gap-3">
                        <span>{humanizeSummaryKey(key)}</span>
                        <span className="font-medium text-foreground">{String(value)}</span>
                    </div>
                ))}
            </div>
        );
    };

    const AnalyticsCard = ({ card }: { card: any }) => {
        const payload = (card?.payload && typeof card.payload === 'object') ? card.payload : {};
        const totals = Array.isArray(payload.totals) ? payload.totals : [];
        const topApplications = Array.isArray(payload.top_applications) ? payload.top_applications : [];
        const topSources = Array.isArray(payload.top_sources) ? payload.top_sources : [];

        return (
            <AiAgentToolCard title={String(card?.title || 'Итоги')} body={String(card?.body || 'Результат расчета готов')}>
                <div className="space-y-3 text-xs text-foreground-secondary">
                    {payload.period_label ? (
                        <div className="flex items-center justify-between gap-3">
                            <span>Период</span>
                            <span className="font-medium text-foreground">{String(payload.period_label)}</span>
                        </div>
                    ) : null}
                    {payload.total_operations != null ? (
                        <div className="flex items-center justify-between gap-3">
                            <span>Операций</span>
                            <span className="font-medium text-foreground">{String(payload.total_operations)}</span>
                        </div>
                    ) : null}
                    {totals.length ? (
                        <div className="space-y-1">
                            {totals.map((item: any) => (
                                <div key={`${item.currency}-${item.total}`} className="flex items-center justify-between gap-3">
                                    <span>{String(item.currency || '')}</span>
                                    <span className="font-medium text-foreground">{String(item.total || '')}</span>
                                </div>
                            ))}
                        </div>
                    ) : null}
                    {topApplications.length ? (
                        <div>
                            <div className="mb-1 font-medium text-foreground">Крупнейшие приложения</div>
                            <div className="space-y-1">
                                {topApplications.map((item: any) => (
                                    <div key={`${item.name}-${item.total}`} className="flex items-center justify-between gap-3">
                                        <span className="truncate">{String(item.name || '')}</span>
                                        <span className="font-medium text-foreground">{String(item.total || '')}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    ) : null}
                    {topSources.length ? (
                        <div>
                            <div className="mb-1 font-medium text-foreground">Крупнейшие источники</div>
                            <div className="space-y-1">
                                {topSources.map((item: any) => (
                                    <div key={`${item.chat_id}-${item.total}`} className="flex items-center justify-between gap-3">
                                        <span className="truncate">{String(item.title || '')}</span>
                                        <span className="font-medium text-foreground">{String(item.total || '')}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    ) : null}
                </div>
                {card?.details ? <DetailsDisclosure value={card.details} /> : null}
            </AiAgentToolCard>
        );
    };

    const AuditCard = ({ card }: { card: any }) => {
        const payload = (card?.payload && typeof card.payload === 'object') ? card.payload : {};
        const categories = (payload.categories && typeof payload.categories === 'object') ? Object.entries(payload.categories) : [];
        const byChat = Array.isArray(payload.by_chat) ? payload.by_chat.slice(0, 5) : [];
        const issuesPreview = Array.isArray(payload.issues_preview) ? payload.issues_preview.slice(0, 5) : [];
        const estimatedCandidates = payload.estimated_candidates != null ? String(payload.estimated_candidates) : null;

        return (
            <AiAgentToolCard title={String(card?.title || 'Аудит мониторинга чеков')} body={String(card?.body || 'Проверка выполнена')}>
                <div className="space-y-3 text-xs text-foreground-secondary">
                    <div className="grid grid-cols-2 gap-2">
                        {payload.period_label ? (
                            <div className="rounded-md bg-surface px-2 py-1.5">
                                <div className="text-[11px] uppercase tracking-wide text-foreground-tertiary">Период</div>
                                <div className="mt-1 font-medium text-foreground">{String(payload.period_label)}</div>
                            </div>
                        ) : null}
                        {payload.checked_chats != null ? (
                            <div className="rounded-md bg-surface px-2 py-1.5">
                                <div className="text-[11px] uppercase tracking-wide text-foreground-tertiary">Проверено чатов</div>
                                <div className="mt-1 font-medium text-foreground">{String(payload.checked_chats)}</div>
                            </div>
                        ) : null}
                        {payload.total_issues != null ? (
                            <div className="rounded-md bg-surface px-2 py-1.5">
                                <div className="text-[11px] uppercase tracking-wide text-foreground-tertiary">Проблем</div>
                                <div className="mt-1 font-medium text-foreground">{String(payload.total_issues)}</div>
                            </div>
                        ) : null}
                        {estimatedCandidates ? (
                            <div className="rounded-md bg-surface px-2 py-1.5">
                                <div className="text-[11px] uppercase tracking-wide text-foreground-tertiary">Кандидатов</div>
                                <div className="mt-1 font-medium text-foreground">{estimatedCandidates}</div>
                            </div>
                        ) : null}
                    </div>
                    {categories.length ? (
                        <div>
                            <div className="mb-1 font-medium text-foreground">Категории</div>
                            <div className="space-y-1">
                                {categories.map(([key, value]) => (
                                    <div key={key} className="flex items-center justify-between gap-3">
                                        <span>{humanizeSummaryKey(key)}</span>
                                        <span className="font-medium text-foreground">{String(value)}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    ) : null}
                    {byChat.length ? (
                        <div>
                            <div className="mb-1 font-medium text-foreground">По чатам</div>
                            <div className="space-y-1">
                                {byChat.map((item: any) => (
                                    <div key={`${item.chat_id}-${item.title || 'chat'}`} className="rounded-md bg-surface px-2 py-1.5">
                                        <div className="font-medium text-foreground">{String(item.title || item.chat_id || 'Источник')}</div>
                                        <div className="mt-1 text-[11px] text-foreground-secondary">
                                            Кандидатов: {String(item.total_candidates || 0)}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    ) : null}
                    {issuesPreview.length ? (
                        <div>
                            <div className="mb-1 font-medium text-foreground">Ключевые кейсы</div>
                            <div className="space-y-1">
                                {issuesPreview.map((item: any, index: number) => (
                                    <div key={`${item.chat_id}-${item.message_id}-${index}`} className="rounded-md bg-surface px-2 py-1.5">
                                        <div className="font-medium text-foreground">{String(item.title || humanizeSummaryKey(item.category || 'problem'))}</div>
                                        <div className="mt-1 text-[11px] text-foreground-secondary whitespace-pre-wrap">{String(item.summary || '')}</div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    ) : null}
                </div>
                {card?.details ? <DetailsDisclosure value={card.details} /> : null}
            </AiAgentToolCard>
        );
    };

    const GenericCard = ({ card }: { card: any }) => {
        const payload = card?.payload;
        const detailValue = card?.details ?? payload;
        const isObjectPayload = payload && typeof payload === 'object' && !Array.isArray(payload);
        const isArrayPayload = Array.isArray(payload);

        return (
            <AiAgentToolCard
                title={String(card?.title || card?.type || 'Результат')}
                body={typeof card?.body === 'string' && card.body.trim() ? card.body : 'Результат готов.'}
            >
                {isObjectPayload ? <KeyValueList payload={payload as Record<string, any>} /> : null}
                {isArrayPayload ? (
                    <div className="text-xs text-foreground-secondary">
                        Найдено записей: <span className="font-medium text-foreground">{payload.length}</span>
                    </div>
                ) : null}
                {detailValue ? <DetailsDisclosure value={detailValue} /> : null}
            </AiAgentToolCard>
        );
    };

    return (
        <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[88%] rounded-2xl px-3 py-2 ${isUser ? 'bg-primary text-white' : 'bg-surface border border-border text-foreground'}`}>
                {content.message ? (
                    <div className="whitespace-pre-wrap text-sm">{String(content.message)}</div>
                ) : null}
                {cards.length ? (
                    <div className="mt-2 space-y-2">
                        {cards.map((card: any, index: number) => {
                            if (card?.type === 'report' && card?.report) {
                                return <AiAgentReportCard key={`${message.id}-report-${index}`} report={card.report as AgentReport} onOpen={onOpenReport} />;
                            }
                            if (card?.type === 'report' && card?.payload?.id) {
                                return <AiAgentReportCard key={`${message.id}-report-${index}`} report={card.payload as AgentReport} onOpen={onOpenReport} />;
                            }
                            if (card?.type === 'analytics') {
                                return <AnalyticsCard key={`${message.id}-analytics-${index}`} card={card} />;
                            }
                            if (String(card?.title || '').toLowerCase().includes('аудит мониторинга')) {
                                return <AuditCard key={`${message.id}-audit-${index}`} card={card} />;
                            }
                            return <GenericCard key={`${message.id}-card-${index}`} card={card} />;
                        })}
                    </div>
                ) : null}
                {navigationTargets.length ? (
                    <div className="mt-2 flex flex-wrap gap-2">
                        {navigationTargets.map((target: AgentLocateResult, index: number) => (
                            <button
                                key={`${message.id}-nav-${index}`}
                                type="button"
                                onClick={() => onNavigate(target)}
                                className="rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-surface"
                            >
                                {formatNavigationLabel(target)}
                            </button>
                        ))}
                    </div>
                ) : null}
                {!isUser && latestRun?.requires_confirmation ? (
                    <div className="mt-2">
                        <AiAgentConfirmationCard run={latestRun} onConfirm={onConfirmRun} pending={confirmPending} />
                    </div>
                ) : null}
            </div>
        </div>
    );
};
