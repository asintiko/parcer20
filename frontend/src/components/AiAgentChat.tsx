import React, { useMemo, useRef, useState } from 'react';
import type { AgentLocateResult, AgentMessage, AgentRun } from '../services/api';
import { AiAgentMessage } from './AiAgentMessage';
import { AiAgentQuickActions } from './AiAgentQuickActions';
import { formatRunStep } from '../utils/aiAgentDisplay';

interface AiAgentChatProps {
    messages: AgentMessage[];
    latestRun: AgentRun | null;
    sendPending?: boolean;
    confirmPending?: boolean;
    onSend: (payload: { text: string; requestedTool?: string | null }) => Promise<void>;
    onNavigate: (target: AgentLocateResult) => void;
    onOpenReport: (reportId: string) => void;
    onConfirmRun: (runId: string) => void;
    initialText?: string | null;
}

export const AiAgentChat: React.FC<AiAgentChatProps> = ({
    messages,
    latestRun,
    sendPending,
    confirmPending,
    onSend,
    onNavigate,
    onOpenReport,
    onConfirmRun,
    initialText,
}) => {
    const [draft, setDraft] = useState('');
    const scrollContainerRef = useRef<HTMLDivElement | null>(null);

    React.useEffect(() => {
        if (initialText) {
            setDraft(initialText);
        }
    }, [initialText]);

    const normalizedMessages = useMemo(() => messages.slice().sort((a, b) => {
        const left = new Date(a.created_at || 0).getTime();
        const right = new Date(b.created_at || 0).getTime();
        return left - right;
    }), [messages]);

    const isRunning = latestRun?.status === 'queued' || latestRun?.status === 'processing';
    const progressLabel = useMemo(() => {
        if (sendPending) return 'Отправляю запрос...';
        if (!isRunning) return '';
        return formatRunStep(String(latestRun?.progress?.step || ''), latestRun?.tool_name);
    }, [isRunning, latestRun?.progress?.step, latestRun?.tool_name, sendPending]);

    React.useEffect(() => {
        const node = scrollContainerRef.current;
        if (!node) return;
        node.scrollTop = node.scrollHeight;
    }, [normalizedMessages.length, isRunning, sendPending]);

    const handleSubmit = React.useCallback(async () => {
        const text = draft.trim();
        if (!text || sendPending) return;
        await onSend({ text });
        setDraft('');
    }, [draft, onSend, sendPending]);

    return (
        <div className="flex h-full flex-col">
            <div className="border-b border-border px-4 py-3">
                <AiAgentQuickActions
                    onAction={(action) => {
                        void onSend({ text: action.prompt, requestedTool: action.tool || null }).catch(() => undefined);
                    }}
                />
            </div>
            <div ref={scrollContainerRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
                {normalizedMessages.length ? normalizedMessages.map((message) => (
                    <AiAgentMessage
                        key={message.id}
                        message={message}
                        latestRun={latestRun}
                        onNavigate={onNavigate}
                        onOpenReport={onOpenReport}
                        onConfirmRun={onConfirmRun}
                        confirmPending={confirmPending}
                    />
                )) : (
                    <div className="rounded-lg border border-dashed border-border p-4 text-sm text-foreground-secondary">
                        Диалог пуст. Запустите quick action или сформулируйте запрос вручную.
                    </div>
                )}
                {(sendPending || isRunning) ? (
                    <div className="flex justify-start">
                        <div className="max-w-[88%] rounded-2xl border border-border bg-surface px-3 py-2 text-foreground">
                            <div className="text-sm font-medium">Думаю...</div>
                            <div className="mt-2 flex items-center gap-2 text-xs text-foreground-secondary">
                                <span className="inline-flex h-2 w-2 rounded-full bg-primary animate-pulse" />
                                <span>{progressLabel || 'Готовлю ответ'}</span>
                            </div>
                        </div>
                    </div>
                ) : null}
            </div>
            <form
                className="border-t border-border p-4"
                style={{ paddingBottom: 'max(1rem, env(safe-area-inset-bottom))' }}
                onSubmit={(event) => {
                    event.preventDefault();
                    void handleSubmit().catch(() => undefined);
                }}
            >
                <div className="flex items-end gap-2">
                    <textarea
                        value={draft}
                        onChange={(event) => setDraft(event.target.value)}
                        onKeyDown={(event) => {
                            if (event.key === 'Enter' && !event.shiftKey) {
                                event.preventDefault();
                                void handleSubmit().catch(() => undefined);
                            }
                        }}
                        rows={3}
                        className="min-h-[84px] flex-1 rounded-lg border border-border bg-input-bg px-3 py-2 text-sm text-input-text focus:outline-none focus:ring-2 focus:ring-primary"
                        placeholder="Напишите запрос. Enter отправляет, Shift+Enter переносит строку."
                    />
                    <button
                        type="submit"
                        disabled={sendPending || !draft.trim()}
                        className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-dark disabled:opacity-60"
                    >
                        {sendPending ? 'Отправка...' : 'Отправить'}
                    </button>
                </div>
            </form>
        </div>
    );
};
