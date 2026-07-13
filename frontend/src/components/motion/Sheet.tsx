import React from 'react';
import { motion, AnimatePresence, type Variants } from 'motion/react';
import { X } from 'lucide-react';
import { useRegisterOverlay } from '../../utils/overlayStore';
import { useModalFocus } from '../../hooks/useModalFocus';

/**
 * Right-side editorial drawer / sheet primitive.
 * Slide-in 320ms ease-out, slide-out 240ms ease-in. Symmetric overlay fade-blur.
 * Uses .sp-* tokens for visual continuity.
 */

export interface SheetProps {
    open: boolean;
    onClose: () => void;
    title: React.ReactNode;
    subtitle?: React.ReactNode;
    children: React.ReactNode;
    footer?: React.ReactNode;
    width?: number | string;
    /**
     * Aria-label / labelledby root id of the sheet.
     */
    ariaLabel?: string;
}

const overlayVariants: Variants = {
    hidden: { opacity: 0 },
    visible: { opacity: 1, transition: { duration: 0.24, ease: [0.16, 1, 0.3, 1] } },
    exit: { opacity: 0, transition: { duration: 0.2, ease: [0.4, 0, 1, 1] } },
};

const panelVariants: Variants = {
    hidden: { x: '100%' },
    visible: { x: 0, transition: { duration: 0.32, ease: [0.16, 1, 0.3, 1] } },
    exit: { x: '100%', transition: { duration: 0.24, ease: [0.4, 0, 1, 1] } },
};

export const Sheet: React.FC<SheetProps> = ({
    open,
    onClose,
    title,
    subtitle,
    children,
    footer,
    width = 480,
    ariaLabel,
}) => {
    const sheetRef = React.useRef<HTMLElement>(null);
    const titleId = React.useId();
    const subtitleId = React.useId();
    useRegisterOverlay(open);
    useModalFocus(open, sheetRef, onClose);

    return (
        <AnimatePresence>
            {open ? (
                <>
                    <motion.div
                        className="sp-sheet-overlay"
                        variants={overlayVariants}
                        initial="hidden"
                        animate="visible"
                        exit="exit"
                        onClick={onClose}
                        aria-hidden
                    />
                    <motion.aside
                        ref={sheetRef}
                        className="sp-shell sp-sheet"
                        role="dialog"
                        aria-modal="true"
                        aria-label={ariaLabel}
                        aria-labelledby={ariaLabel ? undefined : titleId}
                        aria-describedby={subtitle ? subtitleId : undefined}
                        tabIndex={-1}
                        variants={panelVariants}
                        initial="hidden"
                        animate="visible"
                        exit="exit"
                        style={{ width }}
                    >
                        <div className="sp-sheet-head">
                            <div style={{ minWidth: 0 }}>
                                {typeof title === 'string' ? (
                                    <h3 id={titleId} className="sp-sheet-title">{title}</h3>
                                ) : (
                                    <div id={titleId}>{title}</div>
                                )}
                                {subtitle ? <div id={subtitleId} className="sp-sheet-sub">{subtitle}</div> : null}
                            </div>
                            <button
                                type="button"
                                className="sp-btn sp-btn-icon sp-btn-ghost"
                                onClick={onClose}
                                aria-label="Закрыть"
                            >
                                <X size={15} />
                            </button>
                        </div>
                        <div className="sp-sheet-body">{children}</div>
                        {footer ? <div className="sp-sheet-foot">{footer}</div> : null}
                    </motion.aside>
                </>
            ) : null}
        </AnimatePresence>
    );
};
