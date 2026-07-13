import React, { createContext, ReactNode, useCallback, useContext, useMemo, useState } from 'react';

export type AiAgentOpenIntent = {
    threadId?: string | null;
    starterText?: string;
    requestedTool?: string | null;
    systemMessage?: string | null;
};

export type AiAgentUiActionKind =
    | 'apply_filters'
    | 'clear_filters'
    | 'mark_rows'
    | 'export'
    | 'scroll_to_row'
    | 'open_details'
    | 'navigate_view'
    | 'noop'
    | 'nop';

export interface AiAgentUiAction {
    kind: AiAgentUiActionKind | string;
    target?: { area?: string; route?: string; view?: string; ids?: number[]; transaction_id?: number; button?: string; [key: string]: any };
    params?: Record<string, any>;
    animate_cursor?: boolean;
    close_chat?: boolean;
    duration_ms?: number;
}

export type PendingUiAction = AiAgentUiAction & { token: number; messageId?: string };

type AiAgentContextValue = {
    isOpen: boolean;
    activeThreadId: string | null;
    pendingIntent: (AiAgentOpenIntent & { token: number }) | null;
    pendingUiAction: PendingUiAction | null;
    openAgent: (intent?: AiAgentOpenIntent) => void;
    closeAgent: () => void;
    setActiveThreadId: (threadId: string | null) => void;
    consumePendingIntent: () => void;
    dispatchUiAction: (action: AiAgentUiAction, options?: { messageId?: string }) => void;
    consumeUiAction: () => void;
};

const AiAgentContext = createContext<AiAgentContextValue | null>(null);

// m-1: monotonic counter avoids sub-ms collisions when two AiAgentMessage
// components dispatch in the same React batch.
let __uiActionTokenCounter = 0;
const nextUiActionToken = () => {
    __uiActionTokenCounter += 1;
    return __uiActionTokenCounter;
};

let __agentIntentTokenCounter = 0;
const nextAgentIntentToken = () => {
    __agentIntentTokenCounter += 1;
    return __agentIntentTokenCounter;
};

export const AiAgentProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
    const [isOpen, setIsOpen] = useState(false);
    const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
    const [pendingIntent, setPendingIntent] = useState<(AiAgentOpenIntent & { token: number }) | null>(null);
    const [pendingUiAction, setPendingUiAction] = useState<PendingUiAction | null>(null);

    const closeAgent = useCallback(() => setIsOpen(false), []);

    const dispatchUiAction = useCallback((action: AiAgentUiAction, options?: { messageId?: string }) => {
        if (!action || typeof action !== 'object') return;
        const kind = String(action.kind || '').trim();
        if (!kind) return;
        if (kind === 'noop' || kind === 'nop') {
            if (action.close_chat) closeAgent();
            return;
        }
        setPendingUiAction({ ...action, token: nextUiActionToken(), messageId: options?.messageId });
        if (action.close_chat) {
            // Defer the chat-close so the page consumer can react to the dispatched action first.
            setTimeout(() => closeAgent(), 250);
        }
    }, [closeAgent]);

    const consumeUiAction = useCallback(() => setPendingUiAction(null), []);

    const value = useMemo<AiAgentContextValue>(() => ({
        isOpen,
        activeThreadId,
        pendingIntent,
        pendingUiAction,
        openAgent: (intent) => {
            if (intent?.threadId !== undefined) {
                setActiveThreadId(intent.threadId || null);
            }
            setPendingIntent({ ...(intent || {}), token: nextAgentIntentToken() });
            setIsOpen(true);
        },
        closeAgent,
        setActiveThreadId,
        consumePendingIntent: () => setPendingIntent(null),
        dispatchUiAction,
        consumeUiAction,
    }), [activeThreadId, closeAgent, consumeUiAction, dispatchUiAction, isOpen, pendingIntent, pendingUiAction]);

    return <AiAgentContext.Provider value={value}>{children}</AiAgentContext.Provider>;
};

export const useAiAgent = (): AiAgentContextValue => {
    const context = useContext(AiAgentContext);
    if (!context) {
        throw new Error('useAiAgent must be used within AiAgentProvider');
    }
    return context;
};
