import { useCallback, useEffect, useRef, useState } from 'react';
import { Transaction } from '../services/api';
import { db } from '../storage/db';
import { syncManager } from '../services/syncManager';

type SyncProgress = {
    downloaded: number;
    pages: number;
    total?: number;
    status?: 'idle' | 'running' | 'done' | 'error';
};

export const useOfflineTransactions = () => {
    const META_VERSION = '1';
    const [data, setData] = useState<Transaction[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [isOfflineReady, setIsOfflineReady] = useState(false);
    const [syncProgress, setSyncProgress] = useState<SyncProgress>({ downloaded: 0, pages: 0, status: 'idle' });
    const [lastSyncAt, setLastSyncAt] = useState<string | null>(null);
    const retryDelayRef = useRef<number>(5 * 60 * 1000); // 5 minutes
    const INITIAL_LOOP_DELAY_MS = 15 * 1000;

    const sortTransactions = useCallback((items: Transaction[]) => {
        return [...items].sort((a, b) => {
            const at = a.transaction_date ? new Date(a.transaction_date).getTime() : 0;
            const bt = b.transaction_date ? new Date(b.transaction_date).getTime() : 0;
            return at - bt;
        });
    }, []);

    const loadTransactions = useCallback(async () => {
        setIsLoading(true);
        try {
            const [items, meta, versionEntry] = await Promise.all([
                db.transactions.toArray(),
                db.meta.get('lastSyncAt'),
                db.meta.get('version'),
            ]);
            const sorted = sortTransactions(items);
            setData(sorted);
            setIsOfflineReady(items.length > 0);
            setLastSyncAt(meta?.value ?? null);
            if (!versionEntry?.value) {
                db.meta.put({ key: 'version', value: META_VERSION }).catch(() => null);
            }
            return items;
        } catch (error) {
            console.error('Failed to load transactions cache', error);
            setData([]);
            setIsOfflineReady(false);
            setLastSyncAt(null);
            return [];
        } finally {
            setIsLoading(false);
        }
    }, []);

    const syncFromServer = useCallback(async (background = false) => {
        setSyncProgress({ downloaded: 0, pages: 0, status: 'running' });
        if (!background) setIsLoading(true);
        try {
            await syncManager.runSyncCycle();
            const all = await db.transactions.toArray();
            const sortedFetched = sortTransactions(all);

            const txStatus = syncManager.getStatuses().find((item) => item.table === 'transactions');
            setSyncProgress({
                downloaded: sortedFetched.length,
                pages: txStatus ? Math.max(1, Math.ceil((txStatus.rows || 0) / 5000)) : 1,
                total: txStatus?.rows,
                status: 'running',
            });

            const lastSync = await db.meta.get('lastSyncAt');
            setLastSyncAt(lastSync?.value || new Date().toISOString());

            setData(sortedFetched);
            setIsOfflineReady(sortedFetched.length > 0);
            setSyncProgress((prev) => ({ ...prev, status: 'done' }));
            retryDelayRef.current = syncManager.getBackoffMs();
        } catch (error) {
            console.error('Failed to sync from server', error);
            setSyncProgress((prev) => ({ ...prev, status: 'error' }));
            retryDelayRef.current = syncManager.getBackoffMs();
        } finally {
            if (!background) setIsLoading(false);
        }
    }, [sortTransactions]);

    const upsertTransactions = useCallback(async (transactions: Transaction | Transaction[]) => {
        const list = Array.isArray(transactions) ? transactions : [transactions];
        if (!list.length) return;
        await db.transactions.bulkPut(list);
        setData((prev) => {
            const map = new Map(prev.map((tx) => [tx.id, tx]));
            list.forEach((tx) => {
                const existing = map.get(tx.id) || {};
                map.set(tx.id, { ...existing, ...tx });
            });
            return sortTransactions(Array.from(map.values()));
        });
    }, [sortTransactions]);

    const updateTransactionFields = useCallback(async (updates: Array<{ id: number; fields: Record<string, any> }>) => {
        if (!updates.length) return;
        await db.transaction('rw', db.transactions, async () => {
            for (const update of updates) {
                const existing = await db.transactions.get(update.id);
                if (existing) {
                    await db.transactions.put({ ...existing, ...update.fields });
                }
            }
        });
        setData((prev) =>
            sortTransactions(
                prev.map((tx) => {
                    const update = updates.find((u) => u.id === tx.id);
                    return update ? { ...tx, ...update.fields } : tx;
                })
            )
        );
    }, [sortTransactions]);

    const removeTransactions = useCallback(async (ids: number[]) => {
        if (!ids.length) return;
        await db.transactions.bulkDelete(ids);
        setData((prev) => prev.filter((tx) => !ids.includes(tx.id)));
    }, []);

    useEffect(() => {
        let cancelled = false;
        const init = async () => {
            const items = await loadTransactions();
            if (cancelled) return;
            if (items.length === 0) {
                await syncFromServer(false);
            } else {
                syncFromServer(true);
            }
        };
        init();
        return () => {
            cancelled = true;
        };
    }, [loadTransactions, syncFromServer]);

    useEffect(() => {
        let timeout: ReturnType<typeof setTimeout> | null = null;
        let cancelled = false;
        const loop = async () => {
            if (cancelled) return;
            await syncFromServer(true);
            if (cancelled) return;
            timeout = setTimeout(loop, retryDelayRef.current);
        };
        timeout = setTimeout(loop, Math.min(retryDelayRef.current, INITIAL_LOOP_DELAY_MS));
        return () => {
            cancelled = true;
            if (timeout) clearTimeout(timeout);
        };
    }, [syncFromServer]);

    return {
        data,
        isLoading,
        isOfflineReady,
        syncProgress,
        loadTransactions,
        syncFromServer,
        upsertTransactions,
        removeTransactions,
        updateTransactionFields,
        lastSyncAt,
    };
};
