import React, { useState, useCallback, createContext, useContext, ReactNode, useMemo } from 'react';
import { CheckCircle, XCircle, Info, AlertTriangle, X, ChevronDown, ChevronUp } from 'lucide-react';

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

const truncate = (value: string, limit = 180) => {
    if (value.length <= limit) return value;
    return `${value.slice(0, limit).trimEnd()}…`;
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
                className="fixed bottom-4 right-4 z-[var(--z-toast)] space-y-2 max-w-[420px]"
                role="region"
                aria-live="polite"
                aria-label="Уведомления"
            >
                {toasts.map((toast) => (
                    <ToastItem key={toast.id} toast={toast} onDismiss={removeToast} />
                ))}
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

    const colors = {
        success: 'bg-success-light text-success border-success/30',
        error: 'bg-danger-light text-danger border-danger/30',
        info: 'bg-info-light text-info border-info/30',
        warning: 'bg-warning-light text-warning border-warning/30',
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
        <div
            className={`relative overflow-hidden px-4 py-3 rounded-lg border shadow-lg animate-slide-in ${colors[toast.type]}`}
            role="alert"
        >
            <div className="flex items-start gap-3">
                <Icon className="w-5 h-5 flex-shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium whitespace-pre-wrap break-words">{visibleText}</p>
                    <div className="mt-2 flex items-center gap-3">
                        <span className="text-xs opacity-80">Скрытие через {secondsLeft}с</span>
                        {hasDetails ? (
                            <button
                                type="button"
                                onClick={() => setExpanded((v) => !v)}
                                className="text-xs underline underline-offset-2 hover:opacity-80 inline-flex items-center gap-1"
                                aria-label={expanded ? 'Скрыть детали' : 'Показать детали'}
                            >
                                {expanded ? 'Скрыть детали' : 'Подробнее'}
                                {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                            </button>
                        ) : null}
                    </div>
                    {expanded && detailsText ? (
                        <pre className="mt-2 text-xs whitespace-pre-wrap break-words font-mono bg-black/10 rounded p-2">
                            {detailsText}
                        </pre>
                    ) : null}
                </div>
                <button
                    type="button"
                    onClick={() => onDismiss(toast.id)}
                    className="flex-shrink-0 p-0.5 rounded hover:opacity-70 transition-opacity"
                    aria-label="Закрыть уведомление"
                >
                    <X className="w-4 h-4" />
                </button>
            </div>
            <div className="absolute left-0 bottom-0 h-[2px] bg-current/50 transition-[width] duration-200" style={{ width: `${progress}%` }} />
        </div>
    );
};
