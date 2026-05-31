import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'motion/react';
import { Phone, Lock, Unlock, KeyRound, Plug, PlugZap, AlertOctagon, Eye, EyeOff, ScanLine, CheckSquare, ArrowRight, Loader2, AlertCircle } from 'lucide-react';
import { telegramClientApi, type TelegramChat, type TelegramChatMessage } from '../services/api';
import { useToast } from '../components/Toast';
import { useHiddenChatsOverlay } from '../hooks/useHiddenChatsOverlay';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import { ChatList, type ChatFilter } from '../components/telegram/ChatList';
import { ChatHeader, type DateRange } from '../components/telegram/ChatHeader';
import { MessageStream } from '../components/telegram/MessageStream';
import { MessageInput } from '../components/telegram/MessageInput';
import { EmptyState } from '../components/telegram/EmptyState';
import { BulkBar } from '../components/telegram/BulkBar';
import { ContextMenu, type ContextMenuItem } from '../components/telegram/ContextMenu';
import { PasswordDialog } from '../components/telegram/PasswordDialog';
import '../styles/telegram.css';

type AuthStep = 'phone' | 'code' | 'password';

interface AuthCardProps {
    step: AuthStep;
    busy: boolean;
    error: string | null;
    onPhone: (v: string) => void;
    onCode: (v: string) => void;
    onPassword: (v: string) => void;
}

const AuthCard: React.FC<AuthCardProps> = ({ step, busy, error, onPhone, onCode, onPassword }) => {
    const [value, setValue] = useState('');
    useEffect(() => { setValue(''); }, [step]);
    const submit = () => {
        const v = value.trim();
        if (!v) return;
        if (step === 'phone') onPhone(v);
        else if (step === 'code') onCode(v);
        else if (step === 'password') onPassword(v);
    };
    const meta = step === 'phone'
        ? { title: 'Введите номер телефона', sub: 'Отправим код в приложение Telegram. Например: +79991234567', placeholder: '+79991234567', icon: <Phone size={20} />, type: 'tel' as const, eyebrow: '01 / Авторизация' }
        : step === 'code'
            ? { title: 'Шестизначный код', sub: 'Telegram отправил код подтверждения в приложение.', placeholder: '12345', icon: <KeyRound size={20} />, type: 'text' as const, eyebrow: '02 / Подтверждение' }
            : { title: 'Облачный пароль', sub: 'Двухфакторный пароль вашего аккаунта Telegram.', placeholder: '••••••••', icon: <Lock size={20} />, type: 'password' as const, eyebrow: '03 / Защита' };

    return (
        <div className="tg-auth">
            <AnimatePresence mode="wait" initial={false}>
                <motion.div
                    key={step}
                    className="tg-auth-card"
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -6 }}
                    transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
                >
                    <div className="tg-auth-eyebrow">
                        <span className="tg-auth-eyebrow-dot" />
                        {meta.eyebrow}
                    </div>
                    <div className="tg-auth-icon">{meta.icon}</div>
                    <h2 className="tg-auth-title">{meta.title}</h2>
                    <p className="tg-auth-sub">{meta.sub}</p>
                    <input
                        className="tg-auth-input"
                        type={meta.type}
                        placeholder={meta.placeholder}
                        value={value}
                        onChange={(e) => setValue(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); submit(); } }}
                        autoFocus
                    />
                    <AnimatePresence>
                        {error ? (
                            <motion.div
                                key="auth-err"
                                className="tg-auth-error"
                                initial={{ opacity: 0, y: -4 }}
                                animate={{ opacity: 1, y: 0 }}
                                exit={{ opacity: 0 }}
                                transition={{ duration: 0.16 }}
                            >
                                <AlertCircle size={13} />
                                {error}
                            </motion.div>
                        ) : null}
                    </AnimatePresence>
                    <button type="button" className="tg-auth-btn" onClick={submit} disabled={busy || !value.trim()}>
                        {busy ? (
                            <>
                                <Loader2 size={14} className="tg-msg-process-spin" />
                                Отправляем…
                            </>
                        ) : (
                            <>
                                Продолжить
                                <ArrowRight size={14} />
                            </>
                        )}
                    </button>
                    <div className="tg-auth-foot">
                        <span>Telegram · TDLib</span>
                        <span>Enter ↵</span>
                    </div>
                </motion.div>
            </AnimatePresence>
        </div>
    );
};

const StatusBoard: React.FC<{ title: string; sub: string; tone?: 'idle' | 'error' | 'connecting' }> = ({ title, sub, tone = 'idle' }) => {
    const Icon = tone === 'error' ? AlertOctagon : tone === 'connecting' ? PlugZap : Plug;
    return (
        <div className="tg-auth">
            <motion.div
                className="tg-auth-card"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
            >
                <div className="tg-auth-eyebrow">
                    <span
                        className="tg-auth-eyebrow-dot"
                        style={{
                            background: tone === 'error' ? 'var(--danger)' : tone === 'connecting' ? 'var(--warning)' : 'var(--text-muted)',
                        }}
                    />
                    {tone === 'error' ? 'Сервис' : tone === 'connecting' ? 'Подключение' : 'Статус'}
                </div>
                <div className="tg-auth-icon" style={{ background: tone === 'error' ? 'var(--danger)' : 'var(--text)' }}>
                    {tone === 'connecting' ? (
                        <Loader2 size={20} className="tg-msg-process-spin" />
                    ) : (
                        <Icon size={20} />
                    )}
                </div>
                <h2 className="tg-auth-title">{title}</h2>
                <p className="tg-auth-sub">{sub}</p>
            </motion.div>
        </div>
    );
};

type ContextTarget =
    | { kind: 'chat'; chat: TelegramChat }
    | { kind: 'message'; message: TelegramChatMessage }
    | null;

type PasswordDialogState =
    | { open: false }
    | { open: true; chat: TelegramChat; mode: 'set' | 'remove' };

export const UserbotPage: React.FC = () => {
    const queryClient = useQueryClient();
    const { showToast } = useToast();
    const [activeChatId, setActiveChatId] = useState<number | null>(null);
    const [authError, setAuthError] = useState<string | null>(null);
    const [filter, setFilter] = useState<ChatFilter>('active');

    // Selection mode
    const [selectionMode, setSelectionMode] = useState(false);
    const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
    const [processingIds, setProcessingIds] = useState<Set<number>>(new Set());
    const [processedIds, setProcessedIds] = useState<Set<number>>(new Set());
    const [failedIds, setFailedIds] = useState<Set<number>>(new Set());
    const [bulkBusy, setBulkBusy] = useState(false);
    const [bulkStats, setBulkStats] = useState<{ processed: number; failed: number; total: number }>({
        processed: 0,
        failed: 0,
        total: 0,
    });

    // Date range
    const [dateRange, setDateRange] = useState<DateRange>({});

    // Scroll-to-bottom trigger (incremented after explicit user actions like send)
    const [forceScrollKey, setForceScrollKey] = useState(0);

    // Context menu
    const [contextTarget, setContextTarget] = useState<ContextTarget>(null);
    const [contextPos, setContextPos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

    // Password dialog
    const [passwordDialog, setPasswordDialog] = useState<PasswordDialogState>({ open: false });

    // Auth status
    const statusQuery = useQuery({
        queryKey: ['tg-status'],
        queryFn: telegramClientApi.getStatus,
        refetchInterval: (q) => {
            const data: any = q.state.data;
            if (!data) return 5000;
            return data.state === 'ready' ? 30000 : 4000;
        },
    });

    const ready = statusQuery.data?.state === 'ready';
    const rawState = statusQuery.data?.state;

    // Chats
    const chatsQuery = useQuery({
        queryKey: ['tg-chats'],
        queryFn: () => telegramClientApi.getChats({ limit: 200, include_hidden: true }),
        enabled: ready,
        refetchInterval: 15000,
    });

    const { chats, setHidden: setHiddenOverlay, acknowledge: acknowledgeHidden, rollback: rollbackHidden } =
        useHiddenChatsOverlay(chatsQuery.data?.items, 'sandbox');
    const activeChat = useMemo(
        () => chats.find((c) => c.chat_id === activeChatId) || null,
        [chats, activeChatId],
    );

    // Auto-select first visible chat
    useEffect(() => {
        if (!ready || activeChatId) return;
        const visible = chats.filter((c) => filter === 'all' ? true : filter === 'active' ? !c.is_hidden : c.is_hidden);
        if (visible.length > 0) {
            setActiveChatId(visible[0].chat_id);
        }
    }, [ready, activeChatId, chats, filter]);

    // Reset selection when chat changes
    useEffect(() => {
        setSelectionMode(false);
        setSelectedIds(new Set());
        setDateRange({});
    }, [activeChatId]);

    // Messages
    const messagesQuery = useQuery({
        queryKey: ['tg-messages', activeChatId],
        queryFn: () => telegramClientApi.getMessages(activeChatId!, { limit: 100 }),
        enabled: ready && Boolean(activeChatId),
        refetchInterval: 6000,
    });

    const allMessages: TelegramChatMessage[] = useMemo(() => {
        const items = messagesQuery.data?.items || [];
        // Backend (TDLib getChatHistory) returns newest-first. The chat view
        // expects oldest-on-top / newest-on-bottom (Telegram-style). Sort by
        // date ascending; fall back to numeric `id` for items without date so
        // the order stays stable.
        const sortable = items.slice();
        sortable.sort((a, b) => {
            const ta = a.date ? new Date(a.date).getTime() : Number(a.id || 0);
            const tb = b.date ? new Date(b.date).getTime() : Number(b.id || 0);
            if (ta !== tb) return ta - tb;
            return Number(a.id || 0) - Number(b.id || 0);
        });
        return sortable;
    }, [messagesQuery.data?.items]);
    const messages = useMemo(() => {
        if (!dateRange.from && !dateRange.to) return allMessages;
        const fromTs = dateRange.from ? new Date(dateRange.from).getTime() : -Infinity;
        const toTs = dateRange.to ? new Date(dateRange.to).getTime() + 24 * 3600 * 1000 : Infinity;
        return allMessages.filter((m) => {
            if (!m.date) return true;
            const ts = new Date(m.date).getTime();
            return ts >= fromTs && ts <= toTs;
        });
    }, [allMessages, dateRange]);

    // Merge server-side processed status (DB-derived) with local optimistic ids.
    // Server payload from /api/tg/chats/{id}/messages now includes `processed`,
    // `processed_status`, `transaction_id` — we trust those on first paint.
    const effectiveProcessedIds = useMemo(() => {
        const out = new Set(processedIds);
        for (const m of allMessages) {
            if (m.id != null && m.processed === true) out.add(m.id);
        }
        return out;
    }, [allMessages, processedIds]);

    const effectiveFailedIds = useMemo(() => {
        const out = new Set(failedIds);
        for (const m of allMessages) {
            if (m.id != null && m.processed_status === 'failed') out.add(m.id);
        }
        return out;
    }, [allMessages, failedIds]);

    // ── Auth mutations ──
    const phoneMutation = useMutation({
        mutationFn: (phone: string) => telegramClientApi.sendPhoneNumber(phone),
        onSuccess: () => { setAuthError(null); queryClient.invalidateQueries({ queryKey: ['tg-status'] }); },
        onError: (err: any) => setAuthError(err?.response?.data?.detail || err?.message || 'Не удалось отправить номер'),
    });
    const codeMutation = useMutation({
        mutationFn: (code: string) => telegramClientApi.sendCode(code),
        onSuccess: () => { setAuthError(null); queryClient.invalidateQueries({ queryKey: ['tg-status'] }); },
        onError: (err: any) => setAuthError(err?.response?.data?.detail || err?.message || 'Неверный код'),
    });
    const passwordMutation = useMutation({
        mutationFn: (password: string) => telegramClientApi.sendPassword(password),
        onSuccess: () => { setAuthError(null); queryClient.invalidateQueries({ queryKey: ['tg-status'] }); },
        onError: (err: any) => setAuthError(err?.response?.data?.detail || err?.message || 'Неверный пароль'),
    });

    // ── Send mutations ──
    const sendMutation = useMutation({
        mutationFn: ({ chatId, text }: { chatId: number; text: string }) =>
            telegramClientApi.sendMessage(chatId, text),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tg-messages', activeChatId] }),
        onError: (err: any) => showToast('error', err?.response?.data?.detail || err?.message || 'Не удалось отправить'),
    });

    const sendPdfMutation = useMutation({
        mutationFn: ({ chatId, file }: { chatId: number; file: File }) =>
            telegramClientApi.sendPdf(chatId, file),
        onSuccess: () => {
            showToast('success', 'Файл отправлен');
            queryClient.invalidateQueries({ queryKey: ['tg-messages', activeChatId] });
        },
        onError: (err: any) => showToast('error', err?.response?.data?.detail || err?.message || 'Не удалось загрузить файл'),
    });

    const runProcess = useCallback(
        async (chatId: number, messageId: number): Promise<'done' | 'failed'> => {
            setProcessingIds((s) => {
                const n = new Set(s);
                n.add(messageId);
                return n;
            });
            setFailedIds((s) => {
                const n = new Set(s);
                n.delete(messageId);
                return n;
            });
            try {
                let status = (await telegramClientApi.processMessage(chatId, messageId)).status;
                let attempts = 0;
                const maxAttempts = 30;
                while (status !== 'done' && status !== 'failed' && attempts < maxAttempts) {
                    await new Promise((resolve) => setTimeout(resolve, 300));
                    const batch = await telegramClientApi.getReceiptStatus(chatId, [messageId]);
                    const row = batch.results?.[0];
                    status = (row?.status as typeof status) || status;
                    attempts += 1;
                }
                setProcessingIds((s) => {
                    const n = new Set(s);
                    n.delete(messageId);
                    return n;
                });
                if (status === 'done') {
                    setProcessedIds((s) => {
                        const n = new Set(s);
                        n.add(messageId);
                        return n;
                    });
                    return 'done';
                }
                setFailedIds((s) => {
                    const n = new Set(s);
                    n.add(messageId);
                    return n;
                });
                return 'failed';
            } catch {
                setProcessingIds((s) => {
                    const n = new Set(s);
                    n.delete(messageId);
                    return n;
                });
                setFailedIds((s) => {
                    const n = new Set(s);
                    n.add(messageId);
                    return n;
                });
                return 'failed';
            }
        },
        [],
    );

    // ── Selection helpers (must stay above any early returns to keep hook order stable) ──
    const handleSelectAll = useCallback(() => {
        const ids = messages.map((m) => m.id).filter((id): id is number => Boolean(id));
        if (ids.length === 0) return;
        setSelectionMode(true);
        setSelectedIds(new Set(ids));
    }, [messages]);

    const handleDeselectAll = useCallback(() => {
        setSelectedIds(new Set());
    }, []);

    const handleBulkProcess = useCallback(async () => {
        if (!activeChatId || bulkBusy) return;
        const ids = Array.from(selectedIds);
        if (ids.length === 0) return;
        setBulkBusy(true);
        setBulkStats({ processed: 0, failed: 0, total: ids.length });
        let processed = 0;
        let failed = 0;
        for (const messageId of ids) {
            const result = await runProcess(activeChatId, messageId);
            if (result === 'done') processed += 1;
            else failed += 1;
            setBulkStats({ processed, failed, total: ids.length });
        }
        setBulkBusy(false);
        if (failed > 0) {
            showToast('warning', `Готово: ${processed}, ошибок: ${failed}`);
        } else {
            showToast('success', `Готово: ${processed}`);
        }
    }, [activeChatId, bulkBusy, runProcess, selectedIds, showToast]);

    const handleCancelSelection = useCallback(() => {
        if (bulkBusy) return;
        setSelectionMode(false);
        setSelectedIds(new Set());
        setBulkStats({ processed: 0, failed: 0, total: 0 });
    }, [bulkBusy]);

    useKeyboardShortcuts({
        enabled: selectionMode,
        shortcuts: [
            { key: 'Escape', handler: () => handleCancelSelection() },
            { key: 'a', ctrl: true, handler: () => handleSelectAll() },
            { key: 'd', ctrl: true, handler: () => handleDeselectAll() },
            {
                key: 'Enter',
                handler: () => {
                    if (selectedIds.size > 0 && !bulkBusy) {
                        void handleBulkProcess();
                    }
                },
            },
        ],
    });

    // Monitor toggle
    const monitorMutation = useMutation({
        mutationFn: ({ chatId, enabled }: { chatId: number; enabled: boolean }) =>
            telegramClientApi.setMonitor(chatId, enabled),
        onSuccess: (_data, variables) => {
            showToast('success', variables.enabled ? 'Мониторинг включён' : 'Мониторинг выключен');
            queryClient.invalidateQueries({ queryKey: ['tg-chats'] });
        },
        onError: (err: any) => showToast('error', err?.response?.data?.detail || err?.message || 'Не удалось обновить'),
    });

    // Hide / unhide
    const hideChatMutation = useMutation({
        mutationFn: ({ chatId, hidden }: { chatId: number; hidden: boolean }) =>
            telegramClientApi.setChatHidden(chatId, hidden),
        onMutate: ({ chatId, hidden }) => {
            setHiddenOverlay(chatId, hidden);
        },
        onSuccess: (_data, variables) => {
            acknowledgeHidden(variables.chatId);
            showToast('success', variables.hidden ? 'Чат скрыт' : 'Чат показан');
        },
        onError: (err: any, variables) => {
            rollbackHidden(variables.chatId);
            showToast('error', err?.response?.data?.detail || err?.message || 'Не удалось обновить');
        },
    });

    // Password set / remove
    const setPasswordMutation = useMutation({
        mutationFn: ({ chatId, password }: { chatId: number; password: string }) =>
            telegramClientApi.setChatPassword(chatId, password),
        onSuccess: () => {
            showToast('success', 'Пароль установлен');
            setPasswordDialog({ open: false });
            queryClient.invalidateQueries({ queryKey: ['tg-chats'] });
        },
        onError: (err: any) => showToast('error', err?.response?.data?.detail || err?.message || 'Не удалось установить пароль'),
    });

    const removePasswordMutation = useMutation({
        mutationFn: ({ chatId, password }: { chatId: number; password: string }) =>
            telegramClientApi.removeChatPassword(chatId, password),
        onSuccess: () => {
            showToast('success', 'Пароль снят');
            setPasswordDialog({ open: false });
            queryClient.invalidateQueries({ queryKey: ['tg-chats'] });
        },
        onError: (err: any) => showToast('error', err?.response?.data?.detail || err?.message || 'Не удалось снять пароль'),
    });

    // ── Main UI ──
    const statusLabel = ready ? 'подключено' : 'подключение…';
    const statusTone: 'ready' | 'warning' | 'error' = ready ? 'ready' : 'warning';

    const handleSend = (text: string) => {
        if (!activeChatId) return;
        sendMutation.mutate({ chatId: activeChatId, text });
        setForceScrollKey((k) => k + 1);
    };
    const handleAttach = (file: File) => {
        if (!activeChatId) return;
        sendPdfMutation.mutate({ chatId: activeChatId, file });
        setForceScrollKey((k) => k + 1);
    };
    const handleToggleMonitor = (chatId: number, on: boolean) => {
        monitorMutation.mutate({ chatId, enabled: on });
    };
    const handleProcess = (m: TelegramChatMessage) => {
        if (!activeChatId || !m.id) return;
        void runProcess(activeChatId, m.id);
    };

    const handleToggleSelect = (id: number) => {
        setSelectionMode(true);
        setSelectedIds((s) => {
            const n = new Set(s);
            if (n.has(id)) n.delete(id); else n.add(id);
            return n;
        });
    };

    // ── Context menu handlers ──
    const openChatContextMenu = (e: React.MouseEvent, chat: TelegramChat) => {
        e.preventDefault();
        setContextTarget({ kind: 'chat', chat });
        setContextPos({ x: e.clientX, y: e.clientY });
    };

    const openMessageContextMenu = (e: React.MouseEvent, message: TelegramChatMessage) => {
        e.preventDefault();
        setContextTarget({ kind: 'message', message });
        setContextPos({ x: e.clientX, y: e.clientY });
    };

    const closeContextMenu = () => setContextTarget(null);

    const contextItems: ContextMenuItem[] = useMemo(() => {
        if (!contextTarget) return [];
        if (contextTarget.kind === 'chat') {
            const chat = contextTarget.chat;
            const items: ContextMenuItem[] = [
                {
                    key: 'hide',
                    label: chat.is_hidden ? 'Показать' : 'Скрыть',
                    icon: chat.is_hidden ? <Eye size={13} /> : <EyeOff size={13} />,
                    onClick: () => hideChatMutation.mutate({ chatId: chat.chat_id, hidden: !chat.is_hidden }),
                },
            ];
            if (chat.is_protected) {
                items.push({
                    key: 'remove-password',
                    label: 'Снять пароль',
                    icon: <Unlock size={13} />,
                    onClick: () => setPasswordDialog({ open: true, chat, mode: 'remove' }),
                });
            } else {
                items.push({
                    key: 'set-password',
                    label: 'Поставить пароль',
                    icon: <KeyRound size={13} />,
                    onClick: () => setPasswordDialog({ open: true, chat, mode: 'set' }),
                });
            }
            return items;
        }
        // message context
        const m = contextTarget.message;
        const items: ContextMenuItem[] = [
            {
                key: 'process',
                label: 'В обработку',
                    icon: <ScanLine size={13} />,
                onClick: () => handleProcess(m),
                disabled: !m.id,
            },
            {
                key: 'select',
                label: 'Добавить в выбор',
                icon: <CheckSquare size={13} />,
                onClick: () => { if (m.id) handleToggleSelect(m.id); },
                disabled: !m.id,
            },
        ];
        return items;
    }, [contextTarget, hideChatMutation]);

    // ── Render guards for auth flow (placed after all hooks to keep hook order stable) ──
    if (statusQuery.isLoading) {
        return <StatusBoard title="Подключаемся" sub="Получаем статус Telegram-сессии." tone="connecting" />;
    }
    if (rawState === 'wait_phone_number') {
        return <AuthCard step="phone" busy={phoneMutation.isPending} error={authError}
            onPhone={(v) => phoneMutation.mutate(v)} onCode={() => {}} onPassword={() => {}} />;
    }
    if (rawState === 'wait_code') {
        return <AuthCard step="code" busy={codeMutation.isPending} error={authError}
            onPhone={() => {}} onCode={(v) => codeMutation.mutate(v)} onPassword={() => {}} />;
    }
    if (rawState === 'wait_password') {
        return <AuthCard step="password" busy={passwordMutation.isPending} error={authError}
            onPhone={() => {}} onCode={() => {}} onPassword={(v) => passwordMutation.mutate(v)} />;
    }
    if (rawState === 'tdlib_unavailable' || rawState === 'misconfigured') {
        return <StatusBoard title="Сервис недоступен" sub="Telegram-клиент не настроен на сервере." tone="error" />;
    }
    if (!ready) {
        return <StatusBoard title="Инициализация" sub="Telegram готовится к работе." tone="connecting" />;
    }

    return (
        <div className={`tg-shell${activeChatId ? ' has-active-chat' : ''}`}>
            <ChatList
                chats={chats}
                activeChatId={activeChatId}
                onSelect={setActiveChatId}
                onContextMenu={openChatContextMenu}
                isLoading={chatsQuery.isLoading}
                statusLabel={statusLabel}
                statusTone={statusTone}
                filter={filter}
                onFilterChange={setFilter}
            />

            <main className="tg-message-pane">
                {activeChat ? (
                    <>
                        <ChatHeader
                            chat={activeChat}
                            onBack={() => setActiveChatId(null)}
                            onToggleMonitor={handleToggleMonitor}
                            onToggleSelection={() => {
                                setSelectionMode((v) => !v);
                                if (selectionMode) setSelectedIds(new Set());
                            }}
                            selectionMode={selectionMode}
                            dateRange={dateRange}
                            onDateRangeChange={setDateRange}
                        />

                        {selectionMode ? (
                            <BulkBar
                                total={messages.filter((m) => Boolean(m.id)).length}
                                selectedCount={selectedIds.size}
                                processed={bulkStats.processed}
                                failed={bulkStats.failed}
                                inFlight={processingIds.size}
                                busy={bulkBusy}
                                onProcess={handleBulkProcess}
                                onCancel={handleCancelSelection}
                                onSelectAll={handleSelectAll}
                                onDeselectAll={handleDeselectAll}
                            />
                        ) : null}

                        <MessageStream
                            key={activeChatId}
                            messages={messages}
                            isLoading={messagesQuery.isLoading}
                            selectionMode={selectionMode}
                            selectedIds={selectedIds}
                            onToggleSelect={handleToggleSelect}
                            onProcess={handleProcess}
                            onMessageContextMenu={openMessageContextMenu}
                            processingIds={processingIds}
                            processedIds={effectiveProcessedIds}
                            failedIds={effectiveFailedIds}
                            forceScrollToBottomKey={forceScrollKey}
                            emptyTitle={dateRange.from || dateRange.to ? 'В выбранном периоде сообщений нет' : undefined}
                            emptySub={dateRange.from || dateRange.to ? 'Попробуйте расширить диапазон дат.' : undefined}
                        />

                        {!selectionMode ? (
                            <MessageInput
                                onSend={handleSend}
                                onAttach={handleAttach}
                                sending={sendMutation.isPending || sendPdfMutation.isPending}
                                placeholder={`Сообщение в «${activeChat.title}»…`}
                            />
                        ) : null}
                    </>
                ) : (
                    <EmptyState />
                )}
            </main>

            <ContextMenu
                open={Boolean(contextTarget)}
                x={contextPos.x}
                y={contextPos.y}
                items={contextItems}
                onClose={closeContextMenu}
            />

            <PasswordDialog
                open={passwordDialog.open}
                chatTitle={passwordDialog.open ? passwordDialog.chat.title : ''}
                mode={passwordDialog.open ? passwordDialog.mode : 'set'}
                busy={setPasswordMutation.isPending || removePasswordMutation.isPending}
                onClose={() => setPasswordDialog({ open: false })}
                onSubmit={(password) => {
                    if (!passwordDialog.open) return;
                    const chatId = passwordDialog.chat.chat_id;
                    if (passwordDialog.mode === 'set') {
                        setPasswordMutation.mutate({ chatId, password });
                    } else if (passwordDialog.mode === 'remove') {
                        removePasswordMutation.mutate({ chatId, password });
                    }
                }}
            />
        </div>
    );
};
