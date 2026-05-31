import React, { useEffect } from 'react';
import { motion, AnimatePresence, type Variants } from 'motion/react';
import { AppRail } from './AppRail';

interface MobileDrawerProps {
    open: boolean;
    onClose: () => void;
}

const overlayVariants: Variants = {
    hidden: { opacity: 0 },
    visible: { opacity: 1, transition: { duration: 0.2, ease: [0.16, 1, 0.3, 1] } },
    exit: { opacity: 0, transition: { duration: 0.16, ease: [0.4, 0, 1, 1] } },
};

const drawerVariants: Variants = {
    hidden: { x: '-100%' },
    visible: { x: 0, transition: { duration: 0.32, ease: [0.16, 1, 0.3, 1] } },
    exit: { x: '-100%', transition: { duration: 0.24, ease: [0.4, 0, 1, 1] } },
};

export const MobileDrawer: React.FC<MobileDrawerProps> = ({ open, onClose }) => {
    useEffect(() => {
        if (!open) return;
        const onKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                onClose();
            }
        };
        window.addEventListener('keydown', onKey);
        const prev = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        return () => {
            window.removeEventListener('keydown', onKey);
            document.body.style.overflow = prev;
        };
    }, [open, onClose]);

    return (
        <AnimatePresence>
            {open ? (
                <>
                    <motion.div
                        className="rl-mobile-overlay"
                        variants={overlayVariants}
                        initial="hidden"
                        animate="visible"
                        exit="exit"
                        onClick={onClose}
                        aria-hidden
                    />
                    <motion.div
                        className="rl-mobile-drawer"
                        variants={drawerVariants}
                        initial="hidden"
                        animate="visible"
                        exit="exit"
                        role="dialog"
                        aria-modal="true"
                        aria-label="Главная навигация"
                    >
                        <AppRail
                            collapsed={false}
                            onToggleCollapse={() => { /* no-op in mobile */ }}
                            mobile
                            onNavigate={onClose}
                        />
                    </motion.div>
                </>
            ) : null}
        </AnimatePresence>
    );
};
