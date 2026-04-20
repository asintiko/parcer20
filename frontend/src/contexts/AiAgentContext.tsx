import React, { createContext, ReactNode, useContext, useMemo, useState } from 'react';

export type AiAgentOpenIntent = {
    threadId?: string | null;
    starterText?: string;
    requestedTool?: string | null;
    systemMessage?: string | null;
};

type AiAgentContextValue = {
    isOpen: boolean;
    activeThreadId: string | null;
    pendingIntent: (AiAgentOpenIntent & { token: number }) | null;
    openAgent: (intent?: AiAgentOpenIntent) => void;
    closeAgent: () => void;
    setActiveThreadId: (threadId: string | null) => void;
    consumePendingIntent: () => void;
};

const AiAgentContext = createContext<AiAgentContextValue | null>(null);

export const AiAgentProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
    const [isOpen, setIsOpen] = useState(false);
    const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
    const [pendingIntent, setPendingIntent] = useState<(AiAgentOpenIntent & { token: number }) | null>(null);

    const value = useMemo<AiAgentContextValue>(() => ({
        isOpen,
        activeThreadId,
        pendingIntent,
        openAgent: (intent) => {
            if (intent?.threadId !== undefined) {
                setActiveThreadId(intent.threadId || null);
            }
            setPendingIntent({ ...(intent || {}), token: Date.now() });
            setIsOpen(true);
        },
        closeAgent: () => setIsOpen(false),
        setActiveThreadId,
        consumePendingIntent: () => setPendingIntent(null),
    }), [activeThreadId, isOpen, pendingIntent]);

    return <AiAgentContext.Provider value={value}>{children}</AiAgentContext.Provider>;
};

export const useAiAgent = (): AiAgentContextValue => {
    const context = useContext(AiAgentContext);
    if (!context) {
        throw new Error('useAiAgent must be used within AiAgentProvider');
    }
    return context;
};
