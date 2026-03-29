import React from 'react';
import { Bot, Bell, Loader2, AlertTriangle } from 'lucide-react';

type LauncherState = 'idle' | 'has_notifications' | 'thinking' | 'running' | 'error';

interface AiAgentLauncherProps {
    unreadCount: number;
    state?: LauncherState;
    onClick: () => void;
}

export const AiAgentLauncher: React.FC<AiAgentLauncherProps> = ({ unreadCount, state = 'idle', onClick }) => {
    const ringClass =
        state === 'error'
            ? 'ring-danger/30'
            : state === 'running' || state === 'thinking'
                ? 'ring-primary/40'
                : state === 'has_notifications'
                    ? 'ring-warning/40'
                    : 'ring-black/10';

    const icon = state === 'error'
        ? <AlertTriangle className="h-5 w-5" />
        : state === 'running' || state === 'thinking'
            ? <Loader2 className="h-5 w-5 animate-spin" />
            : <Bot className="h-5 w-5" />;

    return (
        <button
            type="button"
            onClick={onClick}
            title="Открыть AI-агента"
            className={`fixed bottom-6 right-6 z-[70] inline-flex h-14 w-14 items-center justify-center rounded-full bg-primary text-white shadow-xl ring-4 transition hover:bg-primary-dark focus:outline-none focus:ring-2 focus:ring-primary ${ringClass}`}
            aria-label="Открыть AI-агента"
        >
            {icon}
            {unreadCount > 0 ? (
                <span className="absolute -right-1 -top-1 inline-flex min-w-[22px] items-center justify-center gap-1 rounded-full bg-white px-1.5 py-0.5 text-[11px] font-semibold text-primary shadow">
                    <Bell className="h-3.5 w-3.5" />
                    {unreadCount}
                </span>
            ) : null}
        </button>
    );
};
