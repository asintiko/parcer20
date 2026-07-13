import React from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Sparkles, Loader2, AlertTriangle, BellDot } from 'lucide-react';
import '../styles/ai-agent.css';

type LauncherState = 'idle' | 'has_notifications' | 'thinking' | 'running' | 'error';

interface AiAgentLauncherProps {
    unreadCount: number;
    state?: LauncherState;
    onClick: () => void;
}

const stateLabel: Record<LauncherState, string> = {
    idle: 'AI-агент',
    has_notifications: 'Новые уведомления',
    thinking: 'Думает…',
    running: 'Работает…',
    error: 'Ошибка агента',
};

export const AiAgentLauncher: React.FC<AiAgentLauncherProps> = ({
    unreadCount,
    state = 'idle',
    onClick,
}) => {
    const isBusy = state === 'thinking' || state === 'running';
    const isError = state === 'error';
    const isAlert = state === 'has_notifications';

    const icon = isError ? (
        <AlertTriangle size={15} aria-hidden />
    ) : isBusy ? (
        <Loader2 size={15} className="ai-fab-spin" aria-hidden />
    ) : (
        <Sparkles size={15} aria-hidden />
    );

    const label = isError ? 'Ошибка' : isBusy ? 'Работаю' : 'Агент';

    return (
        <motion.button
            type="button"
            onClick={onClick}
            className={[
                'ai-fab',
                isError ? 'is-error' : '',
                isBusy ? 'is-busy' : '',
                isAlert ? 'is-alert' : '',
            ]
                .filter(Boolean)
                .join(' ')}
            aria-label={stateLabel[state]}
            title={stateLabel[state]}
            initial={{ opacity: 0, y: 12, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
            whileHover={{ y: -2, transition: { duration: 0.18, ease: [0.2, 0, 0, 1] } }}
            whileTap={{ scale: 0.94, transition: { duration: 0.1, ease: [0.4, 0, 1, 1] } }}
        >
            <span className="ai-fab-eyebrow">AI</span>
            <span className="ai-fab-divider" aria-hidden />
            <span className="ai-fab-icon">
                <AnimatePresence mode="wait" initial={false}>
                    <motion.span
                        key={state}
                        initial={{ opacity: 0, scale: 0.6, rotate: -6 }}
                        animate={{ opacity: 1, scale: 1, rotate: 0 }}
                        exit={{ opacity: 0, scale: 0.6, rotate: 6 }}
                        transition={{ duration: 0.22, ease: [0.34, 1.3, 0.64, 1] }}
                        style={{ display: 'inline-flex' }}
                    >
                        {icon}
                    </motion.span>
                </AnimatePresence>
            </span>
            <span className="ai-fab-label">{label}</span>
            <AnimatePresence>
                {unreadCount > 0 ? (
                    <motion.span
                        key="badge"
                        className="ai-fab-badge"
                        initial={{ opacity: 0, scale: 0.5, x: -4 }}
                        animate={{ opacity: 1, scale: 1, x: 0 }}
                        exit={{ opacity: 0, scale: 0.5, x: -4 }}
                        transition={{ duration: 0.22, ease: [0.34, 1.3, 0.64, 1] }}
                    >
                        <BellDot size={10} aria-hidden />
                        <span>{unreadCount > 99 ? '99+' : unreadCount}</span>
                    </motion.span>
                ) : null}
            </AnimatePresence>
        </motion.button>
    );
};
