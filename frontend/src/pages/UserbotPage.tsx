import { MouseEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
    Bot,
    Menu,
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
    Calendar,
    X,
} from 'lucide-react';
import { MessageItem } from '../components/MessageItem';
import { ChatSyncButton } from '../components/ChatSyncButton';
import { ChatHistoryView } from '../components/ChatHistoryView';
import { ErrorBoundary } from '../components/ErrorBoundary';
import {
    telegramClientApi,
    getChatAccessToken,
    securityApi,
    TelegramChat,
    TelegramChatMessage,
    TelegramProcessResult,
} from '../services/api';
import { useToast } from '../components/Toast';
import { ChatPasswordModal } from '../components/ChatPasswordModal';
import { ru } from '../i18n/ru';
import { useAuth } from '../contexts/AuthContext';
import { buildClientStateScope } from '../utils/clientStateScope';
import {
    acknowledgeHiddenOperation,
    applyHiddenSnapshotOverlay,
    buildServerHiddenSnapshot,
    enqueueHiddenOperation,
    loadHiddenSnapshot,
    mergeServerSnapshotWithQueue,
    peekDueHiddenOperation,
    scheduleHiddenRetry,
    setLocalHiddenState,
} from '../services/chatHiddenState';

const stateMeta: Record<
    string,
    { label: string; tone: string; description?: string }
> = {
    wait_tdlib_parameters: {
        label: 'Инициализация',
        tone: 'bg-info-light text-info',
        description: 'Подключение к Telegram...',
    },
    wait_encryption_key: {
        label: 'Разблокировка хранилища',
        tone: 'bg-info-light text-info',
        description: 'Проверяем ключ шифрования...',
    },
    ready: { label: 'Подключено', tone: 'bg-success-light text-success', description: 'Сессия Telegram активна' },
    wait_phone_number: { label: 'Требуется телефон', tone: 'bg-warning-light text-warning' },
    wait_code: { label: 'Ожидается код', tone: 'bg-warning-light text-warning' },
    wait_password: { label: 'Ожидается пароль', tone: 'bg-warning-light text-warning' },
    tdlib_unavailable: { label: 'Сервис недоступен', tone: 'bg-danger-light text-danger' },
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

const backlogStateMeta: Record<string, { label: string; tone: string }> = {
    healthy: { label: 'в норме', tone: 'bg-success/10 text-success border-success/30' },
    lagging: { label: 'отстаёт', tone: 'bg-warning/10 text-warning border-warning/30' },
    stalled: { label: 'застрял', tone: 'bg-danger/10 text-danger border-danger/30' },
    error: { label: 'ошибка', tone: 'bg-danger/10 text-danger border-danger/30' },
};

const MAX_MESSAGE_ITEMS = 2000;
const RECEIPT_STATUS_CHUNK = 50;
const STATUS_COOLDOWN_MS = 60_000;
const SERVER_MESSAGE_LIMIT = 200; // backend enforces le=200
const MUTATION_COOLDOWN_MS = 500; // throttle hide/unhide bursts

export const UserbotPage: React.FC = () => {
    const { showToast } = useToast();
    const { user } = useAuth();
    const queryClient = useQueryClient();
    const stateScopeKey = useMemo(() => buildClientStateScope(user?.username), [user?.username]);

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
    const [liveHistoryExhausted, setLiveHistoryExhausted] = useState(false);
    const [selectedMessageIds, setSelectedMessageIds] = useState<Set<number>>(new Set());
    const [selectionMode, setSelectionMode] = useState(false);
    const [chatViewTab, setChatViewTab] = useState<'live' | 'history'>('live');
    const [statuses, setStatuses] = useState<Record<number, TelegramProcessResult>>({});
    // Deprecated local polling toggle; server monitor toggle is used now.
    // Keep local polling off by default to avoid hammering the API.
    const [liveRefresh] = useState(false);
    const [previewUrl, setPreviewUrl] = useState<string | null>(null);
    const [processingId, setProcessingId] = useState<number | null>(null);
    const [batchProcessing, setBatchProcessing] = useState(false);
    const [dateRangeFrom, setDateRangeFrom] = useState<string>('');
    const [dateRangeTo, setDateRangeTo] = useState<string>('');
    const [showDateRangePicker, setShowDateRangePicker] = useState(false);
    const [passwordModalOpen, setPasswordModalOpen] = useState(false);
    const [passwordModalChat, setPasswordModalChat] = useState<TelegramChat | null>(null);
    const [managePasswordModal, setManagePasswordModal] = useState<{ mode: 'set' | 'remove'; chat: TelegramChat } | null>(null);
    const [managePasswordValue, setManagePasswordValue] = useState('');
    const [managePasswordError, setManagePasswordError] = useState<string | null>(null);
    const [chatContextMenu, setChatContextMenu] = useState<{ chat: TelegramChat; x: number; y: number } | null>(null);
    const [chatDrawerOpen, setChatDrawerOpen] = useState(false);
    const [desktopChatsCollapsed, setDesktopChatsCollapsed] = useState(false);
    const [localHiddenSnapshot, setLocalHiddenSnapshot] = useState<Record<string, boolean>>({});
    const messagesScrollRef = useRef<HTMLDivElement | null>(null);
    const lastAutoScrollChatRef = useRef<number | null>(null);
    const selectedChatButtonRef = useRef<HTMLButtonElement | null>(null);
    const prependScrollAnchorRef = useRef<{ scrollTop: number; scrollHeight: number } | null>(null);
    const hiddenReplayRunningRef = useRef(false);

    // Telegram Access OTP gate
    const [tgOtpCode, setTgOtpCode] = useState('');
    const [tgOtpExpiresAt, setTgOtpExpiresAt] = useState<number | null>(null);
    const [tgOtpSecondsLeft, setTgOtpSecondsLeft] = useState(0);
    const [tgAccessGranted, setTgAccessGranted] = useState(() => Boolean(securityApi.getTelegramAccessToken()));
    const canToggleSources = user?.role === 'admin' || Boolean(user?.can_toggle_sources);

    const securityStatusQuery = useQuery({
        queryKey: ['security-status'],
        queryFn: securityApi.getStatus,
        refetchInterval: 30000,
    });
    const otpEnabled = Boolean(securityStatusQuery.data?.scopes_enabled);

    const requestTgOtpMutation = useMutation({
        mutationFn: () => securityApi.requestTelegramAccessCode(),
        onSuccess: (data) => {
            if (data.otp_skipped && data.token) {
                setTgAccessGranted(true);
                return;
            }
            const seconds = Math.max(0, Number(data.expires_in) || 0);
            setTgOtpCode('');
            setTgOtpSecondsLeft(seconds);
            setTgOtpExpiresAt(Date.now() + seconds * 1000);
        },
    });

    const verifyTgOtpMutation = useMutation({
        mutationFn: (code: string) => securityApi.verifyTelegramAccessCode(code),
        onSuccess: () => {
            setTgAccessGranted(true);
            setTgOtpCode('');
            setTgOtpExpiresAt(null);
            setTgOtpSecondsLeft(0);
        },
    });

    // OTP countdown timer
    useEffect(() => {
        if (!tgOtpExpiresAt) return;
        const timer = window.setInterval(() => {
            const left = Math.max(0, Math.ceil((tgOtpExpiresAt - Date.now()) / 1000));
            setTgOtpSecondsLeft(left);
            if (left <= 0) setTgOtpExpiresAt(null);
        }, 1000);
        return () => window.clearInterval(timer);
    }, [tgOtpExpiresAt]);

    // Auto-request OTP on mount when OTP is enabled and no access
    useEffect(() => {
        if (otpEnabled && !tgAccessGranted && !requestTgOtpMutation.isPending && tgOtpExpiresAt === null) {
            requestTgOtpMutation.mutate();
        }
    }, [otpEnabled, tgAccessGranted]); // eslint-disable-line react-hooks/exhaustive-deps

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
    const chatTypesKey = useMemo(() => Array.from(selectedTypes).sort().join(','), [selectedTypes]);

    const overviewQuery = useQuery({
        queryKey: ['tg-overview', search, chatTypesKey, canToggleSources ? 'with-hidden' : 'without-hidden'],
        queryFn: () =>
            telegramClientApi.getOverview({
                search: search || undefined,
                include_hidden: canToggleSources,
                limit: 500,
                offset: 0,
                chat_types: Array.from(selectedTypes).join(','),
            }),
        refetchInterval: (query) => {
            if (query.state.error) return false; // при 429 или другой ошибке не долбим сервер
            return query.state.data?.auth?.state === 'ready' ? 60000 : 15000;
        },
        staleTime: 15000,
        retry: false,
        refetchOnWindowFocus: false,
    });
    const authStatus = overviewQuery.data?.auth;
    const authLoading = overviewQuery.isLoading;
    const refetchStatus = overviewQuery.refetch;
    const chatsAll = overviewQuery.data?.chats?.items || [];
    const monitorStatus = overviewQuery.data?.monitor;
    const replayHiddenQueue = useCallback(async () => {
        if (hiddenReplayRunningRef.current) return;
        hiddenReplayRunningRef.current = true;
        try {
            while (true) {
                const queued = peekDueHiddenOperation(stateScopeKey);
                if (!queued) break;
                try {
                    await telegramClientApi.setChatHidden(queued.chatId, queued.hidden);
                    acknowledgeHiddenOperation(stateScopeKey, queued.chatId);
                } catch (err: any) {
                    const status = err?.response?.status;
                    if (status === 401 || status === 403) {
                        break;
                    }
                    if (!status || status >= 500 || status === 429) {
                        scheduleHiddenRetry(stateScopeKey, queued.chatId);
                    } else {
                        // invalid operation for this chat on server, drop from retry queue
                        acknowledgeHiddenOperation(stateScopeKey, queued.chatId);
                    }
                }
                await new Promise((resolve) => setTimeout(resolve, MUTATION_COOLDOWN_MS));
            }
        } finally {
            hiddenReplayRunningRef.current = false;
            setLocalHiddenSnapshot(loadHiddenSnapshot(stateScopeKey));
        }
    }, [stateScopeKey]);

    useEffect(() => {
        setLocalHiddenSnapshot(loadHiddenSnapshot(stateScopeKey));
        void replayHiddenQueue();
        const timer = window.setInterval(() => {
            void replayHiddenQueue();
        }, 15000);
        return () => window.clearInterval(timer);
    }, [stateScopeKey, replayHiddenQueue]);

    useEffect(() => {
        if (!chatsAll.length) return;
        const merged = mergeServerSnapshotWithQueue(stateScopeKey, buildServerHiddenSnapshot(chatsAll));
        setLocalHiddenSnapshot(merged);
    }, [chatsAll, stateScopeKey]);

    const chatsWithHiddenState = useMemo(
        () => applyHiddenSnapshotOverlay(chatsAll, localHiddenSnapshot),
        [chatsAll, localHiddenSnapshot],
    );
    const selectedChatMeta = useMemo(
        () => chatsWithHiddenState.find((chat) => chat.chat_id === selectedChatId) || null,
        [chatsWithHiddenState, selectedChatId]
    );
    const hasSelectedChatAccess = useMemo(() => {
        if (!selectedChatMeta) return false;
        if (!selectedChatMeta.is_protected) return true;
        return Boolean(getChatAccessToken(selectedChatMeta.chat_id));
    }, [selectedChatMeta]);

    const messagesQuery = useQuery({
        queryKey: ['tg-messages', selectedChatId],
        queryFn: () =>
            telegramClientApi.getMessages(selectedChatId!, {
                limit: Math.min(MAX_MESSAGE_ITEMS, SERVER_MESSAGE_LIMIT),
            }),
        enabled: !!selectedChatId && authStatus?.state === 'ready' && hasSelectedChatAccess,
        refetchInterval: liveRefresh ? 15000 : false,
    });

    const mergeMessages = useCallback((input: TelegramChatMessage[]): TelegramChatMessage[] => {
        const deduped = new Map<number, TelegramChatMessage>();
        const withoutId: TelegramChatMessage[] = [];
        input.forEach((msg) => {
            if (typeof msg?.id === 'number') {
                deduped.set(msg.id, msg);
            } else if (msg) {
                withoutId.push(msg);
            }
        });
        const sortedWithId = Array.from(deduped.values()).sort((a, b) => {
            const aTime = a?.date ? new Date(a.date).getTime() : 0;
            const bTime = b?.date ? new Date(b.date).getTime() : 0;
            if (aTime !== bTime) return aTime - bTime;
            return (a.id || 0) - (b.id || 0);
        });
        return [...sortedWithId, ...withoutId].slice(-MAX_MESSAGE_ITEMS);
    }, []);

    const oldestLoadedMessageId = useMemo(() => {
        const ids = messagesState
            .map((m) => m?.id)
            .filter((id): id is number => typeof id === 'number');
        if (!ids.length) return null;
        return Math.min(...ids);
    }, [messagesState]);

    const loadOlderMessagesMutation = useMutation({
        mutationFn: async () => {
            if (!selectedChatId || !oldestLoadedMessageId) {
                return {
                    payload: { total: messagesState.length, items: [] as TelegramChatMessage[] },
                    requestedFrom: oldestLoadedMessageId,
                };
            }
            const payload = await telegramClientApi.getMessages(selectedChatId, {
                limit: SERVER_MESSAGE_LIMIT,
                from_message_id: oldestLoadedMessageId,
            });
            return { payload, requestedFrom: oldestLoadedMessageId };
        },
        onMutate: () => {
            const el = messagesScrollRef.current;
            if (!el) return;
            prependScrollAnchorRef.current = {
                scrollTop: el.scrollTop,
                scrollHeight: el.scrollHeight,
            };
        },
        onSuccess: (result) => {
            const incoming = (result?.payload?.items || []).filter((msg) => typeof msg?.id === 'number');
            const requestedFrom = result?.requestedFrom;
            if (!incoming.length) {
                setLiveHistoryExhausted(true);
                return;
            }

            setMessagesState((prev) => {
                const knownIds = new Set(
                    prev.map((m) => m?.id).filter((id): id is number => typeof id === 'number')
                );
                const strictlyOlder = incoming.filter((msg) => {
                    if (typeof msg.id !== 'number') return false;
                    if (knownIds.has(msg.id)) return false;
                    if (requestedFrom === null || requestedFrom === undefined) return true;
                    return msg.id < requestedFrom;
                });
                if (!strictlyOlder.length) {
                    setLiveHistoryExhausted(true);
                    return prev;
                }
                setLiveHistoryExhausted(strictlyOlder.length < SERVER_MESSAGE_LIMIT);
                return mergeMessages([...strictlyOlder, ...prev]);
            });

            const anchor = prependScrollAnchorRef.current;
            if (!anchor) return;
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    const el = messagesScrollRef.current;
                    if (!el) return;
                    const delta = el.scrollHeight - anchor.scrollHeight;
                    el.scrollTop = anchor.scrollTop + delta;
                    prependScrollAnchorRef.current = null;
                });
            });
        },
        onError: (err: any) => {
            const status = err?.response?.status;
            if (status === 429) {
                showToast('error', 'Слишком много запросов. Повторите загрузку старых сообщений чуть позже.');
                return;
            }
            showToast('error', 'Не удалось загрузить старые сообщения');
        },
    });

    const monitorToggleMutation = useMutation({
        mutationFn: (payload: { chatId: number; enabled: boolean }) =>
            telegramClientApi.setMonitor(payload.chatId, payload.enabled, !payload.enabled ? false : true),
        onSuccess: async () => {
            await Promise.all([
                queryClient.invalidateQueries({ queryKey: ['tg-overview'] }),
            ]);
            showToast('success', 'Статус серверного монитора обновлён');
        },
        onError: () => showToast('error', 'Не удалось изменить мониторинг чата'),
    });

    const visibleChats = useMemo(() => {
        const items = chatsWithHiddenState;
        return canToggleSources && showHidden ? items : items.filter((chat) => !chat.is_hidden);
    }, [canToggleSources, chatsWithHiddenState, showHidden]);

    const hiddenChatsCount = useMemo(() => {
        const allItems = chatsWithHiddenState;
        if (!allItems.length) return 0;
        return allItems.filter((chat) => chat.is_hidden).length;
    }, [chatsWithHiddenState]);

    const visibleChatsCount = useMemo(() => {
        const allItems = chatsWithHiddenState;
        if (!allItems.length) return visibleChats.length;
        return allItems.filter((chat) => !chat.is_hidden).length;
    }, [chatsWithHiddenState, visibleChats.length]);

    useEffect(() => {
        if (!canToggleSources && showHidden) {
            setShowHidden(false);
        }
    }, [canToggleSources, showHidden]);

    const selectChatWithAccessCheck = useCallback(
        async (chat: TelegramChat) => {
            if (!chat.is_protected) {
                setSelectedChatId(chat.chat_id);
                return;
            }
            const existingToken = getChatAccessToken(chat.chat_id);
            if (existingToken) {
                setSelectedChatId(chat.chat_id);
                return;
            }

            // Validate lock state before asking for password.
            try {
                const status = await telegramClientApi.getChatPasswordStatus(chat.chat_id);
                if (status.locked) {
                    showToast(
                        'error',
                        `Чат временно заблокирован${status.locked_until ? ` до ${new Date(status.locked_until).toLocaleString()}` : ''}`
                    );
                    return;
                }
            } catch {
                // non-fatal; fallback to modal
            }

            setPasswordModalChat(chat);
            setPasswordModalOpen(true);
        },
        [showToast]
    );

    useEffect(() => {
        if (visibleChats.length) {
            const exists = visibleChats.some((c) => c.chat_id === selectedChatId);
            if (!selectedChatId || !exists) {
                const firstUnlocked =
                    visibleChats.find((chat) => !chat.is_protected || Boolean(getChatAccessToken(chat.chat_id))) ||
                    visibleChats[0];
                setSelectedChatId(firstUnlocked.chat_id);
            }
        } else if (!overviewQuery.isLoading && !visibleChats.length) {
            setSelectedChatId(null);
        }
    }, [visibleChats, overviewQuery.isLoading, selectedChatId]);

    useEffect(() => {
        if (!selectedChatButtonRef.current) return;
        selectedChatButtonRef.current.scrollIntoView({
            block: 'nearest',
            behavior: 'smooth',
        });
    }, [selectedChatId, visibleChats.length]);

    // Reset messages and selections on chat switch
    useEffect(() => {
        setMessagesState([]);
        setLiveHistoryExhausted(false);
        prependScrollAnchorRef.current = null;
        setSelectedMessageIds(new Set());
        setSelectionMode(false);
        setShowDateRangePicker(false);
    }, [selectedChatId]);

    // Fill messages state from query
    useEffect(() => {
        if (messagesQuery.data?.items) {
            setMessagesState((prev) => mergeMessages([...prev, ...messagesQuery.data.items]));
            setLiveHistoryExhausted((messagesQuery.data.items?.length || 0) < SERVER_MESSAGE_LIMIT);
        }
    }, [messagesQuery.data, mergeMessages]);

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
                const chunks = chunkArray(ids, RECEIPT_STATUS_CHUNK);
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
                const status = (err as any)?.response?.status;
                if (status === 429) {
                    showToast(
                        'error',
                        'Слишком частые запросы к статусам чеков — автообновление остановлено на минуту'
                    );
                }
            }
        };
        void loadStatuses();
    }, [messagesState, selectedChatId, showToast]);

    // Live refresh statuses when enabled
    useEffect(() => {
        if (!liveRefresh || !selectedChatId || !messagesState.length) return;
        const chunkArray = (arr: number[], size: number) => {
            const res: number[][] = [];
            for (let i = 0; i < arr.length; i += size) res.push(arr.slice(i, i + size));
            return res;
        };
        let cooldownUntil = 0;
        const interval = setInterval(async () => {
            const now = Date.now();
            if (now < cooldownUntil) return;
            const ids = messagesState
                .map((m) => m.id)
                .filter((id): id is number => typeof id === 'number');
            if (!ids.length) return;
            try {
                const chunks = chunkArray(ids, RECEIPT_STATUS_CHUNK);
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
                const status = (err as any)?.response?.status;
                if (status === 429) {
                    cooldownUntil = now + STATUS_COOLDOWN_MS;
                    showToast('error', '429 от сервера: автообновление пауза 60 сек');
                }
            }
        }, 15000);
        return () => clearInterval(interval);
    }, [liveRefresh, selectedChatId, messagesState, showToast]);

    // Telegram-like autoscroll: jump to bottom on chat switch or when user
    // already near the bottom; preserve position while reading older messages.
    useEffect(() => {
        const el = messagesScrollRef.current;
        if (!el) return;
        const chatChanged = lastAutoScrollChatRef.current !== selectedChatId;
        const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
        const isNearBottom = distanceToBottom < 140;
        if (chatChanged || isNearBottom) {
            el.scrollTop = el.scrollHeight;
        }
        lastAutoScrollChatRef.current = selectedChatId;
    }, [messagesState.length, selectedChatId]);

    useEffect(() => {
        if (!chatContextMenu) return;
        const close = () => setChatContextMenu(null);
        const onKey = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                close();
            }
        };
        window.addEventListener('click', close);
        window.addEventListener('keydown', onKey);
        return () => {
            window.removeEventListener('click', close);
            window.removeEventListener('keydown', onKey);
        };
    }, [chatContextMenu]);

    useEffect(() => {
        if (!chatDrawerOpen) return;
        const previousOverflow = document.body.style.overflow;
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setChatDrawerOpen(false);
            }
        };
        document.body.style.overflow = 'hidden';
        window.addEventListener('keydown', onKeyDown);
        return () => {
            document.body.style.overflow = previousOverflow;
            window.removeEventListener('keydown', onKeyDown);
        };
    }, [chatDrawerOpen]);

    useEffect(() => {
        const onResize = () => {
            if (window.innerWidth >= 1024) {
                setChatDrawerOpen(false);
            }
        };
        window.addEventListener('resize', onResize);
        return () => window.removeEventListener('resize', onResize);
    }, []);

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

    const openChatContextMenu = (event: MouseEvent, chat: TelegramChat) => {
        event.preventDefault();
        event.stopPropagation();
        setChatContextMenu({
            chat,
            x: event.clientX,
            y: event.clientY,
        });
    };

    const handleSetChatPassword = (chat: TelegramChat) => {
        setManagePasswordModal({ mode: 'set', chat });
        setManagePasswordValue('');
        setManagePasswordError(null);
    };

    const handleRemoveChatPassword = (chat: TelegramChat) => {
        setManagePasswordModal({ mode: 'remove', chat });
        setManagePasswordValue('');
        setManagePasswordError(null);
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

    // Select messages by date range
    const selectMessagesByDateRange = useCallback(() => {
        if (!dateRangeFrom || !dateRangeTo) return;

        const fromTs = new Date(dateRangeFrom).getTime();
        const toTs = new Date(dateRangeTo).getTime();

        if (fromTs > toTs) {
            showToast('error', 'Начальная дата должна быть раньше конечной');
            return;
        }

        const selectedIds = messagesState
            .filter((m) => {
                if (!m.date) return false;
                const msgTime = new Date(m.date).getTime();
                return msgTime >= fromTs && msgTime <= toTs;
            })
            .map((m) => m.id)
            .filter((id): id is number => typeof id === 'number');

        setSelectedMessageIds(new Set(selectedIds));
        showToast('success', `Выбрано ${selectedIds.length} сообщений за период`);
    }, [dateRangeFrom, dateRangeTo, messagesState, showToast]);

    // Quick date range presets
    const setDatePreset = useCallback((preset: 'today' | 'yesterday' | 'week' | 'month') => {
        const now = new Date();
        let from: Date;
        let to: Date = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59);

        switch (preset) {
            case 'today':
                from = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
                break;
            case 'yesterday':
                from = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1, 0, 0, 0);
                to = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1, 23, 59, 59);
                break;
            case 'week':
                from = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 7, 0, 0, 0);
                break;
            case 'month':
                from = new Date(now.getFullYear(), now.getMonth(), 1, 0, 0, 0);
                break;
        }

        // Format for datetime-local input
        const formatDate = (d: Date) => {
            const pad = (n: number) => n.toString().padStart(2, '0');
            return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
        };

        setDateRangeFrom(formatDate(from));
        setDateRangeTo(formatDate(to));
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
            const allIds = chatsWithHiddenState.map((c) => c.chat_id);
            const toHide = allIds.filter((id) => !keepIds.includes(id));
            if (!toHide.length) return;
            for (const id of toHide) {
                setLocalHiddenSnapshot(setLocalHiddenState(stateScopeKey, id, true));
                enqueueHiddenOperation(stateScopeKey, id, true);
                try {
                    await telegramClientApi.setChatHidden(id, true);
                    acknowledgeHiddenOperation(stateScopeKey, id);
                } catch (err: any) {
                    const status = err?.response?.status;
                    if (status !== 401 && status !== 403) {
                        scheduleHiddenRetry(stateScopeKey, id);
                    }
                }
                await new Promise((r) => setTimeout(r, MUTATION_COOLDOWN_MS));
            }
        },
        onSuccess: async () => {
            setKeepSelection(new Set());
            setLocalHiddenSnapshot(loadHiddenSnapshot(stateScopeKey));
            void replayHiddenQueue();
            await queryClient.invalidateQueries({ queryKey: ['tg-overview'] });
            showToast('success', 'Оставили выбранные, остальные скрыты');
        },
        onError: () => showToast('error', 'Не удалось применить выбор'),
    });

    const setChatHiddenMutation = useMutation({
        mutationFn: (payload: { chatId: number; hidden: boolean; silent?: boolean }) =>
            telegramClientApi.setChatHidden(payload.chatId, payload.hidden),
        onMutate: async (payload) => {
            setLocalHiddenSnapshot(setLocalHiddenState(stateScopeKey, payload.chatId, payload.hidden));
            enqueueHiddenOperation(stateScopeKey, payload.chatId, payload.hidden);
            if (!showHidden && payload.hidden && selectedChatId === payload.chatId) {
                setSelectedChatId(null);
            }
            return payload;
        },
        onSuccess: (_response, payload) => {
            acknowledgeHiddenOperation(stateScopeKey, payload.chatId);
            if (!payload.silent) {
                showToast('success', payload.hidden ? 'Чат скрыт' : 'Чат показан');
            }
        },
        onError: (err: any, payload) => {
            const status = err?.response?.status;
            if (status !== 401 && status !== 403) {
                scheduleHiddenRetry(stateScopeKey, payload.chatId);
            }
            if (!payload.silent) {
                showToast('error', payload.hidden ? 'Не удалось скрыть чат' : 'Не удалось показать чат');
            }
        },
        onSettled: async () => {
            setLocalHiddenSnapshot(loadHiddenSnapshot(stateScopeKey));
            void replayHiddenQueue();
            await queryClient.invalidateQueries({ queryKey: ['tg-overview'] });
        },
    });

    const setChatPasswordMutation = useMutation({
        mutationFn: (payload: { chatId: number; password: string }) =>
            telegramClientApi.setChatPassword(payload.chatId, payload.password),
        onSuccess: async () => {
            showToast('success', 'Пароль чата установлен');
            await queryClient.invalidateQueries({ queryKey: ['tg-overview'] });
        },
        onError: (err: any) => {
            showToast('error', err?.response?.data?.detail || 'Не удалось установить пароль чата');
        },
    });

    const removeChatPasswordMutation = useMutation({
        mutationFn: (payload: { chatId: number; password: string }) =>
            telegramClientApi.removeChatPassword(payload.chatId, payload.password),
        onSuccess: async () => {
            showToast('success', 'Пароль чата снят');
            await queryClient.invalidateQueries({ queryKey: ['tg-overview'] });
        },
        onError: (err: any) => {
            showToast('error', err?.response?.data?.detail || 'Не удалось снять пароль чата');
        },
    });

    const submitManageChatPassword = useCallback(async () => {
        if (!managePasswordModal) return;
        const password = managePasswordValue.trim();
        if (!password) {
            setManagePasswordError('Введите пароль');
            return;
        }
        setManagePasswordError(null);
        try {
            if (managePasswordModal.mode === 'set') {
                await setChatPasswordMutation.mutateAsync({
                    chatId: managePasswordModal.chat.chat_id,
                    password,
                });
            } else {
                await removeChatPasswordMutation.mutateAsync({
                    chatId: managePasswordModal.chat.chat_id,
                    password,
                });
            }
            setManagePasswordModal(null);
            setManagePasswordValue('');
            setManagePasswordError(null);
        } catch (err: any) {
            setManagePasswordError(
                err?.response?.data?.detail ||
                (managePasswordModal.mode === 'set'
                    ? 'Не удалось установить пароль чата'
                    : 'Не удалось снять пароль чата')
            );
        }
    }, [
        managePasswordModal,
        managePasswordValue,
        setChatPasswordMutation,
        removeChatPasswordMutation,
    ]);

    const sendMessageMutation = useMutation({
        mutationFn: (payload: { chatId: number; text: string }) =>
            telegramClientApi.sendMessage(payload.chatId, payload.text),
        onSuccess: async (_, variables) => {
            setComposer('');
            await queryClient.invalidateQueries({ queryKey: ['tg-messages', variables.chatId] });
            await queryClient.invalidateQueries({ queryKey: ['tg-overview'] });
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
            await queryClient.invalidateQueries({ queryKey: ['tg-overview'] });
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
        onError: (err: any, variables) => {
            const status = err?.response?.status;
            const detail = err?.response?.data?.detail || 'Ошибка обработки';

            // 409 = Already processed (duplicate)
            if (status === 409) {
                showToast('warning', detail);
                // Update status to show it's already done
                setStatuses((prev) => ({
                    ...prev,
                    [variables.messageId]: {
                        chat_id: variables.chatId,
                        message_id: variables.messageId,
                        status: 'done',
                        error: detail,
                    } as TelegramProcessResult,
                }));
            } else {
                showToast('error', detail);
            }
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
        () => visibleChats.find((c) => c.chat_id === selectedChatId) || null,
        [visibleChats, selectedChatId]
    );

    useEffect(() => {
        if (!currentChat || !currentChat.is_protected) return;
        if (getChatAccessToken(currentChat.chat_id)) return;
        setPasswordModalChat(currentChat);
        setPasswordModalOpen(true);
    }, [currentChat]);

    // Keyboard shortcuts
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            const target = e.target as HTMLElement;
            const isInput = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA';

            // Ctrl/Cmd + A - Select all
            if ((e.ctrlKey || e.metaKey) && e.key === 'a' && !isInput) {
                e.preventDefault();
                setSelectionMode(true);
                selectAllMessages();
            }

            // Escape - Deselect all
            if (e.key === 'Escape') {
                deselectAllMessages();
                if (selectionMode) {
                    setSelectionMode(false);
                    setShowDateRangePicker(false);
                }
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
    }, [selectAllMessages, deselectAllMessages, selectedMessageIds, currentChat, processBatchMutation, selectionMode]);

    const verifyChatPassword = useCallback(
        async (password: string): Promise<{ ok: boolean; error?: string }> => {
            if (!passwordModalChat) {
                return { ok: false, error: 'Чат не выбран' };
            }
            try {
                const response = await telegramClientApi.verifyChatPassword(passwordModalChat.chat_id, password);
                if (response.verified) {
                    setSelectedChatId(passwordModalChat.chat_id);
                    setPasswordModalChat(null);
                    return { ok: true };
                }
                if (response.locked) {
                    return {
                        ok: false,
                        error: `Чат временно заблокирован${response.locked_until ? ` до ${new Date(response.locked_until).toLocaleString()}` : ''}`,
                    };
                }
                return {
                    ok: false,
                    error: `Неверный пароль${typeof response.attempts_left === 'number' ? ` (осталось: ${response.attempts_left})` : ''}`,
                };
            } catch (err: any) {
                return {
                    ok: false,
                    error: err?.response?.data?.detail || 'Не удалось проверить пароль чата',
                };
            }
        },
        [passwordModalChat]
    );

    const managePasswordPending = managePasswordModal?.mode === 'set'
        ? setChatPasswordMutation.isPending
        : removeChatPasswordMutation.isPending;

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
            <div className="bg-surface border border-border rounded-lg p-3 flex flex-col gap-2 shadow-sm flex-shrink-0">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 min-w-0">
                        <div className={`px-3 py-1 rounded-full text-sm font-medium ${meta.tone}`}>
                            {meta.label}
                        </div>
                        {meta.description && authStatus.state !== 'ready' && (
                            <span className="text-sm text-foreground-secondary truncate">{meta.description}</span>
                        )}
                    </div>
                    <button
                        onClick={() => {
                            refetchStatus();
                            overviewQuery.refetch();
                        }}
                        className="flex items-center gap-2 px-3 py-1.5 rounded-md border border-border text-xs text-foreground hover:bg-surface-2 transition-colors focus:outline-none focus:ring-2 focus:ring-primary"
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
                    <div className="flex items-center gap-2 text-sm text-foreground min-w-0">
                        <ShieldCheck className="w-4 h-4 text-success" />
                        <div className="min-w-0">
                            <div className="font-semibold">Сессия активна</div>
                            <div className="text-foreground-secondary text-xs truncate">
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

    const renderChatListPanel = (inDrawer = false) => (
        <div className="bg-surface border border-border rounded-lg shadow-sm grid grid-rows-[auto,1fr] h-full min-h-0">
            <div className="p-4 border-b border-border flex flex-col gap-3">
                <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                        <MessageSquare className="w-5 h-5 text-foreground-secondary flex-shrink-0" />
                        <h2 className="text-sm font-semibold text-foreground truncate">
                            Чаты ({visibleChatsCount}, скрыто: {hiddenChatsCount})
                        </h2>
                    </div>
                    <div className="flex items-center gap-2">
                        {inDrawer && (
                            <button
                                type="button"
                                onClick={() => setChatDrawerOpen(false)}
                                className="lg:hidden w-8 h-8 inline-flex items-center justify-center rounded-md border border-border text-foreground-secondary hover:bg-surface-2"
                                title="Закрыть список чатов"
                            >
                                <X className="w-4 h-4" />
                            </button>
                        )}
                        {canToggleSources && (
                            <label className="flex items-center gap-2 text-xs text-foreground-secondary cursor-pointer">
                                <input
                                    type="checkbox"
                                    checked={showHidden}
                                    onChange={(e) => setShowHidden(e.target.checked)}
                                    className="w-4 h-4 text-primary border-border rounded focus:ring-primary"
                                />
                                Показать скрытые
                            </label>
                        )}
                    </div>
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
                {canToggleSources && (
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
                )}
            </div>

            <div className="overflow-auto min-h-0">
                {overviewQuery.isLoading && (
                    <div className="flex items-center justify-center h-full text-foreground-secondary gap-2">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Загружаем чаты...
                    </div>
                )}

                {!overviewQuery.isLoading && (!visibleChats.length || authStatus?.state !== 'ready') && (
                    <div className="flex flex-col items-center justify-center h-full text-foreground-secondary gap-2 px-4 text-center">
                        <AlertCircle className="w-5 h-5" />
                        <p className="text-sm">
                            {authStatus?.state === 'ready' && !showHidden && hiddenChatsCount > 0
                                ? 'Все чаты скрыты. Включите «Показать скрытые» или откройте часть чатов.'
                                : 'Нет доступных чатов. Убедитесь, что сессия активна и аккаунт подключен.'}
                        </p>
                    </div>
                )}

                <div className="divide-y divide-border">
                    {visibleChats.map((chat: TelegramChat) => (
                        <button
                            key={chat.chat_id}
                            ref={!inDrawer && chat.chat_id === selectedChatId ? selectedChatButtonRef : null}
                            onContextMenu={(event) => openChatContextMenu(event, chat)}
                            onClick={() => {
                                void selectChatWithAccessCheck(chat).finally(() => {
                                    if (inDrawer) {
                                        setChatDrawerOpen(false);
                                    }
                                });
                            }}
                            className={`w-full text-left p-4 transition-colors ${chat.chat_id === selectedChatId
                                ? 'bg-primary-light/40 border-l-2 border-primary'
                                : 'hover:bg-surface-2'
                                }`}
                        >
                            <div className="flex items-start justify-between gap-2">
                                <div className="flex-1">
                                    <div className="flex items-center gap-2">
                                        {canToggleSources && (
                                            <input
                                                type="checkbox"
                                                checked={keepSelection.has(chat.chat_id)}
                                                onChange={(e) => {
                                                    e.stopPropagation();
                                                    toggleKeepChat(chat.chat_id);
                                                }}
                                                className="w-4 h-4 text-primary border-border rounded focus:ring-primary"
                                            />
                                        )}
                                        <span className="text-sm font-semibold text-foreground">{chat.title}</span>
                                        <span className="text-[11px] px-2 py-0.5 rounded-full bg-surface-2 border border-border text-foreground-secondary">
                                            {chatTypeLabel[chat.chat_type] || chat.chat_type}
                                        </span>
                                        {chat.is_protected && (
                                            <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-warning/10 text-warning border border-warning/40">
                                                <Lock className="w-3 h-3" /> пароль
                                            </span>
                                        )}
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
                                        {chat.monitor_enabled && chat.backlog_state && backlogStateMeta[chat.backlog_state] && (
                                            <span className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border ${backlogStateMeta[chat.backlog_state].tone}`}>
                                                {backlogStateMeta[chat.backlog_state].label}
                                            </span>
                                        )}
                                    </div>
                                    <div className="text-xs text-foreground-secondary">
                                        {chat.username ? `@${chat.username}` : chatTypeLabel[chat.chat_type] || '—'}
                                    </div>
                                    {chat.monitor_enabled && (
                                        <div className="text-[11px] text-foreground-muted mt-1">
                                            Обработано до: {formatDateTime(chat.last_processed_message_date || null) || '—'}
                                            {' · '}
                                            Последнее сообщение: {formatDateTime(chat.latest_message_date || chat.last_message?.date || null) || '—'}
                                        </div>
                                    )}
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
                                    {canToggleSources && (
                                        !chat.is_hidden ? (
                                            <button
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    setChatHiddenMutation.mutate({ chatId: chat.chat_id, hidden: true });
                                                }}
                                                disabled={setChatHiddenMutation.isPending}
                                                className="text-xs px-2 py-1 rounded-md border border-border text-foreground-secondary hover:bg-surface-2 disabled:opacity-60"
                                            >
                                                Скрыть
                                            </button>
                                        ) : (
                                            <button
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    setChatHiddenMutation.mutate({ chatId: chat.chat_id, hidden: false });
                                                }}
                                                disabled={setChatHiddenMutation.isPending}
                                                className="text-xs px-2 py-1 rounded-md border border-primary text-primary hover:bg-primary-light/40 disabled:opacity-60"
                                            >
                                                Показать
                                            </button>
                                        )
                                    )}
                                </div>
                            </div>
                        </button>
                    ))}
                </div>
            </div>
        </div>
    );

    // OTP gate: require code for Telegram access when OTP is enabled
    if (otpEnabled && !tgAccessGranted) {
        return (
            <div className="h-full w-full p-6 bg-bg text-foreground">
                <div className="max-w-xl mx-auto bg-surface border border-border rounded-lg p-6 space-y-4">
                    <h2 className="text-xl font-semibold">{ru.telegram.accessTitle}</h2>
                    <p className="text-sm text-foreground-secondary">
                        {ru.telegram.accessDescription}
                    </p>

                    <div className="space-y-3">
                        <button
                            type="button"
                            className="px-3 py-2 rounded-lg border border-primary/40 bg-primary/10 hover:bg-primary/20 disabled:opacity-50"
                            disabled={requestTgOtpMutation.isPending}
                            onClick={() => requestTgOtpMutation.mutate()}
                        >
                            {requestTgOtpMutation.isPending ? ru.scope.requesting : ru.scope.requestOtp}
                        </button>

                        {tgOtpExpiresAt !== null || tgOtpSecondsLeft > 0 ? (
                            <div className="space-y-2">
                                <input
                                    type="text"
                                    value={tgOtpCode}
                                    maxLength={6}
                                    onChange={(e) => setTgOtpCode(e.target.value)}
                                    placeholder={ru.scope.enterCodePlaceholder}
                                    className="w-full px-3 py-2 rounded-lg border border-border bg-bg"
                                />
                                <div className="text-xs text-foreground-secondary">
                                    {tgOtpSecondsLeft > 0 ? `${ru.scope.codeValidFor}: ${tgOtpSecondsLeft}с` : ru.scope.codeExpired}
                                </div>
                                <button
                                    type="button"
                                    className="px-3 py-2 rounded-lg border border-success/40 bg-success/10 hover:bg-success/20 disabled:opacity-50"
                                    disabled={!tgOtpCode.trim() || verifyTgOtpMutation.isPending}
                                    onClick={() => verifyTgOtpMutation.mutate(tgOtpCode.trim())}
                                >
                                    {verifyTgOtpMutation.isPending ? ru.scope.verifying : ru.scope.verifyCode}
                                </button>
                            </div>
                        ) : null}

                        {requestTgOtpMutation.isError ? (
                            <div className="text-xs text-danger">
                                {(requestTgOtpMutation.error as any)?.response?.data?.detail || ru.telegram.otpRequestFailed}
                            </div>
                        ) : null}
                        {verifyTgOtpMutation.isError ? (
                            <div className="text-xs text-danger">
                                {(verifyTgOtpMutation.error as any)?.response?.data?.detail || ru.telegram.otpInvalidCode}
                            </div>
                        ) : null}
                    </div>
                </div>
            </div>
        );
    }

    return (
        <ErrorBoundary
            title="Ошибка в Telegram-клиенте"
            description="Компонент чатов временно недоступен. Повторите загрузку."
            onRetry={() => {
                overviewQuery.refetch();
                if (selectedChatId) {
                    messagesQuery.refetch();
                }
            }}
        >
            <>
            <div className="h-full min-h-0 flex flex-col bg-bg">
                <div className="flex-1 overflow-hidden p-4 md:p-6 min-h-0">
                    <div className="max-w-[1500px] mx-auto h-full min-h-0 flex flex-col gap-2">
                        <div className="flex items-center justify-between gap-3 flex-shrink-0">
                            <div className="flex items-center gap-3">
                                <button
                                    type="button"
                                    onClick={() => setChatDrawerOpen(true)}
                                    className="lg:hidden inline-flex items-center gap-1 px-3 py-2 rounded-md border border-border text-xs text-foreground-secondary hover:bg-surface-2 transition-colors"
                                >
                                    <Menu className="w-4 h-4" />
                                    Чаты
                                </button>
                                <button
                                    type="button"
                                    onClick={() => setDesktopChatsCollapsed((prev) => !prev)}
                                    className="hidden lg:inline-flex items-center gap-1 px-3 py-2 rounded-md border border-border text-xs text-foreground-secondary hover:bg-surface-2 transition-colors"
                                >
                                    <Menu className="w-4 h-4" />
                                    {desktopChatsCollapsed ? 'Показать чаты' : 'Скрыть чаты'}
                                </button>
                                <div className="p-3 rounded-lg bg-gradient-to-br from-primary to-primary-dark text-foreground-inverse shadow-md">
                                    <Bot className="w-6 h-6" />
                                </div>
                                <div>
                                    <h1 className="text-xl font-semibold text-foreground">Telegram Chats</h1>
                                    <p className="text-sm text-foreground-secondary hidden lg:block">
                                        Диалоги, сообщения и мониторинг в одном окне.
                                    </p>
                                </div>
                            </div>
                            <button
                                onClick={() => {
                                    refetchStatus();
                                    overviewQuery.refetch();
                                    if (currentChat) {
                                        messagesQuery.refetch();
                                    }
                                }}
                                className="flex items-center gap-2 px-3 py-2 rounded-md border border-border text-xs text-foreground hover:bg-surface-2 transition-colors focus:outline-none focus:ring-2 focus:ring-primary"
                            >
                                <RefreshCcw className="w-4 h-4" />
                                Обновить
                            </button>
                        </div>

                        {authStatus?.state === 'ready' ? (
                            <div className="bg-surface border border-border rounded-lg p-2.5 flex flex-wrap items-center gap-2 text-xs shadow-sm flex-shrink-0">
                                <span className="inline-flex items-center gap-2 px-2.5 py-1 rounded-md border border-success/40 bg-success/10 text-success">
                                    <ShieldCheck className="w-3.5 h-3.5" />
                                    TDLib подключен
                                </span>
                                <span className="px-2.5 py-1 rounded-md border border-border bg-surface-2 text-foreground-secondary truncate max-w-[280px]">
                                    {authStatus.user?.first_name} {authStatus.user?.last_name} ({authStatus.user?.username || authStatus.phone_number})
                                </span>
                                <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-border bg-surface-2 text-foreground-secondary">
                                    <Sparkles className="w-3.5 h-3.5 text-primary" />
                                    Очередь: {monitorStatus?.queue_size ?? '—'}
                                </span>
                                <span className="px-2.5 py-1 rounded-md border border-border bg-surface-2 text-foreground-secondary">
                                    Воркеров: {monitorStatus?.workers ?? '—'}
                                </span>
                                <span
                                    className={`px-2.5 py-1 rounded-md border ${monitorStatus?.running
                                        ? 'border-success text-success bg-success/10'
                                        : 'border-border text-foreground-secondary bg-surface-2'
                                        }`}
                                >
                                    {monitorStatus?.running ? 'Монитор работает' : 'Монитор остановлен'}
                                </span>
                            </div>
                        ) : (
                            renderAuthPanel()
                        )}

                        <div className="flex gap-4 flex-1 min-h-0">
                            {!desktopChatsCollapsed && (
                                <div className="hidden lg:block w-[360px] min-w-[320px] h-full">
                                    {renderChatListPanel(false)}
                                </div>
                            )}

                            <div className="flex-1 min-w-0 bg-surface border border-border rounded-lg shadow-sm flex flex-col h-full min-h-0">
                                <div className="p-4 border-b border-border flex items-center justify-between flex-shrink-0">
                                    <div>
                                        <div className="flex items-center gap-2">
                                            <button
                                                type="button"
                                                onClick={() => setChatDrawerOpen(true)}
                                                className="lg:hidden inline-flex items-center justify-center w-8 h-8 rounded-md border border-border text-foreground-secondary hover:bg-surface-2"
                                                title="Открыть список чатов"
                                            >
                                                <Menu className="w-4 h-4" />
                                            </button>
                                            <MessageSquare className="w-5 h-5 text-foreground-secondary" />
                                            <h2 className="text-sm font-semibold text-foreground">
                                                {currentChat ? currentChat.title : 'Выберите чат'}
                                            </h2>
                                            {currentChat?.monitor_enabled && (
                                                <span className="text-[11px] px-2 py-0.5 rounded-full bg-success/10 text-success border border-success/30 flex items-center gap-1">
                                                    <BadgeCheck className="w-3 h-3" /> серверный монитор
                                                </span>
                                            )}
                                            {currentChat?.monitor_enabled && currentChat.backlog_state && backlogStateMeta[currentChat.backlog_state] && (
                                                <span className={`text-[11px] px-2 py-0.5 rounded-full border ${backlogStateMeta[currentChat.backlog_state].tone}`}>
                                                    {backlogStateMeta[currentChat.backlog_state].label}
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
                                        {currentChat?.monitor_enabled && (
                                            <div className="text-[11px] text-foreground-muted mt-1">
                                                Обработано до: {formatDateTime(currentChat.last_processed_message_date || null) || '—'}
                                                {' · '}
                                                Последнее сообщение: {formatDateTime(currentChat.latest_message_date || currentChat.last_message?.date || null) || '—'}
                                                {typeof currentChat.backlog_lag_messages === 'number' && currentChat.backlog_lag_messages > 0
                                                    ? ` · лаг: ${currentChat.backlog_lag_messages}`
                                                    : ''}
                                            </div>
                                        )}
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
                                                        disabled={monitorToggleMutation.isPending}
                                                    >
                                                        {currentChat?.monitor_enabled ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
                                                        {currentChat?.monitor_enabled ? 'Серверный монитор вкл' : 'Включить монитор'}
                                                    </button>
                                                    <ChatSyncButton chatId={currentChat.chat_id} />
                                                    <button
                                                onClick={() => messagesQuery.refetch()}
                                                disabled={messagesQuery.isFetching}
                                                className="flex items-center gap-1 px-3 py-2 rounded-md border border-border text-foreground-secondary text-xs hover:bg-surface-2 disabled:opacity-60"
                                            >
                                                <RefreshCcw className={`w-4 h-4 ${messagesQuery.isFetching ? 'animate-spin' : ''}`} />
                                                Обновить чат
                                            </button>
                                                    <button
                                                        onClick={() => {
                                                            setSelectionMode((prev) => {
                                                                const next = !prev;
                                                                if (!next) {
                                                                    setSelectedMessageIds(new Set());
                                                                    setShowDateRangePicker(false);
                                                                }
                                                                return next;
                                                            });
                                                        }}
                                                        className={`flex items-center gap-1 px-3 py-2 rounded-md border text-xs transition-colors ${selectionMode
                                                            ? 'border-primary text-primary bg-primary/10'
                                                            : 'border-border text-foreground-secondary hover:bg-surface-2'
                                                            }`}
                                                    >
                                                        {selectionMode ? 'Готово' : 'Выбрать'}
                                                    </button>
                                                    {canToggleSources && (
                                                        currentChat.is_hidden ? (
                                                            <button
                                                                onClick={() => setChatHiddenMutation.mutate({ chatId: currentChat.chat_id, hidden: false })}
                                                                disabled={setChatHiddenMutation.isPending}
                                                                className="flex items-center gap-1 px-3 py-2 rounded-md border border-primary text-primary text-xs hover:bg-primary-light/30 disabled:opacity-60"
                                                            >
                                                                <Eye className="w-4 h-4" />
                                                                Показать
                                                            </button>
                                                        ) : (
                                                            <button
                                                                onClick={() => setChatHiddenMutation.mutate({ chatId: currentChat.chat_id, hidden: true })}
                                                                disabled={setChatHiddenMutation.isPending}
                                                                className="flex items-center gap-1 px-3 py-2 rounded-md border border-border text-foreground-secondary text-xs hover:bg-surface-2 disabled:opacity-60"
                                                            >
                                                                <EyeOff className="w-4 h-4" />
                                                                Скрыть
                                                            </button>
                                                        )
                                                    )}
                                        </div>
                                    )}
                                </div>

                                {/* LIVE / HISTORY tabs */}
                                <div className="flex items-center gap-0 border-b border-border flex-shrink-0">
                                    <button
                                        type="button"
                                        onClick={() => setChatViewTab('live')}
                                        className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors ${
                                            chatViewTab === 'live'
                                                ? 'border-primary text-primary'
                                                : 'border-transparent text-foreground-secondary hover:text-foreground'
                                        }`}
                                    >
                                        LIVE
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => setChatViewTab('history')}
                                        className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors ${
                                            chatViewTab === 'history'
                                                ? 'border-primary text-primary'
                                                : 'border-transparent text-foreground-secondary hover:text-foreground'
                                        }`}
                                    >
                                        ИСТОРИЯ
                                    </button>
                                </div>

                                {chatViewTab === 'history' && currentChat ? (
                                    <ChatHistoryView
                                        chatId={currentChat.chat_id}
                                        onProcessReceipt={(messageId) => {
                                            processReceiptMutation.mutate({
                                                chatId: currentChat.chat_id,
                                                messageId,
                                            });
                                        }}
                                    />
                                ) : (
                                <>
                                <div
                                    ref={messagesScrollRef}
                                    className="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-3"
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

                                    {!!messagesState.length && (
                                        <div className="flex justify-center pb-2">
                                            <button
                                                type="button"
                                                onClick={() => loadOlderMessagesMutation.mutate()}
                                                disabled={
                                                    loadOlderMessagesMutation.isPending
                                                    || !oldestLoadedMessageId
                                                    || liveHistoryExhausted
                                                }
                                                className="px-3 py-1.5 rounded-md border border-border text-xs text-foreground-secondary hover:bg-surface-2 disabled:opacity-50"
                                            >
                                                {loadOlderMessagesMutation.isPending
                                                    ? 'Загружаем...'
                                                    : liveHistoryExhausted
                                                        ? 'История загружена полностью'
                                                        : 'Загрузить старые сообщения'}
                                            </button>
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
                                                    selectionMode={selectionMode}
                                                    isSelected={selectedMessageIds.has(msgId)}
                                                    status={statuses[msgId]}
                                                    processingId={processingId}
                                                    currentChatId={currentChat?.chat_id || null}
                                                    showProcessingControls={selectionMode}
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

                                {selectionMode && (
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
                                            <button
                                                onClick={() => setShowDateRangePicker(!showDateRangePicker)}
                                                className={`flex items-center gap-1.5 px-3 py-2 min-h-[40px] rounded-md border text-sm transition-colors ${showDateRangePicker
                                                    ? 'border-primary bg-primary/10 text-primary'
                                                    : 'border-border text-foreground-secondary hover:bg-surface-2'
                                                    }`}
                                            >
                                                <Calendar className="w-4 h-4" />
                                                За период
                                            </button>
                                        </div>
                                    </div>

                                    {/* Date Range Picker Panel */}
                                    {showDateRangePicker && (
                                        <div className="bg-surface-2 border border-border rounded-lg p-4 space-y-3">
                                            <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                                                <Calendar className="w-4 h-4 text-primary" />
                                                Выбрать сообщения за период
                                            </div>
                                            <div className="flex flex-wrap items-center gap-3">
                                                <div className="flex items-center gap-2">
                                                    <label className="text-xs text-foreground-secondary">От:</label>
                                                    <input
                                                        type="datetime-local"
                                                        value={dateRangeFrom}
                                                        onChange={(e) => setDateRangeFrom(e.target.value)}
                                                        className="px-2 py-1.5 text-sm border border-border rounded-md bg-input-bg text-input-text focus:ring-2 focus:ring-primary focus:border-transparent"
                                                    />
                                                </div>
                                                <div className="flex items-center gap-2">
                                                    <label className="text-xs text-foreground-secondary">До:</label>
                                                    <input
                                                        type="datetime-local"
                                                        value={dateRangeTo}
                                                        onChange={(e) => setDateRangeTo(e.target.value)}
                                                        className="px-2 py-1.5 text-sm border border-border rounded-md bg-input-bg text-input-text focus:ring-2 focus:ring-primary focus:border-transparent"
                                                    />
                                                </div>
                                                <button
                                                    onClick={selectMessagesByDateRange}
                                                    disabled={!dateRangeFrom || !dateRangeTo}
                                                    className="px-4 py-1.5 text-sm rounded-md bg-primary text-foreground-inverse hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                                                >
                                                    Выбрать
                                                </button>
                                            </div>
                                            <div className="flex flex-wrap gap-2">
                                                <span className="text-xs text-foreground-muted">Быстро:</span>
                                                <button
                                                    onClick={() => setDatePreset('today')}
                                                    className="px-2 py-1 text-xs rounded border border-border text-foreground-secondary hover:bg-surface hover:text-foreground transition-colors"
                                                >
                                                    Сегодня
                                                </button>
                                                <button
                                                    onClick={() => setDatePreset('yesterday')}
                                                    className="px-2 py-1 text-xs rounded border border-border text-foreground-secondary hover:bg-surface hover:text-foreground transition-colors"
                                                >
                                                    Вчера
                                                </button>
                                                <button
                                                    onClick={() => setDatePreset('week')}
                                                    className="px-2 py-1 text-xs rounded border border-border text-foreground-secondary hover:bg-surface hover:text-foreground transition-colors"
                                                >
                                                    7 дней
                                                </button>
                                                <button
                                                    onClick={() => setDatePreset('month')}
                                                    className="px-2 py-1 text-xs rounded border border-border text-foreground-secondary hover:bg-surface hover:text-foreground transition-colors"
                                                >
                                                    Этот месяц
                                                </button>
                                            </div>
                                        </div>
                                    )}
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
                                )}

                                <div className="p-4 border-t border-border bg-surface flex-shrink-0">
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
                                            className="flex-1 min-h-[56px] max-h-[160px] px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent bg-input-bg text-input-text resize-y"
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
                                </>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            </div >
            {chatDrawerOpen && (
                <div className="fixed inset-0 z-40 lg:hidden">
                    <button
                        type="button"
                        className="absolute inset-0 bg-black/45 backdrop-blur-[1px]"
                        onClick={() => setChatDrawerOpen(false)}
                        aria-label="Закрыть меню чатов"
                    />
                    <div className="absolute inset-y-0 left-0 w-[min(94vw,420px)] p-3">
                        {renderChatListPanel(true)}
                    </div>
                </div>
            )}
            {chatContextMenu && (
                <div
                    className="fixed z-50 min-w-[220px] bg-surface border border-border rounded-lg shadow-xl p-2"
                    style={{ left: chatContextMenu.x, top: chatContextMenu.y }}
                    onClick={(event) => event.stopPropagation()}
                >
                    <div className="px-2 py-1 text-xs text-foreground-secondary">
                        {chatContextMenu.chat.title}
                    </div>
                    <button
                        type="button"
                        className="w-full text-left px-3 py-2 text-sm rounded hover:bg-surface-2"
                        onClick={() => {
                            handleSetChatPassword(chatContextMenu.chat);
                            setChatContextMenu(null);
                        }}
                        disabled={setChatPasswordMutation.isPending}
                    >
                        Установить пароль
                    </button>
                    {chatContextMenu.chat.is_protected && (
                        <button
                            type="button"
                            className="w-full text-left px-3 py-2 text-sm rounded hover:bg-surface-2"
                            onClick={() => {
                                handleRemoveChatPassword(chatContextMenu.chat);
                                setChatContextMenu(null);
                            }}
                            disabled={removeChatPasswordMutation.isPending}
                        >
                            Снять пароль
                        </button>
                    )}
                    {canToggleSources && (
                        <button
                            type="button"
                            className="w-full text-left px-3 py-2 text-sm rounded hover:bg-surface-2"
                            onClick={() => {
                                if (chatContextMenu.chat.is_hidden) {
                                    setChatHiddenMutation.mutate({ chatId: chatContextMenu.chat.chat_id, hidden: false });
                                } else {
                                    setChatHiddenMutation.mutate({ chatId: chatContextMenu.chat.chat_id, hidden: true });
                                }
                                setChatContextMenu(null);
                            }}
                            disabled={setChatHiddenMutation.isPending}
                        >
                            {chatContextMenu.chat.is_hidden ? 'Показать чат' : 'Скрыть чат'}
                        </button>
                    )}
                </div>
            )}
            {managePasswordModal && (
                <div className="fixed inset-0 z-[var(--z-overlay)] bg-black/50 flex items-center justify-center p-4">
                    <div className="w-full max-w-sm rounded-lg border border-border bg-surface p-5 shadow-lg">
                        <h3 className="text-base font-semibold text-foreground mb-1">
                            {managePasswordModal.mode === 'set' ? 'Установить пароль' : 'Снять пароль'}
                        </h3>
                        <p className="text-sm text-foreground-secondary mb-4">
                            {managePasswordModal.mode === 'set'
                                ? `Введите новый пароль для "${managePasswordModal.chat.title}"`
                                : `Введите текущий пароль для "${managePasswordModal.chat.title}"`}
                        </p>
                        <input
                            type="password"
                            value={managePasswordValue}
                            onChange={(e) => setManagePasswordValue(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' && managePasswordValue.trim() && !managePasswordPending) {
                                    void submitManageChatPassword();
                                }
                            }}
                            className="w-full px-3 py-2 border border-border rounded-md bg-input-bg text-input-text"
                            autoFocus
                        />
                        {managePasswordError && (
                            <div className="mt-2 text-sm text-danger">{managePasswordError}</div>
                        )}
                        <div className="mt-4 flex justify-end gap-2">
                            <button
                                type="button"
                                onClick={() => {
                                    setManagePasswordModal(null);
                                    setManagePasswordValue('');
                                    setManagePasswordError(null);
                                }}
                                className="px-3 py-2 text-sm border border-border rounded-md"
                                disabled={managePasswordPending}
                            >
                                Отмена
                            </button>
                            <button
                                type="button"
                                onClick={() => {
                                    void submitManageChatPassword();
                                }}
                                disabled={!managePasswordValue.trim() || managePasswordPending}
                                className="px-3 py-2 text-sm bg-primary text-foreground-inverse rounded-md disabled:opacity-50"
                            >
                                {managePasswordPending
                                    ? 'Сохраняем...'
                                    : managePasswordModal.mode === 'set'
                                        ? 'Установить'
                                        : 'Снять'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
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
            )
            }
            <ChatPasswordModal
                open={passwordModalOpen}
                chatTitle={passwordModalChat?.title}
                onClose={() => {
                    setPasswordModalOpen(false);
                    setPasswordModalChat(null);
                }}
                onSubmit={verifyChatPassword}
            />
            </>
        </ErrorBoundary>
    );
};
