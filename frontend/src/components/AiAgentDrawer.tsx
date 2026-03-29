import React, { useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Archive, RotateCcw, Search, Trash2, Pencil, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { AiAgentHeader } from './AiAgentHeader';
import { AiAgentChat } from './AiAgentChat';
import { AiAgentNotificationCenter } from './AiAgentNotificationCenter';
import { AiAgentTimeline } from './AiAgentTimeline';
import { useAiAgent } from '../contexts/AiAgentContext';
import { useAiAgentSession } from '../hooks/useAiAgentSession';
import { useAiAgentNotifications } from '../hooks/useAiAgentNotifications';
import { useAiAgentStream } from '../hooks/useAiAgentStream';
import { useAiAgentNavigation } from '../hooks/useAiAgentNavigation';
import { useAgentRunStatus } from '../hooks/useAgentRunStatus';
import { agentApi, type AgentThread } from '../services/api';
import { useToast } from './Toast';

type TabKey = 'chat' | 'notifications' | 'timeline';
type ThreadView = 'active' | 'archived' | 'trash';

const THREAD_VIEW_LABELS: Record<ThreadView, string> = {
    active: 'Диалоги',
    archived: 'Архив',
    trash: 'Корзина',
};

const formatRetentionLabel = (thread: AgentThread) => {
    if (!thread.purge_after) return null;
    const diffMs = new Date(thread.purge_after).getTime() - Date.now();
    const daysLeft = Math.max(0, Math.ceil(diffMs / (24 * 60 * 60 * 1000)));
    return `Удаление через ${daysLeft} дн.`;
};

export const AiAgentDrawer: React.FC = () => {
    const { isOpen, closeAgent, activeThreadId, setActiveThreadId, pendingIntent, consumePendingIntent } = useAiAgent();
    const { showToast } = useToast();
    const queryClient = useQueryClient();
    const [activeTab, setActiveTab] = useState<TabKey>('chat');
    const [threadView, setThreadView] = useState<ThreadView>('active');
    const [search, setSearch] = useState('');
    const [prefillText, setPrefillText] = useState<string | null>(null);
    const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

    const session = useAiAgentSession(activeThreadId, setActiveThreadId, { view: threadView, search });
    const notifications = useAiAgentNotifications();
    const navigateToTarget = useAiAgentNavigation();
    const runStatus = useAgentRunStatus(session.runs);

    useAiAgentStream(activeThreadId, isOpen);

    useEffect(() => {
        if (!isOpen || !pendingIntent) return;
        setActiveTab('chat');
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

    const sortedThreads = useMemo(
        () => session.threads.slice().sort((a, b) => new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime()),
        [session.threads],
    );

    const handleNewThread = async () => {
        try {
            setThreadView('active');
            await session.createThread({ title: 'Новый диалог' });
            setActiveTab('chat');
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
            setActiveTab('notifications');
        } catch (error: any) {
            showToast('error', 'Не удалось открыть отчет', { details: error?.message || String(error) });
        }
    };

    const handleRenameThread = async (thread: AgentThread) => {
        const nextTitle = window.prompt('Новое название диалога', thread.title || '');
        if (!nextTitle || nextTitle.trim() === thread.title) return;
        try {
            await session.renameThreadMutation.mutateAsync({ threadId: thread.id, title: nextTitle.trim() });
        } catch (error: any) {
            showToast('error', 'Не удалось переименовать диалог', { details: error?.message || String(error) });
        }
    };

    const handleThreadAction = async (action: 'archive' | 'trash' | 'restore' | 'purge', threadId: string) => {
        try {
            if (action === 'archive') await session.archiveThreadMutation.mutateAsync(threadId);
            if (action === 'trash') await session.trashThreadMutation.mutateAsync(threadId);
            if (action === 'restore') await session.restoreThreadMutation.mutateAsync(threadId);
            if (action === 'purge') await session.purgeThreadMutation.mutateAsync(threadId);
        } catch (error: any) {
            showToast('error', 'Не удалось обновить диалог', { details: error?.message || String(error) });
        }
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-[65] flex justify-end">
            <button
                type="button"
                className="absolute inset-0 bg-black/30 backdrop-blur-[1px]"
                onClick={closeAgent}
                aria-label="Закрыть drawer AI-агента"
            />
            <div className="relative h-full w-full max-w-[1180px] bg-bg shadow-2xl border-l border-border flex motion-safe:animate-in motion-safe:slide-in-from-right motion-safe:fade-in duration-200">
                <div className={`${sidebarCollapsed ? 'w-[68px]' : 'w-[290px]'} border-r border-border bg-surface flex flex-col transition-all duration-200`}>
                    <AiAgentHeader title="AI-агент" onNewThread={handleNewThread} onClose={closeAgent} />
                    <div className="px-3 pt-3 flex items-center gap-2">
                        <button
                            type="button"
                            onClick={() => setSidebarCollapsed((current) => !current)}
                            className="rounded-md border border-border p-2 hover:bg-surface-2"
                            aria-label={sidebarCollapsed ? 'Показать список диалогов' : 'Свернуть список диалогов'}
                        >
                            {sidebarCollapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
                        </button>
                        {!sidebarCollapsed ? (
                            <label className="relative flex-1">
                                <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-foreground-secondary" />
                                <input
                                    value={search}
                                    onChange={(event) => setSearch(event.target.value)}
                                    className="w-full rounded-md border border-border bg-bg py-2 pl-8 pr-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                                    placeholder="Поиск по диалогам"
                                />
                            </label>
                        ) : null}
                    </div>
                    {!sidebarCollapsed ? (
                        <div className="px-3 pt-3 flex gap-2">
                            {(['active', 'archived', 'trash'] as ThreadView[]).map((view) => (
                                <button
                                    key={view}
                                    type="button"
                                    onClick={() => setThreadView(view)}
                                    className={`rounded-md px-2.5 py-1.5 text-xs font-medium ${
                                        threadView === view ? 'bg-primary text-white' : 'border border-border hover:bg-surface-2'
                                    }`}
                                >
                                    {THREAD_VIEW_LABELS[view]}
                                </button>
                            ))}
                        </div>
                    ) : null}
                    <div className="mt-3 flex-1 overflow-y-auto px-3 pb-3 space-y-2">
                        {sortedThreads.map((thread) => (
                            <div
                                key={thread.id}
                                className={`rounded-lg border ${
                                    activeThreadId === thread.id ? 'border-primary bg-primary-light text-primary' : 'border-border bg-bg hover:bg-surface-2'
                                }`}
                            >
                                <button
                                    type="button"
                                    onClick={() => {
                                        setActiveThreadId(thread.id);
                                        setActiveTab('chat');
                                    }}
                                    className="w-full px-3 py-2 text-left"
                                >
                                    <div className="text-sm font-medium truncate">{thread.title}</div>
                                    {!sidebarCollapsed ? (
                                        <>
                                            <div className="mt-1 text-xs text-foreground-secondary truncate">{thread.last_message_preview || thread.updated_at || thread.created_at || ''}</div>
                                            {thread.deleted_at ? (
                                                <div className="mt-1 text-[11px] text-warning">{formatRetentionLabel(thread)}</div>
                                            ) : null}
                                        </>
                                    ) : null}
                                </button>
                                {!sidebarCollapsed ? (
                                    <div className="flex items-center gap-1 border-t border-border/70 px-2 py-2">
                                        {threadView === 'active' ? (
                                            <>
                                                <button type="button" className="rounded p-1.5 hover:bg-surface" onClick={() => void handleRenameThread(thread)} title="Переименовать">
                                                    <Pencil className="h-3.5 w-3.5" />
                                                </button>
                                                <button type="button" className="rounded p-1.5 hover:bg-surface" onClick={() => void handleThreadAction('archive', thread.id)} title="Архивировать">
                                                    <Archive className="h-3.5 w-3.5" />
                                                </button>
                                                <button type="button" className="rounded p-1.5 hover:bg-surface" onClick={() => void handleThreadAction('trash', thread.id)} title="В корзину">
                                                    <Trash2 className="h-3.5 w-3.5" />
                                                </button>
                                            </>
                                        ) : null}
                                        {threadView === 'archived' ? (
                                            <>
                                                <button type="button" className="rounded p-1.5 hover:bg-surface" onClick={() => void handleThreadAction('restore', thread.id)} title="Вернуть в активные">
                                                    <RotateCcw className="h-3.5 w-3.5" />
                                                </button>
                                                <button type="button" className="rounded p-1.5 hover:bg-surface" onClick={() => void handleThreadAction('trash', thread.id)} title="В корзину">
                                                    <Trash2 className="h-3.5 w-3.5" />
                                                </button>
                                            </>
                                        ) : null}
                                        {threadView === 'trash' ? (
                                            <>
                                                <button type="button" className="rounded p-1.5 hover:bg-surface" onClick={() => void handleThreadAction('restore', thread.id)} title="Восстановить">
                                                    <RotateCcw className="h-3.5 w-3.5" />
                                                </button>
                                                <button type="button" className="rounded p-1.5 hover:bg-surface text-danger" onClick={() => void handleThreadAction('purge', thread.id)} title="Удалить навсегда">
                                                    <Trash2 className="h-3.5 w-3.5" />
                                                </button>
                                            </>
                                        ) : null}
                                    </div>
                                ) : null}
                            </div>
                        ))}
                        {!sortedThreads.length && !sidebarCollapsed ? (
                            <div className="rounded-lg border border-dashed border-border px-3 py-4 text-sm text-foreground-secondary">
                                В разделе «{THREAD_VIEW_LABELS[threadView]}» пока пусто.
                            </div>
                        ) : null}
                    </div>
                </div>
                <div className="flex-1 min-w-0 bg-bg">
                    <div className="border-b border-border px-4 py-3 flex gap-2">
                        {(['chat', 'notifications', 'timeline'] as TabKey[]).map((tab) => (
                            <button
                                key={tab}
                                type="button"
                                onClick={() => setActiveTab(tab)}
                                className={`rounded-md px-2.5 py-1.5 text-xs font-medium ${
                                    activeTab === tab ? 'bg-primary text-white' : 'border border-border hover:bg-surface-2'
                                }`}
                            >
                                {tab === 'chat' ? 'Чат' : tab === 'notifications' ? 'Уведомления' : 'Выполнение'}
                            </button>
                        ))}
                    </div>
                    {activeTab === 'chat' ? (
                        <AiAgentChat
                            messages={session.messages}
                            latestRun={runStatus.latestRun}
                            sendPending={session.sendMessageMutation.isPending}
                            confirmPending={false}
                            onSend={handleSend}
                            onNavigate={navigateToTarget}
                            onOpenReport={handleOpenReport}
                            onConfirmRun={async (runId) => {
                                try {
                                    await agentApi.confirmRun(runId);
                                    await Promise.all([
                                        queryClient.invalidateQueries({ queryKey: ['agent-thread', activeThreadId] }),
                                        queryClient.invalidateQueries({ queryKey: ['agent-threads'] }),
                                    ]);
                                } catch (error: any) {
                                    showToast('error', 'Не удалось подтвердить действие', { details: error?.message || String(error) });
                                }
                            }}
                            initialText={prefillText}
                        />
                    ) : activeTab === 'notifications' ? (
                        <AiAgentNotificationCenter
                            notifications={notifications.notifications}
                            reports={notifications.reports}
                            onRead={(notificationId) => void notifications.readMutation.mutate(notificationId)}
                            onReadAll={() => void notifications.readAllMutation.mutate()}
                            onClaim={(itemId) => void notifications.claimMutation.mutate(itemId)}
                            onRelease={(itemId) => void notifications.releaseMutation.mutate(itemId)}
                            onOpenReport={handleOpenReport}
                        />
                    ) : (
                        <div className="h-full overflow-y-auto p-4">
                            <AiAgentTimeline runs={session.runs} events={session.runEvents} />
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};
