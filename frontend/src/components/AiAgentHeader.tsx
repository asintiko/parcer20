import React from 'react';
import { Plus, X } from 'lucide-react';

interface AiAgentHeaderProps {
    title: string;
    onNewThread: () => void;
    onClose: () => void;
}

export const AiAgentHeader: React.FC<AiAgentHeaderProps> = ({ title, onNewThread, onClose }) => {
    return (
        <div className="flex items-center justify-between border-b border-border px-4 py-3 bg-surface">
            <div>
                <div className="text-sm font-semibold text-foreground">{title}</div>
                <div className="text-xs text-foreground-secondary">Встроенный помощник</div>
            </div>
            <div className="flex items-center gap-2">
                <button
                    type="button"
                    onClick={onNewThread}
                    className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium hover:bg-surface-2"
                >
                    <Plus className="w-4 h-4" />
                    Новый
                </button>
                <button
                    type="button"
                    onClick={onClose}
                    className="rounded-md p-2 hover:bg-surface-2"
                    aria-label="Закрыть AI-агента"
                >
                    <X className="w-4 h-4" />
                </button>
            </div>
        </div>
    );
};
