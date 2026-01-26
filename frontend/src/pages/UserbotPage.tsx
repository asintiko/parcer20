import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
    Bot,
    MessageSquare,
    EyeOff,
    Eye,
    Send,
    Search,
    Phone,
    ShieldCheck,
    Lock,
    WifiOff,
    Loader2,
    RefreshCcw,
    AlertCircle,
    XCircle,
    Play,
    Pause,
    Sparkles,
    BadgeCheck,
    CheckSquare,
    Square,
} from 'lucide-react';
import { MessageItem } from '../components/MessageItem';
import {
    telegramClientApi,
    TelegramAuthStatus,
    TelegramChat,
    TelegramChatMessage,
    TelegramProcessResult,
    TelegramMonitorStatus,
} from '../services/api';
import { useToast } from '../components/Toast';

const stateMeta: Record<
    string,
    { label: string; tone: string; description?: string }
> = {
    wait_tdlib_parameters: {
        label: 'Инициализация TDLib',
        tone: 'bg-info-light text-info',
        description: 'Подключаем библиотеку и параметры',
    },
    wait_encryption_key: {
        label: 'Разблокировка хранилища',
        tone: 'bg-info-light text-info',
        description: 'Проверяем ключ шифрования базы TDLib',
    },
    ready: { label: 'Подключено', tone: 'bg-success-light text-success', description: 'TDLib сессия активна' },
    wait_phone_number: { label: 'Требуется телефон', tone: 'bg-warning-light text-warning' },
    wait_code: { label: 'Ожидается код', tone: 'bg-warning-light text-warning' },
    wait_password: { label: 'Ожидается пароль', tone: 'bg-warning-light text-warning' },
    tdlib_unavailable: { label: 'TDLib недоступен', tone: 'bg-danger-light text-danger' },
    misconfigured: { label: 'Нет конфигурации', tone: 'bg-danger-light text-danger' },
    logging_out: { label: 'Завершение сессии', tone: 'bg-info-light text-info' },
    closing: { label: 'Завершение', tone: 'bg-info-light text-info' },
    closed: { label: 'Закрыто', tone: 'bg-info-light text-info' },
    unknown: { label: 'Статус неизвестен', tone: 'bg-info-light text-info' },
};

const formatDateTime = (date?: string | null) => {
    if (!date) return '';
    const parsed = new Date(date);
    if (Number.isNaN(parsed.getTime())) return '';
    return parsed.toLocaleString('ru-RU', {
        weekday: 'short',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });
};

export const UserbotPage: React.FC = () => {
    const { showToast } = useToast();
    const queryClient = useQueryClient();

    const [selectedChatId, setSelectedChatId] = useState<number | null>(null);
    const [search, setSearch] = useState('');
    const [showHidden, setShowHidden] = useState(false);
    // Backend expects TDLib types: private, group, supergroup, channel
    const [selectedTypes, setSelectedTypes] = useState<Set<string>>(new Set(['private', 'group', 'supergroup', 'channel']));
    const [keepSelection, setKeepSelection] = useState<Set<number>>(new Set());
    const [composer, setComposer] = useState('');
    const [pdfFile, setPdfFile] = useState<File | null>(null);
    const [authForm, setAuthForm] = useState({ phone: '', code: '', password: '' });
    const [messagesState, setMessagesState] = useState<TelegramChatMessage[]>([]);
    const [selectedMessageIds, setSelectedMessageIds] = useState<Set<number>>(new Set());
    const [statuses, setStatuses] = useState<Record<number, TelegramProcessResult>>({});
    // Deprecated local polling toggle; server monitor toggle is used now.
    const [liveRefresh] = useState(true);
    const [previewUrl, setPreviewUrl] = useState<string | null>(null);
    const [processingId, setProcessingId] = useState<number | null>(null);
    const [batchProcessing, setBatchProcessing] = useState(false);
    const messagesScrollRef = useRef<HTMLDivElement | null>(null);

    const chatTypeLabel: Record<string, string> = useMemo(
        () => ({
            bot: 'Бот',
            user: 'Пользователь',
            group: 'Группа',
            supergroup: 'Супергруппа',
            channel: 'Канал',
        }),
        []
    );

    const chatTypeOptions = useMemo(
        () => [
            { id: 'private', label: 'Боты' },
            { id: 'group', label: 'Группы' },
            { id: 'supergroup', label: 'Супергруппы' },
            { id: 'channel', label: 'Каналы' },
        ],
        []
    );

    const { data: authStatus, isLoading: authLoading, refetch: refetchStatus } = useQuery<TelegramAuthStatus>({
        queryKey: ['tg-status'],
        queryFn: telegramClientApi.getStatus,
        refetchInterval: (query) => (query.state.data?.state === 'ready' ? 30000 : 5000),
    });

    const chatsQuery = useQuery({
        queryKey: ['tg-chats', search, showHidden, Array.from(selectedTypes).sort().join(',')],
        queryFn: () =>
            telegramClientApi.getChats({
                search: search || undefined,
                include_hidden: showHidden,
                limit: 200,
                offset: 0,
                chat_types: Array.from(selectedTypes).join(','),
            }),
        enabled: authStatus?.state === 'ready',
    });

    const messagesQuery = useQuery({
        queryKey: ['tg-messages', selectedChatId],
        queryFn: () => telegramClientApi.getMessages(selectedChatId!, { all: true }),
        enabled: !!selectedChatId && authStatus?.state === 'ready',
        refetchInterval: liveRefresh ? 5000 : false,
    });

    const monitorStatusQuery = useQuery<TelegramMonitorStatus>({
        queryKey: ['tg-monitor-status'],
        queryFn: telegramClientApi.getMonitorStatus,
        enabled: authStatus?.state === 'ready',
        refetchInterval: (query) => (query.state.data?.running ? 7000 : 12000),
    });

    const monitorToggleMutation = useMutation({
        mutationFn: (payload: { chatId: number; enabled: boolean }) =>
            telegramClientApi.setMonitor(payload.chatId, payload.enabled, !payload.enabled ? false : true),
        onSuccess: async () => {
            await Promise.all([
                queryClient.invalidateQueries({ queryKey: ['tg-chats'] }),
                queryClient.invalidateQueries({ queryKey: ['tg-monitor-status'] }),
            ]);
            showToast('success', 'Статус серверного монитора обновлён');
        },
        onError: () => showToast('error', 'Не удалось изменить мониторинг чата'),
    });

    useEffect(() => {
        if (chatsQuery.data?.items?.length) {
            const exists = chatsQuery.data.items.some((c) => c.chat_id === selectedChatId);
            if (!selectedChatId || !exists) {
                setSelectedChatId(chatsQuery.data.items[0].chat_id);
            }
        } else if (!chatsQuery.isLoading && !chatsQuery.data?.items?.length) {
            setSelectedChatId(null);
        }
    }, [chatsQuery.data, chatsQuery.isLoading, selectedChatId]);

    // Reset messages and selections on chat switch
    useEffect(() => {
        setMessagesState([]);
        setSelectedMessageIds(new Set());
    }, [selectedChatId]);

    // Fill messages state from query
    useEffect(() => {
        if (messagesQuery.data?.items) {
            const sorted = [...messagesQuery.data.items].sort((a, b) => {
                const aTime = a?.date ? new Date(a.date).getTime() : 0;
                const bTime = b?.date ? new Date(b.date).getTime() : 0;
                return aTime - bTime;
            });
            setMessagesState(sorted);
        }
    }, [messagesQuery.data]);

    // Fetch receipt statuses for current messages
    useEffect(() => {
        const chunkArray = (arr: number[], size: number) => {
            const res: number[][] = [];
            for (let i = 0; i < arr.length; i += size) {
                res.push(arr.slice(i, i + size));
            }
            return res;
        };
        const loadStatuses = async () => {
            if (!selectedChatId || !messagesState.length) {
                setStatuses({});
                return;
            }
            const ids = messagesState
                .map((m) => m.id)
                .filter((id): id is number => typeof id === 'number');
            if (!ids.length) return;
            try {
                const chunks = chunkArray(ids, 200);
                const results = await Promise.all(
                    chunks.map((chunk) => telegramClientApi.getReceiptStatus(selectedChatId, chunk))
                );
                const merged: Record<number, any> = {};
                results.forEach((r) => {
                    r.results?.forEach((item: TelegramProcessResult) => {
                        merged[item.message_id] = item;
                    });
                });
                setStatuses(merged);
            } catch (err) {
                console.error('Failed to fetch receipt status', err);
            }
        };
        void loadStatuses();
    }, [messagesState, selectedChatId]);

    // Live refresh statuses when enabled
    useEffect(() => {
        if (!liveRefresh || !selectedChatId || !messagesState.length) return;
        const chunkArray = (arr: number[], size: number) => {
            const res: number[][] = [];
            for (let i = 0; i < arr.length; i += size) res.push(arr.slice(i, i + size));
            return res;
        };
        const interval = setInterval(async () => {
            const ids = messagesState
                .map((m) => m.id)
                .filter((id): id is number => typeof id === 'number');
            if (!ids.length) return;
            try {
                const chunks = chunkArray(ids, 200);
                const results = await Promise.all(
                    chunks.map((chunk) => telegramClientApi.getReceiptStatus(selectedChatId, chunk))
                );
                setStatuses((prev) => {
                    const next = { ...prev };
                    results.forEach((r) => {
                        r.results?.forEach((item: TelegramProcessResult) => {
                            next[item.message_id] = item;
                        });
                    });
                    return next;
                });
            } catch (err) {
                console.error('Failed to refresh receipt status', err);
            }
        }, 5000);
        return () => clearInterval(interval);
    }, [liveRefresh, selectedChatId, messagesState]);

    // Auto-scroll to bottom when messages change (newest at bottom)
    useEffect(() => {
        const el = messagesScrollRef.current;
        if (!el) return;
        el.scrollTop = el.scrollHeight;
    }, [messagesState.length, selectedChatId]);

    const toggleType = (typeId: string) => {
        setSelectedTypes((prev) => {
            const next = new Set(prev);
            if (next.has(typeId)) {
                next.delete(typeId);
            } else {
                next.add(typeId);
            }
            return next.size === 0 ? prev : next;
        });
    };

    const toggleKeepChat = (chatId: number) => {
        setKeepSelection((prev) => {
            const next = new Set(prev);
            if (next.has(chatId)) {
                next.delete(chatId);
            } else {
                next.add(chatId);
            }
            return next;
        });
    };

    const toggleSelectMessage = (id?: number) => {
        if (id === undefined || id === null) return;
        setSelectedMessageIds((prev) => {
            const next = new Set(prev);
            if (next.has(id)) {
                next.delete(id);
            } else {
                next.add(id);
            }
            return next;
        });
    };

    // Select all / Deselect all functions
    const selectAllMessages = useCallback(() => {
        const allIds = messagesState
            .map((m) => m.id)
            .filter((id): id is number => typeof id === 'number');
        setSelectedMessageIds(new Set(allIds));
    }, [messagesState]);

    const deselectAllMessages = useCallback(() => {
        setSelectedMessageIds(new Set());
    }, []);

    const sendPhoneMutation = useMutation({
        mutationFn: (phone: string) => telegramClientApi.sendPhoneNumber(phone),
        onSuccess: async () => {
            await refetchStatus();
            showToast('success', 'Телефон принят, ожидаем код');
        },
        onError: () => showToast('error', 'Не удалось отправить номер'),
    });

    const sendCodeMutation = useMutation({
        mutationFn: (code: string) => telegramClientApi.sendCode(code),
        onSuccess: async () => {
            await refetchStatus();
            showToast('success', 'Код принят');
        },
        onError: () => showToast('error', 'Код не принят'),
    });

    const sendPasswordMutation = useMutation({
        mutationFn: (password: string) => telegramClientApi.sendPassword(password),
        onSuccess: async () => {
            await refetchStatus();
            showToast('success', 'Пароль принят');
        },
        onError: () => showToast('error', 'Пароль не принят'),
    });

    const bulkKeepMutation = useMutation({
        mutationFn: async (keepIds: number[]) => {
            const allIds = (chatsQuery.data?.items || []).map((c) => c.chat_id);
            const toHide = allIds.filter((id) => !keepIds.includes(id));
            if (!toHide.length) return;
            await Promise.all(toHide.map((id) => telegramClientApi.hideChat(id)));
        },
        onSuccess: async () => {
            setKeepSelection(new Set());
            await queryClient.invalidateQueries({ queryKey: ['tg-chats'] });
            showToast('success', 'Оставили выбранные, остальные скрыты');
        },
        onError: () => showToast('error', 'Не удалось применить выбор'),
    });

    const hideChatMutation = useMutation({
        mutationFn: (chatId: number) => telegramClientApi.hideChat(chatId),
        onSuccess: async () => {
            await queryClient.invalidateQueries({ queryKey: ['tg-chats'] });
        },
    });

    const unhideChatMutation = useMutation({
        mutationFn: (chatId: number) => telegramClientApi.unhideChat(chatId),
        onSuccess: async () => {
            await queryClient.invalidateQueries({ queryKey: ['tg-chats'] });
        },
    });

    const sendMessageMutation = useMutation({
        mutationFn: (payload: { chatId: number; text: string }) =>
            telegramClientApi.sendMessage(payload.chatId, payload.text),
        onSuccess: async (_, variables) => {
            setComposer('');
            await queryClient.invalidateQueries({ queryKey: ['tg-messages', variables.chatId] });
            await queryClient.invalidateQueries({ queryKey: ['tg-chats'] });
        },
        onError: () => showToast('error', 'Не удалось отправить сообщение'),
    });

    const sendPdfMutation = useMutation({
        mutationFn: (payload: { chatId: number; file: File; caption?: string }) =>
            telegramClientApi.sendPdf(payload.chatId, payload.file, payload.caption),
        onSuccess: async (_, variables) => {
            setPdfFile(null);
            setComposer('');
            await queryClient.invalidateQueries({ queryKey: ['tg-messages', variables.chatId] });
            await queryClient.invalidateQueries({ queryKey: ['tg-chats'] });
            showToast('success', 'PDF отправлен');
        },
        onError: () => showToast('error', 'Не удалось отправить PDF'),
    });

    const processReceiptMutation = useMutation({
        mutationFn: (payload: { chatId: number; messageId: number }) =>
            telegramClientApi.processMessage(payload.chatId, payload.messageId),
        onMutate: (variables) => {
            setProcessingId(variables.messageId);
        },
        onSettled: () => setProcessingId(null),
        onSuccess: (data, variables) => {
            setStatuses((prev) => ({
                ...prev,
                [variables.messageId]: data,
            }));
            showToast('success', `Задача ${data.task_id || ''} → ${data.status}`);
            queryClient.invalidateQueries({ queryKey: ['tg-messages', variables.chatId] });
        },
        onError: (err: any) => {
            const detail = err?.response?.data?.detail || 'Ошибка обработки';
            showToast('error', detail);
        },
    });

    const reprocessMutation = useMutation({
        mutationFn: (payload: { chatId: number; messageId: number }) =>
            telegramClientApi.processReceiptDirect(payload.chatId, payload.messageId, true),
        onMutate: (variables) => setProcessingId(variables.messageId),
        onSettled: () => setProcessingId(null),
        onSuccess: (data, variables) => {
            setStatuses((prev) => ({
                ...prev,
                [variables.messageId]: {
                    chat_id: variables.chatId,
                    message_id: variables.messageId,
                    status: 'done',
                    check_id: (data as any)?.transaction?.id,
                } as TelegramProcessResult,
            }));
            showToast('success', 'Повторная обработка завершена');
            queryClient.invalidateQueries({ queryKey: ['tg-messages', variables.chatId] });
        },
        onError: (err: any) => {
            const detail = err?.response?.data?.detail || 'Ошибка повторной обработки';
            showToast('error', detail);
        },
    });

    const processBatchMutation = useMutation({
        mutationFn: (payload: { chatId: number; messageIds: number[] }) =>
            telegramClientApi.processBatch(payload.chatId, payload.messageIds),
        onMutate: () => setBatchProcessing(true),
        onSettled: () => setBatchProcessing(false),
        onSuccess: (data, variables) => {
            if (data.results?.length) {
                setStatuses((prev) => {
                    const next = { ...prev };
                    data.results.forEach((r) => {
                        next[r.message_id] = r;
                    });
                    return next;
                });
            }
            const failed = data.results?.filter((r) => r.status === 'failed') || [];
            const queued = data.results?.filter((r) => r.status !== 'failed') || [];
            if (queued.length) {
                showToast('success', `В очередь: ${queued.length}`);
            }
            if (failed.length) {
                showToast('error', `Ошибки: ${failed.length}. Пример: ${failed[0].error || 'неизвестно'}`);
            }
            queryClient.invalidateQueries({ queryKey: ['tg-messages', variables.chatId] });
        },
        onError: (err: any) => {
            const detail = err?.response?.data?.detail || 'Ошибка пакетной обработки';
            showToast('error', detail);
        },
    });

    const currentChat = useMemo(
        () => chatsQuery.data?.items.find((c) => c.chat_id === selectedChatId) || null,
        [chatsQuery.data, selectedChatId]
    );

    // Keyboard shortcuts
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            const target = e.target as HTMLElement;
            const isInput = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA';

            // Ctrl/Cmd + A - Select all
            if ((e.ctrlKey || e.metaKey) && e.key === 'a' && !isInput) {
                e.preventDefault();
                selectAllMessages();
            }

            // Escape - Deselect all
            if (e.key === 'Escape') {
                deselectAllMessages();
            }

            // Ctrl/Cmd + Enter - Process selected
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && selectedMessageIds.size > 0 && currentChat) {
                e.preventDefault();
                const ids = Array.from(selectedMessageIds);
                processBatchMutation.mutate({ chatId: currentChat.chat_id, messageIds: ids });
            }
        };

        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [selectAllMessages, deselectAllMessages, selectedMessageIds, currentChat, processBatchMutation]);

    const renderAuthPanel = () => {
        if (authLoading) {
            return (
                <div className="flex items-center gap-3 text-foreground-secondary">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Проверяем статус TDLib...
                </div>
            );
        }

        if (!authStatus) return null;
        const meta = stateMeta[authStatus.state] || stateMeta.unknown;

        const formDisabled = authStatus.state === 'tdlib_unavailable' || authStatus.state === 'misconfigured';

        return (
            <div className="bg-surface border border-border rounded-lg p-4 flex flex-col gap-3 shadow-sm">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className={`px-3 py-1 rounded-full text-sm font-medium ${meta.tone}`}>
                            {meta.label}
                        </div>
                        {meta.description && (
                            <span className="text-sm text-foreground-secondary">{meta.description}</span>
                        )}
                    </div>
                    <button
                        onClick={() => {
                            refetchStatus();
                            chatsQuery.refetch();
                        }}
                        className="flex items-center gap-2 px-3 py-2 rounded-md border border-border text-sm text-foreground hover:bg-surface-2 transition-colors focus:outline-none focus:ring-2 focus:ring-primary"
                    >
                        <RefreshCcw className="w-4 h-4" />
                        Обновить
                    </button>
                </div>

                {(authStatus.state === 'tdlib_unavailable' || authStatus.state === 'misconfigured') && (
                    <div className="flex items-start gap-3 bg-danger-light border border-danger/30 rounded-md px-3 py-2 text-sm text-danger">
                        <WifiOff className="w-4 h-4 mt-0.5" />
                        <div>
                            <p className="font-semibold">TDLib недоступен</p>
                            <p className="text-danger">
                                Проверьте сборку контейнера и переменные окружения для TDLib.
                            </p>
                        </div>
                    </div>
                )}

                {authStatus.state === 'ready' && (
                    <div className="flex items-center gap-3 text-sm text-foreground">
                        <ShieldCheck className="w-4 h-4 text-success" />
                        <div>
                            <div className="font-semibold">Сессия активна</div>
                            <div className="text-foreground-secondary">
                                {authStatus.user?.first_name} {authStatus.user?.last_name} ({authStatus.user?.username || authStatus.phone_number})
                            </div>
                        </div>
                    </div>
                )}

                {authStatus.state === 'wait_phone_number' && (
                    <form
                        className="grid grid-cols-1 md:grid-cols-3 gap-3"
                        onSubmit={(e) => {
                            e.preventDefault();
                            if (!authForm.phone.trim()) return;
                            sendPhoneMutation.mutate(authForm.phone);
                        }}
                    >
                        <label className="col-span-2 flex flex-col gap-1 text-sm text-foreground">
                            Телефон для авторизации
                            <div className="flex items-center gap-2">
                                <div className="p-2 bg-surface-2 rounded-md border border-border">
                                    <Phone className="w-4 h-4 text-foreground-secondary" />
                                </div>
                                <input
                                    type="tel"
                                    value={authForm.phone}
                                    onChange={(e) => setAuthForm((prev) => ({ ...prev, phone: e.target.value }))}
                                    placeholder="+998..."
                                    className="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent bg-input-bg text-input-text"
                                    disabled={formDisabled || sendPhoneMutation.isPending}
                                />
                            </div>
                        </label>
                        <div className="flex items-end">
                            <button
                                type="submit"
                                disabled={formDisabled || sendPhoneMutation.isPending}
                                className="w-full px-4 py-2 bg-primary text-foreground-inverse rounded-lg hover:bg-primary-hover transition-colors flex items-center justify-center gap-2 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-primary"
                            >
                                {sendPhoneMutation.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
                                Отправить номер
                            </button>
                        </div>
                    </form>
                )}

                {authStatus.state === 'wait_code' && (
                    <form
                        className="grid grid-cols-1 md:grid-cols-3 gap-3"
                        onSubmit={(e) => {
                            e.preventDefault();
                            if (!authForm.code.trim()) return;
                            sendCodeMutation.mutate(authForm.code);
                        }}
                    >
                        <label className="col-span-2 flex flex-col gap-1 text-sm text-foreground">
                            Код из Telegram
                            <input
                                type="text"
                                value={authForm.code}
                                onChange={(e) => setAuthForm((prev) => ({ ...prev, code: e.target.value }))}
                                placeholder="00000"
                                className="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent bg-input-bg text-input-text"
                                disabled={formDisabled || sendCodeMutation.isPending}
                            />
                        </label>
                        <div className="flex items-end">
                            <button
                                type="submit"
                                disabled={formDisabled || sendCodeMutation.isPending}
                                className="w-full px-4 py-2 bg-primary text-foreground-inverse rounded-lg hover:bg-primary-hover transition-colors flex items-center justify-center gap-2 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-primary"
                            >
                                {sendCodeMutation.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
                                Подтвердить код
                            </button>
                        </div>
                    </form>
                )}

                {authStatus.state === 'wait_password' && (
                    <form
                        className="grid grid-cols-1 md:grid-cols-3 gap-3"
                        onSubmit={(e) => {
                            e.preventDefault();
                            if (!authForm.password.trim()) return;
                            sendPasswordMutation.mutate(authForm.password);
                        }}
                    >
                        <label className="col-span-2 flex flex-col gap-1 text-sm text-foreground">
                            Пароль 2FA
                            <div className="flex items-center gap-2">
                                <div className="p-2 bg-surface-2 rounded-md border border-border">
                                    <Lock className="w-4 h-4 text-foreground-secondary" />
                                </div>
                                <input
                                    type="password"
                                    value={authForm.password}
                                    onChange={(e) => setAuthForm((prev) => ({ ...prev, password: e.target.value }))}
                                    className="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent bg-input-bg text-input-text"
                                    disabled={formDisabled || sendPasswordMutation.isPending}
                                />
                            </div>
                        </label>
                        <div className="flex items-end">
                            <button
                                type="submit"
                                disabled={formDisabled || sendPasswordMutation.isPending}
                                className="w-full px-4 py-2 bg-primary text-foreground-inverse rounded-lg hover:bg-primary-hover transition-colors flex items-center justify-center gap-2 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-primary"
                            >
                                {sendPasswordMutation.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
                                Подтвердить пароль
                            </button>
                        </div>
                    </form>
                )}
            </div>
        );
    };

    return (
        <>
            <div className="h-screen flex flex-col bg-bg">
                <div className="flex-1 overflow-hidden p-6 min-h-0">
                    <div className="max-w-7xl mx-auto space-y-4 h-full flex flex-col min-h-0">
                        <div className="flex items-center gap-3">
                            <div className="p-3 rounded-lg bg-gradient-to-br from-primary to-primary-dark text-foreground-inverse shadow-md">
                                <Bot className="w-6 h-6" />
                            </div>
                            <div>
                                <h1 className="text-2xl font-semibold text-foreground">Telegram Chats</h1>
                                <p className="text-sm text-foreground-secondary">
                                    TDLib-клиент для ботов и групп: авторизация, список чатов, сообщения и скрытие диалогов.
                                </p>
                            </div>
                        </div>

                        {renderAuthPanel()}

                        {authStatus?.state === 'ready' && (
                            <div className="bg-surface border border-border rounded-lg p-3 flex flex-wrap items-center gap-4 text-sm shadow-sm">
                                <div className="flex items-center gap-2">
                                    <Sparkles className="w-4 h-4 text-primary" />
                                    <span className="font-semibold text-foreground">Серверный автомониторинг</span>
                                </div>
                                {monitorStatusQuery.isLoading ? (
                                    <div className="flex items-center gap-2 text-foreground-secondary">
                                        <Loader2 className="w-4 h-4 animate-spin" /> Загружаем статус...
                                    </div>
                                ) : monitorStatusQuery.data ? (
                                    <>
                                        <span className="px-2 py-1 rounded-md text-xs border border-border bg-surface-2">
                                            Очередь: {monitorStatusQuery.data.queue_size}
                                        </span>
                                        <span className="px-2 py-1 rounded-md text-xs border border-border bg-surface-2">
                                            Воркеров: {monitorStatusQuery.data.workers}
                                        </span>
                                        <span
                                            className={`px-2 py-1 rounded-md text-xs border ${monitorStatusQuery.data.running
                                                ? 'border-success text-success bg-success/10'
                                                : 'border-border text-foreground-secondary'
                                                }`}
                                        >
                                            {monitorStatusQuery.data.running ? 'Работает' : 'Остановлен'}
                                        </span>
                                    </>
                                ) : (
                                    <span className="text-foreground-secondary">Статус недоступен</span>
                                )}
                            </div>
                        )}

                        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 h-full min-h-0">
                            <div className="bg-surface border border-border rounded-lg shadow-sm grid grid-rows-[auto,1fr] h-full min-h-0">
                                <div className="p-4 border-b border-border flex flex-col gap-3">
                                    <div className="flex items-center justify-between">
                                        <div className="flex items-center gap-2">
                                            <MessageSquare className="w-5 h-5 text-foreground-secondary" />
                                            <h2 className="text-sm font-semibold text-foreground">Чаты (боты и группы)</h2>
                                        </div>
                                        <label className="flex items-center gap-2 text-xs text-foreground-secondary cursor-pointer">
                                            <input
                                                type="checkbox"
                                                checked={showHidden}
                                                onChange={(e) => setShowHidden(e.target.checked)}
                                                className="w-4 h-4 text-primary border-border rounded focus:ring-primary"
                                            />
                                            Показать скрытые
                                        </label>
                                    </div>
                                    <div className="relative">
                                        <Search className="w-4 h-4 text-foreground-muted absolute left-3 top-3" />
                                        <input
                                            type="text"
                                            value={search}
                                            onChange={(e) => setSearch(e.target.value)}
                                            placeholder="Поиск чатов"
                                            className="w-full pl-9 pr-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent bg-input-bg text-input-text"
                                        />
                                    </div>
                                    <div className="flex flex-wrap gap-2">
                                        {chatTypeOptions.map((opt) => {
                                            const active = selectedTypes.has(opt.id);
                                            return (
                                                <button
                                                    key={opt.id}
                                                    onClick={() => toggleType(opt.id)}
                                                    className={`px-3 py-1.5 rounded-md text-xs border transition-colors ${active
                                                        ? 'border-primary bg-primary/10 text-primary'
                                                        : 'border-border text-foreground-secondary hover:bg-surface-2'
                                                        }`}
                                                >
                                                    {opt.label}
                                                </button>
                                            );
                                        })}
                                    </div>
                                    <div className="flex items-center gap-2 flex-wrap">
                                        <button
                                            onClick={() => bulkKeepMutation.mutate(Array.from(keepSelection))}
                                            disabled={!keepSelection.size || bulkKeepMutation.isPending}
                                            className={`px-3 py-1.5 rounded-md text-xs border transition-colors ${keepSelection.size
                                                ? 'border-primary bg-primary/10 text-primary hover:bg-primary/15'
                                                : 'border-border text-foreground-secondary bg-surface-2 cursor-not-allowed'
                                                }`}
                                        >
                                            {bulkKeepMutation.isPending ? 'Применяем...' : 'Оставить выбранные (скрыть остальные)'}
                                        </button>
                                        {keepSelection.size > 0 && (
                                            <span className="text-xs text-foreground-secondary">
                                                Выбрано {keepSelection.size}
                                            </span>
                                        )}
                                    </div>
                                </div>

                                <div className="overflow-auto min-h-0">
                                    {chatsQuery.isLoading && (
                                        <div className="flex items-center justify-center h-full text-foreground-secondary gap-2">
                                            <Loader2 className="w-4 h-4 animate-spin" />
                                            Загружаем чаты...
                                        </div>
                                    )}

                                    {!chatsQuery.isLoading && (!chatsQuery.data?.items?.length || authStatus?.state !== 'ready') && (
                                        <div className="flex flex-col items-center justify-center h-full text-foreground-secondary gap-2 px-4 text-center">
                                            <AlertCircle className="w-5 h-5" />
                                            <p className="text-sm">Нет доступных чатов. Убедитесь, что сессия активна и аккаунт подключен.</p>
                                        </div>
                                    )}

                                    <div className="divide-y divide-border">
                                        {chatsQuery.data?.items.map((chat: TelegramChat) => (
                                            <button
                                                key={chat.chat_id}
                                                onClick={() => setSelectedChatId(chat.chat_id)}
                                                className={`w-full text-left p-4 transition-colors ${chat.chat_id === selectedChatId
                                                    ? 'bg-primary-light/40 border-l-2 border-primary'
                                                    : 'hover:bg-surface-2'
                                                    }`}
                                            >
                                                <div className="flex items-start justify-between gap-2">
                                                    <div className="flex-1">
                                                        <div className="flex items-center gap-2">
                                                            <input
                                                                type="checkbox"
                                                                checked={keepSelection.has(chat.chat_id)}
                                                                onChange={(e) => {
                                                                    e.stopPropagation();
                                                                    toggleKeepChat(chat.chat_id);
                                                                }}
                                                                className="w-4 h-4 text-primary border-border rounded focus:ring-primary"
                                                            />
                                                            <span className="text-sm font-semibold text-foreground">{chat.title}</span>
                                                            <span className="text-[11px] px-2 py-0.5 rounded-full bg-surface-2 border border-border text-foreground-secondary">
                                                                {chatTypeLabel[chat.chat_type] || chat.chat_type}
                                                            </span>
                                                            {chat.is_hidden && (
                                                                <span className="text-[11px] px-2 py-0.5 rounded-full bg-border text-foreground-secondary">
                                                                    скрыт
                                                                </span>
                                                            )}
                                                            {chat.monitor_enabled && (
                                                                <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-success/10 text-success border border-success/40">
                                                                    <BadgeCheck className="w-3 h-3" /> мониторится
                                                                </span>
                                                            )}
                                                        </div>
                                                        <div className="text-xs text-foreground-secondary">
                                                            {chat.username ? `@${chat.username}` : chatTypeLabel[chat.chat_type] || '—'}
                                                        </div>
                                                        {chat.last_message?.text && (
                                                            <div className="text-xs text-foreground-muted mt-1 overflow-hidden text-ellipsis max-h-10">
                                                                {chat.last_message.text}
                                                            </div>
                                                        )}
                                                    </div>
                                                    <div className="flex flex-col items-end gap-2">
                                                        <span className="text-[11px] text-foreground-muted text-right">
                                                            {formatDateTime(chat.last_message?.date || null)}
                                                        </span>
                                                        {!chat.is_hidden ? (
                                                            <button
                                                                onClick={(e) => {
                                                                    e.stopPropagation();
                                                                    hideChatMutation.mutate(chat.chat_id);
                                                                }}
                                                                className="text-xs px-2 py-1 rounded-md border border-border text-foreground-secondary hover:bg-surface-2"
                                                            >
                                                                Скрыть
                                                            </button>
                                                        ) : (
                                                            <button
                                                                onClick={(e) => {
                                                                    e.stopPropagation();
                                                                    unhideChatMutation.mutate(chat.chat_id);
                                                                }}
                                                                className="text-xs px-2 py-1 rounded-md border border-primary text-primary hover:bg-primary-light/40"
                                                            >
                                                                Показать
                                                            </button>
                                                        )}
                                                    </div>
                                                </div>
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            </div>

                            <div className="lg:col-span-2 bg-surface border border-border rounded-lg shadow-sm grid grid-rows-[auto,1fr,auto] h-full min-h-0">
                                <div className="p-4 border-b border-border flex items-center justify-between sticky top-0 bg-surface z-10">
                                    <div>
                                        <div className="flex items-center gap-2">
                                            <MessageSquare className="w-5 h-5 text-foreground-secondary" />
                                            <h2 className="text-sm font-semibold text-foreground">
                                                {currentChat ? currentChat.title : 'Выберите чат'}
                                            </h2>
                                            {currentChat?.monitor_enabled && (
                                                <span className="text-[11px] px-2 py-0.5 rounded-full bg-success/10 text-success border border-success/30 flex items-center gap-1">
                                                    <BadgeCheck className="w-3 h-3" /> серверный монитор
                                                </span>
                                            )}
                                        </div>
                                        <div className="text-xs text-foreground-secondary">
                                            {currentChat
                                                ? currentChat.username
                                                    ? `@${currentChat.username}`
                                                    : chatTypeLabel[currentChat.chat_type] || '—'
                                                : 'Нет выбранного диалога'}
                                        </div>
                                    </div>
                                    {currentChat && (
                                        <div className="flex items-center gap-2 flex-wrap justify-end">
                                            <button
                                                onClick={() => {
                                                    if (!currentChat) return;
                                                    const enable = !currentChat.monitor_enabled;
                                                    monitorToggleMutation.mutate({ chatId: currentChat.chat_id, enabled: enable });
                                                }}
                                                className={`flex items-center gap-2 px-3 py-2 rounded-md text-xs border ${currentChat?.monitor_enabled
                                                    ? 'border-success text-success bg-success/10'
                                                    : 'border-border text-foreground-secondary hover:bg-surface-2'
                                                    }`}
                                            >
                                                {currentChat?.monitor_enabled ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
                                                {currentChat?.monitor_enabled ? 'Серверный монитор вкл' : 'Включить монитор'}
                                            </button>
                                            <button
                                                onClick={() => messagesQuery.refetch()}
                                                disabled={messagesQuery.isFetching}
                                                className="flex items-center gap-1 px-3 py-2 rounded-md border border-border text-foreground-secondary text-xs hover:bg-surface-2 disabled:opacity-60"
                                            >
                                                <RefreshCcw className={`w-4 h-4 ${messagesQuery.isFetching ? 'animate-spin' : ''}`} />
                                                Обновить чат
                                            </button>
                                            {currentChat.is_hidden ? (
                                                <button
                                                    onClick={() => unhideChatMutation.mutate(currentChat.chat_id)}
                                                    className="flex items-center gap-1 px-3 py-2 rounded-md border border-primary text-primary text-xs hover:bg-primary-light/30"
                                                >
                                                    <Eye className="w-4 h-4" />
                                                    Показать
                                                </button>
                                            ) : (
                                                <button
                                                    onClick={() => hideChatMutation.mutate(currentChat.chat_id)}
                                                    className="flex items-center gap-1 px-3 py-2 rounded-md border border-border text-foreground-secondary text-xs hover:bg-surface-2"
                                                >
                                                    <EyeOff className="w-4 h-4" />
                                                    Скрыть
                                                </button>
                                            )}
                                        </div>
                                    )}
                                </div>

                                <div
                                    ref={messagesScrollRef}
                                    className="overflow-auto px-4 py-3 space-y-3 min-h-0"
                                >
                                    {messagesQuery.isLoading && (
                                        <div className="flex items-center justify-center h-full text-foreground-secondary gap-2">
                                            <Loader2 className="w-4 h-4 animate-spin" />
                                            Загружаем сообщения...
                                        </div>
                                    )}

                                    {!messagesQuery.isLoading && !messagesState.length && (
                                        <div className="flex flex-col items-center justify-center h-full text-foreground-secondary gap-2 text-sm">
                                            <AlertCircle className="w-5 h-5" />
                                            Нет сообщений в этом чате
                                        </div>
                                    )}

                                    {messagesState
                                        .filter((m) => typeof m.id === 'number')
                                        .map((message) => {
                                            const msgId = message.id as number;
                                            return (
                                                <MessageItem
                                                    key={`${msgId}-${message.date}`}
                                                    message={message}
                                                    isSelected={selectedMessageIds.has(msgId)}
                                                    status={statuses[msgId]}
                                                    processingId={processingId}
                                                    currentChatId={currentChat?.chat_id || null}
                                                    onToggleSelect={toggleSelectMessage}
                                                    onProcess={(chatId, messageIdArg) => {
                                                        processReceiptMutation.mutate({ chatId, messageId: messageIdArg });
                                                    }}
                                                    onReprocess={(chatId, messageIdArg) => {
                                                        reprocessMutation.mutate({ chatId, messageId: messageIdArg });
                                                    }}
                                                    onPreview={setPreviewUrl}
                                                    formatDateTime={formatDateTime}
                                                />
                                            );
                                        })}
                                </div>

                                <div className="flex items-center justify-between px-4 py-3 border-t border-border bg-surface flex-shrink-0">
                                    <div className="flex items-center gap-3">
                                        <span className="text-sm text-foreground-muted">
                                            Сообщений: {messagesState.length}
                                        </span>
                                        <div className="flex items-center gap-2">
                                            <button
                                                onClick={selectAllMessages}
                                                disabled={!messagesState.length}
                                                className="flex items-center gap-1.5 px-3 py-2 min-h-[40px] rounded-md border border-border text-foreground-secondary text-sm hover:bg-surface-2 disabled:opacity-50 transition-colors"
                                                title="Ctrl/Cmd + A"
                                            >
                                                <CheckSquare className="w-4 h-4" />
                                                Выбрать все
                                            </button>
                                            <button
                                                onClick={deselectAllMessages}
                                                disabled={!selectedMessageIds.size}
                                                className="flex items-center gap-1.5 px-3 py-2 min-h-[40px] rounded-md border border-border text-foreground-secondary text-sm hover:bg-surface-2 disabled:opacity-50 transition-colors"
                                                title="Escape"
                                            >
                                                <Square className="w-4 h-4" />
                                                Снять
                                            </button>
                                        </div>
                                    </div>
                                    <button
                                        onClick={() => {
                                            if (!currentChat) return;
                                            const ids = Array.from(selectedMessageIds);
                                            if (!ids.length) return;
                                            processBatchMutation.mutate({ chatId: currentChat.chat_id, messageIds: ids });
                                        }}
                                        disabled={!selectedMessageIds.size || batchProcessing}
                                        className="px-5 py-2.5 min-h-[44px] rounded-md border-2 border-primary text-primary text-sm font-semibold hover:bg-primary hover:text-foreground-inverse disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                                        title="Ctrl/Cmd + Enter"
                                    >
                                        {batchProcessing ? (
                                            <span className="flex items-center gap-2">
                                                <Loader2 className="w-5 h-5 animate-spin" /> Обрабатываем...
                                            </span>
                                        ) : (
                                            <>▶ Обработать выбранные ({selectedMessageIds.size || 0})</>
                                        )}
                                    </button>
                                </div>

                                <div className="p-4 border-t border-border bg-surface sticky bottom-0">
                                    <div className="flex gap-3 items-end flex-wrap">
                                        <textarea
                                            value={composer}
                                            onChange={(e) => setComposer(e.target.value)}
                                            placeholder={
                                                authStatus?.state === 'ready'
                                                    ? currentChat
                                                        ? 'Введите сообщение...'
                                                        : 'Выберите чат'
                                                    : 'Авторизуйтесь, чтобы отправлять сообщения'
                                            }
                                            className="flex-1 min-h-[80px] px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent bg-input-bg text-input-text resize-none"
                                            disabled={!currentChat || authStatus?.state !== 'ready' || sendMessageMutation.isPending}
                                        />
                                        <div className="flex flex-col gap-1">
                                            <label className="flex items-center gap-2 px-3 py-2 border border-border rounded-lg bg-surface-2 text-xs cursor-pointer hover:bg-surface-2/80">
                                                <span className="text-foreground">Прикрепить PDF</span>
                                                <input
                                                    type="file"
                                                    accept="application/pdf"
                                                    className="hidden"
                                                    onChange={(e) => {
                                                        const file = e.target.files?.[0];
                                                        if (file) setPdfFile(file);
                                                    }}
                                                />
                                            </label>
                                            {pdfFile && (
                                                <div className="text-[11px] text-foreground-muted max-w-[200px] line-clamp-2">
                                                    {pdfFile.name}
                                                </div>
                                            )}
                                        </div>
                                        <button
                                            onClick={() => {
                                                if (!currentChat) return;
                                                if (pdfFile) {
                                                    sendPdfMutation.mutate({
                                                        chatId: currentChat.chat_id,
                                                        file: pdfFile,
                                                        caption: composer.trim() || undefined,
                                                    });
                                                } else {
                                                    if (!composer.trim()) return;
                                                    sendMessageMutation.mutate({ chatId: currentChat.chat_id, text: composer });
                                                }
                                            }}
                                            disabled={
                                                (!pdfFile && !composer.trim()) ||
                                                !currentChat ||
                                                authStatus?.state !== 'ready' ||
                                                sendMessageMutation.isPending ||
                                                sendPdfMutation.isPending
                                            }
                                            className="h-[44px] px-4 bg-primary text-foreground-inverse rounded-lg hover:bg-primary-hover transition-colors flex items-center gap-2 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-primary"
                                        >
                                            {sendMessageMutation.isPending || sendPdfMutation.isPending ? (
                                                <Loader2 className="w-4 h-4 animate-spin" />
                                            ) : (
                                                <Send className="w-4 h-4" />
                                            )}
                                            {pdfFile ? 'Отправить PDF' : 'Отправить'}
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            {previewUrl && (
                <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
                    <div className="bg-white w-11/12 h-[90vh] rounded-lg shadow-lg overflow-hidden relative">
                        <button
                            className="absolute top-3 right-3 text-foreground hover:text-danger"
                            onClick={() => setPreviewUrl(null)}
                        >
                            <XCircle className="w-6 h-6" />
                        </button>
                        <iframe src={previewUrl} title="PDF preview" className="w-full h-full border-0" />
                    </div>
                </div>
            )}
        </>
    );
};
