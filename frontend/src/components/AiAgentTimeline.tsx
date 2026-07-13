import React from 'react';
import { Globe } from 'lucide-react';
import type { AgentRun, AgentRunEvent } from '../services/api';
import {
    formatRunEventLabel,
    formatRunStatus,
    formatRunStep,
    formatToolLabel,
    formatToolPurpose,
    formatWebSearchLabel,
    humanizeSummaryKey,
    isWebSearchPayload,
} from '../utils/aiAgentDisplay';

const EVENT_STATUS_LABELS: Record<NonNullable<AgentRunEvent['status']>, string> = {
    pending: 'В очереди',
    running: 'Выполняется',
    completed: 'Готово',
    failed: 'Ошибка',
};

const DETAIL_KEYS = ['count', 'total', 'processed', 'checked_chats', 'loaded_count', 'total_issues', 'chat_title'] as const;

const renderPayloadDetails = (payload: Record<string, any> | null | undefined): string[] => {
    if (!payload || typeof payload !== 'object') return [];
    const parts: string[] = [];
    if (payload.percent != null && Number.isFinite(Number(payload.percent))) {
        parts.push(`${Math.round(Number(payload.percent))}%`);
    }
    for (const key of DETAIL_KEYS) {
        const value = payload[key];
        if (value == null || value === '') continue;
        if (typeof value === 'object') continue;
        parts.push(`${humanizeSummaryKey(key)}: ${String(value)}`);
    }
    return parts;
};

export const AiAgentTimeline: React.FC<{ runs: AgentRun[]; events?: AgentRunEvent[] }> = ({ runs, events = [] }) => {
    if (!runs.length && !events.length) return null;
    const eventMap = new Map<string, AgentRunEvent[]>();
    events.forEach((event) => {
        const bucket = eventMap.get(event.run_id) || [];
        bucket.push(event);
        eventMap.set(event.run_id, bucket);
    });
    return (
        <div className="space-y-2">
            {runs.slice(0, 8).map((run) => {
                const runToolName = run.progress?.tool_name || run.tool_name || null;
                return (
                    <div key={run.id} className="rounded-lg border border-border px-3 py-2 bg-surface">
                        <div className="flex items-center justify-between gap-3 text-xs">
                            <span className="font-medium text-foreground">{formatToolLabel(runToolName)}</span>
                            <span className="text-foreground-secondary">{formatRunStatus(run.status)}</span>
                        </div>
                        {formatToolPurpose(runToolName) ? (
                            <div className="mt-0.5 text-[11px] text-foreground-secondary">
                                {formatToolPurpose(runToolName)}
                            </div>
                        ) : null}
                        {run.progress?.step ? (
                            <div className="mt-1 text-xs text-foreground-secondary">
                                {formatRunStep(String(run.progress.step), runToolName)}
                                {Number(run.progress.total) > 0
                                    ? ` • Шаг ${Number(run.progress.current ?? 0)}/${Number(run.progress.total)}`
                                    : run.progress.percent != null
                                        ? ` • ${run.progress.percent}%`
                                        : ''}
                            </div>
                        ) : null}
                        {(eventMap.get(run.id) || []).length ? (
                            <div className="mt-3 space-y-2 border-t border-border/70 pt-3">
                                {(eventMap.get(run.id) || []).map((event) => {
                                    const eventTool = String(event.payload?.tool_name || runToolName || '');
                                    const details = renderPayloadDetails(event.payload);
                                    const isWeb = isWebSearchPayload(event.payload, event.label);
                                    if (isWeb) {
                                        const operator =
                                            String(
                                                event.payload?.operator ||
                                                    event.payload?.query ||
                                                    event.payload?.term ||
                                                    '',
                                            ).trim() ||
                                            formatWebSearchLabel(event.payload).replace(/^🌐\s*/, '');
                                        const current = Number(event.payload?.current ?? 0);
                                        const total = Number(event.payload?.total ?? 0);
                                        const active = event.status === 'running';
                                        return (
                                            <div
                                                key={event.id}
                                                className={`agent-web-read agent-web-read--inline${
                                                    active ? ' is-active' : ''
                                                }`}
                                            >
                                                <Globe size={13} className="agent-web-read-icon" aria-hidden />
                                                <span className="agent-web-read-text">
                                                    Читаю в интернете:{' '}
                                                    <span className="agent-web-read-operator">{operator}</span>
                                                </span>
                                                {total > 0 ? (
                                                    <span className="agent-web-read-count">
                                                        {current}/{total}
                                                    </span>
                                                ) : null}
                                                {active ? (
                                                    <span className="agent-web-read-bar" aria-hidden>
                                                        <span className="agent-web-read-bar-fill" />
                                                    </span>
                                                ) : null}
                                            </div>
                                        );
                                    }
                                    return (
                                        <div key={event.id} className="flex items-start gap-2 text-xs">
                                            <span
                                                className={`mt-1 inline-flex h-2.5 w-2.5 rounded-full ${
                                                    event.status === 'failed'
                                                        ? 'bg-danger'
                                                        : event.status === 'completed'
                                                            ? 'bg-success'
                                                            : event.status === 'running'
                                                                ? 'bg-primary animate-pulse'
                                                                : 'bg-foreground-secondary'
                                                }`}
                                                aria-label={EVENT_STATUS_LABELS[event.status] || event.status}
                                            />
                                            <div className="min-w-0 flex-1">
                                                <div className="font-medium text-foreground">
                                                    {formatRunEventLabel(event.event_type, event.label, eventTool, event.payload)}
                                                </div>
                                                {details.length ? (
                                                    <div className="text-foreground-secondary">{details.join(' • ')}</div>
                                                ) : null}
                                            </div>
                                            <span className="shrink-0 text-[10px] uppercase tracking-wider text-foreground-secondary">
                                                {EVENT_STATUS_LABELS[event.status] || ''}
                                            </span>
                                        </div>
                                    );
                                })}
                            </div>
                        ) : null}
                        {run.error_text ? (
                            <div className="mt-1 text-xs text-danger whitespace-pre-wrap">{run.error_text}</div>
                        ) : null}
                    </div>
                );
            })}
        </div>
    );
};
