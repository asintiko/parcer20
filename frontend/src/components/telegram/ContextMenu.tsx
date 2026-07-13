import React, { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { motion } from 'motion/react';

export interface ContextMenuItem {
    key: string;
    label: string;
    icon?: React.ReactNode;
    onClick: () => void;
    danger?: boolean;
    disabled?: boolean;
}

interface ContextMenuProps {
    open: boolean;
    x: number;
    y: number;
    items: ContextMenuItem[];
    onClose: () => void;
}

const containerVariants = {
    hidden: { opacity: 0, scale: 0.96, y: -4 },
    visible: {
        opacity: 1,
        scale: 1,
        y: 0,
        transition: {
            duration: 0.16,
            ease: [0.16, 1, 0.3, 1] as [number, number, number, number],
            staggerChildren: 0.024,
            delayChildren: 0.02,
        },
    },
};

const itemVariants = {
    hidden: { opacity: 0, x: -4 },
    visible: { opacity: 1, x: 0, transition: { duration: 0.14, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] } },
};

export const ContextMenu: React.FC<ContextMenuProps> = ({ open, x, y, items, onClose }) => {
    const ref = useRef<HTMLDivElement | null>(null);

    useEffect(() => {
        if (!open) return;
        const onDown = (e: MouseEvent) => {
            if (ref.current?.contains(e.target as Node)) return;
            onClose();
        };
        const onKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape') onClose();
        };
        document.addEventListener('mousedown', onDown);
        document.addEventListener('keydown', onKey);
        return () => {
            document.removeEventListener('mousedown', onDown);
            document.removeEventListener('keydown', onKey);
        };
    }, [open, onClose]);

    if (!open) return null;

    const left = Math.min(x, window.innerWidth - 240);
    const top = Math.min(y, window.innerHeight - items.length * 34 - 16);

    return createPortal(
        <motion.div
            ref={ref}
            className="tg-context-menu"
            style={{ left, top, transformOrigin: 'top left' }}
            role="menu"
            onContextMenu={(e) => e.preventDefault()}
            variants={containerVariants}
            initial="hidden"
            animate="visible"
        >
            {items.map((it) => (
                <motion.button
                    key={it.key}
                    type="button"
                    role="menuitem"
                    className={`tg-context-item${it.danger ? ' is-danger' : ''}`}
                    onClick={() => {
                        if (it.disabled) return;
                        it.onClick();
                        onClose();
                    }}
                    disabled={it.disabled}
                    variants={itemVariants}
                >
                    {it.icon ? <span className="tg-context-icon">{it.icon}</span> : null}
                    <span>{it.label}</span>
                </motion.button>
            ))}
        </motion.div>,
        document.body,
    );
};
