import { db, SyncMetaEntry } from '../storage/db';
import { securityApi, syncApi, SyncManifestResponse, SyncTableResponse } from './api';

export type SyncState = 'idle' | 'syncing' | 'error';

export type SyncTableStatus = {
    table: string;
    rows: number;
    serverRows?: number;
    lagRows?: number;
    lastSyncAt?: string;
    checksum?: string;
    error?: string;
};

export type SyncSnapshot = {
    state: SyncState;
    statuses: SyncTableStatus[];
    backoffMs: number;
};

const DEFAULT_PAGE_SIZE = Number((import.meta as any)?.env?.VITE_SYNC_PAGE_SIZE || 5000);

const TABLE_ORDER = [
    'accessScopes',
    'operatorMappings',
    'operatorReferences',
    'transactions',
    'monitoredBotChats',
    'hiddenBotChats',
    'parsingLogs',
    'hourlyReports',
    'receiptProcessingTasks',
    'lockedPeriods',
];

const TABLE_MAP: Record<string, keyof typeof db> = {
    transactions: 'transactions',
    operatorMappings: 'operatorMappings',
    operatorReferences: 'operatorReferences',
    monitoredBotChats: 'monitoredBotChats',
    hiddenBotChats: 'hiddenBotChats',
    parsingLogs: 'parsingLogs',
    hourlyReports: 'hourlyReports',
    accessScopes: 'accessScopes',
    receiptProcessingTasks: 'receiptProcessingTasks',
    lockedPeriods: 'lockedPeriods',
};

const nowIso = () => new Date().toISOString();
const SCOPE_TOKEN_KEY = 'access_scope_token';
const SCOPE_FINGERPRINT_META_KEY = 'scopeFingerprint';
const SYNC_BOOTSTRAP_CURSOR_PREFIX = 'syncBootstrapCursor:';
const SYNC_BOOTSTRAP_STARTED_AT_PREFIX = 'syncBootstrapStartedAt:';
const DEFAULT_SYNC_BACKOFF_MS = 5 * 60 * 1000;
const INITIAL_SYNC_CONTINUE_DELAY_MS = Math.max(
    5000,
    Number((import.meta as any)?.env?.VITE_SYNC_INITIAL_CONTINUE_DELAY_MS || 15000)
);
const INITIAL_SYNC_MAX_PAGES_PER_CYCLE = Math.max(
    1,
    Number((import.meta as any)?.env?.VITE_SYNC_INITIAL_MAX_PAGES_PER_CYCLE || 3)
);
const INCREMENTAL_SYNC_MAX_PAGES_PER_CYCLE = Math.max(
    1,
    Number((import.meta as any)?.env?.VITE_SYNC_INCREMENTAL_MAX_PAGES_PER_CYCLE || 20)
);
const TABLE_SYNC_TIMEOUT_MS = Math.max(
    10_000,
    Number((import.meta as any)?.env?.VITE_SYNC_TABLE_TIMEOUT_MS || 60_000)
);
const MANIFEST_LOCAL_CACHE_TTL_MS = Math.max(
    10_000,
    Number((import.meta as any)?.env?.VITE_SYNC_MANIFEST_TTL_MS || 120_000)
);

export class SyncManager {
    private state: SyncState = 'idle';
    private statuses = new Map<string, SyncTableStatus>();
    private backoffMs = DEFAULT_SYNC_BACKOFF_MS;
    private listeners = new Set<(snapshot: SyncSnapshot) => void>();
    private manifestCache: { expiresAt: number; payload: SyncManifestResponse } | null = null;

    getState() {
        return this.state;
    }

    getStatuses(): SyncTableStatus[] {
        return Array.from(this.statuses.values());
    }

    getBackoffMs() {
        return this.backoffMs;
    }

    subscribe(listener: (snapshot: SyncSnapshot) => void): () => void {
        this.listeners.add(listener);
        listener({
            state: this.state,
            statuses: this.getStatuses(),
            backoffMs: this.backoffMs,
        });
        return () => {
            this.listeners.delete(listener);
        };
    }

    private emit() {
        const snapshot: SyncSnapshot = {
            state: this.state,
            statuses: this.getStatuses(),
            backoffMs: this.backoffMs,
        };
        this.listeners.forEach((listener) => listener(snapshot));
    }

    private setTableStatus(table: string, patch: Partial<SyncTableStatus>) {
        const current = this.statuses.get(table) || { table, rows: 0 };
        this.statuses.set(table, { ...current, ...patch });
        this.emit();
    }

    private async tableMeta(tableName: string): Promise<SyncMetaEntry | undefined> {
        return db.syncMeta.get(tableName);
    }

    private getScopeFingerprint(): string {
        if (typeof window === 'undefined') return 'server';
        let token = window.localStorage.getItem(SCOPE_TOKEN_KEY) || '';
        if (!token) {
            const legacySessionToken = window.sessionStorage.getItem(SCOPE_TOKEN_KEY) || '';
            if (legacySessionToken) {
                token = legacySessionToken;
                window.localStorage.setItem(SCOPE_TOKEN_KEY, legacySessionToken);
                window.sessionStorage.removeItem(SCOPE_TOKEN_KEY);
            }
        }
        let hash = 0;
        for (let i = 0; i < token.length; i += 1) {
            hash = ((hash << 5) - hash + token.charCodeAt(i)) | 0;
        }
        return `scope:${hash}`;
    }

    private async clearSyncedTables(): Promise<void> {
        for (const tableName of Object.keys(TABLE_MAP)) {
            const tableRef: any = (db as any)[TABLE_MAP[tableName]];
            if (tableRef) {
                await tableRef.clear();
            }
        }
        // Legacy synced tables removed from backend manifest in v1.2.0+.
        if ((db as any).accessAuditLog) {
            await (db as any).accessAuditLog.clear();
        }
        if ((db as any).chatPasswords) {
            await (db as any).chatPasswords.clear();
        }
        await db.syncMeta.clear();
        await db.meta.where('key').startsWith(SYNC_BOOTSTRAP_CURSOR_PREFIX).delete();
        await db.meta.where('key').startsWith(SYNC_BOOTSTRAP_STARTED_AT_PREFIX).delete();
    }

    private async resetMirrorOnScopeChangeIfNeeded(): Promise<void> {
        const currentFingerprint = this.getScopeFingerprint();
        const stored = await db.meta.get(SCOPE_FINGERPRINT_META_KEY);
        if (stored?.value === currentFingerprint) {
            return;
        }
        await this.clearSyncedTables();
        await db.meta.put({ key: SCOPE_FINGERPRINT_META_KEY, value: currentFingerprint });
    }

    private bootstrapCursorMetaKey(tableName: string): string {
        return `${SYNC_BOOTSTRAP_CURSOR_PREFIX}${tableName}`;
    }

    private bootstrapStartedMetaKey(tableName: string): string {
        return `${SYNC_BOOTSTRAP_STARTED_AT_PREFIX}${tableName}`;
    }

    private async readBootstrapCursor(tableName: string): Promise<number | undefined> {
        const raw = await db.meta.get(this.bootstrapCursorMetaKey(tableName));
        if (!raw?.value) return undefined;
        const parsed = Number(raw.value);
        if (!Number.isFinite(parsed) || parsed <= 0) {
            return undefined;
        }
        return parsed;
    }

    private async setBootstrapCursor(tableName: string, lastServerId: number): Promise<void> {
        if (!Number.isFinite(lastServerId) || lastServerId <= 0) return;
        await db.meta.put({ key: this.bootstrapCursorMetaKey(tableName), value: String(lastServerId) });
    }

    private async ensureBootstrapStartedAt(tableName: string): Promise<string> {
        const key = this.bootstrapStartedMetaKey(tableName);
        const existing = await db.meta.get(key);
        if (existing?.value) {
            return existing.value;
        }
        const value = nowIso();
        await db.meta.put({ key, value });
        return value;
    }

    private async clearBootstrapState(tableName: string): Promise<void> {
        await db.meta.delete(this.bootstrapCursorMetaKey(tableName));
        await db.meta.delete(this.bootstrapStartedMetaKey(tableName));
    }

    private async applyBlockedRangesForTransactions(tableRef: any, blockedRanges: Array<{ from: string; to: string }>): Promise<void> {
        if (!blockedRanges?.length) return;
        const idsToDelete: number[] = [];
        await tableRef.each((row: any) => {
            const rowId = Number(row?.id);
            const txDate = typeof row?.transaction_date === 'string' ? row.transaction_date.slice(0, 10) : '';
            if (!rowId || !txDate) return;
            const isBlocked = blockedRanges.some((range) => txDate >= range.from && txDate <= range.to);
            if (isBlocked) {
                idsToDelete.push(rowId);
            }
        });
        if (idsToDelete.length) {
            await tableRef.bulkDelete(idsToDelete);
        }
    }

    private shouldSyncTable(table: string, manifest: SyncManifestResponse, localMeta?: SyncMetaEntry): boolean {
        const server = manifest.tables[table];
        if (!server) return false;
        if (!localMeta) return true;
        return localMeta.checksum !== server.checksum;
    }

    private async applyTableRows(
        tableName: string,
        payload: SyncTableResponse,
        options?: { persistLastSyncAt?: boolean; forcedLastSyncAt?: string; overrideLastServerId?: number }
    ): Promise<void> {
        const tableKey = TABLE_MAP[tableName];
        if (!tableKey) return;
        const tableRef: any = (db as any)[tableKey];
        if (!tableRef) return;

        const rows = payload.rows || [];
        const deleted = payload.deleted_ids || [];
        const blockedRanges = Array.isArray(payload.blocked_ranges) ? payload.blocked_ranges : [];
        const persistLastSyncAt = options?.persistLastSyncAt ?? true;

        await db.transaction('rw', tableRef, db.syncMeta, async () => {
            if (rows.length) {
                await tableRef.bulkPut(rows);
            }
            if (deleted.length) {
                await tableRef.bulkDelete(deleted);
            }
            if (tableName === 'transactions' && blockedRanges.length) {
                await this.applyBlockedRangesForTransactions(tableRef, blockedRanges);
            }

            const existingMeta = await db.syncMeta.get(tableName);
            const lastRow = rows.length ? rows[rows.length - 1] : null;
            const payloadLastServerId = lastRow?.id || lastRow?.chat_id || undefined;
            const lastServerId =
                options?.overrideLastServerId ??
                (typeof payloadLastServerId === 'number' ? payloadLastServerId : existingMeta?.last_server_id);
            const actualRowCount = await tableRef.count();
            await db.syncMeta.put({
                table_name: tableName,
                last_sync_at: persistLastSyncAt
                    ? (options?.forcedLastSyncAt || nowIso())
                    : existingMeta?.last_sync_at,
                last_server_id: typeof lastServerId === 'number' ? lastServerId : undefined,
                checksum: payload.server_checksum,
                row_count: actualRowCount,
            });
        });
    }

    private async getManifestCached(force = false): Promise<SyncManifestResponse> {
        const now = Date.now();
        if (!force && this.manifestCache && this.manifestCache.expiresAt > now) {
            return this.manifestCache.payload;
        }
        const lastSyncMeta = await db.meta.get('lastSyncAt');
        const payload = await syncApi.getManifest({
            client_last_sync: lastSyncMeta?.value || undefined,
        });
        if (payload.full_resync_required) {
            await this.clearSyncedTables();
            await db.meta.put({ key: SCOPE_FINGERPRINT_META_KEY, value: this.getScopeFingerprint() });
            const freshPayload = await syncApi.getManifest();
            this.manifestCache = {
                payload: freshPayload,
                expiresAt: now + MANIFEST_LOCAL_CACHE_TTL_MS,
            };
            return freshPayload;
        }
        this.manifestCache = {
            payload,
            expiresAt: now + MANIFEST_LOCAL_CACHE_TTL_MS,
        };
        return payload;
    }

    private async syncSingleTable(tableName: string, localMeta?: SyncMetaEntry): Promise<boolean> {
        const cursor = await this.readBootstrapCursor(tableName);
        const isInitialSync = !localMeta?.last_sync_at && !localMeta?.checksum;
        const bootstrapMode = isInitialSync || Number.isFinite(cursor);
        const bootstrapStartedAt = bootstrapMode ? await this.ensureBootstrapStartedAt(tableName) : undefined;
        const since = bootstrapMode ? undefined : localMeta?.last_sync_at;
        const sinceId = bootstrapMode ? cursor : localMeta?.last_server_id;
        const maxPages = bootstrapMode ? INITIAL_SYNC_MAX_PAGES_PER_CYCLE : INCREMENTAL_SYNC_MAX_PAGES_PER_CYCLE;

        let pagesFetched = 0;
        let hasMore = true;
        let completed = false;
        let currentCursor = sinceId;
        let currentCursorUpdatedAt = bootstrapMode ? undefined : localMeta?.last_sync_at;
        const startedAt = Date.now();
        while (hasMore) {
            if (pagesFetched >= maxPages) {
                this.setTableStatus(tableName, {
                    table: tableName,
                    error: bootstrapMode
                        ? 'Первичная синхронизация продолжается в фоне'
                        : 'Инкрементальная синхронизация ограничена по страницам',
                });
                break;
            }
            if (Date.now() - startedAt > TABLE_SYNC_TIMEOUT_MS) {
                this.setTableStatus(tableName, {
                    table: tableName,
                    error: 'Превышен таймаут синхронизации таблицы',
                });
                break;
            }
            const page = await syncApi.getTable(tableName, {
                since: since || undefined,
                since_id: currentCursor || undefined,
                cursor_updated_at: currentCursorUpdatedAt || undefined,
                cursor_id: currentCursor || undefined,
                offset: 0,
                limit: tableName === 'transactions' ? DEFAULT_PAGE_SIZE : 5000,
            });
            pagesFetched += 1;
            const pageRows = page.rows?.length || 0;

            const lastRow = pageRows ? page.rows[pageRows - 1] : null;
            const pageLastServerId = Number(lastRow?.id ?? lastRow?.chat_id ?? 0);
            const shouldPersistLastSyncAt = !bootstrapMode || !page.has_more;
            const forcedLastSyncAt = shouldPersistLastSyncAt && bootstrapMode ? bootstrapStartedAt : undefined;
            await this.applyTableRows(tableName, page, {
                persistLastSyncAt: shouldPersistLastSyncAt,
                forcedLastSyncAt,
                overrideLastServerId:
                    Number.isFinite(pageLastServerId) && pageLastServerId > 0
                        ? pageLastServerId
                        : currentCursor,
            });

            hasMore = Boolean(page.has_more);
            if (page.next_cursor?.updated_at) {
                currentCursorUpdatedAt = page.next_cursor.updated_at;
            }
            if (Number.isFinite(pageLastServerId) && pageLastServerId > 0) {
                currentCursor = pageLastServerId;
                if (bootstrapMode) {
                    await this.setBootstrapCursor(tableName, pageLastServerId);
                }
            }
            if (page.next_cursor?.id && Number.isFinite(page.next_cursor.id)) {
                currentCursor = page.next_cursor.id;
                if (bootstrapMode) {
                    await this.setBootstrapCursor(tableName, page.next_cursor.id);
                }
            }
            const syncedRows = Number((await this.tableMeta(tableName))?.row_count || 0);
            const remaining = Math.max(0, Number(page.total_count || 0) - pageRows);
            this.setTableStatus(tableName, {
                table: tableName,
                rows: syncedRows,
                serverRows: Number(page.total_count || 0),
                lagRows: hasMore ? remaining : 0,
                lastSyncAt: page.server_time,
                checksum: page.server_checksum,
                error: undefined,
            });

            if (!pageRows && !page.has_more) {
                completed = true;
                break;
            }
            if (!hasMore) {
                completed = true;
                break;
            }
        }

        if (bootstrapMode && completed) {
            await this.clearBootstrapState(tableName);
        }
        return bootstrapMode && !completed;
    }

    private isExpectedAccessBlock(error: any): boolean {
        const status = Number(error?.response?.status || 0);
        const detail = error?.response?.data?.detail;
        const errorCode =
            detail && typeof detail === 'object'
                ? String((detail as any).error || '').toLowerCase()
                : '';
        if (status === 401) return true;
        if (status === 403 && (errorCode === 'launch_required' || errorCode === 'launch_expired')) {
            return true;
        }
        if (status === 403 && typeof detail === 'string' && detail.toLowerCase().includes('scope')) {
            return true;
        }
        return false;
    }

    private async canSyncNow(): Promise<boolean> {
        try {
            const status = await securityApi.getStatus();
            if (status.scopes_enabled && !status.current_scope) {
                return false;
            }
            return true;
        } catch (error: any) {
            if (this.isExpectedAccessBlock(error)) {
                return false;
            }
            throw error;
        }
    }

    async runSyncCycle(): Promise<void> {
        this.state = 'syncing';
        this.emit();
        try {
            const syncAllowed = await this.canSyncNow();
            if (!syncAllowed) {
                this.state = 'idle';
                this.backoffMs = INITIAL_SYNC_CONTINUE_DELAY_MS;
                this.statuses.clear();
                this.setTableStatus('global', {
                    table: 'global',
                    rows: 0,
                    error: undefined,
                });
                this.emit();
                return;
            }
            await this.resetMirrorOnScopeChangeIfNeeded();
            const manifest = await this.getManifestCached();
            let bootstrapPending = false;
            for (const table of TABLE_ORDER) {
                const serverMeta = manifest.tables[table];
                if (!serverMeta) {
                    continue;
                }
                const meta = await this.tableMeta(table);
                const localRows = Number(meta?.row_count || 0);
                const serverRows = Number(serverMeta.row_count || 0);
                const lagRows = Math.max(0, serverRows - localRows);
                this.setTableStatus(table, {
                    table,
                    rows: localRows,
                    serverRows,
                    lagRows,
                    lastSyncAt: meta?.last_sync_at,
                    checksum: meta?.checksum,
                    error: undefined,
                });
                const hasBootstrapCursor = Boolean(await this.readBootstrapCursor(table));
                if (!hasBootstrapCursor && !this.shouldSyncTable(table, manifest, meta)) {
                    continue;
                }
                const tableBootstrapPending = await this.syncSingleTable(table, meta);
                bootstrapPending = bootstrapPending || tableBootstrapPending;
            }
            await db.meta.put({ key: 'lastSyncAt', value: nowIso() });
            this.state = 'idle';
            this.backoffMs = bootstrapPending ? INITIAL_SYNC_CONTINUE_DELAY_MS : DEFAULT_SYNC_BACKOFF_MS;
            this.emit();
        } catch (error: any) {
            this.manifestCache = null;
            if (this.isExpectedAccessBlock(error)) {
                this.state = 'idle';
                this.backoffMs = INITIAL_SYNC_CONTINUE_DELAY_MS;
                this.statuses.clear();
                this.setTableStatus('global', {
                    table: 'global',
                    rows: 0,
                    error: undefined,
                });
                this.emit();
                return;
            }
            this.state = 'error';
            this.backoffMs = Math.min(this.backoffMs * 2, 30 * 60 * 1000);
            this.setTableStatus('global', {
                table: 'global',
                rows: 0,
                error: error?.message || 'sync failed',
            });
            this.emit();
            throw error;
        }
    }
}

export const syncManager = new SyncManager();
