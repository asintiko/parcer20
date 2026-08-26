import React, { useEffect, useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'motion/react';
import {
    Archive,
    ArrowLeft,
    Bell,
    Menu,
    Pencil,
    Plus,
    RotateCcw,
    Search,
    Sparkles,
    Trash2,
    X,
} from 'lucide-react';
import { AiAgentChat } from './AiAgentChat';
import { useAiAgent } from '../contexts/AiAgentContext';
import { useAiAgentSession } from '../hooks/useAiAgentSession';
import { useAiAgentNotifications } from '../hooks/useAiAgentNotifications';
import { useAiAgentStream } from '../hooks/useAiAgentStream';
import { useAiAgentNavigation } from '../hooks/useAiAgentNavigation';
import { useAgentRunStatus } from '../hooks/useAgentRunStatus';
import { agentApi, type AgentThread } from '../services/api';
import { useToast } from './Toast';
import { Dialog } from './motion/Dialog';
import { ConfirmDialog } from './motion/ConfirmDialog';
import '../styles/agent.css';

type ThreadView = 'active' | 'archived' | 'trash';

const THREAD_VIEW_LABELS: Record<ThreadView, string> = {
    active: 'Активные',
    archived: 'Архив',
    trash: 'Корзина',
};

const drawerOverlayVariants = {
    hidden: { opacity: 0 },
    visible: {
        opacity: 1,
        transition: { duration: 0.28, ease: [0.2, 0, 0, 1] as [number, number, number, number] },
    },
    exit: {
        opacity: 0,
        transition: { duration: 0.18, ease: [0.3, 0, 1, 1] as [number, number, number, number] },
    },
};

const drawerPanelVariants = {
    hidden: { x: '100%' },
    visible: {
        x: 0,
        transition: { duration: 0.42, ease: [0.05, 0.7, 0.1, 1] as [number, number, number, number] },
    },
    exit: {
        x: '100%',
        transition: { duration: 0.26, ease: [0.3, 0, 0.8, 0.15] as [number, number, number, number] },
    },
};

export const AiAgentDrawer: React.FC = () => {
    const { isOpen, closeAgent, activeThreadId, setActiveThreadId, pendingIntent, consumePendingIntent } = useAiAgent();
    const { showToast } = useToast();
    const queryClient = useQueryClient();
    const [sidebarOpen, setSidebarOpen] = useState(false);
    const [threadView, setThreadView] = useState<ThreadView>('active');
    const [search, setSearch] = useState('');
    const [prefillText, setPrefillText] = useState<string | null>(null);
    const [renameTarget, setRenameTarget] = useState<AgentThread | null>(null);
    const [renameValue, setRenameValue] = useState('');
    const [purgeTarget, setPurgeTarget] = useState<AgentThread | null>(null);

    const session = useAiAgentSession(activeThreadId, setActiveThreadId, { view: threadView, search });
    const notifications = useAiAgentNotifications();
    const navigateToTarget = useAiAgentNavigation();
    const runStatus = useAgentRunStatus(session.runs);

    const confirmRunMutation = useMutation({
        mutationFn: (runId: string) => agentApi.confirmRun(runId),
        onSuccess: async () => {
            await Promise.all([
                queryClient.invalidateQueries({ queryKey: ['agent-thread', activeThreadId] }),
                queryClient.invalidateQueries({ queryKey: ['agent-threads'] }),
            ]);
        },
        onError: (error: any) => {
            showToast('error', 'Не удалось подтвердить действие', { details: error?.message || String(error) });
        },
    });

    const rejectRunMutation = useMutation({
        mutationFn: (runId: string) => agentApi.rejectRun(runId),
        onSuccess: async () => {
            await Promise.all([
                queryClient.invalidateQueries({ queryKey: ['agent-thread', activeThreadId] }),
                queryClient.invalidateQueries({ queryKey: ['agent-threads'] }),
            ]);
        },
        onError: (error: any) => {
            showToast('error', 'Не удалось отклонить действие', { details: error?.message || String(error) });
        },
    });

    useAiAgentStream(activeThreadId, isOpen);

    useEffect(() => {
        if (!isOpen || !pendingIntent) return;
        setThreadView('active');
        if (pendingIntent.threadId) {
            setActiveThreadId(pendingIntent.threadId);
        }
        if (pendingIntent.systemMessage) {
            showToast('info', pendingIntent.systemMessage);
        }
        if (pendingIntent.starterText) {
            setPrefillText(pendingIntent.starterText);
            if (pendingIntent.requestedTool) {
                void session.sendMessage({
                    text: pendingIntent.starterText,
                    requestedTool: pendingIntent.requestedTool,
                }).catch((error: any) => {
                    showToast('error', 'Не удалось отправить запрос агенту', {
                        details: error?.message || String(error),
                    });
                });
                setPrefillText(null);
            }
        }
        consumePendingIntent();
    }, [consumePendingIntent, isOpen, pendingIntent, session, setActiveThreadId, showToast]);

    useEffect(() => {
        if (!isOpen || activeThreadId || !session.threads.length) return;
        setActiveThreadId(session.threads[0].id);
    }, [activeThreadId, isOpen, session.threads, setActiveThreadId]);

    useEffect(() => {
        if (!isOpen) return;
        const onKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                if (sidebarOpen) {
                    setSidebarOpen(false);
                } else {
                    closeAgent();
                }
            }
        };
        window.addEventListener('keydown', onKey);
        const prev = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        return () => {
            window.removeEventListener('keydown', onKey);
            document.body.style.overflow = prev;
        };
    }, [closeAgent, isOpen, sidebarOpen]);

    const sortedThreads = useMemo(
        () => session.threads.slice().sort((a, b) => new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime()),
        [session.threads],
    );

    const activeThread = useMemo(
        () => sortedThreads.find((t) => t.id === activeThreadId) || null,
        [sortedThreads, activeThreadId],
    );

    const unreadCount = notifications.notifications.filter((n) => !n.is_read).length;

    const handleNewThread = async () => {
        try {
            setThreadView('active');
            await session.createThread({ title: 'Новый диалог' });
            setSidebarOpen(false);
        } catch (error: any) {
            showToast('error', 'Не удалось создать диалог', { details: error?.message || String(error) });
        }
    };

    const handleSend = async ({ text, requestedTool }: { text: string; requestedTool?: string | null }) => {
        try {
            await session.sendMessage({ text, requestedTool });
            setPrefillText(null);
            setThreadView('active');
        } catch (error: any) {
            showToast('error', 'Не удалось отправить запрос агенту', { details: error?.message || String(error) });
            throw error;
        }
    };

    const handleOpenReport = async (reportId: string) => {
        try {
            const report = await agentApi.getReport(reportId);
            queryClient.setQueryData(['agent-reports'], (prev: any) => {
                if (!Array.isArray(prev)) return [report];
                const filtered = prev.filter((item: any) => item.id !== report.id);
                return [report, ...filtered];
            });
            showToast('success', 'Отчёт загружен');
        } catch (error: any) {
            showToast('error', 'Не удалось открыть отчет', { details: error?.message || String(error) });
        }
    };

    const handleRenameThread = (thread: AgentThread) => {
        setRenameTarget(thread);
        setRenameValue(thread.title || '');
    };

    const submitRenameThread = async () => {
        if (!renameTarget) return;
        const trimmed = renameValue.trim();
        if (!trimmed || trimmed === (renameTarget.title || '')) {
            setRenameTarget(null);
            return;
        }
        try {
            await session.renameThreadMutation.mutateAsync({ threadId: renameTarget.id, title: trimmed });
            setRenameTarget(null);
        } catch (error: any) {
            showToast('error', 'Не удалось переименовать диалог', { details: error?.message || String(error) });
        }
    };

    const handleThreadAction = async (action: 'archive' | 'trash' | 'restore' | 'purge', threadId: string) => {
        if (action === 'purge') {
            const target = sortedThreads.find((t) => t.id === threadId) || null;
            setPurgeTarget(target);
            return;
        }
        try {
            if (action === 'archive') await session.archiveThreadMutation.mutateAsync(threadId);
            if (action === 'trash') await session.trashThreadMutation.mutateAsync(threadId);
            if (action === 'restore') await session.restoreThreadMutation.mutateAsync(threadId);
        } catch (error: any) {
            showToast('error', 'Не удалось обновить диалог', { details: error?.message || String(error) });
        }
    };

    const submitPurgeThread = async () => {
        if (!purgeTarget) return;
        try {
            await session.purgeThreadMutation.mutateAsync(purgeTarget.id);
            setPurgeTarget(null);
        } catch (error: any) {
            showToast('error', 'Не удалось удалить диалог', { details: error?.message || String(error) });
        }
    };

    const formatThreadDate = (raw?: string | null) => {
        if (!raw) return '';
        const d = new Date(raw);
        if (Number.isNaN(d.getTime())) return '';
        const now = new Date();
        if (d.toDateString() === now.toDateString()) {
            return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
        }
        return d.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' });
    };

    return (
        <AnimatePresence>
            {isOpen ? (
                <div className="fixed inset-0 z-[var(--z-drawer,80)] flex justify-end" role="presentation">
                    <motion.div
                        className="absolute inset-0"
                        style={{
                            background: 'color-mix(in srgb, #000 28%, transparent)',
                            backdropFilter: 'blur(2px)',
                        }}
                        variants={drawerOverlayVariants}
                        initial="hidden"
                        animate="visible"
                        exit="exit"
                        onClick={closeAgent}
                        aria-hidden
                    />
                    <motion.aside
                        role="dialog"
                        aria-modal="true"
                        aria-label="AI-агент"
                        className="agent-shell"
                        style={{
                            position: 'relative',
                            width: 'min(640px, 100%)',
                            height: '100%',
                            boxShadow: '-32px 0 80px -24px rgba(0,0,0,0.32)',
                        }}
                        variants={drawerPanelVariants}
                        initial="hidden"
                        animate="visible"
                        exit="exit"
                    >
                        {/* Header — adapts to current pane */}
                        <div className="agent-head">
                            <button
                                type="button"
                                className="agent-icon-btn"
                                onClick={() => setSidebarOpen((v) => !v)}
                                aria-label={sidebarOpen ? 'К диалогу' : 'Все диалоги'}
                                title={sidebarOpen ? 'К диалогу' : 'Все диалоги'}
                            >
                                <AnimatePresence mode="wait" initial={false}>
                                    {sidebarOpen ? (
                                        <motion.span
                                            key="back"
                                            initial={{ opacity: 0, x: 4 }}
                                            animate={{ opacity: 1, x: 0 }}
                                            exit={{ opacity: 0, x: -4 }}
                                            transition={{ duration: 0.16, ease: [0.2, 0, 0, 1] }}
                                            style={{ display: 'inline-flex' }}
                                        >
                                            <ArrowLeft size={16} />
                                        </motion.span>
                                    ) : (
                                        <motion.span
                                            key="menu"
                                            initial={{ opacity: 0, x: -4 }}
                                            animate={{ opacity: 1, x: 0 }}
                                            exit={{ opacity: 0, x: 4 }}
                                            transition={{ duration: 0.16, ease: [0.2, 0, 0, 1] }}
                                            style={{ display: 'inline-flex' }}
                                        >
                                            <Menu size={16} />
                                        </motion.span>
                                    )}
                                </AnimatePresence>
                            </button>
                            <div className="agent-head-text">
                                <div className="agent-eyebrow">
                                    <Sparkles size={10} style={{ display: 'inline', verticalAlign: '-1px', marginRight: 4 }} />
                                    {sidebarOpen ? 'История' : 'AI-агент'}
                                </div>
                                <h2 className="agent-title">
                                    {sidebarOpen
                                        ? `Диалоги · ${THREAD_VIEW_LABELS[threadView]}`
                                        : activeThread?.title || 'Новый диалог'}
                                </h2>
                            </div>
                            <div className="agent-head-actions">
                                <button
                                    type="button"
                                    className="agent-icon-btn"
                                    onClick={handleNewThread}
                                    aria-label="Новый диалог"
                                    title="Новый диалог"
                                >
                                    <Plus size={16} />
                                </button>
                                <button
                                    type="button"
                                    className="agent-icon-btn"
                                    aria-label={`Уведомления (${unreadCount})`}
                                    title="Уведомления"
                                >
                                    <Bell size={16} />
                                    {unreadCount > 0 ? (
                                        <span className="agent-icon-btn-badge">
                                            {unreadCount > 99 ? '99+' : unreadCount}
                                        </span>
                                    ) : null}
                                </button>
                                <button
                                    type="button"
                                    className="agent-icon-btn"
                                    onClick={closeAgent}
                                    aria-label="Закрыть"
                                    title="Закрыть"
                                >
                                    <X size={16} />
                                </button>
                            </div>
                        </div>

                        {/* Pane track: chat (left) + history (right) */}
                        <div className="agent-pane-viewport">
                            <motion.div
                                className="agent-pane-track"
                                animate={{ x: sidebarOpen ? '-50%' : '0%' }}
                                transition={{
                                    type: 'spring',
                                    stiffness: 380,
                                    damping: 38,
                                    mass: 0.9,
                                }}
                            >
                                <div
                                    className="agent-pane agent-pane-chat"
                                    aria-hidden={sidebarOpen}
                                    {...(sidebarOpen ? { inert: '' as any } : {})}
                                >
                                    <AiAgentChat
                                        messages={session.messages}
                                        latestRun={runStatus.latestRun}
                                        runEvents={session.runEvents}
                                        sendPending={session.sendMessageMutation.isPending}
                                        confirmPending={confirmRunMutation.isPending}
                                        rejectPending={rejectRunMutation.isPending}
                                        onSend={handleSend}
                                        onNavigate={navigateToTarget}
                                        onOpenReport={handleOpenReport}
                                        onConfirmRun={(runId) => confirmRunMutation.mutate(runId)}
                                        onRejectRun={(runId) => rejectRunMutation.mutate(runId)}
                                        initialText={prefillText}
                                    />
                                </div>
                                <div
                                    className="agent-pane agent-pane-history"
                                    aria-hidden={!sidebarOpen}
                                    {...(!sidebarOpen ? { inert: '' as any } : {})}
                                >
                                    <div className="agent-history">
                                        <div className="agent-history-search">
                                            <Search size={13} className="agent-history-search-icon" />
                                            <input
                                                type="text"
                                                value={search}
                                                onChange={(e) => setSearch(e.target.value)}
                                                placeholder="Поиск по диалогам"
                                                className="agent-history-search-input"
                                            />
                                        </div>
                                        <div className="agent-history-views">
                                            {(['active', 'archived', 'trash'] as ThreadView[]).map((view) => (
                                                <button
                                                    key={view}
                                                    type="button"
                                                    className={`agent-history-view-btn${threadView === view ? ' is-active' : ''}`}
                                                    onClick={() => setThreadView(view)}
                                                >
                                                    {THREAD_VIEW_LABELS[view]}
                                                </button>
                                            ))}
                                        </div>
                                        <div className="agent-history-list">
                                            {sortedThreads.length === 0 ? (
                                                <div className="agent-history-empty">
                                                    {threadView === 'active'
                                                        ? 'Активных диалогов нет'
                                                        : threadView === 'archived'
                                                        ? 'Архив пуст'
                                                        : 'Корзина пуста'}
                                                </div>
                                            ) : (
                                                sortedThreads.map((thread) => (
                                                    <div
                                                        key={thread.id}
                                                        className={`agent-thread${activeThreadId === thread.id ? ' is-active' : ''}`}
                                                    >
                                                        <button
                                                            type="button"
                                                            className="agent-thread-button"
                                                            onClick={() => {
                                                                setActiveThreadId(thread.id);
                                                                setSidebarOpen(false);
                                                            }}
                                                        >
                                                            <div className="agent-thread-title">
                                                                {thread.title || 'Без названия'}
                                                            </div>
                                                            <div className="agent-thread-meta">
                                                                {thread.last_message_preview ||
                                                                    formatThreadDate(thread.updated_at) ||
                                                                    formatThreadDate(thread.created_at) ||
                                                                    ''}
                                                            </div>
                                                        </button>
                                                        <div className="agent-thread-actions">
                                                            {threadView === 'active' ? (
                                                                <>
                                                                    <button
                                                                        type="button"
                                                                        className="agent-icon-btn"
                                                                        onClick={() => handleRenameThread(thread)}
                                                                        title="Переименовать"
                                                                        aria-label="Переименовать"
                                                                    >
                                                                        <Pencil size={13} />
                                                                    </button>
                                                                    <button
                                                                        type="button"
                                                                        className="agent-icon-btn"
                                                                        onClick={() => handleThreadAction('archive', thread.id)}
                                                                        title="В архив"
                                                                        aria-label="В архив"
                                                                    >
                                                                        <Archive size={13} />
                                                                    </button>
                                                                    <button
                                                                        type="button"
                                                                        className="agent-icon-btn"
                                                                        onClick={() => handleThreadAction('trash', thread.id)}
                                                                        title="В корзину"
                                                                        aria-label="В корзину"
                                                                    >
                                                                        <Trash2 size={13} />
                                                                    </button>
                                                                </>
                                                            ) : null}
                                                            {threadView === 'archived' ? (
                                                                <>
                                                                    <button
                                                                        type="button"
                                                                        className="agent-icon-btn"
                                                                        onClick={() => handleThreadAction('restore', thread.id)}
                                                                        title="Восстановить"
                                                                        aria-label="Восстановить"
                                                                    >
                                                                        <RotateCcw size={13} />
                                                                    </button>
                                                                    <button
                                                                        type="button"
                                                                        className="agent-icon-btn"
                                                                        onClick={() => handleThreadAction('trash', thread.id)}
                                                                        title="В корзину"
                                                                        aria-label="В корзину"
                                                                    >
                                                                        <Trash2 size={13} />
                                                                    </button>
                                                                </>
                                                            ) : null}
                                                            {threadView === 'trash' ? (
                                                                <>
                                                                    <button
                                                                        type="button"
                                                                        className="agent-icon-btn"
                                                                        onClick={() => handleThreadAction('restore', thread.id)}
                                                                        title="Восстановить"
                                                                        aria-label="Восстановить"
                                                                    >
                                                                        <RotateCcw size={13} />
                                                                    </button>
                                                                    <button
                                                                        type="button"
                                                                        className="agent-icon-btn"
                                                                        style={{ color: 'var(--danger)' }}
                                                                        onClick={() => handleThreadAction('purge', thread.id)}
                                                                        title="Удалить навсегда"
                                                                        aria-label="Удалить навсегда"
                                                                    >
                                                                        <Trash2 size={13} />
                                                                    </button>
                                                                </>
                                                            ) : null}
                                                        </div>
                                                    </div>
                                                ))
                                            )}
                                        </div>
                                    </div>
                                </div>
                            </motion.div>
                        </div>
                    </motion.aside>

                    {/* Rename modal */}
                    <Dialog
                        open={Boolean(renameTarget)}
                        onClose={() => setRenameTarget(null)}
                        title="Переименовать диалог"
                        description="Дайте диалогу понятное имя."
                        width={420}
                        footer={
                            <>
                                <span className="sp-spacer" />
                                <button
                                    type="button"
                                    className="agent-btn"
                                    onClick={() => setRenameTarget(null)}
                                >
                                    Отмена
                                </button>
                                <button
                                    type="button"
                                    className="agent-btn agent-btn-primary"
                                    onClick={() => void submitRenameThread()}
                                    disabled={
                                        session.renameThreadMutation.isPending ||
                                        !renameValue.trim() ||
                                        renameValue.trim() === (renameTarget?.title || '')
                                    }
                                >
                                    {session.renameThreadMutation.isPending ? 'Сохраняю…' : 'Сохранить'}
                                </button>
                            </>
                        }
                    >
                        <input
                            type="text"
                            value={renameValue}
                            autoFocus
                            onChange={(e) => setRenameValue(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                    e.preventDefault();
                                    void submitRenameThread();
                                }
                            }}
                            className="tx-field-input"
                            placeholder="Название диалога"
                            style={{ marginTop: 4 }}
                        />
                    </Dialog>

                    {/* Purge confirm */}
                    <ConfirmDialog
                        open={Boolean(purgeTarget)}
                        title={`Удалить «${purgeTarget?.title || 'без названия'}»?`}
                        description="Диалог удалится навсегда. Действие нельзя отменить."
                        confirmLabel="Удалить навсегда"
                        cancelLabel="Отмена"
                        tone="danger"
                        onConfirm={submitPurgeThread}
                        onClose={() => setPurgeTarget(null)}
                    />
                </div>
            ) : null}
        </AnimatePresence>
    );
};
