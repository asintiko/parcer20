import React, { useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence, type Variants } from 'motion/react';
import { ChevronRight, Send } from 'lucide-react';
import type { AgentLocateResult, AgentMessage, AgentRun, AgentRunEvent } from '../services/api';
import { AiAgentMessage } from './AiAgentMessage';
import { formatRunEventLabel, formatRunStatus, formatRunStep, formatToolLabel } from '../utils/aiAgentDisplay';

const emptyContainerVariants: Variants = {
    hidden: { opacity: 0 },
    visible: {
        opacity: 1,
        transition: {
            duration: 0.32,
            ease: [0.2, 0, 0, 1],
            staggerChildren: 0.06,
            delayChildren: 0.08,
        },
    },
};

const emptyItemVariants: Variants = {
    hidden: { opacity: 0, y: 10 },
    visible: {
        opacity: 1,
        y: 0,
        transition: { duration: 0.32, ease: [0.2, 0, 0, 1] },
    },
};

const tileVariants: Variants = {
    hidden: { opacity: 0, y: 12, scale: 0.98 },
    visible: {
        opacity: 1,
        y: 0,
        scale: 1,
        transition: { duration: 0.34, ease: [0.16, 1, 0.3, 1] },
    },
};

const QUICK_TILES: Array<{
    id: string;
    eyebrow: string;
    title: string;
    desc: string;
    prompt: string;
    tool: string;
}> = [
    {
        id: 'mapping',
        eyebrow: '01',
        title: 'Сопоставление',
        desc: 'Подобрать приложения для непривязанных операций.',
        prompt: 'Проведи сопоставление приложений и покажи элементы, которые ждут проверки',
        tool: 'app_mapping',
    },
    {
        id: 'verify',
        eyebrow: '02',
        title: 'Проверка',
        desc: 'Найти проблемные транзакции и собрать гипотезы.',
        prompt: 'Проведи проверку проблемных транзакций',
        tool: 'data_verification',
    },
    {
        id: 'reconcile',
        eyebrow: '03',
        title: 'Сверка',
        desc: 'Сравнить Telegram-историю и базу транзакций.',
        prompt: 'Запусти сверку Telegram истории и локальной базы',
        tool: 'bot_reconciliation',
    },
    {
        id: 'report',
        eyebrow: '04',
        title: 'Недельный отчёт',
        desc: 'Собрать итоги по неделе с разбором источников.',
        prompt: 'Собери недельный отчет по системе',
        tool: 'report_builder',
    },
];

const formatElapsedSeconds = (run?: AgentRun | null) => {
    if (!run?.created_at) return '';
    const start = new Date(run.created_at).getTime();
    const isFinished = run.status === 'completed' || run.status === 'failed' || run.status === 'cancelled';
    const end = isFinished && run.updated_at ? new Date(run.updated_at).getTime() : Date.now();
    const seconds = Math.max(0, Math.round((end - start) / 100) / 10);
    return seconds < 60 ? `${seconds.toFixed(1)}s` : `${Math.round(seconds / 60)}m ${Math.round(seconds % 60)}s`;
};

interface AiAgentChatProps {
    messages: AgentMessage[];
    latestRun: AgentRun | null;
    runEvents: AgentRunEvent[];
    sendPending?: boolean;
    confirmPending?: boolean;
    rejectPending?: boolean;
    onSend: (payload: { text: string; requestedTool?: string | null }) => Promise<void>;
    onNavigate: (target: AgentLocateResult) => void;
    onOpenReport: (reportId: string) => void;
    onConfirmRun: (runId: string) => void;
    onRejectRun?: (runId: string) => void;
    initialText?: string | null;
}

export const AiAgentChat: React.FC<AiAgentChatProps> = ({
    messages,
    latestRun,
    runEvents,
    sendPending,
    confirmPending,
    rejectPending,
    onSend,
    onNavigate,
    onOpenReport,
    onConfirmRun,
    onRejectRun,
    initialText,
}) => {
    const [draft, setDraft] = useState('');
    const [timelineOpen, setTimelineOpen] = useState(false);
    const scrollContainerRef = useRef<HTMLDivElement | null>(null);
    const textareaRef = useRef<HTMLTextAreaElement | null>(null);

    useEffect(() => {
        if (initialText) setDraft(initialText);
    }, [initialText]);

    const normalizedMessages = useMemo(
        () =>
            messages.slice().sort((a, b) => {
                const left = new Date(a.created_at || 0).getTime();
                const right = new Date(b.created_at || 0).getTime();
                return left - right;
            }),
        [messages],
    );

    const isRunning = latestRun?.status === 'queued' || latestRun?.status === 'processing';
    const isAwaiting = latestRun?.status === 'awaiting_confirmation';
    const showTimeline = isRunning || isAwaiting;

    const progressLabel = useMemo(() => {
        if (sendPending) return 'Отправляю запрос…';
        if (!latestRun) return '';
        if (isAwaiting) return 'Ждёт подтверждения';
        return formatRunStep(String(latestRun?.progress?.step || ''), latestRun?.tool_name);
    }, [isAwaiting, latestRun, sendPending]);

    const totalSteps = Number(latestRun?.progress?.total ?? 0);
    const currentStep = Number(latestRun?.progress?.current ?? 0);
    const progressPct = totalSteps > 0 ? Math.min(100, Math.round((currentStep / totalSteps) * 100)) : isRunning ? 35 : 100;

    useEffect(() => {
        const node = scrollContainerRef.current;
        if (!node) return;
        node.scrollTop = node.scrollHeight;
    }, [normalizedMessages.length, isRunning, sendPending]);

    useEffect(() => {
        const el = textareaRef.current;
        if (!el) return;
        el.style.height = 'auto';
        el.style.height = `${Math.min(160, el.scrollHeight)}px`;
    }, [draft]);

    const handleSubmit = React.useCallback(async () => {
        const text = draft.trim();
        if (!text || sendPending) return;
        await onSend({ text });
        setDraft('');
    }, [draft, onSend, sendPending]);

    const handleQuickTile = (tile: (typeof QUICK_TILES)[number]) => {
        void onSend({ text: tile.prompt, requestedTool: tile.tool }).catch(() => undefined);
    };

    const filteredEvents = runEvents
        .filter((evt) => !latestRun || evt.run_id === latestRun.id)
        .slice(-8);

    const isEmpty = normalizedMessages.length === 0 && !sendPending && !isRunning;

    return (
        <div className="agent-chat">
            <div ref={scrollContainerRef} className="agent-stream">
                {isEmpty ? (
                    <motion.div
                        className="agent-empty"
                        variants={emptyContainerVariants}
                        initial="hidden"
                        animate="visible"
                    >
                        <motion.div className="agent-empty-eyebrow" variants={emptyItemVariants}>
                            AI · АГЕНТ
                        </motion.div>
                        <motion.h3 className="agent-empty-title" variants={emptyItemVariants}>
                            С чего начнём?
                        </motion.h3>
                        <motion.div className="agent-empty-sub" variants={emptyItemVariants}>
                            Запустите типовой сценарий или сформулируйте запрос своими словами.
                        </motion.div>
                        <motion.div className="agent-empty-grid" variants={emptyItemVariants}>
                            {QUICK_TILES.map((tile) => (
                                <motion.button
                                    key={tile.id}
                                    type="button"
                                    className="agent-empty-tile"
                                    variants={tileVariants}
                                    whileHover={{ y: -1, transition: { duration: 0.16, ease: [0.2, 0, 0, 1] } }}
                                    whileTap={{ scale: 0.985, transition: { duration: 0.1, ease: [0.4, 0, 1, 1] } }}
                                    onClick={() => handleQuickTile(tile)}
                                >
                                    <div className="agent-empty-tile-eyebrow">{tile.eyebrow}</div>
                                    <div className="agent-empty-tile-title">{tile.title}</div>
                                    <div className="agent-empty-tile-desc">{tile.desc}</div>
                                </motion.button>
                            ))}
                        </motion.div>
                    </motion.div>
                ) : (
                    normalizedMessages.map((message) => (
                        <AiAgentMessage
                            key={message.id}
                            message={message}
                            latestRun={latestRun}
                            onNavigate={onNavigate}
                            onOpenReport={onOpenReport}
                            onConfirmRun={onConfirmRun}
                            onRejectRun={onRejectRun}
                            confirmPending={confirmPending}
                            rejectPending={rejectPending}
                        />
                    ))
                )}

                <AnimatePresence>
                    {(sendPending || isRunning) && !isEmpty ? (
                        <motion.div
                            className="agent-working"
                            initial={{ opacity: 0, y: 6 }}
                            animate={{ opacity: 1, y: 0, transition: { duration: 0.24, ease: [0.2, 0, 0, 1] } }}
                            exit={{ opacity: 0, transition: { duration: 0.16, ease: [0.3, 0, 1, 1] } }}
                        >
                            <div className="agent-working-dots" aria-hidden>
                                <span className="agent-working-dot" />
                                <span className="agent-working-dot" />
                                <span className="agent-working-dot" />
                            </div>
                            <div className="agent-working-eyebrow">{progressLabel || 'Думаю'}</div>
                        </motion.div>
                    ) : null}
                </AnimatePresence>
            </div>

            {/* Timeline collapsible */}
            <AnimatePresence initial={false}>
                {showTimeline ? (
                    <motion.div
                        className="agent-timeline"
                        initial={{ opacity: 0, y: 6 }}
                        animate={{
                            opacity: 1,
                            y: 0,
                            transition: { duration: 0.26, ease: [0.3, 0, 0, 1] },
                        }}
                        exit={{
                            opacity: 0,
                            y: 6,
                            transition: { duration: 0.18, ease: [0.3, 0, 1, 1] },
                        }}
                    >
                        <button
                            type="button"
                            className={`agent-timeline-head${timelineOpen ? ' is-open' : ''}`}
                            onClick={() => setTimelineOpen((open) => !open)}
                            aria-expanded={timelineOpen}
                            aria-label={timelineOpen ? 'Свернуть выполнение' : 'Развернуть выполнение'}
                        >
                            <ChevronRight size={14} className="agent-timeline-chevron" />
                            <span className="agent-timeline-eyebrow">Выполнение</span>
                            <span className="agent-timeline-step">
                                {progressLabel ||
                                    formatRunStatus(latestRun?.status) ||
                                    formatToolLabel(latestRun?.tool_name)}
                            </span>
                            {totalSteps > 0 ? (
                                <span
                                    className="agent-timeline-elapsed"
                                    aria-label={`Шаг ${currentStep} из ${totalSteps}`}
                                >
                                    {currentStep}/{totalSteps}
                                </span>
                            ) : null}
                            <div className="agent-timeline-progress" aria-hidden>
                                <div
                                    className="agent-timeline-progress-fill"
                                    style={{ width: `${progressPct}%` }}
                                />
                            </div>
                            <span className="agent-timeline-elapsed">
                                {formatElapsedSeconds(latestRun)}
                            </span>
                        </button>
                        <div
                            className={`agent-timeline-body-wrap${timelineOpen ? ' is-open' : ''}`}
                            aria-hidden={!timelineOpen}
                        >
                            <div className="agent-timeline-body">
                                {filteredEvents.length === 0 ? (
                                    <div className="agent-timeline-event">
                                        <span className="agent-timeline-event-dot is-active" />
                                        <span className="agent-timeline-event-text">
                                            Готовим выполнение…
                                        </span>
                                    </div>
                                ) : (
                                    filteredEvents.map((evt, i) => {
                                        const isLast = i === filteredEvents.length - 1;
                                        const status =
                                            evt.event_type === 'completed' ||
                                            evt.event_type === 'tool_finished'
                                                ? 'is-done'
                                                : evt.event_type === 'failed'
                                                ? 'is-failed'
                                                : isLast && isRunning
                                                ? 'is-active'
                                                : 'is-done';
                                        return (
                                            <div
                                                key={evt.id || `${evt.event_type}-${i}`}
                                                className={`agent-timeline-event ${status}`}
                                            >
                                                <span
                                                    className={`agent-timeline-event-dot ${status}`}
                                                />
                                                <span className="agent-timeline-event-time">
                                                    {evt.created_at
                                                        ? new Date(evt.created_at).toLocaleTimeString(
                                                              'ru-RU',
                                                              {
                                                                  hour: '2-digit',
                                                                  minute: '2-digit',
                                                                  second: '2-digit',
                                                              },
                                                          )
                                                        : ''}
                                                </span>
                                                <span className="agent-timeline-event-text">
                                                    {formatRunEventLabel(
                                                        evt.event_type,
                                                        evt.label,
                                                        latestRun?.tool_name,
                                                    )}
                                                </span>
                                            </div>
                                        );
                                    })
                                )}
                            </div>
                        </div>
                    </motion.div>
                ) : null}
            </AnimatePresence>

            {/* Composer */}
            <div className="agent-composer">
                <form
                    className="agent-composer-form"
                    onSubmit={(event) => {
                        event.preventDefault();
                        void handleSubmit().catch(() => undefined);
                    }}
                >
                    <textarea
                        ref={textareaRef}
                        value={draft}
                        onChange={(event) => setDraft(event.target.value)}
                        onKeyDown={(event) => {
                            if (event.key === 'Enter' && !event.shiftKey) {
                                event.preventDefault();
                                void handleSubmit().catch(() => undefined);
                            }
                        }}
                        rows={1}
                        className="agent-composer-textarea"
                        placeholder="Напишите запрос или задайте вопрос…"
                    />
                    <motion.button
                        type="submit"
                        className="agent-send-btn"
                        disabled={sendPending || !draft.trim()}
                        aria-label="Отправить"
                        animate={{
                            scale: !draft.trim() || sendPending ? 0.92 : 1,
                            opacity: !draft.trim() || sendPending ? 0.45 : 1,
                        }}
                        transition={{ duration: 0.18, ease: [0.2, 0, 0, 1] }}
                        whileTap={!draft.trim() || sendPending ? undefined : { scale: 0.88, transition: { duration: 0.1 } }}
                    >
                        <Send size={14} />
                    </motion.button>
                </form>
                <div className="agent-composer-hints">
                    <span><kbd>Enter</kbd>отправить</span>
                    <span><kbd>Shift</kbd>+<kbd>Enter</kbd>перенос строки</span>
                </div>
            </div>
        </div>
    );
};
