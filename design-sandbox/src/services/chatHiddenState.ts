import type { TelegramChat } from './api';

type HiddenSnapshot = Record<string, boolean>;

export type HiddenQueueOperation = {
    chatId: number;
    hidden: boolean;
    queuedAt: number;
    attempt: number;
    nextRetryAt: number;
};

const SNAPSHOT_KEY_PREFIX = 'tgHiddenSnapshot:v1';
const QUEUE_KEY_PREFIX = 'tgHiddenQueue:v1';
const RETRY_BACKOFF_MS = [1000, 2500, 5000, 10000, 20000, 40000];

const buildStorageKey = (prefix: string, scope: string) => `${prefix}:${scope}`;

const readJson = <T,>(key: string, fallback: T): T => {
    try {
        const raw = localStorage.getItem(key);
        if (!raw) return fallback;
        return JSON.parse(raw) as T;
    } catch {
        return fallback;
    }
};

const writeJson = <T,>(key: string, payload: T) => {
    try {
        localStorage.setItem(key, JSON.stringify(payload));
    } catch {
        // no-op
    }
};

const normalizeQueue = (value: unknown): HiddenQueueOperation[] => {
    if (!Array.isArray(value)) return [];
    return value
        .map((item) => {
            const chatId = Number((item as any)?.chatId);
            const hidden = Boolean((item as any)?.hidden);
            const queuedAt = Number((item as any)?.queuedAt) || Date.now();
            const attempt = Number((item as any)?.attempt) || 0;
            const nextRetryAt = Number((item as any)?.nextRetryAt) || queuedAt;
            if (!Number.isFinite(chatId) || chatId <= 0) return null;
            return { chatId, hidden, queuedAt, attempt, nextRetryAt };
        })
        .filter((item): item is HiddenQueueOperation => Boolean(item))
        .sort((a, b) => a.nextRetryAt - b.nextRetryAt || a.queuedAt - b.queuedAt);
};

const getSnapshotKey = (scope: string) => buildStorageKey(SNAPSHOT_KEY_PREFIX, scope);
const getQueueKey = (scope: string) => buildStorageKey(QUEUE_KEY_PREFIX, scope);

export const loadHiddenSnapshot = (scope: string): HiddenSnapshot =>
    readJson<HiddenSnapshot>(getSnapshotKey(scope), {});

export const saveHiddenSnapshot = (scope: string, snapshot: HiddenSnapshot): HiddenSnapshot => {
    writeJson(getSnapshotKey(scope), snapshot);
    return snapshot;
};

export const buildServerHiddenSnapshot = (chats: TelegramChat[]): HiddenSnapshot => {
    const snapshot: HiddenSnapshot = {};
    chats.forEach((chat) => {
        snapshot[String(chat.chat_id)] = Boolean(chat.is_hidden);
    });
    return snapshot;
};

export const loadHiddenQueue = (scope: string): HiddenQueueOperation[] =>
    normalizeQueue(readJson<HiddenQueueOperation[]>(getQueueKey(scope), []));

const saveHiddenQueue = (scope: string, queue: HiddenQueueOperation[]): HiddenQueueOperation[] => {
    const normalized = normalizeQueue(queue);
    writeJson(getQueueKey(scope), normalized);
    return normalized;
};

export const mergeServerSnapshotWithQueue = (scope: string, serverSnapshot: HiddenSnapshot): HiddenSnapshot => {
    const queue = loadHiddenQueue(scope);
    if (!queue.length) {
        return saveHiddenSnapshot(scope, serverSnapshot);
    }
    const merged = { ...serverSnapshot };
    queue.forEach((op) => {
        merged[String(op.chatId)] = op.hidden;
    });
    return saveHiddenSnapshot(scope, merged);
};

export const setLocalHiddenState = (scope: string, chatId: number, hidden: boolean): HiddenSnapshot => {
    const current = loadHiddenSnapshot(scope);
    const next = { ...current, [String(chatId)]: hidden };
    return saveHiddenSnapshot(scope, next);
};

export const enqueueHiddenOperation = (scope: string, chatId: number, hidden: boolean): HiddenQueueOperation[] => {
    const current = loadHiddenQueue(scope);
    const next: HiddenQueueOperation[] = [
        ...current.filter((op) => op.chatId !== chatId),
        {
            chatId,
            hidden,
            queuedAt: Date.now(),
            attempt: 0,
            nextRetryAt: Date.now(),
        },
    ];
    return saveHiddenQueue(scope, next);
};

export const acknowledgeHiddenOperation = (scope: string, chatId: number): HiddenQueueOperation[] => {
    const current = loadHiddenQueue(scope);
    const next = current.filter((op) => op.chatId !== chatId);
    return saveHiddenQueue(scope, next);
};

export const scheduleHiddenRetry = (scope: string, chatId: number): HiddenQueueOperation[] => {
    const current = loadHiddenQueue(scope);
    const now = Date.now();
    const next = current.map((op) => {
        if (op.chatId !== chatId) return op;
        const nextAttempt = op.attempt + 1;
        const delay = RETRY_BACKOFF_MS[Math.min(nextAttempt - 1, RETRY_BACKOFF_MS.length - 1)];
        return {
            ...op,
            attempt: nextAttempt,
            nextRetryAt: now + delay,
        };
    });
    return saveHiddenQueue(scope, next);
};

export const peekDueHiddenOperation = (scope: string): HiddenQueueOperation | null => {
    const queue = loadHiddenQueue(scope);
    const now = Date.now();
    return queue.find((op) => op.nextRetryAt <= now) || null;
};

export const applyHiddenSnapshotOverlay = (chats: TelegramChat[], snapshot: HiddenSnapshot): TelegramChat[] =>
    chats.map((chat) => {
        const hidden = snapshot[String(chat.chat_id)];
        if (typeof hidden !== 'boolean' || hidden === chat.is_hidden) return chat;
        return {
            ...chat,
            is_hidden: hidden,
        };
    });
