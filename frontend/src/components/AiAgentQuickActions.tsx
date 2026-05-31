import React from 'react';

type QuickAction = {
    label: string;
    prompt: string;
    tool?: string;
};

const QUICK_ACTIONS: QuickAction[] = [
    { label: 'Сопоставление', prompt: 'Проведи сопоставление приложений и покажи элементы, которые ждут проверки', tool: 'app_mapping' },
    { label: 'Проверка', prompt: 'Проведи проверку проблемных транзакций', tool: 'data_verification' },
    { label: 'Сверка', prompt: 'Запусти сверку Telegram истории и локальной базы', tool: 'bot_reconciliation' },
    { label: 'Недельный отчет', prompt: 'Собери недельный отчет по системе', tool: 'report_builder' },
];

interface AiAgentQuickActionsProps {
    onAction: (action: QuickAction) => void;
}

export const AiAgentQuickActions: React.FC<AiAgentQuickActionsProps> = ({ onAction }) => {
    return (
        <div className="flex flex-wrap gap-2">
            {QUICK_ACTIONS.map((action) => (
                <button
                    key={action.label}
                    type="button"
                    onClick={() => onAction(action)}
                    className="rounded-full border border-border bg-surface px-3 py-1.5 text-xs font-medium text-foreground hover:bg-surface-2"
                >
                    {action.label}
                </button>
            ))}
        </div>
    );
};
