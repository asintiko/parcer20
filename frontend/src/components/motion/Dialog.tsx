import React from 'react';
import { motion, AnimatePresence, type Variants } from 'motion/react';
import { X } from 'lucide-react';
import { useRegisterOverlay } from '../../utils/overlayStore';
import { useModalFocus } from '../../hooks/useModalFocus';

/**
 * Center pop dialog primitive.
 * scale(0.96 → 1) + fade 240ms ease-out, scale(1 → 0.98) + fade 160ms ease-in on exit.
 * Backdrop fade with subtle blur.
 *
 * Centering done via flex wrapper (not transform). This avoids Framer Motion's
 * inline `transform: scale(...)` overriding CSS `transform: translate(-50%, -50%)`.
 */

export interface DialogProps {
    open: boolean;
    onClose: () => void;
    title: React.ReactNode;
    description?: React.ReactNode;
    children: React.ReactNode;
    footer?: React.ReactNode;
    width?: number | string;
    ariaLabel?: string;
}

const overlayVariants: Variants = {
    hidden: { opacity: 0 },
    visible: { opacity: 1, transition: { duration: 0.24, ease: [0.16, 1, 0.3, 1] } },
    exit: { opacity: 0, transition: { duration: 0.16, ease: [0.4, 0, 1, 1] } },
};

const dialogVariants: Variants = {
    hidden: { opacity: 0, scale: 0.96 },
    visible: {
        opacity: 1,
        scale: 1,
        transition: { duration: 0.24, ease: [0.16, 1, 0.3, 1] },
    },
    exit: {
        opacity: 0,
        scale: 0.98,
        transition: { duration: 0.16, ease: [0.4, 0, 1, 1] },
    },
};

export const Dialog: React.FC<DialogProps> = ({
    open,
    onClose,
    title,
    description,
    children,
    footer,
    width = 440,
    ariaLabel,
}) => {
    const dialogRef = React.useRef<HTMLDivElement>(null);
    const titleId = React.useId();
    const descriptionId = React.useId();
    useRegisterOverlay(open);
    useModalFocus(open, dialogRef, onClose);

    const widthCss = typeof width === 'number' ? `${width}px` : width;

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
                    {/* Centering wrapper — does NOT animate, owns flex layout */}
                    <div className="sp-dialog-center" role="presentation">
                        <motion.div
                            ref={dialogRef}
                            className="sp-dialog"
                            role="dialog"
                            aria-modal="true"
                            aria-label={ariaLabel}
                            aria-labelledby={ariaLabel ? undefined : titleId}
                            aria-describedby={description ? descriptionId : undefined}
                            tabIndex={-1}
                            variants={dialogVariants}
                            initial="hidden"
                            animate="visible"
                            exit="exit"
                            style={{ width: `min(${widthCss}, calc(100vw - 32px))` }}
                            onClick={(e) => e.stopPropagation()}
                        >
                            <div className="sp-sheet-head">
                                <div style={{ minWidth: 0 }}>
                                    {typeof title === 'string' ? (
                                        <h3 id={titleId} className="sp-sheet-title">{title}</h3>
                                    ) : (
                                        <div id={titleId}>{title}</div>
                                    )}
                                    {description ? <div id={descriptionId} className="sp-sheet-sub">{description}</div> : null}
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
                            <div className="sp-sheet-body" style={{ paddingBottom: 4 }}>
                                {children}
                            </div>
                            {footer ? <div className="sp-sheet-foot">{footer}</div> : null}
                        </motion.div>
                    </div>
                </>
            ) : null}
        </AnimatePresence>
    );
};
