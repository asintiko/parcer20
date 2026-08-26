import React from 'react';

type EmptyStateProps = {
    icon?: React.ReactNode;
    title: string;
    description: string;
    action?: React.ReactNode;
    compact?: boolean;
};

export function EmptyState({ icon, title, description, action, compact = false }: EmptyStateProps) {
    return (
        <div className={`bg-surface rounded-lg border border-border ${compact ? 'p-6' : 'p-12'} text-center`}>
            <div className="max-w-md mx-auto">
                {icon ? (
                    <div className="w-14 h-14 bg-surface-2 rounded-full flex items-center justify-center mx-auto mb-4">
                        {icon}
                    </div>
                ) : null}
                <h3 className="text-lg font-semibold text-foreground mb-2">{title}</h3>
                <p className="text-sm text-foreground-secondary">{description}</p>
                {action ? <div className="mt-4">{action}</div> : null}
            </div>
        </div>
    );
}
