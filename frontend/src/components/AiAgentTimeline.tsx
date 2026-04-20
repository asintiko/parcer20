import React from 'react';
import type { AgentRun, AgentRunEvent } from '../services/api';
import { formatRunEventLabel, formatRunStatus, formatRunStep, formatToolLabel } from '../utils/aiAgentDisplay';

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
            {runs.slice(0, 8).map((run) => (
                <div key={run.id} className="rounded-lg border border-border px-3 py-2 bg-surface">
                    <div className="flex items-center justify-between gap-3 text-xs">
                        <span className="font-medium text-foreground">{formatToolLabel(run.tool_name)}</span>
                        <span className="text-foreground-secondary">{formatRunStatus(run.status)}</span>
                    </div>
                    {run.progress?.step ? (
                        <div className="mt-1 text-xs text-foreground-secondary">
                            {formatRunStep(String(run.progress.step), run.tool_name)} {run.progress.percent != null ? `• ${run.progress.percent}%` : ''}
                        </div>
                    ) : null}
                    {(eventMap.get(run.id) || []).length ? (
                        <div className="mt-3 space-y-2 border-t border-border/70 pt-3">
                            {(eventMap.get(run.id) || []).map((event) => (
                                <div key={event.id} className="flex items-start gap-2 text-xs">
                                    <span
                                        className={`mt-1 inline-flex h-2.5 w-2.5 rounded-full ${
                                            event.status === 'failed'
                                                ? 'bg-danger'
                                                : event.status === 'completed'
                                                    ? 'bg-success'
                                                    : 'bg-primary animate-pulse'
                                        }`}
                                    />
                                    <div className="min-w-0 flex-1">
                                        <div className="font-medium text-foreground">
                                            {formatRunEventLabel(event.event_type, event.label, String(event.payload?.tool_name || run.tool_name || ''))}
                                        </div>
                                        {event.payload?.percent != null ? (
                                            <div className="text-foreground-secondary">{String(event.payload.percent)}%</div>
                                        ) : null}
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : null}
                    {run.error_text ? (
                        <div className="mt-1 text-xs text-danger whitespace-pre-wrap">{run.error_text}</div>
                    ) : null}
                </div>
            ))}
        </div>
    );
};
