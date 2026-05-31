import React, { useState } from 'react';
import { Dialog } from './Dialog';
import { AlertTriangle } from 'lucide-react';

/**
 * Replacement for window.confirm. Editorial-styled, async-aware.
 * Use for destructive actions (logout, delete user, deactivate).
 */

export interface ConfirmDialogProps {
    open: boolean;
    title: string;
    description?: React.ReactNode;
    confirmLabel?: string;
    cancelLabel?: string;
    tone?: 'neutral' | 'danger';
    onConfirm: () => void | Promise<void>;
    onClose: () => void;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
    open,
    title,
    description,
    confirmLabel = 'Подтвердить',
    cancelLabel = 'Отмена',
    tone = 'neutral',
    onConfirm,
    onClose,
}) => {
    const [busy, setBusy] = useState(false);

    const handleConfirm = async () => {
        setBusy(true);
        try {
            await onConfirm();
        } finally {
            setBusy(false);
        }
    };

    return (
        <Dialog
            open={open}
            onClose={busy ? () => {} : onClose}
            ariaLabel={title}
            title={
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    {tone === 'danger' ? (
                        <span
                            aria-hidden
                            style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                width: 28,
                                height: 28,
                                borderRadius: 4,
                                background: 'color-mix(in srgb, var(--danger) 14%, transparent)',
                                color: 'var(--danger)',
                            }}
                        >
                            <AlertTriangle size={15} />
                        </span>
                    ) : null}
                    <h3 className="sp-sheet-title">{title}</h3>
                </div>
            }
            description={description}
            footer={
                <>
                    <span className="sp-spacer" />
                    <button
                        type="button"
                        className="sp-btn"
                        onClick={onClose}
                        disabled={busy}
                    >
                        {cancelLabel}
                    </button>
                    <button
                        type="button"
                        className={
                            tone === 'danger'
                                ? 'sp-btn sp-btn-danger sp-btn-solid'
                                : 'sp-btn sp-btn-primary'
                        }
                        onClick={handleConfirm}
                        disabled={busy}
                        autoFocus
                    >
                        {busy ? (
                            <>
                                <span className="sp-btn-spinner" aria-hidden />
                                Выполняем
                            </>
                        ) : (
                            confirmLabel
                        )}
                    </button>
                </>
            }
        >
            <div className="sp-row-hint" style={{ marginTop: -4 }}>
                Это действие нельзя отменить автоматически.
            </div>
        </Dialog>
    );
};
