import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { ChevronDown, MessageSquare } from 'lucide-react';
import { MessageBubble } from './MessageBubble';
import type { TelegramChatMessage, TgKeyboardButton } from '../../services/api';

interface MessageStreamProps {
    chatId: number;
    messages: TelegramChatMessage[];
    isLoading?: boolean;
    selectionMode?: boolean;
    selectedIds?: Set<number>;
    onToggleSelect?: (id: number) => void;
    onProcess?: (message: TelegramChatMessage) => void;
    onMessageContextMenu?: (e: React.MouseEvent, message: TelegramChatMessage) => void;
    onOpenWebApp?: (message: TelegramChatMessage, btn: TgKeyboardButton) => void;
    onOpenLink?: (url: string) => void;
    processingIds?: Set<number>;
    processedIds?: Set<number>;
    failedIds?: Set<number>;
    /** When this number changes (e.g. after send), force smooth scroll to bottom. */
    forceScrollToBottomKey?: number;
    emptyTitle?: string;
    emptySub?: string;
}

const NEAR_BOTTOM_THRESHOLD = 80;

const dateLabel = (iso?: string | null): string => {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yesterday = new Date(today.getTime() - 24 * 60 * 60 * 1000);
    const dDay = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    if (dDay.getTime() === today.getTime()) return 'Сегодня';
    if (dDay.getTime() === yesterday.getTime()) return 'Вчера';
    return d.toLocaleDateString('ru-RU', {
        day: 'numeric',
        month: 'long',
        year: d.getFullYear() !== now.getFullYear() ? 'numeric' : undefined,
    });
};

const sameDay = (a?: string | null, b?: string | null): boolean => {
    if (!a || !b) return false;
    const da = new Date(a);
    const db = new Date(b);
    return da.toDateString() === db.toDateString();
};

export const MessageStream: React.FC<MessageStreamProps> = ({
    chatId,
    messages,
    isLoading,
    selectionMode,
    selectedIds,
    onToggleSelect,
    onProcess,
    onMessageContextMenu,
    onOpenWebApp,
    onOpenLink,
    processingIds,
    processedIds,
    failedIds,
    forceScrollToBottomKey,
    emptyTitle,
    emptySub,
}) => {
    const ref = useRef<HTMLDivElement | null>(null);
    const wasNearBottomRef = useRef<boolean>(true);
    const lastSeenLengthRef = useRef<number>(0);
    const lastSeenLastIdRef = useRef<number | null>(null);
    const [showFab, setShowFab] = useState(false);

    const scrollToBottom = (smooth: boolean) => {
        const el = ref.current;
        if (!el) return;
        if (smooth) {
            el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
        } else {
            el.scrollTop = el.scrollHeight;
        }
    };

    const checkNearBottom = () => {
        const el = ref.current;
        if (!el) return;
        const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
        const near = distance < NEAR_BOTTOM_THRESHOLD;
        wasNearBottomRef.current = near;
        setShowFab(!near && messages.length > 0);
    };

    // Initial mount / chat switch — instant scroll to the bottom.
    useLayoutEffect(() => {
        scrollToBottom(false);
        wasNearBottomRef.current = true;
        lastSeenLengthRef.current = messages.length;
        lastSeenLastIdRef.current = messages.length ? messages[messages.length - 1].id ?? null : null;
        setShowFab(false);
        // Run only once per mount or when the messages identity changes drastically.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // First batch of messages arrives async after mount — make sure we land at the bottom.
    useEffect(() => {
        if (messages.length === 0) return;
        if (lastSeenLengthRef.current === 0) {
            requestAnimationFrame(() => scrollToBottom(false));
            lastSeenLengthRef.current = messages.length;
            lastSeenLastIdRef.current = messages[messages.length - 1].id ?? null;
            wasNearBottomRef.current = true;
            setShowFab(false);
        }
    }, [messages.length]);

    // New messages arrived — autoscroll only if the user was near the bottom.
    useEffect(() => {
        const last = messages.length ? messages[messages.length - 1] : null;
        const lastId = last?.id ?? null;
        const grew = messages.length > lastSeenLengthRef.current || lastId !== lastSeenLastIdRef.current;
        if (grew) {
            if (wasNearBottomRef.current) {
                // Defer to next paint so layout is stable.
                requestAnimationFrame(() => scrollToBottom(false));
            }
            lastSeenLengthRef.current = messages.length;
            lastSeenLastIdRef.current = lastId;
            // Re-evaluate FAB visibility post-update.
            requestAnimationFrame(checkNearBottom);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [messages.length, messages[messages.length - 1]?.id]);

    // Explicit force (e.g. after user sends a message) — always smooth scroll.
    useEffect(() => {
        if (typeof forceScrollToBottomKey !== 'number') return;
        if (forceScrollToBottomKey === 0) return;
        requestAnimationFrame(() => scrollToBottom(true));
    }, [forceScrollToBottomKey]);

    if (isLoading) {
        return (
            <div className="tg-stream">
                <div className="tg-stream-empty">
                    <div className="tg-stream-empty-title">Загружаем сообщения…</div>
                </div>
            </div>
        );
    }

    if (!messages.length) {
        return (
            <div className="tg-stream">
                <div className="tg-stream-empty">
                    <div className="tg-stream-empty-icon">
                        <MessageSquare size={24} />
                    </div>
                    <div className="tg-stream-empty-title">{emptyTitle || 'Сообщений ещё нет'}</div>
                    <div>{emptySub || 'Напишите первое сообщение в этом чате.'}</div>
                </div>
            </div>
        );
    }

    const lastIndex = messages.length - 1;

    return (
        <div className="tg-stream-wrap">
            <div className="tg-stream" ref={ref} onScroll={checkNearBottom}>
                {messages.map((m, idx) => {
                    const prev = idx > 0 ? messages[idx - 1] : null;
                    const showDateDivider = !prev || !sameDay(prev.date, m.date);
                    const id = m.id;
                    const animate = idx === lastIndex && messages.length > lastSeenLengthRef.current;
                    return (
                        <React.Fragment key={id != null ? `m-${id}` : `i-${idx}`}>
                            {showDateDivider ? (
                                <div className="tg-date-divider tg-date-divider-sticky">{dateLabel(m.date)}</div>
                            ) : null}
                            <MessageBubble
                                chatId={chatId}
                                message={m}
                                selectionMode={selectionMode}
                                selected={id ? selectedIds?.has(id) : false}
                                onToggleSelect={onToggleSelect}
                                onProcess={onProcess}
                                onContextMenu={onMessageContextMenu}
                                onOpenWebApp={onOpenWebApp}
                                onOpenLink={onOpenLink}
                                processing={id ? processingIds?.has(id) : false}
                                processed={id ? processedIds?.has(id) : false}
                                failed={id ? failedIds?.has(id) : false}
                                animateEnter={animate}
                            />
                        </React.Fragment>
                    );
                })}
            </div>
            <AnimatePresence>
                {showFab ? (
                    <motion.button
                        type="button"
                        className="tg-scroll-fab"
                        onClick={() => scrollToBottom(true)}
                        aria-label="Прокрутить вниз"
                        title="Прокрутить вниз"
                        initial={{ opacity: 0, y: 8, scale: 0.85 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        exit={{ opacity: 0, y: 8, scale: 0.85 }}
                        whileHover={{ y: -2 }}
                        whileTap={{ scale: 0.92 }}
                        transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
                    >
                        <ChevronDown size={18} />
                    </motion.button>
                ) : null}
            </AnimatePresence>
        </div>
    );
};
