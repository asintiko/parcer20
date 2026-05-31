import React from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { FileText, CheckCheck, Download, ScanLine, Check, Loader2, RefreshCw } from 'lucide-react';
import type { TelegramChatMessage } from '../../services/api';

interface MessageBubbleProps {
    message: TelegramChatMessage;
    selectionMode?: boolean;
    selected?: boolean;
    onToggleSelect?: (id: number) => void;
    onProcess?: (message: TelegramChatMessage) => void;
    onContextMenu?: (e: React.MouseEvent, message: TelegramChatMessage) => void;
    processing?: boolean;
    processed?: boolean;
    failed?: boolean;
    /** Last bubble that just appeared — play enter animation */
    animateEnter?: boolean;
}

const formatTime = (iso?: string | null): string => {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
};

const formatBytes = (bytes?: number): string => {
    if (!bytes) return '';
    const u = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    let n = bytes;
    while (n >= 1024 && i < u.length - 1) {
        n /= 1024;
        i += 1;
    }
    return `${n.toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
};

const enterVariants = {
    hidden: { opacity: 0, y: 8, scale: 0.985 },
    visible: {
        opacity: 1,
        y: 0,
        scale: 1,
        transition: { duration: 0.24, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] },
    },
};

const checkboxVariants = {
    hidden: { opacity: 0, scale: 0.6, x: -4 },
    visible: { opacity: 1, scale: 1, x: 0, transition: { duration: 0.18, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] } },
    exit: { opacity: 0, scale: 0.6, x: -4, transition: { duration: 0.12 } },
};

const checkInnerVariants = {
    hidden: { opacity: 0, scale: 0.5 },
    visible: { opacity: 1, scale: 1, transition: { duration: 0.16, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] } },
};

const ProcessIcon: React.FC<{ processing?: boolean; processed?: boolean; failed?: boolean }> = ({
    processing,
    processed,
    failed,
}) => {
    if (processing) {
        return (
            <Loader2 size={16} className="tg-msg-process-spin" aria-hidden />
        );
    }
    if (failed) return <RefreshCw size={15} aria-hidden />;
    if (processed) return <Check size={15} aria-hidden />;
    return <ScanLine size={15} aria-hidden />;
};

export const MessageBubble: React.FC<MessageBubbleProps> = ({
    message,
    selectionMode,
    selected,
    onToggleSelect,
    onProcess,
    onContextMenu,
    processing,
    processed,
    failed,
    animateEnter,
}) => {
    const outgoing = Boolean(message.is_outgoing);
    const time = formatTime(message.date);
    const hasId = Boolean(message.id);
    const showProcess = !selectionMode && hasId && Boolean(onProcess);

    const handleClick = (e: React.MouseEvent) => {
        if (selectionMode && onToggleSelect && message.id) {
            onToggleSelect(message.id);
            return;
        }
        if ((e.ctrlKey || e.metaKey) && onToggleSelect && message.id) {
            e.preventDefault();
            onToggleSelect(message.id);
        }
    };

    const handleContextMenu = (e: React.MouseEvent) => {
        if (onContextMenu) {
            onContextMenu(e, message);
        }
    };

    const processLabel = failed ? 'Повторить' : processed ? 'Готово' : processing ? '…' : 'Обработать';
    const processTitle = failed
        ? 'Ошибка обработки — нажмите чтобы повторить'
        : processed
        ? 'Уже обработано'
        : processing
        ? 'Обработка…'
        : 'Отправить в обработку';

    const rowClass = [
        'tg-msg-row',
        outgoing ? 'is-outgoing' : 'is-incoming',
        selectionMode ? 'is-select-mode' : '',
        selected ? 'is-selected' : '',
    ]
        .filter(Boolean)
        .join(' ');

    const innerContent = (
        <>
            <AnimatePresence initial={false}>
                {selectionMode ? (
                    <motion.div
                        className="tg-msg-checkbox"
                        aria-checked={selected}
                        role="checkbox"
                        tabIndex={0}
                        variants={checkboxVariants}
                        initial="hidden"
                        animate="visible"
                        exit="exit"
                        onKeyDown={(e) => {
                            if (e.key === ' ' || e.key === 'Enter') {
                                e.preventDefault();
                                if (message.id && onToggleSelect) onToggleSelect(message.id);
                            }
                        }}
                    >
                        <AnimatePresence initial={false}>
                            {selected ? (
                                <motion.span
                                    key="check"
                                    variants={checkInnerVariants}
                                    initial="hidden"
                                    animate="visible"
                                    exit="hidden"
                                    style={{ display: 'inline-flex' }}
                                >
                                    <Check size={12} />
                                </motion.span>
                            ) : null}
                        </AnimatePresence>
                    </motion.div>
                ) : null}
            </AnimatePresence>

            <div className="tg-msg-bubble-wrap">
                <div className="tg-msg-bubble">
                    {message.photo ? (
                        message.photo.download_url ? (
                            <a
                                href={message.photo.download_url}
                                target="_blank"
                                rel="noreferrer"
                                className="tg-msg-photo"
                                aria-label="Открыть фото"
                                onClick={(e) => {
                                    if (selectionMode) e.preventDefault();
                                }}
                            >
                                <img
                                    src={message.photo.download_url}
                                    alt={message.photo.file_name || 'photo'}
                                    loading="lazy"
                                />
                            </a>
                        ) : (
                            <div className="tg-msg-photo">
                                <div
                                    style={{
                                        padding: '40px 80px',
                                        textAlign: 'center',
                                        color: 'var(--text-muted)',
                                    }}
                                >
                                    📷 Фото
                                </div>
                            </div>
                        )
                    ) : null}

                    {message.document ? (
                        <a
                            href={message.document.download_url || '#'}
                            target="_blank"
                            rel="noreferrer"
                            className="tg-msg-document"
                            aria-label={`Скачать ${message.document.file_name || 'документ'}`}
                            onClick={(e) => {
                                if (selectionMode) e.preventDefault();
                            }}
                        >
                            <span className="tg-msg-doc-icon">
                                <FileText size={16} />
                            </span>
                            <span className="tg-msg-doc-meta">
                                <span className="tg-msg-doc-name">
                                    {message.document.file_name || 'Документ'}
                                </span>
                                <span className="tg-msg-doc-size">
                                    {formatBytes(message.document.size)}
                                    {message.document.mime_type ? ` · ${message.document.mime_type}` : ''}
                                </span>
                            </span>
                            <Download size={14} aria-hidden style={{ opacity: 0.6, flexShrink: 0 }} />
                        </a>
                    ) : null}

                    {message.text ? <div className="tg-msg-text">{message.text}</div> : null}

                    <div className="tg-msg-meta">
                        <AnimatePresence>
                            {processed ? (
                                <motion.span
                                    key="processed-tag"
                                    className="tg-msg-processed-tag"
                                    aria-label="Обработано"
                                    initial={{ opacity: 0, scale: 0.85, x: -4 }}
                                    animate={{ opacity: 1, scale: 1, x: 0 }}
                                    exit={{ opacity: 0, scale: 0.85 }}
                                    transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
                                >
                                    обработано
                                </motion.span>
                            ) : null}
                        </AnimatePresence>
                        <span>{time}</span>
                        {outgoing ? (
                            <span className="tg-msg-tick" aria-label="Отправлено">
                                <CheckCheck size={12} />
                            </span>
                        ) : null}
                    </div>
                </div>

                {showProcess ? (
                    <button
                        type="button"
                        className={[
                            'tg-msg-process',
                            processing ? 'is-busy' : '',
                            processed ? 'is-done' : '',
                            failed ? 'is-failed' : '',
                        ]
                            .filter(Boolean)
                            .join(' ')}
                        onClick={(e) => {
                            e.stopPropagation();
                            if (!processing) onProcess?.(message);
                        }}
                        title={processTitle}
                        aria-label={processTitle}
                        aria-busy={processing}
                        disabled={processing}
                    >
                        <AnimatePresence mode="wait" initial={false}>
                            <motion.span
                                key={processing ? 'p' : processed ? 'd' : failed ? 'f' : 'i'}
                                initial={{ opacity: 0, scale: 0.7, rotate: -20 }}
                                animate={{ opacity: 1, scale: 1, rotate: 0 }}
                                exit={{ opacity: 0, scale: 0.7, rotate: 20 }}
                                transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
                                style={{ display: 'inline-flex' }}
                            >
                                <ProcessIcon processing={processing} processed={processed} failed={failed} />
                            </motion.span>
                        </AnimatePresence>
                        <span className="tg-msg-process-label">{processLabel}</span>
                    </button>
                ) : null}
            </div>
        </>
    );

    if (animateEnter) {
        return (
            <motion.div
                className={rowClass}
                onClick={handleClick}
                onContextMenu={handleContextMenu}
                variants={enterVariants}
                initial="hidden"
                animate="visible"
            >
                {innerContent}
            </motion.div>
        );
    }

    // No motion wrapper for stable bubbles — saves perf on every refetch.
    return (
        <div className={rowClass} onClick={handleClick} onContextMenu={handleContextMenu}>
            {innerContent}
        </div>
    );
};
