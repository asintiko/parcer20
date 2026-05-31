import { useCallback, useMemo } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { TelegramChat } from '../services/api';
import {
    acknowledgeHiddenOperation,
    applyHiddenSnapshotOverlay,
    buildServerHiddenSnapshot,
    enqueueHiddenOperation,
    loadHiddenSnapshot,
    mergeServerSnapshotWithQueue,
    scheduleHiddenRetry,
    setLocalHiddenState,
} from '../services/chatHiddenState';

const TG_CHATS_QUERY_KEY = ['tg-chats'];

interface OverlayResult {
    chats: TelegramChat[];
    setHidden: (chatId: number, hidden: boolean) => void;
    acknowledge: (chatId: number) => void;
    rollback: (chatId: number) => void;
}

/**
 * Накладывает локальный snapshot скрытых чатов поверх данных из API,
 * чтобы скрытие было оптимистичным и не "отменялось" при refetch.
 *
 * Если бэкенд недоступен или ответил ошибкой — операция остаётся в очереди
 * и применяется при следующем merge до подтверждения через `acknowledge`.
 */
export function useHiddenChatsOverlay(
    serverChats: TelegramChat[] | undefined,
    scope: string = 'sandbox',
): OverlayResult {
    const queryClient = useQueryClient();

    const chats = useMemo<TelegramChat[]>(() => {
        if (!serverChats) return [];
        const serverSnapshot = buildServerHiddenSnapshot(serverChats);
        const merged = mergeServerSnapshotWithQueue(scope, serverSnapshot);
        return applyHiddenSnapshotOverlay(serverChats, merged);
    }, [serverChats, scope]);

    const writeOverlayToCache = useCallback(
        (chatId: number, hidden: boolean) => {
            queryClient.setQueriesData<{ total: number; items: TelegramChat[] } | undefined>(
                { queryKey: TG_CHATS_QUERY_KEY },
                (data) => {
                    if (!data) return data;
                    const next = data.items.map((chat) =>
                        chat.chat_id === chatId ? { ...chat, is_hidden: hidden } : chat,
                    );
                    return { ...data, items: next };
                },
            );
        },
        [queryClient],
    );

    const setHidden = useCallback(
        (chatId: number, hidden: boolean) => {
            setLocalHiddenState(scope, chatId, hidden);
            enqueueHiddenOperation(scope, chatId, hidden);
            writeOverlayToCache(chatId, hidden);
        },
        [scope, writeOverlayToCache],
    );

    const acknowledge = useCallback(
        (chatId: number) => {
            acknowledgeHiddenOperation(scope, chatId);
        },
        [scope],
    );

    const rollback = useCallback(
        (chatId: number) => {
            scheduleHiddenRetry(scope, chatId);
            // Re-read the snapshot post-retry so cache reflects the queued state.
            const snapshot = loadHiddenSnapshot(scope);
            const hidden = snapshot[String(chatId)];
            if (typeof hidden === 'boolean') {
                writeOverlayToCache(chatId, hidden);
            }
        },
        [scope, writeOverlayToCache],
    );

    return { chats, setHidden, acknowledge, rollback };
}
