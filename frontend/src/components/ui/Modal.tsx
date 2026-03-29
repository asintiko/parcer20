import React from 'react';
import { X } from 'lucide-react';

type ModalProps = {
    open: boolean;
    title: string;
    subtitle?: string;
    onClose: () => void;
    children: React.ReactNode;
    footer?: React.ReactNode;
    widthClassName?: string;
    zIndexClassName?: string;
};

export function Modal({
    open,
    title,
    subtitle,
    onClose,
    children,
    footer,
    widthClassName = 'max-w-xl',
    zIndexClassName = 'z-[var(--z-modal)]',
}: ModalProps) {
    if (!open) return null;

    return (
        <div className={`fixed inset-0 ${zIndexClassName} flex items-center justify-center p-4`}>
            <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden="true" />
            <div className={`relative w-full ${widthClassName} rounded-lg border border-border bg-surface shadow-xl`}>
                <div className="flex items-start justify-between p-4 border-b border-border">
                    <div>
                        <h3 className="text-lg font-semibold text-foreground">{title}</h3>
                        {subtitle ? <p className="text-sm text-foreground-secondary mt-1">{subtitle}</p> : null}
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        className="p-2 rounded-md hover:bg-surface-2 text-foreground-secondary"
                        aria-label="Закрыть окно"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>
                <div className="p-4">{children}</div>
                {footer ? <div className="p-4 border-t border-border bg-surface-2">{footer}</div> : null}
            </div>
        </div>
    );
}
