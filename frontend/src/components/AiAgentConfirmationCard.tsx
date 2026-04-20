import React from 'react';
import type { AgentRun } from '../services/api';
import { AiAgentToolCard } from './AiAgentToolCard';

interface AiAgentConfirmationCardProps {
    run: AgentRun;
    onConfirm: (runId: string) => void;
    pending?: boolean;
}

export const AiAgentConfirmationCard: React.FC<AiAgentConfirmationCardProps> = ({ run, onConfirm, pending }) => {
    if (!run.requires_confirmation) return null;
    const action = String(run.result?.confirmation_payload?.action || '');
    const confirmLabel =
        action === 'merge_duplicates'
            ? 'Объединить'
            : action === 'reparse_receipt'
                ? 'Запустить разбор'
                : action === 'publish_report'
                    ? 'Опубликовать'
                    : 'Подтвердить';
    return (
        <AiAgentToolCard
            title="Требуется подтверждение"
            body={run.result?.message || 'Для продолжения агент ожидает подтверждение действия.'}
        >
            <button
                type="button"
                onClick={() => onConfirm(run.id)}
                disabled={pending}
                className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-dark disabled:opacity-60"
            >
                {pending ? 'Подтверждение...' : confirmLabel}
            </button>
        </AiAgentToolCard>
    );
};
