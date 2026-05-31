import React, { useState, useCallback, createContext, useContext, ReactNode, useMemo } from 'react';
import { motion, AnimatePresence, type Variants } from 'motion/react';
import { CheckCircle, XCircle, Info, AlertTriangle, X, ChevronDown, ChevronUp } from 'lucide-react';
import '../styles/toast.css';

type ToastType = 'success' | 'error' | 'info' | 'warning';

type ToastOptions = {
    duration?: number;
    details?: string;
};

interface Toast {
    id: string;
    type: ToastType;
    message: string;
    details?: string;
    duration: number;
    createdAt: number;
}

interface ToastContextValue {
    showToast: (type: ToastType, message: string, durationOrOptions?: number | ToastOptions) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export const useToast = () => {
    const context = useContext(ToastContext);
    if (!context) {
        throw new Error('useToast must be used within ToastProvider');
    }
    return context;
};

const DEFAULT_DURATIONS: Record<ToastType, number> = {
    success: 3000,
    info: 3000,
    warning: 4000,
    error: 6000,
};

const TYPE_LABELS: Record<ToastType, string> = {
    success: 'Готово',
    error: 'Ошибка',
    info: 'Сообщение',
    warning: 'Внимание',
};

const truncate = (value: string, limit = 180) => {
    if (value.length <= limit) return value;
    return `${value.slice(0, limit).trimEnd()}…`;
};

const itemVariants: Variants = {
    hidden: { opacity: 0, x: 24, scale: 0.985 },
    visible: {
        opacity: 1,
        x: 0,
        scale: 1,
        transition: { duration: 0.32, ease: [0.2, 0, 0, 1] },
    },
    exit: {
        opacity: 0,
        x: 24,
        scale: 0.97,
        transition: { duration: 0.18, ease: [0.3, 0, 1, 1] },
    },
};

export const ToastProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
    const [toasts, setToasts] = useState<Toast[]>([]);

    const removeToast = useCallback((id: string) => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
    }, []);

    const showToast = useCallback((type: ToastType, message: string, durationOrOptions?: number | ToastOptions) => {
        const id = `${Date.now()}-${Math.random()}`;
        const options: ToastOptions =
            typeof durationOrOptions === 'number'
                ? { duration: durationOrOptions }
                : (durationOrOptions || {});
        const duration = options.duration ?? DEFAULT_DURATIONS[type];
        const toast: Toast = {
            id,
            type,
            message,
            details: options.details,
            duration,
            createdAt: Date.now(),
        };
        setToasts((prev) => [...prev, toast]);

        window.setTimeout(() => {
            setToasts((prev) => prev.filter((t) => t.id !== id));
        }, duration);
    }, []);

    return (
        <ToastContext.Provider value={{ showToast }}>
            {children}
            <div
                className="ed-toast-stack"
                role="region"
                aria-live="polite"
                aria-label="Уведомления"
            >
                <AnimatePresence initial={false}>
                    {toasts.map((toast) => (
                        <ToastItem key={toast.id} toast={toast} onDismiss={removeToast} />
                    ))}
                </AnimatePresence>
            </div>
        </ToastContext.Provider>
    );
};

const ToastItem: React.FC<{ toast: Toast; onDismiss: (id: string) => void }> = ({ toast, onDismiss }) => {
    const [expanded, setExpanded] = useState(false);
    const [now, setNow] = useState(Date.now());

    React.useEffect(() => {
        const interval = window.setInterval(() => setNow(Date.now()), 250);
        return () => window.clearInterval(interval);
    }, []);

    const icons = {
        success: CheckCircle,
        error: XCircle,
        info: Info,
        warning: AlertTriangle,
    };

    const Icon = icons[toast.type];
    const secondsLeft = Math.max(0, Math.ceil((toast.createdAt + toast.duration - now) / 1000));
    const progress = useMemo(() => {
        const elapsed = now - toast.createdAt;
        return Math.max(0, Math.min(100, ((toast.duration - elapsed) / toast.duration) * 100));
    }, [now, toast.createdAt, toast.duration]);

    const hasDetails = Boolean(toast.details) || toast.message.length > 180;
    const detailsText = toast.details || toast.message;
    const visibleText = expanded ? toast.message : truncate(toast.message);

    return (
        <motion.div
            className={`ed-toast is-${toast.type}`}
            role="alert"
            variants={itemVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            layout
        >
            <span className="ed-toast-accent" aria-hidden />
            <div className="ed-toast-icon">
                <Icon size={15} aria-hidden />
            </div>
            <div className="ed-toast-body">
                <div className="ed-toast-eyebrow">{TYPE_LABELS[toast.type]}</div>
                <div className="ed-toast-message">{visibleText}</div>
                <div className="ed-toast-meta">
                    <span className="ed-toast-countdown">{secondsLeft}s</span>
                    {hasDetails ? (
                        <button
                            type="button"
                            onClick={() => setExpanded((v) => !v)}
                            className="ed-toast-toggle"
                            aria-label={expanded ? 'Скрыть детали' : 'Показать детали'}
                        >
                            {expanded ? 'Скрыть' : 'Подробнее'}
                            {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
                        </button>
                    ) : null}
                </div>
                {expanded && detailsText ? (
                    <pre className="ed-toast-details">{detailsText}</pre>
                ) : null}
            </div>
            <button
                type="button"
                onClick={() => onDismiss(toast.id)}
                className="ed-toast-close"
                aria-label="Закрыть уведомление"
            >
                <X size={13} />
            </button>
            <div
                className="ed-toast-progress"
                style={{ width: `${progress}%` }}
                aria-hidden
            />
        </motion.div>
    );
};
