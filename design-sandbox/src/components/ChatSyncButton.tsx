import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, Loader2, CheckCircle2, XCircle, CalendarRange } from 'lucide-react';
import { telegramClientApi, type TelegramHistoryLoadRequest, type TelegramHistoryLoadStatus } from '../services/api';

interface ChatSyncButtonProps {
    chatId: number;
    wsRef?: React.RefObject<WebSocket | null>;
    compact?: boolean;
}

export const ChatSyncButton: React.FC<ChatSyncButtonProps> = ({ chatId, wsRef, compact }) => {
    const queryClient = useQueryClient();
    const [wsProgress, setWsProgress] = useState<{ loaded: number; cursor: number } | null>(null);
    const [showPeriodPanel, setShowPeriodPanel] = useState(false);
    const [dateFrom, setDateFrom] = useState('');
    const [dateTo, setDateTo] = useState('');
    const [excludeEnabled, setExcludeEnabled] = useState(false);
    const [excludeFrom, setExcludeFrom] = useState('');
    const [excludeTo, setExcludeTo] = useState('');
    const prevChatIdRef = useRef(chatId);

    // Reset WS progress when chat changes
    useEffect(() => {
        if (prevChatIdRef.current !== chatId) {
            setWsProgress(null);
            prevChatIdRef.current = chatId;
        }
    }, [chatId]);

    const statusQuery = useQuery({
        queryKey: ['history-load-status', chatId],
        queryFn: () => telegramClientApi.getHistoryLoadStatus(chatId),
        refetchInterval: (query) => {
            const data = query.state.data as TelegramHistoryLoadStatus | undefined;
            if (data?.running) return 5000;
            return false;
        },
        enabled: chatId > 0,
    });

    const startMutation = useMutation({
        mutationFn: (payload: TelegramHistoryLoadRequest = {}) =>
            telegramClientApi.startHistoryLoad(chatId, {
                ...payload,
            }),
        onSuccess: () => {
            setWsProgress(null);
            queryClient.invalidateQueries({ queryKey: ['history-load-status', chatId] });
        },
    });

    // Listen to WS progress events
    useEffect(() => {
        const ws = wsRef?.current;
        if (!ws) return;

        function onMessage(event: MessageEvent) {
            try {
                const data = JSON.parse(event.data);
                if (
                    data.type === 'progress' &&
                    data.channel === 'history' &&
                    data.chat_id === chatId &&
                    data.status === 'running'
                ) {
                    setWsProgress({ loaded: data.loaded || 0, cursor: data.cursor_message_id || 0 });
                }
                if (
                    data.type === 'progress' &&
                    data.channel === 'history' &&
                    data.chat_id === chatId &&
                    (data.status === 'completed' || data.status === 'failed')
                ) {
                    setWsProgress(null);
                    queryClient.invalidateQueries({ queryKey: ['history-load-status', chatId] });
                }
            } catch {
                // ignore
            }
        }

        ws.addEventListener('message', onMessage);
        return () => ws.removeEventListener('message', onMessage);
    }, [chatId, wsRef, queryClient]);

    const status = statusQuery.data;
    const isRunning = status?.running === true;
    const loadedCount = wsProgress?.loaded ?? status?.loaded_count ?? 0;
    const dateRangeInvalid = Boolean(dateFrom && dateTo && dateFrom > dateTo);
    const excludeRangeInvalid = excludeEnabled && Boolean(
        !excludeFrom || !excludeTo || excludeFrom > excludeTo
    );

    const buildPayload = useCallback((restart = false): TelegramHistoryLoadRequest => {
        const payload: TelegramHistoryLoadRequest = { restart };
        if (dateFrom) payload.date_from = dateFrom;
        if (dateTo) payload.date_to = dateTo;
        if (excludeEnabled && excludeFrom && excludeTo) {
            payload.exclude_from = excludeFrom;
            payload.exclude_to = excludeTo;
        }
        return payload;
    }, [dateFrom, dateTo, excludeEnabled, excludeFrom, excludeTo]);

    const handleStart = useCallback(() => {
        if (dateRangeInvalid || excludeRangeInvalid) return;
        startMutation.mutate(buildPayload(false));
    }, [buildPayload, dateRangeInvalid, excludeRangeInvalid, startMutation]);

    const handleRestart = useCallback(() => {
        if (dateRangeInvalid || excludeRangeInvalid) return;
        startMutation.mutate(buildPayload(true));
    }, [buildPayload, dateRangeInvalid, excludeRangeInvalid, startMutation]);

    if (statusQuery.isLoading) {
        return null;
    }

    // Running state — show progress
    if (isRunning) {
        return (
            <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-md border border-primary/30 bg-primary/5 text-xs text-primary">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Синхронизация: {loadedCount.toLocaleString()}</span>
            </div>
        );
    }

    // Completed state
    if (status?.status === 'completed' && loadedCount > 0) {
        return (
            <div className="inline-flex items-center gap-1.5 flex-wrap">
                <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-success/30 bg-success/5 text-xs text-success">
                    <CheckCircle2 className="w-3 h-3" />
                    {loadedCount.toLocaleString()} сообщ.
                </span>
                {!compact && (
                    <button
                        type="button"
                        onClick={() => setShowPeriodPanel((prev) => !prev)}
                        className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-border text-xs text-foreground-secondary hover:bg-surface-2"
                        title="Период синхронизации"
                    >
                        <CalendarRange className="w-3 h-3" />
                        Период
                    </button>
                )}
                <button
                    type="button"
                    onClick={handleRestart}
                    disabled={startMutation.isPending || dateRangeInvalid || excludeRangeInvalid}
                    className="px-2 py-1 rounded-md border border-border text-xs text-foreground-secondary hover:bg-surface-2 disabled:opacity-50"
                    title="Пересинхронизировать с начала"
                >
                    {startMutation.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Пересинхр.'}
                </button>
                {!compact && showPeriodPanel && (
                    <div className="w-full rounded-md border border-border bg-surface p-2 space-y-2 text-xs">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                            <label className="space-y-1">
                                <span className="text-foreground-secondary">От</span>
                                <input
                                    type="date"
                                    value={dateFrom}
                                    onChange={(e) => setDateFrom(e.target.value)}
                                    className="w-full px-2 py-1 rounded-md border border-border bg-input-bg text-input-text"
                                />
                            </label>
                            <label className="space-y-1">
                                <span className="text-foreground-secondary">До</span>
                                <input
                                    type="date"
                                    value={dateTo}
                                    onChange={(e) => setDateTo(e.target.value)}
                                    className="w-full px-2 py-1 rounded-md border border-border bg-input-bg text-input-text"
                                />
                            </label>
                        </div>
                        <label className="inline-flex items-center gap-2">
                            <input
                                type="checkbox"
                                checked={excludeEnabled}
                                onChange={(e) => setExcludeEnabled(e.target.checked)}
                            />
                            <span>Исключить период</span>
                        </label>
                        {excludeEnabled && (
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                                <label className="space-y-1">
                                    <span className="text-foreground-secondary">Искл. от</span>
                                    <input
                                        type="date"
                                        value={excludeFrom}
                                        onChange={(e) => setExcludeFrom(e.target.value)}
                                        className="w-full px-2 py-1 rounded-md border border-border bg-input-bg text-input-text"
                                    />
                                </label>
                                <label className="space-y-1">
                                    <span className="text-foreground-secondary">Искл. до</span>
                                    <input
                                        type="date"
                                        value={excludeTo}
                                        onChange={(e) => setExcludeTo(e.target.value)}
                                        className="w-full px-2 py-1 rounded-md border border-border bg-input-bg text-input-text"
                                    />
                                </label>
                            </div>
                        )}
                        {(dateRangeInvalid || excludeRangeInvalid) && (
                            <div className="text-danger">Проверьте корректность диапазонов дат.</div>
                        )}
                    </div>
                )}
            </div>
        );
    }

    // Failed state
    if (status?.status === 'failed') {
        return (
            <div className="inline-flex items-center gap-1.5 flex-wrap">
                <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-danger/30 bg-danger/5 text-xs text-danger">
                    <XCircle className="w-3 h-3" />
                    Ошибка
                </span>
                <button
                    type="button"
                    onClick={handleStart}
                    disabled={startMutation.isPending || dateRangeInvalid || excludeRangeInvalid}
                    className="px-2 py-1 rounded-md border border-primary/30 text-xs text-primary hover:bg-primary/5 disabled:opacity-50"
                >
                    Повторить
                </button>
            </div>
        );
    }

    // Idle / partially loaded — show sync button
    return (
        <div className="inline-flex items-center gap-1.5 flex-wrap">
            <button
                type="button"
                onClick={handleStart}
                disabled={startMutation.isPending || dateRangeInvalid || excludeRangeInvalid}
                className={`inline-flex items-center gap-1.5 rounded-md border border-border text-xs text-foreground-secondary hover:bg-surface-2 disabled:opacity-50 ${
                    compact ? 'px-1.5 py-1' : 'px-2.5 py-1'
                }`}
                title="Загрузить историю чата"
            >
                {startMutation.isPending ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                    <Download className="w-3 h-3" />
                )}
                {!compact && (
                    <span>
                        {loadedCount > 0 ? `Досинхронизировать (${loadedCount.toLocaleString()})` : 'Синхронизировать'}
                    </span>
                )}
            </button>
            {!compact && (
                <button
                    type="button"
                    onClick={() => setShowPeriodPanel((prev) => !prev)}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-border text-xs text-foreground-secondary hover:bg-surface-2"
                    title="Период синхронизации"
                >
                    <CalendarRange className="w-3 h-3" />
                    Период
                </button>
            )}
            {!compact && showPeriodPanel && (
                <div className="w-full rounded-md border border-border bg-surface p-2 space-y-2 text-xs">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                        <label className="space-y-1">
                            <span className="text-foreground-secondary">От</span>
                            <input
                                type="date"
                                value={dateFrom}
                                onChange={(e) => setDateFrom(e.target.value)}
                                className="w-full px-2 py-1 rounded-md border border-border bg-input-bg text-input-text"
                            />
                        </label>
                        <label className="space-y-1">
                            <span className="text-foreground-secondary">До</span>
                            <input
                                type="date"
                                value={dateTo}
                                onChange={(e) => setDateTo(e.target.value)}
                                className="w-full px-2 py-1 rounded-md border border-border bg-input-bg text-input-text"
                            />
                        </label>
                    </div>
                    <label className="inline-flex items-center gap-2">
                        <input
                            type="checkbox"
                            checked={excludeEnabled}
                            onChange={(e) => setExcludeEnabled(e.target.checked)}
                        />
                        <span>Исключить период</span>
                    </label>
                    {excludeEnabled && (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                            <label className="space-y-1">
                                <span className="text-foreground-secondary">Искл. от</span>
                                <input
                                    type="date"
                                    value={excludeFrom}
                                    onChange={(e) => setExcludeFrom(e.target.value)}
                                    className="w-full px-2 py-1 rounded-md border border-border bg-input-bg text-input-text"
                                />
                            </label>
                            <label className="space-y-1">
                                <span className="text-foreground-secondary">Искл. до</span>
                                <input
                                    type="date"
                                    value={excludeTo}
                                    onChange={(e) => setExcludeTo(e.target.value)}
                                    className="w-full px-2 py-1 rounded-md border border-border bg-input-bg text-input-text"
                                />
                            </label>
                        </div>
                    )}
                    {(dateRangeInvalid || excludeRangeInvalid) && (
                        <div className="text-danger">Проверьте корректность диапазонов дат.</div>
                    )}
                </div>
            )}
        </div>
    );
};
