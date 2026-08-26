// Lightweight axios-shaped client that resolves all requests with seed data.
// Used by the design sandbox in place of the real backend.

import {
    MOCK_APPLICATIONS,
    MOCK_OPERATORS,
    MOCK_TRANSACTIONS,
    MOCK_USER,
} from './mockData';
import {
    TG_MOCK_CHATS,
    TG_MOCK_MESSAGES,
    pushMessageToChat,
    startMockPushLoop,
} from './mockTelegram';

type MockConfig = {
    method?: string;
    url?: string;
    params?: Record<string, any>;
    data?: any;
    headers?: Record<string, any>;
    [key: string]: any;
};

type MockResponse<T = any> = {
    data: T;
    status: number;
    statusText: string;
    headers: Record<string, string>;
    config: MockConfig;
};

type Handler = (ctx: { config: MockConfig; match: RegExpMatchArray | null }) => any | Promise<any>;

type Route = {
    method: string;
    pattern: RegExp;
    handler: Handler;
};

const routes: Route[] = [];

const register = (method: string, pattern: RegExp, handler: Handler) => {
    routes.push({ method: method.toLowerCase(), pattern, handler });
};

const ok = <T>(data: T, config: MockConfig = {}): MockResponse<T> => ({
    data,
    status: 200,
    statusText: 'OK',
    headers: {},
    config,
});

const delay = (ms = 60) => new Promise((resolve) => setTimeout(resolve, ms));

const sliceItems = <T>(items: T[], page = 1, pageSize = 50) => {
    const start = (page - 1) * pageSize;
    return items.slice(start, start + pageSize);
};

const matchAuth = (data: any) => {
    const username = String(data?.username || '').trim().toLowerCase();
    const password = String(data?.password || '');
    return username === 'admin' && password === 'admin';
};

// ─── Auth ─────────────────────────────────────────────────────────────────────
register('post', /\/api\/auth\/login$/, ({ config }) => {
    if (!matchAuth(config.data)) {
        return {
            ok: false,
            error: 'invalid_credentials',
            attempts_left: 4,
        };
    }
    return {
        ok: true,
        token: 'mock-access-token',
        refresh_token: 'mock-refresh-token',
        scope_token: null,
        user: MOCK_USER,
    };
});

register('post', /\/api\/auth\/login\/2fa$/, () => ({
    ok: true,
    token: 'mock-access-token',
    refresh_token: 'mock-refresh-token',
    user: MOCK_USER,
}));

register('post', /\/api\/auth\/refresh$/, () => ({
    ok: true,
    token: 'mock-access-token',
    refresh_token: 'mock-refresh-token',
    user: MOCK_USER,
}));

register('post', /\/api\/auth\/logout$/, () => ({ success: true, message: 'logged out' }));

register('get', /\/api\/auth\/me$/, () => MOCK_USER);

register('get', /\/api\/auth\/verify$/, () => ({
    valid: true,
    user_id: MOCK_USER.id,
    permissions_version: MOCK_USER.permissions_version,
    role: MOCK_USER.role,
}));

register('post', /\/api\/auth\/qr\/generate$/, () => ({
    session_id: 'mock-qr-session',
    qr_url: 'https://example.com/mock-qr',
    expires_in: 300,
}));

register('get', /\/api\/auth\/qr\/status\/.+$/, () => ({ status: 'pending' }));

// ─── Transactions ─────────────────────────────────────────────────────────────
register('get', /\/api\/transactions\/?($|\?)/, ({ config }) => {
    const params = config.params || {};
    const page = Number(params.page) || 1;
    const pageSize = Number(params.page_size) || 50;
    const items = sliceItems(MOCK_TRANSACTIONS, page, pageSize);
    return {
        ok: true,
        total: MOCK_TRANSACTIONS.length,
        page,
        page_size: pageSize,
        items,
        has_more: page * pageSize < MOCK_TRANSACTIONS.length,
        next_cursor: null,
        cursor_mode: false,
        latest_transaction_at: MOCK_TRANSACTIONS[0]?.transaction_date || null,
        oldest_transaction_at:
            MOCK_TRANSACTIONS[MOCK_TRANSACTIONS.length - 1]?.transaction_date || null,
        server_generated_at: new Date().toISOString(),
    };
});

register('get', /\/api\/transactions\/init$/, () => ({
    security_status: { scopes_enabled: false, available_years: [2024, 2025, 2026] },
    years: [
        { year: 2026, count: 60 },
        { year: 2025, count: 45 },
        { year: 2024, count: 15 },
    ],
    operators: Array.from(new Set(MOCK_TRANSACTIONS.map((t) => t.operator_raw).filter(Boolean) as string[])),
    applications: MOCK_APPLICATIONS,
    telegram_sources: [
        { chat_id: -1001234567890, title: 'Bank Notifications', chat_type: 'bot', count: 96 },
        { chat_id: -1009876543210, title: 'Card Alerts', chat_type: 'channel', count: 24 },
    ],
}));

register('get', /\/api\/transactions\/years$/, () => ({
    items: [
        { year: 2026, count: 60 },
        { year: 2025, count: 45 },
        { year: 2024, count: 15 },
    ],
}));

register('get', /\/api\/transactions\/locate$/, () => ({
    exists: false,
    route: '/',
    focus_mode: 'filter',
    suggested_filters: {},
    sort_hint: {},
}));

register('get', /\/api\/transactions\/duplicate-events$/, () => []);

register('get', /\/api\/transactions\/processed-status$/, () => ({ statuses: {} }));

register('get', /\/api\/transactions\/\d+$/, ({ config }) => {
    const idMatch = String(config.url || '').match(/\/(\d+)$/);
    const id = Number(idMatch?.[1] || 0);
    return MOCK_TRANSACTIONS.find((t) => t.id === id) || MOCK_TRANSACTIONS[0];
});

register('post', /\/api\/transactions\/?$/, ({ config }) => {
    const payload = config.data || {};
    return {
        id: Math.floor(Math.random() * 1_000_000),
        ...MOCK_TRANSACTIONS[0],
        amount: payload.amount || '0',
        operator_raw: payload.operator || 'NEW',
        application_mapped: payload.app || null,
    };
});

register('put', /\/api\/transactions\/\d+$/, ({ config }) => {
    const idMatch = String(config.url || '').match(/\/(\d+)$/);
    const id = Number(idMatch?.[1] || 0);
    return {
        success: true,
        message: 'updated',
        transaction: MOCK_TRANSACTIONS.find((t) => t.id === id) || MOCK_TRANSACTIONS[0],
    };
});

register('delete', /\/api\/transactions\/\d+$/, ({ config }) => {
    const idMatch = String(config.url || '').match(/\/(\d+)$/);
    return { success: true, message: 'deleted', deleted_id: Number(idMatch?.[1] || 0) };
});

register('post', /\/api\/transactions\/bulk-delete$/, ({ config }) => ({
    success: true,
    deleted_count: (config.data?.ids || []).length,
    failed_ids: [],
    errors: [],
}));

register('patch', /\/api\/transactions\/bulk-update$/, ({ config }) => ({
    success: true,
    updated_count: (config.data?.updates || []).length,
    failed_ids: [],
    errors: [],
}));

register('post', /\/api\/transactions\/process-receipt(-batch)?$/, () => ({
    created: false,
    duplicate: true,
    transaction: MOCK_TRANSACTIONS[0],
    parsing: { method: 'regex', confidence: 0.9 },
}));

// ─── Analytics ────────────────────────────────────────────────────────────────
register('get', /\/api\/analytics\/top-agent$/, () => ({
    period_start: new Date(Date.now() - 7 * 86400000).toISOString(),
    period_end: new Date().toISOString(),
    transaction_count: 47,
    top_application: 'Click',
    top_application_count: 18,
    top_application_volume: '4 320 000',
    total_volume: '12 480 000',
    insight: 'Click — топ-приложение этой недели по числу операций.',
}));

register('get', /\/api\/analytics\/summary$/, () => ({
    total_transactions: MOCK_TRANSACTIONS.length,
    debit_count: MOCK_TRANSACTIONS.filter((t) => t.transaction_type === 'DEBIT').length,
    credit_count: MOCK_TRANSACTIONS.filter((t) => t.transaction_type === 'CREDIT').length,
    gpt_parsed_count: 18,
    gpt_usage_percentage: 15,
    total_volume_uzs: '24 800 000',
    average_confidence: 0.91,
}));

// ─── Sync ─────────────────────────────────────────────────────────────────────
register('get', /\/api\/sync\/manifest$/, () => ({
    tables: {},
    server_time: new Date().toISOString(),
    full_resync_required: false,
}));

register('get', /\/api\/sync\/.+$/, ({ config }) => {
    const m = String(config.url || '').match(/\/api\/sync\/([^/?]+)/);
    return {
        table: m?.[1] || 'unknown',
        rows: [],
        total_count: 0,
        has_more: false,
        server_checksum: 'mock',
        server_time: new Date().toISOString(),
        deleted_ids: [],
        next_cursor: null,
    };
});

// ─── Reference ────────────────────────────────────────────────────────────────
// Mutable in-memory store so the sandbox actually responds to filters and edits.
const referenceStore: typeof MOCK_OPERATORS = [...MOCK_OPERATORS];
let referenceNextId = referenceStore.reduce((m, x) => Math.max(m, x.id), 0) + 1;

const applicationsList = () =>
    Array.from(new Set(referenceStore.map((o) => o.application_name).filter(Boolean))).sort();

register('get', /\/api\/reference\/applications$/, () => applicationsList());

register('get', /\/api\/reference\/?($|\?)/, ({ config }) => {
    const params = config.params || {};
    const page = Math.max(1, Number(params.page) || 1);
    const pageSize = Number(params.page_size) || 50;
    const all = params.all === true || params.all === 'true';
    const search = (params.search || '').toString().trim().toLowerCase();
    const application = (params.application || '').toString().trim();
    const isActive = typeof params.is_active === 'boolean' ? params.is_active : undefined;
    const isP2p = typeof params.is_p2p === 'boolean' ? params.is_p2p : undefined;

    let filtered = referenceStore.slice();
    if (search) {
        filtered = filtered.filter(
            (o) =>
                o.operator_name.toLowerCase().includes(search) ||
                o.application_name.toLowerCase().includes(search),
        );
    }
    if (application) {
        filtered = filtered.filter((o) => o.application_name === application);
    }
    if (isActive !== undefined) {
        filtered = filtered.filter((o) => o.is_active === isActive);
    }
    if (isP2p !== undefined) {
        filtered = filtered.filter((o) => o.is_p2p === isP2p);
    }

    filtered.sort((a, b) => a.operator_name.localeCompare(b.operator_name, 'ru'));

    const total = filtered.length;
    const items = all ? filtered : sliceItems(filtered, page, pageSize);
    return { total, page, page_size: all ? total : pageSize, items };
});

register('post', /\/api\/reference\/?$/, ({ config }) => {
    const data = config.data || {};
    const item = {
        id: referenceNextId++,
        operator_name: String(data.operator_name || '').trim() || 'NEW',
        application_name: String(data.application_name || '').trim() || 'unknown',
        is_p2p: !!data.is_p2p,
        is_active: data.is_active !== false,
    };
    referenceStore.unshift(item);
    return item;
});

register('put', /\/api\/reference\/\d+$/, ({ config }) => {
    const id = Number(String(config.url).match(/\/(\d+)$/)?.[1] || 0);
    const idx = referenceStore.findIndex((x) => x.id === id);
    if (idx === -1) {
        const fallback = {
            id,
            operator_name: 'unknown',
            application_name: 'unknown',
            is_p2p: false,
            is_active: true,
            ...(config.data || {}),
        };
        referenceStore.push(fallback);
        return fallback;
    }
    const next = { ...referenceStore[idx], ...(config.data || {}) };
    referenceStore[idx] = next;
    return next;
});

register('delete', /\/api\/reference\/\d+$/, ({ config }) => {
    const id = Number(String(config.url).match(/\/(\d+)$/)?.[1] || 0);
    const idx = referenceStore.findIndex((x) => x.id === id);
    if (idx !== -1) referenceStore.splice(idx, 1);
    return { ok: true, deleted_id: id };
});

register('get', /\/api\/reference\/export\/excel$/, () => {
    const header = 'operator_name,application_name,is_p2p,is_active';
    const rows = referenceStore.map(
        (o) => `${o.operator_name},${o.application_name},${o.is_p2p},${o.is_active}`,
    );
    const blob = new Blob([[header, ...rows].join('\n')], { type: 'text/csv' });
    return blob;
});

register('post', /\/api\/reference\/import\/excel$/, () => ({
    imported: 0,
    skipped: 0,
    errors: ['Импорт недоступен в design-sandbox'],
}));

// ─── Automation ───────────────────────────────────────────────────────────────
register('post', /\/api\/automation\/.*$/, () => ({
    task_id: 'mock-task',
    status: 'queued',
    message: 'Задача поставлена в очередь',
}));

register('get', /\/api\/automation\/.*-status\/.+$/, () => ({
    task_id: 'mock-task',
    status: 'completed',
    progress: { total: 10, processed: 10, percent: 100 },
    results: { suggestions_count: 0, high_confidence: 0, low_confidence: 0 },
}));

register('get', /\/api\/automation\/(suggestions|verification-suggestions)$/, () => []);

register('get', /\/api\/automation\/reconciliation\/.*$/, () => ({
    task_id: 'mock-task',
    status: 'completed',
    progress: null,
    summary: null,
    items: [],
    total_items: 0,
}));

// ─── Userbot / Telegram ───────────────────────────────────────────────────────

// Process-message state machine.
// Each entry transitions queued → processing → done over ~1.5s.
type ProcessState = { status: 'queued' | 'processing' | 'done' | 'failed'; t0: number; taskId: string };
const PROCESS_STATES: Map<string, ProcessState> = new Map();
const processKey = (chatId: number, messageId: number) => `${chatId}:${messageId}`;

function ensureProcessState(chatId: number, messageId: number): ProcessState {
    const key = processKey(chatId, messageId);
    const existing = PROCESS_STATES.get(key);
    if (existing) return existing;
    const state: ProcessState = {
        status: 'queued',
        t0: Date.now(),
        taskId: `mock-task-${Date.now()}-${messageId}`,
    };
    PROCESS_STATES.set(key, state);
    // Random ~5% failure for demo retry.
    const willFail = Math.random() < 0.05;
    setTimeout(() => {
        const cur = PROCESS_STATES.get(key);
        if (cur && cur.status === 'queued') {
            cur.status = 'processing';
        }
    }, 600);
    setTimeout(() => {
        const cur = PROCESS_STATES.get(key);
        if (cur && cur.status === 'processing') {
            cur.status = willFail ? 'failed' : 'done';
        }
    }, 1500);
    return state;
}

// Lazy-start the push loop on first telegram-related request.
let pushLoopStarted = false;
function ensurePushLoopStarted() {
    if (pushLoopStarted) return;
    pushLoopStarted = true;
    if (typeof window === 'undefined') return;
    if ((import.meta as any).env?.MODE === 'test') return;
    const stop = startMockPushLoop({ intervalMs: 9000, jitterMs: 6000 });
    if ((import.meta as any).hot) {
        (import.meta as any).hot.dispose(() => stop());
    }
}

register('get', /\/api\/userbot\/config$/, () => ({
    api_id: '',
    api_hash: '',
    phone_number: '',
    target_chat_ids: [],
}));

register('get', /\/api\/userbot\/status$/, () => ({
    is_connected: false,
    phone_number: '',
    monitored_chats: [],
}));

register('post', /\/api\/userbot\/.*$/, () => ({ success: true, message: 'ok' }));

register('get', /\/api\/tg\/status$/, () => {
    ensurePushLoopStarted();
    return {
        state: 'ready',
        raw_state: 'ready',
        is_authorized: true,
        phone_number: '+998901234567',
        user: { id: 1, first_name: 'Demo', username: 'demo_user' },
    };
});

register('get', /\/api\/tg\/overview$/, () => ({
    auth: {
        state: 'ready',
        raw_state: 'ready',
        is_authorized: true,
        phone_number: '+998901234567',
        user: { id: 1, first_name: 'Demo', username: 'demo_user' },
    },
    chats: {
        total: 2,
        items: [
            {
                chat_id: -1001234567890,
                title: 'Bank Notifications',
                chat_type: 'bot',
                is_hidden: false,
                is_protected: false,
                is_monitored: true,
                monitor_enabled: true,
                last_message: null,
                latest_message_id: 1024,
                latest_message_date: new Date().toISOString(),
                backlog_lag_messages: 0,
                backlog_state: 'healthy',
            },
            {
                chat_id: -1009876543210,
                title: 'Card Alerts',
                chat_type: 'channel',
                is_hidden: false,
                is_protected: false,
                is_monitored: false,
                monitor_enabled: false,
                last_message: null,
                latest_message_id: 712,
                latest_message_date: new Date().toISOString(),
                backlog_lag_messages: 0,
                backlog_state: 'healthy',
            },
        ],
    },
    monitor: { running: true, queue_size: 0, workers: 2 },
    server_time: new Date().toISOString(),
}));

register('get', /\/api\/tg\/chats$/, () => {
    ensurePushLoopStarted();
    return {
        total: TG_MOCK_CHATS.length,
        items: TG_MOCK_CHATS,
    };
});

register('get', /\/api\/tg\/chats\/[-\d]+\/messages$/, ({ config }) => {
    const m = String(config.url || '').match(/\/chats\/([-\d]+)\/messages/);
    const chatId = Number(m?.[1] || 0);
    const items = (TG_MOCK_MESSAGES[chatId] || [])
        .slice()
        .sort((a, b) => {
            const ta = a.date ? new Date(a.date).getTime() : 0;
            const tb = b.date ? new Date(b.date).getTime() : 0;
            return ta - tb;
        });
    return {
        total: items.length,
        items,
    };
});

register('get', /\/api\/tg\/chats\/[-\d]+\/messages\/by-date-range$/, ({ config }) => {
    const m = String(config.url || '').match(/\/chats\/([-\d]+)\//);
    const chatId = Number(m?.[1] || 0);
    return {
        total: (TG_MOCK_MESSAGES[chatId] || []).length,
        items: TG_MOCK_MESSAGES[chatId] || [],
    };
});

// Send / process / monitor / hide / password
register('post', /\/api\/tg\/chats\/[-\d]+\/messages$/, ({ config }) => {
    const m = String(config.url || '').match(/\/chats\/([-\d]+)\/messages/);
    const chatId = Number(m?.[1] || 0);
    const text = config.data?.text || '';
    return pushMessageToChat(chatId, { is_outgoing: true, text });
});

register('post', /\/api\/tg\/chats\/[-\d]+\/documents$/, ({ config }) => {
    const m = String(config.url || '').match(/\/chats\/([-\d]+)\/documents/);
    const chatId = Number(m?.[1] || 0);
    const file: File | undefined = config.data instanceof FormData ? (config.data.get('file') as File) : undefined;
    const fileName = file?.name || 'uploaded.pdf';
    const mimeType = file?.type || 'application/pdf';
    const size = file?.size || 100000;
    return pushMessageToChat(chatId, {
        is_outgoing: true,
        text: null,
        document: { file_id: Date.now(), file_name: fileName, mime_type: mimeType, size },
    });
});

register('post', /\/api\/tg\/chats\/[-\d]+\/messages\/\d+\/process$/, ({ config }) => {
    const m = String(config.url || '').match(/\/chats\/([-\d]+)\/messages\/(\d+)\/process/);
    const chatId = Number(m?.[1] || 0);
    const messageId = Number(m?.[2] || 0);
    const state = ensureProcessState(chatId, messageId);
    return {
        chat_id: chatId,
        message_id: messageId,
        task_id: state.taskId,
        status: state.status,
    };
});

register('get', /\/api\/tg\/chats\/[-\d]+\/messages\/\d+\/process-status$/, ({ config }) => {
    const m = String(config.url || '').match(/\/chats\/([-\d]+)\/messages\/(\d+)\/process-status/);
    const chatId = Number(m?.[1] || 0);
    const messageId = Number(m?.[2] || 0);
    const key = processKey(chatId, messageId);
    const state = PROCESS_STATES.get(key);
    if (!state) {
        return { chat_id: chatId, message_id: messageId, status: 'not_processed' };
    }
    return {
        chat_id: chatId,
        message_id: messageId,
        task_id: state.taskId,
        status: state.status,
    };
});

register('post', /\/api\/tg\/chats\/[-\d]+\/process-batch$/, ({ config }) => {
    const m = String(config.url || '').match(/\/chats\/([-\d]+)\/process-batch/);
    const chatId = Number(m?.[1] || 0);
    const ids: number[] = Array.isArray(config.data?.message_ids) ? config.data.message_ids : [];
    const results = ids.map((messageId) => {
        const state = ensureProcessState(chatId, messageId);
        return {
            chat_id: chatId,
            message_id: messageId,
            task_id: state.taskId,
            status: state.status,
        };
    });
    return { results };
});

register('post', /\/api\/tg\/chats\/[-\d]+\/monitor$/, ({ config }) => {
    const m = String(config.url || '').match(/\/chats\/([-\d]+)\/monitor/);
    const chatId = Number(m?.[1] || 0);
    const enabled = !!config.data?.enabled;
    const idx = TG_MOCK_CHATS.findIndex((c) => c.chat_id === chatId);
    if (idx >= 0) {
        TG_MOCK_CHATS[idx].monitor_enabled = enabled;
        TG_MOCK_CHATS[idx].is_monitored = enabled;
    }
    return { chat_id: chatId, enabled };
});

register('post', /\/api\/tg\/chats\/[-\d]+\/hidden$/, ({ config }) => {
    const m = String(config.url || '').match(/\/chats\/([-\d]+)\/hidden/);
    const chatId = Number(m?.[1] || 0);
    const hidden = !!config.data?.hidden;
    const idx = TG_MOCK_CHATS.findIndex((c) => c.chat_id === chatId);
    if (idx >= 0) {
        TG_MOCK_CHATS[idx].is_hidden = hidden;
    }
    return { chat_id: chatId, hidden, updated_at: new Date().toISOString() };
});

register('post', /\/api\/tg\/chats\/[-\d]+\/password$/, ({ config }) => {
    const m = String(config.url || '').match(/\/chats\/([-\d]+)\/password/);
    const chatId = Number(m?.[1] || 0);
    const idx = TG_MOCK_CHATS.findIndex((c) => c.chat_id === chatId);
    if (idx >= 0) {
        TG_MOCK_CHATS[idx].is_protected = true;
    }
    return { chat_id: chatId, protected: true };
});

register('delete', /\/api\/tg\/chats\/[-\d]+\/password$/, ({ config }) => {
    const m = String(config.url || '').match(/\/chats\/([-\d]+)\/password/);
    const chatId = Number(m?.[1] || 0);
    const idx = TG_MOCK_CHATS.findIndex((c) => c.chat_id === chatId);
    if (idx >= 0) {
        TG_MOCK_CHATS[idx].is_protected = false;
    }
    return { chat_id: chatId, protected: false };
});

register('get', /\/api\/tg\/chats\/[-\d]+\/history\/messages$/, () => ({
    total: 0,
    items: [],
}));

register('get', /\/api\/tg\/chats\/[-\d]+\/history\/(load\/status|stats|receipt-status)$/, ({ config }) => {
    const m = String(config.url || '').match(/\/chats\/([-\d]+)\//);
    const chatId = Number(m?.[1] || 0);
    if (config.url?.includes('stats')) {
        return {
            chat_id: chatId,
            sync: { chat_id: chatId, status: 'idle', loaded_count: 0, running: false },
            total_messages: 0,
            oldest_message_date: null,
            newest_message_date: null,
            linked_receipts: 0,
            total_transactions: 0,
        };
    }
    if (config.url?.includes('receipt-status')) {
        return {
            chat_id: chatId,
            total_messages: 0,
            processed_messages: 0,
            total_transactions_from_chat: 0,
        };
    }
    return {
        chat_id: chatId,
        status: 'idle',
        cursor_message_id: 0,
        loaded_count: 0,
        running: false,
    };
});

register('get', /\/api\/tg\/chats\/[-\d]+\/password\/status$/, () => ({
    protected: false,
    locked: false,
}));

register('get', /\/api\/tg\/chats\/[-\d]+\/receipt-status$/, () => ({ results: [] }));

register('get', /\/api\/tg\/monitors$/, () => []);

register('get', /\/api\/tg\/monitor\/status$/, () => ({
    running: true,
    queue_size: 0,
    workers: 2,
}));

register('post', /\/api\/tg\/.*$/, () => ({ ok: true }));
register('put', /\/api\/tg\/.*$/, () => ({ ok: true }));
register('delete', /\/api\/tg\/.*$/, () => ({ ok: true }));

// ─── Security ─────────────────────────────────────────────────────────────────
register('get', /\/api\/security\/status$/, () => ({
    scopes_enabled: false,
    available_years: [2024, 2025, 2026],
    current_scope: null,
}));

register('get', /\/api\/security\/system-status$/, () => ({
    enforced: false,
    path: null,
    loaded: false,
    error: null,
    scopes_managed_by_config: false,
    available_scope_count: 0,
}));

register('get', /\/api\/security\/scopes$/, () => []);

register('get', /\/api\/security\/sessions$/, () => [
    {
        session_id: 'mock-current',
        token_kind: 'access',
        subject: 'admin',
        user_id: MOCK_USER.id,
        ip_address: '127.0.0.1',
        created_at: new Date(Date.now() - 60_000).toISOString(),
        last_activity_at: new Date().toISOString(),
        expires_at: new Date(Date.now() + 24 * 3600 * 1000).toISOString(),
    },
]);

register('get', /\/api\/security\/audit$/, () => []);

register('get', /\/api\/security\/locked-periods$/, () => ({ periods: [] }));

register('get', /\/api\/security\/app\/launch-status$/, () => ({
    password_set: false,
    locked: false,
}));

register('post', /\/api\/security\/.*$/, () => ({ ok: true }));
register('put', /\/api\/security\/.*$/, () => ({ ok: true }));
register('delete', /\/api\/security\/.*$/, () => ({ ok: true }));

// ─── System settings / 2FA / periods / sessions / admin ───────────────────────
register('get', /\/api\/system-settings$/, () => ({
    id: 1,
    otp_enabled: false,
    bot_control_enabled: false,
    totp_2fa_enabled: false,
    launch_gate_enabled: false,
    updated_at: new Date().toISOString(),
    updated_by: MOCK_USER.id,
}));

register('patch', /\/api\/system-settings$/, ({ config }) => ({
    id: 1,
    otp_enabled: false,
    bot_control_enabled: false,
    totp_2fa_enabled: false,
    launch_gate_enabled: false,
    ...(config.data || {}),
    updated_at: new Date().toISOString(),
}));

register('get', /\/api\/2fa\/status$/, () => ({
    enabled: false,
    force_2fa: false,
    confirmed_at: null,
    global_policy_enabled: false,
    required_now: false,
}));

register('post', /\/api\/2fa\/.*$/, () => ({ ok: true }));
register('delete', /\/api\/2fa.*$/, () => ({ ok: true }));

register('get', /\/api\/periods$/, () => []);
register('post', /\/api\/periods$/, ({ config }) => ({
    id: Math.floor(Math.random() * 1000),
    is_active: true,
    ...(config.data || {}),
}));
register('patch', /\/api\/periods\/\d+$/, ({ config }) => ({
    id: 1,
    is_active: true,
    ...(config.data || {}),
}));
register('delete', /\/api\/periods\/\d+$/, () => ({ status: 'ok', id: 1, is_active: false }));

register('get', /\/api\/admin\/users$/, () => [
    {
        ...MOCK_USER,
        is_active: true,
        failed_attempts: 0,
        last_login_at: new Date().toISOString(),
    },
    {
        id: 2,
        username: 'operator',
        display_name: 'Оператор Иван',
        role: 'operator',
        is_active: true,
        allowed_tabs: ['dashboard', 'reference'],
        allowed_folders: [],
        forbidden_periods: [],
        allowed_sources: [],
        can_toggle_sources: false,
        permissions_version: 1,
        force_2fa: false,
        totp_enabled: false,
        session_ttl_days: 7,
        failed_attempts: 0,
        last_login_at: new Date(Date.now() - 3600_000).toISOString(),
    },
]);

register('post', /\/api\/admin\/users(\/.+)?$/, ({ config }) => ({
    ...MOCK_USER,
    is_active: true,
    failed_attempts: 0,
    ...(config.data || {}),
}));

register('patch', /\/api\/admin\/users\/\d+$/, ({ config }) => ({
    ...MOCK_USER,
    is_active: true,
    failed_attempts: 0,
    ...(config.data || {}),
}));

register('delete', /\/api\/admin\/users\/\d+$/, () => ({ ...MOCK_USER, is_active: false }));

// ─── Audit ────────────────────────────────────────────────────────────────────
register('get', /\/api\/audit$/, () => [
    {
        id: 1,
        action: 'login',
        success: true,
        user_id: MOCK_USER.id,
        ip_address: '127.0.0.1',
        details: null,
        created_at: new Date().toISOString(),
    },
    {
        id: 2,
        action: 'transaction.update',
        success: true,
        user_id: MOCK_USER.id,
        ip_address: '127.0.0.1',
        details: { transaction_id: 1001 },
        created_at: new Date(Date.now() - 5 * 60_000).toISOString(),
    },
]);

// ─── AI agent ─────────────────────────────────────────────────────────────────
register('get', /\/api\/agent\/threads$/, () => []);
register('post', /\/api\/agent\/threads$/, () => ({
    id: 'mock-thread',
    created_by_user_id: MOCK_USER.id,
    title: 'Новая беседа',
    context: {},
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
}));

register('get', /\/api\/agent\/threads\/[\w-]+$/, () => ({
    id: 'mock-thread',
    created_by_user_id: MOCK_USER.id,
    title: 'Новая беседа',
    context: {},
    messages: [],
    runs: [],
    run_events: [],
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
}));

register('post', /\/api\/agent\/threads\/[\w-]+\/messages$/, () => ({
    accepted: true,
    thread_id: 'mock-thread',
    message: { id: 'mock-msg', created_at: new Date().toISOString() },
    run: {
        id: 'mock-run',
        thread_id: 'mock-thread',
        created_by_user_id: MOCK_USER.id,
        status: 'completed',
        progress: {},
        result: { text: 'Mock-ответ от агента в дизайн-режиме.' },
        requires_confirmation: false,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
    },
}));

register('get', /\/api\/agent\/notifications$/, () => []);
register('post', /\/api\/agent\/notifications\/.*$/, () => ({ ok: true }));
register('post', /\/api\/agent\/threads\/[\w-]+\/(archive|trash|restore|purge)$/, () => ({ ok: true }));
register('patch', /\/api\/agent\/threads\/[\w-]+$/, ({ config }) => ({
    id: 'mock-thread',
    created_by_user_id: MOCK_USER.id,
    title: 'Новая беседа',
    context: {},
    ...(config.data || {}),
}));
register('get', /\/api\/agent\/reports$/, () => []);
register('post', /\/api\/agent\/reports\/.*$/, () => ({ ok: true }));
register('get', /\/api\/agent\/reports\/[\w-]+$/, () => ({
    id: 'mock-report',
    created_by_user_id: MOCK_USER.id,
    scope: 'personal',
    title: 'Демо-отчёт',
    status: 'ready',
    summary: {},
    payload: {},
    items: [],
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
}));
register('post', /\/api\/agent\/runs\/[\w-]+\/(confirm|reject)$/, () => ({
    id: 'mock-run',
    thread_id: 'mock-thread',
    created_by_user_id: MOCK_USER.id,
    status: 'completed',
    progress: {},
    result: null,
    requires_confirmation: false,
}));

// ─── Health ───────────────────────────────────────────────────────────────────
register('get', /\/health$/, () => ({ status: 'ok', mode: 'design-sandbox' }));

// ─── Dispatcher ───────────────────────────────────────────────────────────────
const dispatch = async (method: string, url: string, config: MockConfig): Promise<MockResponse> => {
    await delay(40);
    const fullConfig: MockConfig = { ...config, url, method };
    for (const route of routes) {
        if (route.method !== method) continue;
        const m = url.match(route.pattern);
        if (m) {
            try {
                const data = await route.handler({ config: fullConfig, match: m });
                return ok(data, fullConfig);
            } catch (err) {
                // eslint-disable-next-line no-console
                console.error('[mock] handler error', method, url, err);
                return ok({ ok: false, error: 'mock_handler_failed' }, fullConfig);
            }
        }
    }
    // eslint-disable-next-line no-console
    console.warn('[mock] unmatched route', method.toUpperCase(), url);
    return ok({}, fullConfig);
};

const buildClient = () => {
    const client: any = {
        defaults: {
            baseURL: '',
            withCredentials: false,
            headers: { common: {}, get: {}, post: {}, put: {}, patch: {}, delete: {} },
        },
        interceptors: {
            request: { use: () => 0, eject: () => undefined, clear: () => undefined },
            response: { use: () => 0, eject: () => undefined, clear: () => undefined },
        },
        get: (url: string, config: MockConfig = {}) => dispatch('get', url, config),
        delete: (url: string, config: MockConfig = {}) => dispatch('delete', url, config),
        head: (url: string, config: MockConfig = {}) => dispatch('head', url, config),
        options: (url: string, config: MockConfig = {}) => dispatch('options', url, config),
        post: (url: string, data?: any, config: MockConfig = {}) =>
            dispatch('post', url, { ...config, data }),
        put: (url: string, data?: any, config: MockConfig = {}) =>
            dispatch('put', url, { ...config, data }),
        patch: (url: string, data?: any, config: MockConfig = {}) =>
            dispatch('patch', url, { ...config, data }),
        request: (config: MockConfig) =>
            dispatch(String(config.method || 'get').toLowerCase(), String(config.url || ''), config),
    };
    // Allow `apiClient(config)` style call as well.
    const callable = (config: MockConfig) => client.request(config);
    Object.assign(callable, client);
    return callable;
};

export const createMockApiClient = () => buildClient();
