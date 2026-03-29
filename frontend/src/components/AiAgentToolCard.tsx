import React from 'react';

export const AiAgentToolCard: React.FC<{ title: string; body?: string; children?: React.ReactNode }> = ({ title, body, children }) => {
    return (
        <div className="rounded-lg border border-border bg-surface-2 px-3 py-2">
            <div className="text-xs font-semibold uppercase tracking-wide text-primary">{title}</div>
            {body ? <div className="mt-1 text-sm text-foreground-secondary whitespace-pre-wrap">{body}</div> : null}
            {children ? <div className="mt-2">{children}</div> : null}
        </div>
    );
};
