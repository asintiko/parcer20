import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence, type Variants } from 'motion/react';

/**
 * Popover that renders into <body> via portal and positions itself
 * relative to an anchor element via fixed coordinates. Avoids
 * clipping by overflow:auto / overflow:hidden ancestors (e.g. tables).
 *
 * Place keyboard-nav and aria-menu props on items at call site.
 */

export interface PopoverProps {
    open: boolean;
    anchorRef: React.RefObject<HTMLElement>;
    onClose: () => void;
    placement?: 'bottom-end' | 'bottom-start';
    minWidth?: number;
    children: React.ReactNode;
    ariaLabel?: string;
}

const variants: Variants = {
    hidden: { opacity: 0, y: -4, scale: 0.98 },
    visible: { opacity: 1, y: 0, scale: 1, transition: { duration: 0.16, ease: [0.16, 1, 0.3, 1] } },
    exit: { opacity: 0, y: -4, scale: 0.98, transition: { duration: 0.12, ease: [0.4, 0, 1, 1] } },
};

export const Popover: React.FC<PopoverProps> = ({
    open,
    anchorRef,
    onClose,
    placement = 'bottom-end',
    minWidth = 200,
    children,
    ariaLabel,
}) => {
    const popRef = useRef<HTMLDivElement | null>(null);
    const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

    // Compute position when open or on layout change
    useLayoutEffect(() => {
        if (!open) {
            setPos(null);
            return;
        }
        const anchor = anchorRef.current;
        if (!anchor) return;

        const update = () => {
            const r = anchor.getBoundingClientRect();
            const popW = Math.max(popRef.current?.offsetWidth || 0, minWidth);
            const popH = popRef.current?.offsetHeight || 0;
            const margin = 6;

            let top = r.bottom + margin;
            let left = placement === 'bottom-end' ? r.right - popW : r.left;

            // Flip up if no room below
            if (top + popH > window.innerHeight - 8) {
                top = Math.max(8, r.top - popH - margin);
            }
            // Clamp left within viewport
            const maxLeft = window.innerWidth - popW - 8;
            if (left > maxLeft) left = maxLeft;
            if (left < 8) left = 8;

            setPos({ top, left });
        };

        update();
        window.addEventListener('resize', update);
        window.addEventListener('scroll', update, true);
        return () => {
            window.removeEventListener('resize', update);
            window.removeEventListener('scroll', update, true);
        };
    }, [open, anchorRef, placement, minWidth]);

    // Close on outside click / Escape
    useEffect(() => {
        if (!open) return;
        const onDown = (e: MouseEvent) => {
            const target = e.target as Node;
            if (popRef.current?.contains(target)) return;
            if (anchorRef.current?.contains(target)) return;
            onClose();
        };
        const onKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                onClose();
            }
        };
        document.addEventListener('mousedown', onDown);
        document.addEventListener('keydown', onKey);
        return () => {
            document.removeEventListener('mousedown', onDown);
            document.removeEventListener('keydown', onKey);
        };
    }, [open, anchorRef, onClose]);

    if (typeof document === 'undefined') return null;

    return createPortal(
        <AnimatePresence>
            {open && pos ? (
                <motion.div
                    ref={popRef}
                    role="menu"
                    aria-label={ariaLabel}
                    className="sp-pop sp-pop-portal"
                    variants={variants}
                    initial="hidden"
                    animate="visible"
                    exit="exit"
                    style={{
                        position: 'fixed',
                        top: pos.top,
                        left: pos.left,
                        minWidth,
                        zIndex: 60,
                    }}
                    onClick={(e) => e.stopPropagation()}
                >
                    {children}
                </motion.div>
            ) : null}
        </AnimatePresence>,
        document.body
    );
};
