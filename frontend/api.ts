/**
 * API client for backend communication
 */
import axios from 'axios';

const normalizeBaseUrl = (url?: string) => {
    if (!url) return undefined;
    try {
        const parsed = new URL(url);
        if (parsed.hostname === 'localhost') {
            parsed.hostname = '127.0.0.1';
        }
        return parsed.toString().replace(/\/$/, '');
    } catch {
        return url;
    }
};

const isAllowedLocalOverrideUrl = (url: string): boolean => {
    try {
        const parsed = new URL(url);
        return ['localhost', '127.0.0.1'].includes(parsed.hostname);
    } catch {
        return false;
    }
};

const getLocalApiOverride = () => {
    if (typeof window === 'undefined') return undefined;
    const isDev = Boolean((import.meta as any).env?.DEV);
    if (!isDev) return undefined;
    try {
        const raw = window.localStorage.getItem('api_base_url_override') || '';
        const trimmed = raw.trim();
        if (!trimmed || !isAllowedLocalOverrideUrl(trimmed)) {
            return undefined;
        }
        return normalizeBaseUrl(trimmed || undefined);
    } catch {
        return undefined;
    }
};

type ElectronSystemAccessStatus = {
    ok: boolean;
    path?: string;
    source?: string;
    error?: string | null;
    token?: string | null;
    apiBaseUrl?: string | null;
};

const getElectronSystemAccessApi = () => {
    if (typeof window === 'undefined') return null;
    const electronApi = (window as any).electronAPI;
    if (!electronApi?.isElectron || !electronApi?.systemAccess?.getStatus) return null;
    return electronApi.systemAccess;
};

let electronSystemAccessStatusPromise: Promise<ElectronSystemAccessStatus | null> | null = null;

export const loadElectronSystemAccessStatus = async (force = false): Promise<ElectronSystemAccessStatus | null> => {
    if (force) {
        electronSystemAccessStatusPromise = null;
    }
    if (!electronSystemAccessStatusPromise) {
        const systemApi = getElectronSystemAccessApi();
        if (!systemApi) {
            return null;
        }
        electronSystemAccessStatusPromise = systemApi
            .getStatus()
            .then((status: ElectronSystemAccessStatus) => status)
            .catch((err: any) => ({
                ok: false,
                error: err?.message || String(err),
                token: null,
                apiBaseUrl: null,
            }));
    }
    return electronSystemAccessStatusPromise;
};

const envApiUrl = normalizeBaseUrl((import.meta as any).env?.VITE_API_URL);
const defaultHost =
    typeof window !== 'undefined'
        ? (window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname || '127.0.0.1')
        : '127.0.0.1';
const isElectronRuntime = typeof window !== 'undefined' && Boolean((window as any).electronAPI?.isElectron);
const localApiOverride = getLocalApiOverride();
const electronDefaultApiUrl = 'http://127.0.0.1:8000';
export const API_BASE_URL =
    localApiOverride ||
    (isElectronRuntime
        ? (envApiUrl || electronDefaultApiUrl)
        : (envApiUrl || `http://${defaultHost}:8000`));

const EXPECTED_API_VERSION = String(
    (import.meta as any).env?.VITE_API_VERSION ||
    (import.meta as any).env?.VITE_APP_VERSION ||
    ''
).trim();
let lastApiVersionMismatch: string | null = null;

const dispatchApiVersionMismatch = (serverVersionRaw: unknown) => {
    if (typeof window === 'undefined' || !EXPECTED_API_VERSION) return;
    const serverVersion = String(serverVersionRaw || '').trim();
    if (!serverVersion) return;
    if (serverVersion === EXPECTED_API_VERSION) {
        lastApiVersionMismatch = null;
        return;
    }
    if (lastApiVersionMismatch === serverVersion) {
        return;
    }
    lastApiVersionMismatch = serverVersion;
    window.dispatchEvent(
        new CustomEvent('api-version-mismatch', {
            detail: {
                expected: EXPECTED_API_VERSION,
                server: serverVersion,
            },
        }),
    );
};

export const apiClient = axios.create({
    baseURL: API_BASE_URL,
    withCredentials: true,
    headers: {
        'Content-Type': 'application/json',
    },
});

const SCOPE_TOKEN_KEY = 'access_scope_token';
const SCOPE_TOKEN_CACHE_KEY = 'access_scope_token_cache';
const SCOPE_TOKEN_EXPIRES_KEY = 'access_scope_token_expires_at';
const AUTH_TOKEN_KEY = 'auth_token';
const LEGACY_AUTH_TOKEN_KEY = 'token';
const REFRESH_TOKEN_KEY = 'auth_refresh_token';
const SYSTEM_ACCESS_TOKEN_KEY = 'system_access_token';
const TELEGRAM_ACCESS_TOKEN_KEY = 'telegram_access_token';
const SCOPE_TOKEN_CACHE_TTL_MS = 60 * 60 * 1000;
let launchSessionToken: string | null = null;
const chatAccessTokens = new Map<number, string>();
let onLaunchSessionRevoked: (() => void) | null = null;
let onAuthSessionRevoked: (() => void) | null = null;
let browserSystemAccessStatusPromise: Promise<ElectronSystemAccessStatus | null> | null = null;

const bootstrapTokenStorageMigration = () => {
    if (typeof window === 'undefined') return;
    try {
        const migrateToLocal = (key: string, legacyKeys: string[] = []) => {
            const localExisting = window.localStorage.getItem(key);
            if (localExisting) {
                window.sessionStorage.removeItem(key);
                legacyKeys.forEach((legacy) => {
                    window.sessionStorage.removeItem(legacy);
                    if (legacy !== key) {
                        window.localStorage.removeItem(legacy);
                    }
                });
                return;
            }

            const migrated = [key, ...legacyKeys]
                .map((k) => window.sessionStorage.getItem(k))
                .find((v): v is string => Boolean(v))
                || [key, ...legacyKeys]
                    .map((k) => window.localStorage.getItem(k))
                    .find((v): v is string => Boolean(v));

            if (migrated) {
                window.localStorage.setItem(key, migrated);
            }

            window.sessionStorage.removeItem(key);
            legacyKeys.forEach((legacy) => {
                window.sessionStorage.removeItem(legacy);
                if (legacy !== key) {
                    window.localStorage.removeItem(legacy);
                }
            });
        };

        migrateToLocal(AUTH_TOKEN_KEY, [LEGACY_AUTH_TOKEN_KEY]);
        migrateToLocal(REFRESH_TOKEN_KEY, ['refresh_token']);
        migrateToLocal(SYSTEM_ACCESS_TOKEN_KEY);
        migrateToLocal(SCOPE_TOKEN_KEY);
        migrateToLocal(SCOPE_TOKEN_EXPIRES_KEY);
        migrateToLocal(SCOPE_TOKEN_CACHE_KEY);
        migrateToLocal(TELEGRAM_ACCESS_TOKEN_KEY);
    } catch {
        // ignore storage bootstrap errors
    }
};

bootstrapTokenStorageMigration();

const clearScopeTokenStorage = (): void => {
    if (typeof window === 'undefined') return;
    window.localStorage.removeItem(SCOPE_TOKEN_KEY);
    window.localStorage.removeItem(SCOPE_TOKEN_EXPIRES_KEY);
    window.localStorage.removeItem(SCOPE_TOKEN_CACHE_KEY);
    window.sessionStorage.removeItem(SCOPE_TOKEN_KEY);
    window.sessionStorage.removeItem(SCOPE_TOKEN_EXPIRES_KEY);
    window.sessionStorage.removeItem(SCOPE_TOKEN_CACHE_KEY);
};

const getFromLocalThenLegacySession = (key: string, legacyKeys: string[] = []): string | null => {
    if (typeof window === 'undefined') return null;

    const localValue = window.localStorage.getItem(key);
    if (localValue) {
        return localValue;
    }

    const fromLegacy = [key, ...legacyKeys]
        .map((k) => window.sessionStorage.getItem(k))
        .find((v): v is string => Boolean(v))
        || [key, ...legacyKeys]
            .map((k) => window.localStorage.getItem(k))
            .find((v): v is string => Boolean(v));

    if (!fromLegacy) {
        return null;
    }

    window.localStorage.setItem(key, fromLegacy);
    window.sessionStorage.removeItem(key);
    legacyKeys.forEach((legacy) => {
        window.sessionStorage.removeItem(legacy);
        if (legacy !== key) {
            window.localStorage.removeItem(legacy);
        }
    });
    return fromLegacy;
};

const setPersistentWithLegacyCleanup = (key: string, value: string | null, legacyKeys: string[] = []) => {
    if (typeof window === 'undefined') return;
    if (value) {
        window.localStorage.setItem(key, value);
        window.sessionStorage.removeItem(key);
        legacyKeys.forEach((legacy) => {
            window.localStorage.removeItem(legacy);
            window.sessionStorage.removeItem(legacy);
        });
        return;
    }
    window.localStorage.removeItem(key);
    window.sessionStorage.removeItem(key);
    legacyKeys.forEach((legacy) => {
        window.localStorage.removeItem(legacy);
        window.sessionStorage.removeItem(legacy);
    });
};

const loadBrowserSystemAccessStatus = async (force = false): Promise<ElectronSystemAccessStatus | null> => {
    if (typeof window === 'undefined' || isElectronRuntime) {
        return null;
    }
    if (force) {
        browserSystemAccessStatusPromise = null;
    }
    if (!browserSystemAccessStatusPromise) {
        browserSystemAccessStatusPromise = fetch('/client-access.json', {
            method: 'GET',
            cache: 'no-store',
        })
            .then(async (response) => {
                if (!response.ok) {
                    return null;
                }
                const contentType = response.headers.get('content-type') || '';
                const raw = await response.text();
                if (!raw.trim()) {
                    return null;
                }
                const looksJson =
                    contentType.toLowerCase().includes('application/json') ||
                    raw.trim().startsWith('{');
                if (!looksJson) {
                    return null;
                }
                const parsed = JSON.parse(raw) as {
                    system_access_token?: string;
                    api_base_url?: string;
                };
                const token = String(parsed.system_access_token || '').trim();
                if (!token) {
                    return null;
                }
                setPersistentWithLegacyCleanup(SYSTEM_ACCESS_TOKEN_KEY, token);
                return {
                    ok: true,
                    token,
                    apiBaseUrl: normalizeBaseUrl(parsed.api_base_url || undefined) || null,
                    source: 'web-client-access',
                };
            })
            .catch(() => null);
    }
    return browserSystemAccessStatusPromise;
};

const _parseScopeExpiryMs = (value?: string | null): number | null => {
    if (!value) return null;
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : null;
};

const _decodeJwtPayload = (token?: string | null): Record<string, any> | null => {
    if (!token || typeof window === 'undefined') return null;
    try {
        const parts = token.split('.');
        if (parts.length < 2) return null;
        const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
        const padded = base64 + '='.repeat((4 - (base64.length % 4 || 4)) % 4);
        return JSON.parse(window.atob(padded));
    } catch {
        return null;
    }
};

const _decodeJwtExpMs = (token?: string | null): number | null => {
    const payload = _decodeJwtPayload(token);
    const exp = Number(payload?.exp);
    if (!Number.isFinite(exp) || exp <= 0) return null;
    return exp * 1000;
};

const setScopeTokenWithExpiry = (token: string | null, expiresAt?: string | null): void => {
    if (!token) {
        clearScopeTokenStorage();
        return;
    }

    const now = Date.now();
    const explicitExpiryMs = _parseScopeExpiryMs(expiresAt || null);
    const tokenExpiryMs = _decodeJwtExpMs(token);
    const resolvedExpiryMs = [explicitExpiryMs, tokenExpiryMs]
        .filter((value): value is number => Number.isFinite(value))
        .reduce<number | null>((acc, value) => (acc === null ? value : Math.min(acc, value)), null);

    if (resolvedExpiryMs !== null && resolvedExpiryMs <= now) {
        clearScopeTokenStorage();
        return;
    }

    setPersistentWithLegacyCleanup(SCOPE_TOKEN_KEY, token);
    if (resolvedExpiryMs !== null) {
        setPersistentWithLegacyCleanup(SCOPE_TOKEN_EXPIRES_KEY, new Date(resolvedExpiryMs).toISOString());
    } else {
        setPersistentWithLegacyCleanup(SCOPE_TOKEN_EXPIRES_KEY, null);
    }
};

const getValidScopeToken = (): string | null => {
    const token = getFromLocalThenLegacySession(SCOPE_TOKEN_KEY);
    if (!token) return null;

    const now = Date.now();
    const storedExpiryRaw = getFromLocalThenLegacySession(SCOPE_TOKEN_EXPIRES_KEY);
    const storedExpiryMs = _parseScopeExpiryMs(storedExpiryRaw);
    const jwtExpiryMs = _decodeJwtExpMs(token);
    const effectiveExpiryMs = [storedExpiryMs, jwtExpiryMs]
        .filter((value): value is number => Number.isFinite(value))
        .reduce<number | null>((acc, value) => (acc === null ? value : Math.min(acc, value)), null);

    if (effectiveExpiryMs !== null && effectiveExpiryMs <= now) {
        clearScopeTokenStorage();
        return null;
    }

    if (effectiveExpiryMs !== null && storedExpiryMs !== effectiveExpiryMs) {
        setPersistentWithLegacyCleanup(SCOPE_TOKEN_EXPIRES_KEY, new Date(effectiveExpiryMs).toISOString());
    }

    return token;
};

export const getAuthToken = (): string | null =>
    getFromLocalThenLegacySession(AUTH_TOKEN_KEY, [LEGACY_AUTH_TOKEN_KEY]);

export const setAuthToken = (token: string | null): void => {
    setPersistentWithLegacyCleanup(AUTH_TOKEN_KEY, token, [LEGACY_AUTH_TOKEN_KEY]);
};

export const getRefreshToken = (): string | null => getFromLocalThenLegacySession(REFRESH_TOKEN_KEY, ['refresh_token']);

export const setRefreshToken = (token: string | null): void => {
    setPersistentWithLegacyCleanup(REFRESH_TOKEN_KEY, token, ['refresh_token']);
};

export const getSystemAccessToken = (): string | null =>
    getFromLocalThenLegacySession(SYSTEM_ACCESS_TOKEN_KEY);

export const setSystemAccessToken = (token: string | null): void => {
    setPersistentWithLegacyCleanup(SYSTEM_ACCESS_TOKEN_KEY, token);
};

export const setLaunchSessionToken = (token: string | null) => {
    launchSessionToken = token;
};

export const getLaunchSessionToken = () => launchSessionToken;

export const setOnLaunchSessionRevoked = (callback: (() => void) | null) => {
    onLaunchSessionRevoked = callback;
};

export const setOnAuthSessionRevoked = (callback: (() => void) | null) => {
    onAuthSessionRevoked = callback;
};

export const setChatAccessToken = (chatId: number, token: string | null) => {
    if (!token) {
        chatAccessTokens.delete(chatId);
        return;
    }
    chatAccessTokens.set(chatId, token);
};

export const getChatAccessToken = (chatId: number) => chatAccessTokens.get(chatId) || null;

export const clearChatAccessTokens = () => {
    chatAccessTokens.clear();
};

export const clearClientSecurityState = (): void => {
    setLaunchSessionToken(null);
    clearChatAccessTokens();
    if (typeof window === 'undefined') return;
    setAuthToken(null);
    setRefreshToken(null);
    clearScopeTokenStorage();
};

export const buildAuthorizedRequestHeaders = async (
    extraHeaders?: Record<string, string>,
): Promise<Record<string, string>> => {
    const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        ...(extraHeaders || {}),
    };

    if (isElectronRuntime) {
        const access = await loadElectronSystemAccessStatus();
        if (!access || !access.ok) {
            throw new Error(
                access?.error ||
                'Доступ закрыт: отсутствует или поврежден client-access.json',
            );
        }
        if (access.token) {
            headers['X-System-Access'] = access.token;
        }
    } else {
        let systemToken = getSystemAccessToken();
        if (!systemToken) {
            const access = await loadBrowserSystemAccessStatus();
            systemToken = access?.token || null;
        }
        if (systemToken) {
            headers['X-System-Access'] = systemToken;
        }
    }

    const token = getAuthToken();
    if (token) {
        headers.Authorization = `Bearer ${token}`;
    }
    const scopeToken = getValidScopeToken();
    if (scopeToken) {
        headers['X-Access-Token'] = scopeToken;
    }
    if (launchSessionToken) {
        headers['X-Launch-Session'] = launchSessionToken;
    }
    return headers;
};

// Add auth token to all requests
apiClient.interceptors.request.use((config) => {
    const applyAuthHeaders = async () => {
        if (isElectronRuntime) {
            const access = await loadElectronSystemAccessStatus();
            if (!access || !access.ok) {
                throw new Error(
                    access?.error ||
                        'Доступ закрыт: отсутствует или поврежден client-access.json'
                );
            }
            if (access.apiBaseUrl) {
                const normalized = normalizeBaseUrl(access.apiBaseUrl);
                if (normalized) {
                    config.baseURL = normalized;
                }
            }
            if (access.token) {
                config.headers['X-System-Access'] = access.token;
            } else {
                throw new Error('Доступ закрыт: в client-access.json нет system_access_token');
            }
        } else {
            let systemToken = getSystemAccessToken();
            if (!systemToken) {
                const access = await loadBrowserSystemAccessStatus();
                systemToken = access?.token || null;
            }
            if (systemToken) {
                config.headers['X-System-Access'] = systemToken;
            }
        }

        const token = getAuthToken();
        if (token) {
            config.headers.Authorization = `Bearer ${token}`;
        }
        const scopeToken = getValidScopeToken();
        if (scopeToken) {
            config.headers['X-Access-Token'] = scopeToken;
        }
        if (launchSessionToken) {
            config.headers['X-Launch-Session'] = launchSessionToken;
        }
        return config;
    };

    return applyAuthHeaders();
});

let refreshInFlight: Promise<string | null> | null = null;

const isAuthRefreshExemptUrl = (url?: string): boolean => {
    const value = String(url || '');
    return (
        value.includes('/api/auth/login') ||
        value.includes('/api/auth/login/2fa') ||
        value.includes('/api/auth/refresh') ||
        value.includes('/api/auth/logout')
    );
};

const handleUnauthorizedFailure = (error: any) => {
    const detail = error?.response?.data?.detail;
    const detailText =
        typeof detail === 'string'
            ? detail.toLowerCase()
            : typeof detail?.error === 'string'
                ? String(detail.error).toLowerCase()
                : '';
    setAuthToken(null);
    setRefreshToken(null);
    if (detailText.includes('permissions_outdated')) {
        clearScopeTokenStorage();
        clearChatAccessTokens();
    }
    if (onAuthSessionRevoked) {
        onAuthSessionRevoked();
    }
};

const refreshAuthToken = async (): Promise<string | null> => {
    const refreshToken = getRefreshToken();
    const response = await apiClient.post<LoginResponse>(
        '/api/auth/refresh',
        { refresh_token: refreshToken || undefined },
        {
            headers: refreshToken ? { 'X-Refresh-Token': refreshToken } : undefined,
            // @ts-ignore - custom marker used by interceptor logic
            __isRefreshRequest: true,
            validateStatus: (status: number) => [200, 401, 403].includes(status || 0),
        } as any
    );
    if (!response.data?.ok || !response.data?.token) {
        return null;
    }
    setAuthToken(response.data.token);
    if (response.data.refresh_token) {
        setRefreshToken(response.data.refresh_token);
    }
    return response.data.token;
};

// Handle 401/403 responses + single-flight refresh retry.
apiClient.interceptors.response.use(
    (response) => {
        dispatchApiVersionMismatch(response?.headers?.['x-api-version']);
        return response;
    },
    async (error) => {
        const status = error.response?.status;
        const config = (error.config || {}) as any;
        dispatchApiVersionMismatch(error?.response?.headers?.['x-api-version']);

        if (status === 401) {
            const alreadyRetried = Boolean(config.__retriedAfterRefresh);
            const isRefreshRequest = Boolean(config.__isRefreshRequest);
            const skipRefresh = isRefreshRequest || isAuthRefreshExemptUrl(config.url);

            if (!alreadyRetried && !skipRefresh && getAuthToken()) {
                if (!refreshInFlight) {
                    refreshInFlight = refreshAuthToken().finally(() => {
                        refreshInFlight = null;
                    });
                }
                const newAccessToken = await refreshInFlight;
                if (newAccessToken) {
                    config.__retriedAfterRefresh = true;
                    config.headers = config.headers || {};
                    config.headers.Authorization = `Bearer ${newAccessToken}`;
                    return apiClient(config);
                }
            }

            handleUnauthorizedFailure(error);
        }

        if (status === 403) {
            const detail = error.response?.data?.detail;
            const errorCode =
                detail && typeof detail === 'object'
                    ? String((detail as any).error || '').toLowerCase()
                    : '';
            if (errorCode === 'launch_expired' || errorCode === 'launch_required') {
                setLaunchSessionToken(null);
                clearScopeTokenStorage();
                clearChatAccessTokens();
                if (onLaunchSessionRevoked) {
                    onLaunchSessionRevoked();
                }
            }
            if (
                (typeof detail === 'string' && detail.toLowerCase().includes('scope')) ||
                errorCode.includes('scope')
            ) {
                clearScopeTokenStorage();
            }
        }
        return Promise.reject(error);
    }
);

export const clearElectronSystemAccessCache = (): void => {
    electronSystemAccessStatusPromise = null;
};

// Types
export interface Transaction {
    id: number;
    transaction_date: string;
    amount: string;
    currency: string;
    card_last_4: string | null;
    operator_raw: string | null;
    application_mapped: string | null;
    transaction_type: 'DEBIT' | 'CREDIT' | 'CONVERSION' | 'REVERSAL';
    transaction_type_display: string;
    balance_after: string | null;
    receiver_name?: string | null;
    receiver_card?: string | null;
    source_type: 'MANUAL' | 'AUTO' | 'SMS';
    source_channel: 'TELEGRAM' | 'SMS' | 'MANUAL';
    source_display: string;
    source_chat_id?: number | null;
    source_chat_title?: string | null;
    source_origin_type?: 'bot' | 'group' | 'supergroup' | 'channel' | 'private' | null;
    parsing_method: string | null;
    parsing_confidence: number | null;
    is_p2p?: boolean;
    created_at: string;
    raw_message?: string | null;
}

export interface TransactionListResponse {
    ok?: boolean;
    total: number;
    page: number;
    page_size: number;
    items: Transaction[];
    has_more?: boolean;
    next_cursor?: { id: number; updated_at?: string | null } | null;
    cursor_mode?: boolean;
    locked_notice?: string | null;
}

export interface TransactionsQueryParams {
    page?: number;
    page_size?: number;
    sort_by?: string;
    sort_dir?: 'asc' | 'desc';
    date_from?: string;
    date_to?: string;
    operators?: string[];
    apps?: string[];
    operator?: string;
    app?: string;
    amount_min?: string;
    amount_max?: string;
    parsing_method?: string;
    confidence_min?: number;
    confidence_max?: number;
    search?: string;
    source_type?: 'AUTO' | 'MANUAL' | 'SMS';
    source_channel?: 'TELEGRAM' | 'SMS' | 'MANUAL';
    source_chat_ids?: number[];
    transaction_type?: 'DEBIT' | 'CREDIT' | 'CONVERSION' | 'REVERSAL';
    transaction_types?: string[];
    currency?: 'UZS' | 'USD';
    card?: string;
    days_of_week?: number[];
    columns?: string[];
    cursor_updated_at?: string;
    cursor_id?: number;
}

export interface TransactionsExportResponse {
    blob: Blob;
    filename?: string | null;
}

const parseContentDispositionFilename = (contentDisposition?: string | null): string | null => {
    if (!contentDisposition) return null;
    const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8Match?.[1]) {
        try {
            return decodeURIComponent(utf8Match[1]);
        } catch {
            return utf8Match[1];
        }
    }
    const basicMatch = contentDisposition.match(/filename="?([^"]+)"?/i);
    return basicMatch?.[1] || null;
};

// Update/Delete types
export interface TransactionUpdateRequest {
    transaction_date?: string;
    operator_raw?: string;
    application_mapped?: string;
    amount?: string;
    balance_after?: string;
    card_last_4?: string;
    receiver_name?: string;
    receiver_card?: string;
    transaction_type?: 'DEBIT' | 'CREDIT' | 'CONVERSION' | 'REVERSAL';
    currency?: 'UZS' | 'USD';
    source_type?: 'AUTO' | 'MANUAL' | 'SMS';
    parsing_method?: string;
    parsing_confidence?: number;
}

export interface TransactionUpdateResponse {
    success: boolean;
    message: string;
    transaction: Transaction;
}

export interface DeleteResponse {
    success: boolean;
    message: string;
    deleted_id: number;
}

export interface BulkDeleteRequest {
    ids: number[];
}

export interface BulkDeleteResponse {
    success: boolean;
    deleted_count: number;
    failed_ids: number[];
    errors: string[];
}

export interface BulkUpdatePayload {
    updates: Array<{
        id: number;
        fields: Record<string, any>;
    }>;
}

export interface BulkUpdateResponse {
    success: boolean;
    updated_count: number;
    failed_ids: number[];
    errors: string[];
}

export interface ProcessReceiptResponse {
    created: boolean;
    duplicate: boolean;
    transaction: Transaction;
    parsing: {
        method: string | null;
        confidence: number | null;
        notes?: string | null;
    };
}

export interface ProcessReceiptBatchItem {
    message_id: number;
    success: boolean;
    error?: string;
    created?: boolean;
    duplicate?: boolean;
    transaction?: Transaction;
}

export interface ProcessReceiptBatchResponse {
    results: ProcessReceiptBatchItem[];
}

export interface ProcessedStatusResponse {
    statuses: Record<number, boolean>;
}

export interface TransactionYearsResponse {
    items: Array<{ year: number; count: number }>;
}

export interface TransactionsInitResponse {
    security_status: {
        scopes_enabled: boolean;
        available_years: number[];
        current_scope?: Record<string, any> | null;
    };
    years: Array<{ year: number; count: number }>;
    operators: string[];
    applications: string[];
    telegram_sources: Array<{
        chat_id: number;
        title: string;
        chat_type?: 'bot' | 'group' | 'supergroup' | 'channel' | 'private' | null;
        count: number;
    }>;
}

export interface DuplicateMergeEvent {
    id: number;
    fingerprint?: string | null;
    existing_transaction_id: number;
    source_chat_id?: number | null;
    source_message_id?: number | null;
    merged: boolean;
    candidate_method?: string | null;
    candidate_confidence?: number | null;
    existing_method?: string | null;
    existing_confidence?: number | null;
    details?: Record<string, any> | null;
    created_at?: string | null;
}

export interface CreateTransactionRequest {
    datetime: string;
    operator: string;
    amount: string;
    card_last4: string;
    transaction_type: 'DEBIT' | 'CREDIT' | 'CONVERSION' | 'REVERSAL';
    currency: 'UZS' | 'USD';
    app?: string | null;
    balance?: string | null;
    is_p2p?: boolean;
    receiver_name?: string | null;
    receiver_card?: string | null;
    raw_text?: string | null;
}

export interface TopAgentResponse {
    period_start: string;
    period_end: string;
    transaction_count: number;
    top_application: string | null;
    top_application_count: number;
    top_application_volume: string;
    total_volume: string;
    insight: string;
}

export interface SummaryResponse {
    total_transactions: number;
    debit_count: number;
    credit_count: number;
    gpt_parsed_count: number;
    gpt_usage_percentage: number;
    total_volume_uzs: string;
    average_confidence: number;
}

// API methods
export const transactionsApi = {
    getTransactions: async (params: TransactionsQueryParams): Promise<TransactionListResponse> => {
        const query: Record<string, any> = {
            page: params.page,
            page_size: params.page_size,
            sort_by: params.sort_by,
            sort_dir: params.sort_dir,
            date_from: params.date_from,
            date_to: params.date_to,
            operator: params.operator,
            app: params.app,
            amount_min: params.amount_min,
            amount_max: params.amount_max,
            parsing_method: params.parsing_method,
            confidence_min: params.confidence_min,
            confidence_max: params.confidence_max,
            search: params.search,
            source_type: params.source_type,
            source_channel: params.source_channel,
            transaction_type: params.transaction_type,
            currency: params.currency,
            card: params.card,
            cursor_updated_at: params.cursor_updated_at,
            cursor_id: params.cursor_id,
        };

        if (params.operators?.length) {
            query.operators = params.operators.join(',');
        }
        if (params.apps?.length) {
            query.apps = params.apps.join(',');
        }
        if (params.transaction_types?.length) {
            query.transaction_types = params.transaction_types.join(',');
        }
        if (params.days_of_week?.length) {
            query.days_of_week = params.days_of_week.join(',');
        }
        if (params.source_chat_ids?.length) {
            query.source_chat_ids = params.source_chat_ids.join(',');
        }

        const response = await apiClient.get<TransactionListResponse>('/api/transactions/', { params: query });
        return response.data;
    },

    exportTransactions: async (
        params: Omit<TransactionsQueryParams, 'page' | 'page_size' | 'cursor_updated_at' | 'cursor_id'>
    ): Promise<TransactionsExportResponse> => {
        const query = new URLSearchParams();
        const append = (key: string, value: unknown) => {
            if (value === undefined || value === null || value === '') return;
            query.append(key, String(value));
        };

        append('sort_by', params.sort_by);
        append('sort_dir', params.sort_dir);
        append('date_from', params.date_from);
        append('date_to', params.date_to);
        append('operator', params.operator);
        append('app', params.app);
        append('amount_min', params.amount_min);
        append('amount_max', params.amount_max);
        append('parsing_method', params.parsing_method);
        append('confidence_min', params.confidence_min);
        append('confidence_max', params.confidence_max);
        append('search', params.search);
        append('source_type', params.source_type);
        append('source_channel', params.source_channel);
        append('transaction_type', params.transaction_type);
        append('currency', params.currency);
        append('card', params.card);

        if (params.operators?.length) append('operators', params.operators.join(','));
        if (params.apps?.length) append('apps', params.apps.join(','));
        if (params.transaction_types?.length) append('transaction_types', params.transaction_types.join(','));
        if (params.days_of_week?.length) append('days_of_week', params.days_of_week.join(','));
        if (params.source_chat_ids?.length) append('source_chat_ids', params.source_chat_ids.join(','));
        if (params.columns?.length) {
            params.columns.forEach((col) => append('columns', col));
        }

        const response = await apiClient.get<Blob>('/api/transactions/export', {
            params: query,
            responseType: 'blob',
        });
        return {
            blob: response.data,
            filename: parseContentDispositionFilename(response.headers?.['content-disposition'] as string | undefined),
        };
    },

    getTransaction: async (id: number): Promise<Transaction> => {
        const response = await apiClient.get<Transaction>(`/api/transactions/${id}`);
        return response.data;
    },

    updateTransaction: async (id: number, data: TransactionUpdateRequest): Promise<TransactionUpdateResponse> => {
        const response = await apiClient.put<TransactionUpdateResponse>(`/api/transactions/${id}`, data);
        return response.data;
    },

    deleteTransaction: async (id: number): Promise<DeleteResponse> => {
        const response = await apiClient.delete<DeleteResponse>(`/api/transactions/${id}`);
        return response.data;
    },

    bulkDeleteTransactions: async (ids: number[]): Promise<BulkDeleteResponse> => {
        const response = await apiClient.post<BulkDeleteResponse>('/api/transactions/bulk-delete', { ids });
        return response.data;
    },

    bulkUpdateTransactions: async (payload: BulkUpdatePayload): Promise<BulkUpdateResponse> => {
        const response = await apiClient.patch<BulkUpdateResponse>('/api/transactions/bulk-update', payload);
        return response.data;
    },

    createTransaction: async (payload: CreateTransactionRequest): Promise<Transaction> => {
        const response = await apiClient.post<Transaction>('/api/transactions/', payload);
        return response.data;
    },

    processReceipt: async (chatId: number, messageId: number, force = false): Promise<ProcessReceiptResponse> => {
        const response = await apiClient.post<ProcessReceiptResponse>('/api/transactions/process-receipt', {
            chat_id: chatId,
            message_id: messageId,
            force,
        });
        return response.data;
    },

    processReceiptBatch: async (
        chatId: number,
        messageIds: number[],
        force = false
    ): Promise<ProcessReceiptBatchResponse> => {
        const response = await apiClient.post<ProcessReceiptBatchResponse>('/api/transactions/process-receipt-batch', {
            chat_id: chatId,
            message_ids: messageIds,
            force,
        });
        return response.data;
    },

    getProcessedStatus: async (chatId: number, messageIds: number[]): Promise<ProcessedStatusResponse> => {
        const params = {
            chat_id: chatId,
            message_ids: messageIds.join(','),
        };
        const response = await apiClient.get<ProcessedStatusResponse>('/api/transactions/processed-status', { params });
        return response.data;
    },

    getYears: async (): Promise<TransactionYearsResponse> => {
        const response = await apiClient.get<TransactionYearsResponse>('/api/transactions/years');
        return response.data;
    },

    getInit: async (): Promise<TransactionsInitResponse> => {
        const response = await apiClient.get<TransactionsInitResponse>('/api/transactions/init');
        return response.data;
    },

    getDuplicateEvents: async (params?: { limit?: number; merged?: boolean }): Promise<DuplicateMergeEvent[]> => {
        const response = await apiClient.get<DuplicateMergeEvent[]>('/api/transactions/duplicate-events', { params });
        return response.data;
    },
};

export const analyticsApi = {
    getTopAgent: async (): Promise<TopAgentResponse> => {
        const response = await apiClient.get<TopAgentResponse>('/api/analytics/top-agent');
        return response.data;
    },

    getSummary: async (): Promise<SummaryResponse> => {
        const response = await apiClient.get<SummaryResponse>('/api/analytics/summary');
        return response.data;
    },
};

export interface SyncTableManifestItem {
    row_count: number;
    last_updated?: string | null;
    checksum: string;
}

export interface SyncManifestResponse {
    tables: Record<string, SyncTableManifestItem>;
    server_time: string;
    full_resync_required?: boolean;
    reason?: string;
    retention_days?: number;
}

export interface SyncTableResponse<T = any> {
    table: string;
    rows: T[];
    total_count: number;
    has_more: boolean;
    server_checksum: string;
    server_time: string;
    deleted_ids: number[];
    blocked_ranges?: Array<{ from: string; to: string }>;
    next_cursor?: { id: number; updated_at?: string | null } | null;
}

export const syncApi = {
    getManifest: async (params?: { client_last_sync?: string }): Promise<SyncManifestResponse> => {
        const response = await apiClient.get<SyncManifestResponse>('/api/sync/manifest', { params });
        return response.data;
    },

    getTable: async (
        tableName: string,
        params?: {
            since?: string;
            since_id?: number;
            limit?: number;
            offset?: number;
            cursor_updated_at?: string;
            cursor_id?: number;
        }
    ): Promise<SyncTableResponse> => {
        const response = await apiClient.get<SyncTableResponse>(`/api/sync/${tableName}`, { params });
        return response.data;
    },
};

// Reference types
export interface OperatorReference {
    id: number;
    operator_name: string;
    application_name: string;
    is_p2p: boolean;
    is_active: boolean;
}

export interface OperatorReferenceListResponse {
    total: number;
    page: number;
    page_size: number;
    items: OperatorReference[];
}

export interface OperatorReferenceCreate {
    operator_name: string;
    application_name: string;
    is_p2p?: boolean;
    is_active?: boolean;
}

export interface OperatorReferenceUpdate {
    operator_name?: string;
    application_name?: string;
    is_p2p?: boolean;
    is_active?: boolean;
}

// Reference API methods
export const referenceApi = {
    getOperators: async (params: {
        page?: number;
        page_size?: number;
        search?: string;
        application?: string;
        is_p2p?: boolean;
        is_active?: boolean;
        all?: boolean;
    }): Promise<OperatorReferenceListResponse> => {
        const response = await apiClient.get<OperatorReferenceListResponse>('/api/reference', { params });
        return response.data;
    },

    createOperator: async (operator: OperatorReferenceCreate): Promise<OperatorReference> => {
        const response = await apiClient.post<OperatorReference>('/api/reference', operator);
        return response.data;
    },

    updateOperator: async (id: number, operator: OperatorReferenceUpdate): Promise<OperatorReference> => {
        const response = await apiClient.put<OperatorReference>(`/api/reference/${id}`, operator);
        return response.data;
    },

    deleteOperator: async (id: number): Promise<void> => {
        await apiClient.delete(`/api/reference/${id}`);
    },

    getApplications: async (): Promise<string[]> => {
        const response = await apiClient.get<string[]>('/api/reference/applications');
        return response.data;
    },

    exportToExcel: async (): Promise<Blob> => {
        const response = await apiClient.get('/api/reference/export/excel', {
            responseType: 'blob',
        });
        return response.data;
    },

    importFromExcel: async (file: File): Promise<{ imported: number; skipped: number; errors: string[] }> => {
        const formData = new FormData();
        formData.append('file', file);
        const response = await apiClient.post('/api/reference/import/excel', formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        });
        return response.data;
    },
};

// Verification types
export interface VerifyRequest {
    limit?: number;
    date_from?: string;
    date_to?: string;
}

export interface VerifyResponse {
    task_id: string;
    status: string;
    message: string;
}

export interface VerifyStatusResponse {
    task_id: string;
    status: string;
    progress: {
        total: number;
        processed: number;
        percent: number;
    };
    results?: {
        total_verified: number;
        transactions_with_errors: number;
        total_corrections: number;
    };
}

export interface VerificationSuggestion {
    id: string;
    task_id: string;
    transaction_id: number;
    field_name: string;
    field_label: string;
    current_value: string | null;
    suggested_value: string | null;
    confidence: number;
    reasoning: string | null;
    status: string;
    created_at: string;
}

// Automation types
export interface AnalyzeRequest {
    limit?: number;
    only_unmapped?: boolean;
    currency_filter?: string;
}

export interface AnalyzeResponse {
    task_id: string;
    status: string;
    message: string;
}

export interface AnalyzeStatusResponse {
    task_id: string;
    status: string;
    progress: {
        total: number;
        processed: number;
        percent: number;
    };
    results?: {
        suggestions_count: number;
        high_confidence: number;
        low_confidence: number;
    };
}

export interface AISuggestion {
    id: string;
    transaction_id: string;
    operator_raw: string;
    current_application: string | null;
    suggested_application: string;
    confidence: number;
    reasoning: string;
    is_new_application: boolean;
    is_p2p: boolean;
    status: string;
    created_at: string;
}

// Automation API methods
export const automationApi = {
    analyzeTransactions: async (request: AnalyzeRequest): Promise<AnalyzeResponse> => {
        const response = await apiClient.post<AnalyzeResponse>('/api/automation/analyze-transactions', request);
        return response.data;
    },

    getAnalyzeStatus: async (taskId: string): Promise<AnalyzeStatusResponse> => {
        try {
            const response = await apiClient.get<AnalyzeStatusResponse>(`/api/automation/analyze-status/${taskId}`);
            return response.data;
        } catch (err: any) {
            const status = err?.response?.status;
            if (status === 404) {
                // Gracefully handle missing/expired task ids
                return {
                    task_id: taskId,
                    status: 'not_found',
                    progress: { total: 0, processed: 0, percent: 0 },
                    results: undefined,
                };
            }
            throw err;
        }
    },

    getSuggestions: async (params: {
        status?: string;
        confidence_min?: number;
        task_id?: string;
    }): Promise<AISuggestion[]> => {
        const response = await apiClient.get<AISuggestion[]>('/api/automation/suggestions', { params });
        return response.data;
    },

    applySuggestion: async (suggestionId: string): Promise<{ success: boolean; transaction_id: string }> => {
        const response = await apiClient.post(`/api/automation/suggestions/${suggestionId}/apply`);
        return response.data;
    },

    rejectSuggestion: async (suggestionId: string): Promise<{ success: boolean }> => {
        const response = await apiClient.post(`/api/automation/suggestions/${suggestionId}/reject`);
        return response.data;
    },

    batchApplySuggestions: async (suggestionIds: string[]): Promise<{
        success: boolean;
        applied: number;
        errors: Array<{ suggestion_id: string; error: string }>;
    }> => {
        const response = await apiClient.post('/api/automation/suggestions/batch-apply', suggestionIds);
        return response.data;
    },

    // Verification methods
    verifyTransactions: async (request: VerifyRequest): Promise<VerifyResponse> => {
        const response = await apiClient.post<VerifyResponse>('/api/automation/verify-transactions', request);
        return response.data;
    },

    getVerifyStatus: async (taskId: string): Promise<VerifyStatusResponse> => {
        try {
            const response = await apiClient.get<VerifyStatusResponse>(`/api/automation/verify-status/${taskId}`);
            return response.data;
        } catch (err: any) {
            if (err?.response?.status === 404) {
                return { task_id: taskId, status: 'not_found', progress: { total: 0, processed: 0, percent: 0 } };
            }
            throw err;
        }
    },

    getVerificationSuggestions: async (params: {
        status?: string;
        task_id?: string;
        confidence_min?: number;
    }): Promise<VerificationSuggestion[]> => {
        const response = await apiClient.get<VerificationSuggestion[]>('/api/automation/verification-suggestions', { params });
        return response.data;
    },

    applyVerificationSuggestion: async (suggestionId: string): Promise<{ success: boolean }> => {
        const response = await apiClient.post(`/api/automation/verification-suggestions/${suggestionId}/apply`);
        return response.data;
    },

    rejectVerificationSuggestion: async (suggestionId: string): Promise<{ success: boolean }> => {
        const response = await apiClient.post(`/api/automation/verification-suggestions/${suggestionId}/reject`);
        return response.data;
    },

    batchApplyVerificationSuggestions: async (suggestionIds: string[]): Promise<{
        success: boolean;
        applied: number;
        errors: Array<{ suggestion_id: string; error: string }>;
    }> => {
        const response = await apiClient.post('/api/automation/verification-suggestions/batch-apply', suggestionIds);
        return response.data;
    },

    // ── Reconciliation methods ──────────────────────────────────────────────

    reconcileStart: async (request: ReconcileRequest): Promise<ReconcileResponse> => {
        const response = await apiClient.post<ReconcileResponse>('/api/automation/reconciliation/start', request);
        return response.data;
    },

    getReconcileStatus: async (taskId: string): Promise<ReconcileStatusResponse> => {
        try {
            const response = await apiClient.get<ReconcileStatusResponse>(`/api/automation/reconciliation/status/${taskId}`);
            return response.data;
        } catch (err: any) {
            if (err?.response?.status === 404) {
                return { task_id: taskId, status: 'not_found', progress: null };
            }
            throw err;
        }
    },

    getReconcileResults: async (taskId: string, params?: {
        category?: string;
        offset?: number;
        limit?: number;
    }): Promise<ReconcileResultsResponse> => {
        const response = await apiClient.get<ReconcileResultsResponse>(
            `/api/automation/reconciliation/results/${taskId}`,
            { params },
        );
        return response.data;
    },

    getChatSyncStatuses: async (chatIds: number[]): Promise<ChatSyncStatusItem[]> => {
        const response = await apiClient.get<ChatSyncStatusItem[]>(
            '/api/automation/reconciliation/chat-sync-status',
            { params: { chat_ids: chatIds.join(',') } },
        );
        return response.data;
    },

    autoParseReconciliation: async (taskId: string, category?: string): Promise<AutoParseResponse> => {
        const response = await apiClient.post<AutoParseResponse>(
            `/api/automation/reconciliation/${taskId}/auto-parse`,
            null,
            { params: category ? { category } : undefined },
        );
        return response.data;
    },
};

// Reconciliation types
export interface ReconcileRequest {
    period_start: string;
    period_end: string;
    bot_chat_ids: number[];
    auto_parse?: boolean;
    source?: 'local' | 'tdlib';
    sync_if_needed?: boolean;
}

export interface ReconcileResponse {
    task_id: string;
    status: string;
    message: string;
    sync_warnings?: Array<{ chat_id: number; warning: string; message: string }> | null;
}

export interface ReconcileStatusResponse {
    task_id: string;
    status: string;
    progress: { step?: string; percent?: number; [key: string]: any } | null;
}

export interface ReconciliationItem {
    message_id: number;
    chat_id: number;
    message_date: string | null;
    text_preview: string | null;
    category: 'MATCHED' | 'MISSING_IN_DB' | 'FAILED_PARSE' | 'ORPHANED_IN_DB';
    transaction_id: number | null;
    can_auto_parse: boolean;
}

export interface ReconciliationSummary {
    total_receipt_candidates: number;
    matched: number;
    missing_in_db: number;
    failed_parse: number;
    orphaned_in_db: number;
}

export interface ReconcileResultsResponse {
    task_id: string;
    status: string;
    summary: ReconciliationSummary | null;
    items: ReconciliationItem[];
    total_items: number;
    sync_warnings?: Array<{ chat_id: number; warning: string; message: string }> | null;
}

export interface ChatSyncStatusItem {
    chat_id: number;
    status: string;
    loaded_count: number;
    error: string | null;
    started_at: string | null;
    finished_at: string | null;
}

export interface AutoParseResponse {
    queued: number;
    skipped: number;
    errors: number;
}

// Userbot types
export interface UserbotConfig {
    api_id: string;
    api_hash: string;
    phone_number: string;
    target_chat_ids: string[];
}

export interface UserbotStatus {
    is_connected: boolean;
    phone_number?: string;
    monitored_chats?: string[];
}

// Userbot API methods
export const userbotApi = {
    getConfig: async (): Promise<UserbotConfig> => {
        const response = await apiClient.get<UserbotConfig>('/api/userbot/config');
        return response.data;
    },

    updateConfig: async (config: UserbotConfig): Promise<{ success: boolean }> => {
        const response = await apiClient.post('/api/userbot/config', config);
        return response.data;
    },

    getStatus: async (): Promise<UserbotStatus> => {
        const response = await apiClient.get<UserbotStatus>('/api/userbot/status');
        return response.data;
    },

    connect: async (): Promise<{ success: boolean; message: string }> => {
        const response = await apiClient.post('/api/userbot/connect');
        return response.data;
    },

    disconnect: async (): Promise<{ success: boolean; message: string }> => {
        const response = await apiClient.post('/api/userbot/disconnect');
        return response.data;
    },
};

export interface AccessScope {
    id: number;
    name: string;
    years: number[];
    period_start?: string | null;
    period_end?: string | null;
    allow_transactions: boolean;
    allow_sources: boolean;
    is_active: boolean;
    created_at?: string | null;
    updated_at?: string | null;
}

export interface AccessStatusResponse {
    scopes_enabled: boolean;
    available_years: number[];
    current_scope?: AccessScope | null;
}

export interface SystemAccessStatusResponse {
    enforced: boolean;
    path?: string | null;
    loaded: boolean;
    error?: string | null;
    scopes_managed_by_config: boolean;
    available_scope_count: number;
}

let systemStatusEndpointSupported: boolean | null = null;

type ScopeTokenCacheEntry = {
    token: string;
    cached_until: string;
    scope_id?: number | null;
};

type ScopeTokenCache = Record<string, ScopeTokenCacheEntry>;

const readScopeTokenCache = (): ScopeTokenCache => {
    if (typeof window === 'undefined') return {};
    try {
        const raw = getFromLocalThenLegacySession(SCOPE_TOKEN_CACHE_KEY);
        if (!raw) return {};
        const parsed = JSON.parse(raw) as ScopeTokenCache;
        if (!parsed || typeof parsed !== 'object') return {};
        return parsed;
    } catch {
        return {};
    }
};

const writeScopeTokenCache = (cache: ScopeTokenCache): void => {
    if (typeof window === 'undefined') return;
    if (!Object.keys(cache).length) {
        window.localStorage.removeItem(SCOPE_TOKEN_CACHE_KEY);
        window.sessionStorage.removeItem(SCOPE_TOKEN_CACHE_KEY);
        return;
    }
    window.localStorage.setItem(SCOPE_TOKEN_CACHE_KEY, JSON.stringify(cache));
    window.sessionStorage.removeItem(SCOPE_TOKEN_CACHE_KEY);
};

const pruneScopeTokenCache = (): ScopeTokenCache => {
    const cache = readScopeTokenCache();
    const now = Date.now();
    const cleaned: ScopeTokenCache = {};

    for (const [year, entry] of Object.entries(cache)) {
        if (!entry || typeof entry.token !== 'string' || typeof entry.cached_until !== 'string') {
            continue;
        }
        const expires = new Date(entry.cached_until).getTime();
        if (!Number.isFinite(expires) || expires <= now) {
            continue;
        }
        cleaned[year] = entry;
    }

    writeScopeTokenCache(cleaned);
    return cleaned;
};

const collectScopeYearsForCache = (scope?: AccessScope | null, preferredYear?: number): number[] => {
    const years = new Set<number>();

    (scope?.years || []).forEach((year) => {
        if (Number.isFinite(year)) {
            years.add(year);
        }
    });

    if (Number.isFinite(preferredYear)) {
        years.add(preferredYear as number);
    }

    const startYear =
        scope?.period_start && !Number.isNaN(new Date(scope.period_start).getTime())
            ? new Date(scope.period_start).getFullYear()
            : null;
    const endYear =
        scope?.period_end && !Number.isNaN(new Date(scope.period_end).getTime())
            ? new Date(scope.period_end).getFullYear()
            : null;

    if (startYear !== null || endYear !== null) {
        const from = Math.min(startYear ?? endYear!, endYear ?? startYear!);
        const to = Math.max(startYear ?? endYear!, endYear ?? startYear!);
        if (to - from <= 50) {
            for (let year = from; year <= to; year += 1) {
                years.add(year);
            }
        }
    }

    return Array.from(years);
};

const cacheScopeTokenByYears = (
    token: string,
    scope?: AccessScope | null,
    expiresAt?: string | null,
    preferredYear?: number
): void => {
    if (typeof window === 'undefined' || !token) return;

    const years = collectScopeYearsForCache(scope, preferredYear);
    if (!years.length) return;

    const now = Date.now();
    const maxCachedUntil = now + SCOPE_TOKEN_CACHE_TTL_MS;
    const responseExpiresAt = expiresAt ? new Date(expiresAt).getTime() : null;
    const finalExpiresAt =
        Number.isFinite(responseExpiresAt) && (responseExpiresAt as number) > now
            ? Math.min(maxCachedUntil, responseExpiresAt as number)
            : maxCachedUntil;

    if (finalExpiresAt <= now) return;

    const cache = pruneScopeTokenCache();
    const cachedUntilIso = new Date(finalExpiresAt).toISOString();

    years.forEach((year) => {
        cache[String(year)] = {
            token,
            cached_until: cachedUntilIso,
            scope_id: scope?.id ?? null,
        };
    });

    writeScopeTokenCache(cache);
};

const applyCachedScopeTokenForYear = (year: number): boolean => {
    if (typeof window === 'undefined' || !Number.isFinite(year)) return false;

    // If user navigated away from data pages, require fresh OTP
    const scopeExited = sessionStorage.getItem('scope_exited_at');
    if (scopeExited) {
        sessionStorage.removeItem('scope_exited_at');
        clearScopeTokenStorage();
        return false;
    }

    const cache = pruneScopeTokenCache();
    const entry = cache[String(year)];
    if (!entry?.token) {
        return false;
    }

    setScopeTokenWithExpiry(entry.token, entry.cached_until);
    return true;
};

export interface AccessAuditRecord {
    id: number;
    action: string;
    success: boolean;
    scope_id?: number | null;
    user_id?: number | null;
    ip_address?: string | null;
    details?: Record<string, any> | null;
    created_at?: string | null;
}

export interface CreateAccessScopeRequest {
    name: string;
    password: string;
    years: number[];
    period_start?: string | null;
    period_end?: string | null;
    allow_transactions: boolean;
    allow_sources: boolean;
    is_active: boolean;
}

export interface UpdateAccessScopeRequest {
    name?: string;
    password?: string;
    years?: number[];
    period_start?: string | null;
    period_end?: string | null;
    allow_transactions?: boolean;
    allow_sources?: boolean;
    is_active?: boolean;
}

export interface UnlockScopeResponse {
    token: string;
    expires_at?: string | null;
    scope: AccessScope;
}

export interface ScopeCodeRequestResponse {
    status: 'code_sent' | 'otp_disabled';
    expires_in: number;
    code_length: number;
    otp_skipped?: boolean;
    token?: string;
    expires_at?: string | null;
    scope?: AccessScope;
}

export interface ScopeCodeVerifyRequest {
    scope_id: number;
    code: string;
}

export interface LaunchStatusResponse {
    password_set: boolean;
    locked: boolean;
    locked_until?: string | null;
}

export interface LaunchVerifyResponse {
    verified: boolean;
    session_token?: string;
    expires_at?: string | null;
    attempts_left?: number;
    locked?: boolean;
    locked_until?: string | null;
}

export interface LockedPeriodItem {
    id: number;
    date_from: string;
    date_to: string;
    reason?: string | null;
    locked_at?: string | null;
}

export const securityApi = {
    getStatus: async (): Promise<AccessStatusResponse> => {
        const response = await apiClient.get<AccessStatusResponse>('/api/security/status');
        return response.data;
    },

    getSystemStatus: async (): Promise<SystemAccessStatusResponse> => {
        if (systemStatusEndpointSupported === false) {
            return {
                enforced: false,
                path: null,
                loaded: false,
                error: null,
                scopes_managed_by_config: false,
                available_scope_count: 0,
            };
        }
        try {
            const response = await apiClient.get<SystemAccessStatusResponse>('/api/security/system-status');
            systemStatusEndpointSupported = true;
            return response.data;
        } catch (err: any) {
            if (err?.response?.status === 404) {
                systemStatusEndpointSupported = false;
                return {
                    enforced: false,
                    path: null,
                    loaded: false,
                    error: null,
                    scopes_managed_by_config: false,
                    available_scope_count: 0,
                };
            }
            throw err;
        }
    },

    listScopes: async (): Promise<AccessScope[]> => {
        const response = await apiClient.get<AccessScope[]>('/api/security/scopes');
        return response.data;
    },

    createScope: async (payload: CreateAccessScopeRequest): Promise<AccessScope> => {
        const response = await apiClient.post<AccessScope>('/api/security/scopes', payload);
        return response.data;
    },

    updateScope: async (scopeId: number, payload: UpdateAccessScopeRequest): Promise<AccessScope> => {
        const response = await apiClient.put<AccessScope>(`/api/security/scopes/${scopeId}`, payload);
        return response.data;
    },

    deleteScope: async (scopeId: number): Promise<{ success: boolean }> => {
        const response = await apiClient.delete<{ success: boolean }>(`/api/security/scopes/${scopeId}`);
        return response.data;
    },

    unlockScope: async (payload: { password: string; target_year?: number; action?: 'transactions' | 'sources' }): Promise<UnlockScopeResponse> => {
        const response = await apiClient.post<UnlockScopeResponse>('/api/security/unlock', payload);
        if (response.data?.token) {
            setScopeTokenWithExpiry(response.data.token, response.data.expires_at || null);
            cacheScopeTokenByYears(
                response.data.token,
                response.data.scope,
                response.data.expires_at,
                payload.target_year
            );
        }
        return response.data;
    },

    requestScopeCode: async (scopeId: number): Promise<ScopeCodeRequestResponse> => {
        const response = await apiClient.post<ScopeCodeRequestResponse>(`/api/security/scope/${scopeId}/request-code`, {});
        if (response.data?.token && response.data?.scope) {
            setScopeTokenWithExpiry(response.data.token, response.data.expires_at || null);
            cacheScopeTokenByYears(
                response.data.token,
                response.data.scope,
                response.data.expires_at || null
            );
        }
        return response.data;
    },

    verifyScopeCode: async (payload: ScopeCodeVerifyRequest): Promise<UnlockScopeResponse> => {
        const response = await apiClient.post<UnlockScopeResponse>(
            `/api/security/scope/${payload.scope_id}/verify-code`,
            { code: payload.code }
        );
        if (response.data?.token) {
            setScopeTokenWithExpiry(response.data.token, response.data.expires_at || null);
            cacheScopeTokenByYears(response.data.token, response.data.scope, response.data.expires_at);
        }
        return response.data;
    },

    getLaunchStatus: async (): Promise<LaunchStatusResponse> => {
        const response = await apiClient.get<LaunchStatusResponse>('/api/security/app/launch-status');
        return response.data;
    },

    verifyLaunch: async (password: string): Promise<LaunchVerifyResponse> => {
        const response = await apiClient.post<LaunchVerifyResponse>('/api/security/app/verify-launch', { password });
        if (response.data?.session_token) {
            setLaunchSessionToken(response.data.session_token);
        }
        return response.data;
    },

    clearLaunchSession: () => {
        setLaunchSessionToken(null);
    },

    getLockedPeriods: async (): Promise<{ periods: LockedPeriodItem[] }> => {
        const response = await apiClient.get<{ periods: LockedPeriodItem[] }>('/api/security/locked-periods');
        return response.data;
    },

    clearScopeToken: (): void => {
        clearScopeTokenStorage();
    },

    setScopeToken: (token: string | null): void => {
        setScopeTokenWithExpiry(token);
    },

    applyCachedScopeTokenForYear: (year: number): boolean => {
        return applyCachedScopeTokenForYear(year);
    },

    pruneScopeTokenCache: (): void => {
        pruneScopeTokenCache();
    },

    getAudit: async (limit = 200): Promise<AccessAuditRecord[]> => {
        const response = await apiClient.get<AccessAuditRecord[]>('/api/security/audit', { params: { limit } });
        return response.data;
    },

    requestTelegramAccessCode: async (): Promise<{
        status: string;
        expires_in: number;
        code_length: number;
        otp_skipped: boolean;
        token?: string;
        expires_at?: string;
    }> => {
        const response = await apiClient.post('/api/security/otp/telegram-access', {});
        if (response.data?.token) {
            setPersistentWithLegacyCleanup(TELEGRAM_ACCESS_TOKEN_KEY, response.data.token);
        }
        return response.data;
    },

    verifyTelegramAccessCode: async (code: string): Promise<{ token: string; expires_at?: string }> => {
        const response = await apiClient.post('/api/security/otp/telegram-access/verify', { code });
        if (response.data?.token) {
            setPersistentWithLegacyCleanup(TELEGRAM_ACCESS_TOKEN_KEY, response.data.token);
        }
        return response.data;
    },

    getTelegramAccessToken: (): string | null => {
        return getFromLocalThenLegacySession(TELEGRAM_ACCESS_TOKEN_KEY);
    },

    clearTelegramAccessToken: (): void => {
        setPersistentWithLegacyCleanup(TELEGRAM_ACCESS_TOKEN_KEY, null);
    },
};

// Telegram TDLib client types
export type TelegramAuthState =
    | 'wait_phone_number'
    | 'wait_code'
    | 'wait_password'
    | 'wait_tdlib_parameters'
    | 'wait_encryption_key'
    | 'ready'
    | 'closing'
    | 'closed'
    | 'logging_out'
    | 'tdlib_unavailable'
    | 'misconfigured'
    | 'unknown';

export interface TelegramUserSummary {
    id?: number;
    first_name?: string;
    last_name?: string;
    username?: string;
    phone_number?: string;
}

export interface TelegramAuthStatus {
    state: TelegramAuthState;
    raw_state: string;
    is_authorized: boolean;
    phone_number?: string;
    user?: TelegramUserSummary;
}

export interface TelegramChatMessage {
    id?: number;
    date?: string;
    is_outgoing?: boolean;
    sender_id?: any;
    text?: string | null;
    document?: {
        file_id: number;
        file_name?: string;
        mime_type?: string;
        size?: number;
        download_url?: string;
        local_path?: string;
    } | null;
    photo?: {
        file_id: number;
        file_name?: string;
        mime_type?: string;
        size?: number;
        download_url?: string;
        local_path?: string;
        width?: number;
        height?: number;
    } | null;
    _receipt_transaction_id?: number | null;
}

export interface TelegramChat {
    chat_id: number;
    title: string;
    username?: string;
    chat_type: string; // 'bot', 'user', 'group', 'supergroup', 'channel'
    member_count?: number; // For groups and channels
    is_hidden: boolean;
    is_protected?: boolean;
    is_monitored?: boolean;
    monitor_enabled?: boolean;
    last_message?: TelegramChatMessage | null;
}

export interface TelegramChatListResponse {
    total: number;
    items: TelegramChat[];
}

export interface TelegramMessagesResponse {
    total: number;
    items: TelegramChatMessage[];
}

export interface TelegramProcessResult {
    chat_id: number;
    message_id: number;
    task_id?: string;
    status: 'queued' | 'processing' | 'done' | 'failed' | 'not_processed';
    check_id?: number;
    error?: string;
}

export interface TelegramProcessBatchResponse {
    results: TelegramProcessResult[];
}

export interface TelegramMonitoredChat {
    chat_id: number;
    enabled: boolean;
    last_processed_message_id: number;
    last_error?: string | null;
    created_at?: string | null;
    updated_at?: string | null;
}

export interface TelegramMonitorStatus {
    running: boolean;
    queue_size: number;
    workers: number;
}

export interface TelegramHistoryLoadStatus {
    chat_id: number;
    status: 'idle' | 'running' | 'completed' | 'failed';
    cursor_message_id: number;
    loaded_count: number;
    error?: string | null;
    started_at?: string | null;
    finished_at?: string | null;
    running: boolean;
}

export interface TelegramHistoryLoadRequest {
    max_messages?: number;
    restart?: boolean;
    date_from?: string;
    date_to?: string;
    exclude_from?: string;
    exclude_to?: string;
}

export interface TelegramOverview {
    auth: TelegramAuthStatus;
    chats: TelegramChatListResponse;
    monitor: TelegramMonitorStatus;
    server_time: string;
}

export interface TelegramChatPasswordVerifyResponse {
    verified: boolean;
    session_token?: string;
    expires_in?: number;
    attempts_left?: number;
    locked?: boolean;
    locked_until?: string | null;
}

const chatAccessHeaders = (chatId: number) => {
    const token = getChatAccessToken(chatId);
    if (!token) return {};
    return { 'X-Chat-Access': token };
};

// Telegram TDLib client API
export const telegramClientApi = {
    getStatus: async (): Promise<TelegramAuthStatus> => {
        const response = await apiClient.get<TelegramAuthStatus>('/api/tg/status');
        return response.data;
    },

    sendPhoneNumber: async (phone_number: string): Promise<TelegramAuthStatus> => {
        const response = await apiClient.post<TelegramAuthStatus>('/api/tg/auth/phone', { phone_number });
        return response.data;
    },

    sendCode: async (code: string): Promise<TelegramAuthStatus> => {
        const response = await apiClient.post<TelegramAuthStatus>('/api/tg/auth/code', { code });
        return response.data;
    },

    sendPassword: async (password: string): Promise<TelegramAuthStatus> => {
        const response = await apiClient.post<TelegramAuthStatus>('/api/tg/auth/password', { password });
        return response.data;
    },

    getChats: async (params: { search?: string; include_hidden?: boolean; limit?: number; offset?: number; chat_types?: string }): Promise<TelegramChatListResponse> => {
        const response = await apiClient.get<TelegramChatListResponse>('/api/tg/chats', { params });
        return response.data;
    },

    getOverview: async (params?: { search?: string; include_hidden?: boolean; limit?: number; offset?: number; chat_types?: string }): Promise<TelegramOverview> => {
        const response = await apiClient.get<TelegramOverview>('/api/tg/overview', { params });
        return response.data;
    },

    setChatHidden: async (chatId: number, hidden: boolean): Promise<{ chat_id: number; hidden: boolean; updated_at: string }> => {
        const response = await apiClient.put<{ chat_id: number; hidden: boolean; updated_at: string }>(
            `/api/tg/chats/${chatId}/hidden`,
            { hidden }
        );
        return response.data;
    },

    hideChat: async (chatId: number): Promise<void> => {
        await telegramClientApi.setChatHidden(chatId, true);
    },

    unhideChat: async (chatId: number): Promise<void> => {
        await telegramClientApi.setChatHidden(chatId, false);
    },

    setChatPassword: async (chatId: number, password: string): Promise<{ chat_id: number; protected: boolean }> => {
        const response = await apiClient.post<{ chat_id: number; protected: boolean }>(`/api/tg/chats/${chatId}/password`, { password });
        return response.data;
    },

    removeChatPassword: async (chatId: number, password: string): Promise<{ chat_id: number; protected: boolean }> => {
        const response = await apiClient.delete<{ chat_id: number; protected: boolean }>(`/api/tg/chats/${chatId}/password`, {
            data: { password },
        });
        setChatAccessToken(chatId, null);
        return response.data;
    },

    verifyChatPassword: async (chatId: number, password: string): Promise<TelegramChatPasswordVerifyResponse> => {
        const response = await apiClient.post<TelegramChatPasswordVerifyResponse>(`/api/tg/chats/${chatId}/password/verify`, { password });
        if (response.data?.verified && response.data?.session_token) {
            setChatAccessToken(chatId, response.data.session_token);
        }
        return response.data;
    },

    getChatPasswordStatus: async (chatId: number): Promise<{ protected: boolean; locked: boolean; locked_until?: string | null }> => {
        const response = await apiClient.get<{ protected: boolean; locked: boolean; locked_until?: string | null }>(`/api/tg/chats/${chatId}/password/status`);
        return response.data;
    },

    getMessages: async (chatId: number, params?: { limit?: number; from_message_id?: number; all?: boolean }): Promise<TelegramMessagesResponse> => {
        const response = await apiClient.get<TelegramMessagesResponse>(`/api/tg/chats/${chatId}/messages`, {
            params,
            headers: chatAccessHeaders(chatId),
        });
        return response.data;
    },

    getMessagesByDateRange: async (
        chatId: number,
        dateFrom: string,
        dateTo: string,
        limit?: number
    ): Promise<TelegramMessagesResponse> => {
        const params = { date_from: dateFrom, date_to: dateTo, limit };
        const response = await apiClient.get<TelegramMessagesResponse>(
            `/api/tg/chats/${chatId}/messages/by-date-range`,
            { params, headers: chatAccessHeaders(chatId) }
        );
        return response.data;
    },

    startHistoryLoad: async (chatId: number, payload?: TelegramHistoryLoadRequest): Promise<{ accepted: boolean; status: TelegramHistoryLoadStatus }> => {
        const response = await apiClient.post<{ accepted: boolean; status: TelegramHistoryLoadStatus }>(
            `/api/tg/chats/${chatId}/history/load`,
            payload || {},
            { headers: chatAccessHeaders(chatId) }
        );
        return response.data;
    },

    getHistoryLoadStatus: async (chatId: number): Promise<TelegramHistoryLoadStatus> => {
        const response = await apiClient.get<TelegramHistoryLoadStatus>(
            `/api/tg/chats/${chatId}/history/load/status`,
            { headers: chatAccessHeaders(chatId) }
        );
        return response.data;
    },

    getHistoryMessages: async (
        chatId: number,
        params?: { limit?: number; offset?: number; search?: string; date_from?: string; date_to?: string },
    ): Promise<TelegramMessagesResponse> => {
        const response = await apiClient.get<TelegramMessagesResponse>(
            `/api/tg/chats/${chatId}/history/messages`,
            { params, headers: chatAccessHeaders(chatId) }
        );
        return response.data;
    },


    processHistoryReceipts: async (
        chatId: number,
        params?: { message_ids?: number[]; max_messages?: number; force?: boolean },
    ): Promise<{
        chat_id: number;
        total_scanned: number;
        queued: number;
        skipped: number;
        errors: number;
        results: Array<{ message_id: number; status: string; task_id?: string; transaction_id?: number; error?: string }>;
    }> => {
        const response = await apiClient.post(
            `/api/tg/chats/${chatId}/history/process-receipts`,
            params || {},
            { headers: chatAccessHeaders(chatId) },
        );
        return response.data;
    },

    getHistoryReceiptStatus: async (
        chatId: number,
    ): Promise<{
        chat_id: number;
        total_messages: number;
        processed_messages: number;
        total_transactions_from_chat: number;
    }> => {
        const response = await apiClient.get(
            `/api/tg/chats/${chatId}/history/receipt-status`,
            { headers: chatAccessHeaders(chatId) },
        );
        return response.data;
    },

    getHistoryStats: async (
        chatId: number,
    ): Promise<{
        chat_id: number;
        sync: { chat_id: number; status: string; loaded_count: number; running: boolean };
        total_messages: number;
        oldest_message_date: string | null;
        newest_message_date: string | null;
        linked_receipts: number;
        total_transactions: number;
    }> => {
        const response = await apiClient.get(
            `/api/tg/chats/${chatId}/history/stats`,
            { headers: chatAccessHeaders(chatId) },
        );
        return response.data;
    },

    sendMessage: async (chatId: number, text: string): Promise<TelegramChatMessage> => {
        const response = await apiClient.post<TelegramChatMessage>(`/api/tg/chats/${chatId}/messages`, { text }, {
            headers: chatAccessHeaders(chatId),
        });
        return response.data;
    },

    sendPdf: async (chatId: number, file: File, caption?: string): Promise<TelegramChatMessage> => {
        const form = new FormData();
        form.append('file', file);
        if (caption) form.append('caption', caption);
        const response = await apiClient.post<TelegramChatMessage>(`/api/tg/chats/${chatId}/documents`, form, {
            headers: { 'Content-Type': 'multipart/form-data', ...chatAccessHeaders(chatId) },
        });
        return response.data;
    },

    processMessage: async (chatId: number, messageId: number): Promise<TelegramProcessResult> => {
        const response = await apiClient.post<TelegramProcessResult>(
            `/api/tg/chats/${chatId}/messages/${messageId}/process`,
            {},
            { headers: chatAccessHeaders(chatId) }
        );
        return response.data;
    },

    processBatch: async (chatId: number, messageIds: number[]): Promise<TelegramProcessBatchResponse> => {
        const response = await apiClient.post<TelegramProcessBatchResponse>(`/api/tg/chats/${chatId}/process-batch`, {
            message_ids: messageIds,
        }, {
            headers: chatAccessHeaders(chatId),
        });
        return response.data;
    },

    getReceiptStatus: async (chatId: number, messageIds: number[]): Promise<TelegramProcessBatchResponse> => {
        const params = { message_ids: messageIds.join(',') };
        const response = await apiClient.get<TelegramProcessBatchResponse>(
            `/api/tg/chats/${chatId}/receipt-status`,
            { params, headers: chatAccessHeaders(chatId) }
        );
        return response.data;
    },

    getMonitors: async (): Promise<TelegramMonitoredChat[]> => {
        const response = await apiClient.get<TelegramMonitoredChat[]>('/api/tg/monitors');
        return response.data;
    },

    setMonitor: async (chatId: number, enabled: boolean, startFromLatest = true): Promise<TelegramMonitoredChat> => {
        const response = await apiClient.put<TelegramMonitoredChat>(`/api/tg/monitors/${chatId}`, {
            enabled,
            start_from_latest: startFromLatest,
        });
        return response.data;
    },

    getMonitorStatus: async (): Promise<TelegramMonitorStatus> => {
        const response = await apiClient.get<TelegramMonitorStatus>('/api/tg/monitor/status');
        return response.data;
    },

    processReceiptDirect: async (
        chatId: number,
        messageId: number,
        force = false
    ): Promise<ProcessReceiptResponse> => {
        const response = await apiClient.post<ProcessReceiptResponse>('/api/transactions/process-receipt', {
            chat_id: chatId,
            message_id: messageId,
            force,
        });
        return response.data;
    },
};

export interface UserInfo {
    id: number;
    username: string;
    display_name: string;
    role: 'admin' | 'operator';
    allowed_tabs: string[];
    allowed_folders: number[];
    forbidden_periods: Array<{ from: string; to: string }>;
    allowed_sources: number[];
    can_toggle_sources: boolean;
    permissions_version: number;
    totp_enabled?: boolean;
    totp_confirmed_at?: string | null;
    force_2fa?: boolean;
    session_ttl_days?: number;
    exp?: number | null;
}

export interface LoginRequest {
    username: string;
    password: string;
}

export interface LoginResponse {
    ok: boolean;
    token?: string | null;
    scope_token?: string | null;
    refresh_token?: string | null;
    user?: UserInfo;
    error?: 'invalid_credentials' | 'locked' | 'inactive_user' | 'permissions_outdated' | 'requires_2fa' | string;
    requires_2fa?: boolean;
    requires_2fa_setup?: boolean;
    temp_token?: string | null;
    attempts_left?: number;
    locked_seconds?: number;
}

// Auth API methods
export const authApi = {
    login: async (payload: LoginRequest): Promise<LoginResponse> => {
        const response = await apiClient.post<LoginResponse>('/api/auth/login', payload, {
            validateStatus: (status) => [200, 400, 401, 403, 423].includes(status || 0),
        });
        return response.data;
    },

    login2fa: async (payload: { temp_token: string; code: string }): Promise<LoginResponse> => {
        const response = await apiClient.post<LoginResponse>('/api/auth/login/2fa', payload, {
            validateStatus: (status) => [200, 400, 401, 403, 429].includes(status || 0),
        });
        return response.data;
    },

    refresh: async (refreshToken?: string | null): Promise<LoginResponse> => {
        const response = await apiClient.post<LoginResponse>(
            '/api/auth/refresh',
            { refresh_token: refreshToken || undefined },
            {
                headers: refreshToken ? { 'X-Refresh-Token': refreshToken } : undefined,
                validateStatus: (status) => [200, 401, 403].includes(status || 0),
            }
        );
        return response.data;
    },

    logout: async (): Promise<{ success: boolean; message: string }> => {
        const token = getAuthToken();
        const refreshToken = getRefreshToken();
        const response = await apiClient.post('/api/auth/logout', { refresh_token: refreshToken || undefined }, {
            headers: {
                ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
                ...(refreshToken ? { 'X-Refresh-Token': refreshToken } : {}),
            }
        });
        return response.data;
    },

    getCurrentUser: async (): Promise<UserInfo> => {
        const response = await apiClient.get<UserInfo>('/api/auth/me');
        return response.data;
    },

    verifyToken: async (): Promise<{ valid: boolean; user_id: number; permissions_version?: number; role?: string }> => {
        const response = await apiClient.get('/api/auth/verify');
        return response.data;
    },

    qrGenerate: async (): Promise<{ session_id: string; qr_url: string; expires_in: number }> => {
        const response = await apiClient.post('/api/auth/qr/generate', {});
        return response.data;
    },

    qrStatus: async (sessionId: string): Promise<{
        status: 'pending' | 'confirmed' | 'expired';
        token?: string;
        scope_token?: string;
        refresh_token?: string;
        user?: any;
    }> => {
        const response = await apiClient.get(`/api/auth/qr/status/${sessionId}`);
        return response.data;
    },
};

export interface AdminUser {
    id: number;
    username: string;
    display_name: string;
    role: 'admin' | 'operator';
    is_active: boolean;
    allowed_tabs: string[];
    allowed_folders: number[];
    forbidden_periods: Array<{ from: string; to: string }>;
    allowed_sources: number[];
    can_toggle_sources: boolean;
    permissions_version: number;
    force_2fa: boolean;
    totp_enabled: boolean;
    totp_confirmed_at?: string | null;
    telegram_id?: number | null;
    telegram_username?: string | null;
    session_ttl_days: number;
    failed_attempts: number;
    locked_until?: string | null;
    last_login_at?: string | null;
}

export interface AdminCreateUserPayload {
    username: string;
    password: string;
    role: 'admin' | 'operator';
    display_name?: string;
    is_active?: boolean;
    allowed_tabs: string[];
    allowed_folders: number[];
    forbidden_periods: Array<{ from: string; to: string }>;
    allowed_sources: number[];
    can_toggle_sources: boolean;
    force_2fa?: boolean;
    session_ttl_days?: number;
    telegram_id?: number;
    telegram_username?: string;
}

export interface AdminUpdateUserPayload {
    role?: 'admin' | 'operator';
    display_name?: string;
    is_active?: boolean;
    allowed_tabs?: string[];
    allowed_folders?: number[];
    forbidden_periods?: Array<{ from: string; to: string }>;
    allowed_sources?: number[];
    can_toggle_sources?: boolean;
    force_2fa?: boolean;
    session_ttl_days?: number;
}

export const adminApi = {
    listUsers: async (includeInactive = true): Promise<AdminUser[]> => {
        const response = await apiClient.get<AdminUser[]>('/api/admin/users', {
            params: { include_inactive: includeInactive },
        });
        return response.data;
    },

    createUser: async (payload: AdminCreateUserPayload): Promise<AdminUser> => {
        const response = await apiClient.post<AdminUser>('/api/admin/users', payload);
        return response.data;
    },

    updateUser: async (id: number, payload: AdminUpdateUserPayload): Promise<AdminUser> => {
        const response = await apiClient.patch<AdminUser>(`/api/admin/users/${id}`, payload);
        return response.data;
    },

    resetPassword: async (id: number, password: string): Promise<AdminUser> => {
        const response = await apiClient.post<AdminUser>(`/api/admin/users/${id}/reset-password`, { password });
        return response.data;
    },

    reset2fa: async (id: number): Promise<AdminUser> => {
        const response = await apiClient.post<AdminUser>(`/api/admin/users/${id}/reset-2fa`);
        return response.data;
    },

    force2fa: async (id: number, force = true): Promise<AdminUser> => {
        const response = await apiClient.post<AdminUser>(`/api/admin/users/${id}/force-2fa`, { force });
        return response.data;
    },

    unlockUser: async (id: number): Promise<AdminUser> => {
        const response = await apiClient.post<AdminUser>(`/api/admin/users/${id}/unlock`);
        return response.data;
    },

    deactivateUser: async (id: number): Promise<AdminUser> => {
        const response = await apiClient.delete<AdminUser>(`/api/admin/users/${id}`);
        return response.data;
    },

    linkTelegram: async (id: number, telegramId: number, telegramUsername?: string): Promise<AdminUser> => {
        const response = await apiClient.post<AdminUser>(`/api/admin/users/${id}/link-telegram`, {
            telegram_id: telegramId,
            telegram_username: telegramUsername || null,
        });
        return response.data;
    },

    unlinkTelegram: async (id: number): Promise<AdminUser> => {
        const response = await apiClient.post<AdminUser>(`/api/admin/users/${id}/unlink-telegram`);
        return response.data;
    },
};

export interface SystemSettings {
    id: number;
    otp_enabled: boolean;
    bot_control_enabled: boolean;
    totp_2fa_enabled: boolean;
    launch_gate_enabled: boolean;
    updated_at?: string | null;
    updated_by?: number | null;
}

export interface PeriodRecord {
    id: number;
    date_from: string;
    date_to: string;
    reason?: string | null;
    is_active: boolean;
    locked_by_tg_id?: number | null;
    created_at?: string | null;
}

export interface TwoFactorStatus {
    enabled: boolean;
    force_2fa: boolean;
    confirmed_at?: string | null;
    global_policy_enabled: boolean;
    required_now: boolean;
}

export interface AuditRecord {
    id: number;
    action: string;
    success: boolean;
    scope_id?: number | null;
    user_id?: number | null;
    ip_address?: string | null;
    details?: Record<string, any> | null;
    created_at?: string | null;
}

export const systemSettingsApi = {
    get: async (): Promise<SystemSettings> => {
        const response = await apiClient.get<SystemSettings>('/api/system-settings');
        return response.data;
    },
    update: async (payload: Partial<SystemSettings>): Promise<SystemSettings> => {
        const response = await apiClient.patch<SystemSettings>('/api/system-settings', payload);
        return response.data;
    },
};

export const periodsApi = {
    list: async (activeOnly = false): Promise<PeriodRecord[]> => {
        const response = await apiClient.get<PeriodRecord[]>('/api/periods', {
            params: { active_only: activeOnly },
        });
        return response.data;
    },
    create: async (payload: { date_from: string; date_to: string; reason?: string }): Promise<PeriodRecord> => {
        const response = await apiClient.post<PeriodRecord>('/api/periods', payload);
        return response.data;
    },
    update: async (
        id: number,
        payload: Partial<{ date_from: string; date_to: string; reason: string; is_active: boolean }>
    ): Promise<PeriodRecord> => {
        const response = await apiClient.patch<PeriodRecord>(`/api/periods/${id}`, payload);
        return response.data;
    },
    deactivate: async (id: number): Promise<{ status: string; id: number; is_active: boolean }> => {
        const response = await apiClient.delete<{ status: string; id: number; is_active: boolean }>(`/api/periods/${id}`);
        return response.data;
    },
};

export const twoFactorApi = {
    getStatus: async (): Promise<TwoFactorStatus> => {
        const response = await apiClient.get<TwoFactorStatus>('/api/2fa/status');
        return response.data;
    },
    setup: async (temp_token?: string): Promise<{ secret: string; otpauth_uri: string; qr_code_base64: string; backup_codes: string[] }> => {
        const response = await apiClient.post('/api/2fa/setup', { temp_token: temp_token || undefined });
        return response.data;
    },
    confirm: async (code: string, temp_token?: string): Promise<{ ok: boolean; enabled: boolean }> => {
        const response = await apiClient.post('/api/2fa/confirm', { code, temp_token: temp_token || undefined }, {
            validateStatus: (status) => [200, 400, 401, 429].includes(status || 0),
        });
        return response.data;
    },
    verify: async (temp_token: string, code: string): Promise<{ ok: boolean; method?: string }> => {
        const response = await apiClient.post('/api/2fa/verify', { temp_token, code }, {
            validateStatus: (status) => [200, 401, 404, 429].includes(status || 0),
        });
        return response.data;
    },
    regenerateBackupCodes: async (): Promise<{ ok: boolean; backup_codes: string[] }> => {
        const response = await apiClient.post('/api/2fa/backup-codes');
        return response.data;
    },
    disable: async (): Promise<{ ok: boolean }> => {
        const response = await apiClient.delete('/api/2fa');
        return response.data;
    },
};

export interface ActiveSession {
    session_id: string;
    token_kind: string;
    subject?: string | null;
    user_id?: number | null;
    ip_address?: string | null;
    created_at?: string | null;
    last_activity_at?: string | null;
    expires_at?: string | null;
}

export const sessionsApi = {
    list: async (limit = 200): Promise<ActiveSession[]> => {
        const response = await apiClient.get<ActiveSession[]>('/api/security/sessions', { params: { limit } });
        return response.data;
    },
    kill: async (sessionId: string): Promise<{ ok: boolean; session_id: string }> => {
        const response = await apiClient.delete<{ ok: boolean; session_id: string }>(`/api/security/sessions/${encodeURIComponent(sessionId)}`);
        return response.data;
    },
    killAllExceptCurrent: async (exceptSessionId: string): Promise<{ ok: boolean; killed: number }> => {
        const response = await apiClient.post<{ ok: boolean; killed: number }>('/api/security/sessions/kill-all-except-current', {
            except_session_id: exceptSessionId,
        });
        return response.data;
    },
    getCurrentSessionId: (): string | null => {
        const payload = _decodeJwtPayload(getAuthToken());
        return payload?.sid || payload?.session_id || null;
    },
};

export interface AgentThread {
    id: string;
    created_by_user_id: number;
    title: string;
    context: Record<string, any>;
    created_at?: string | null;
    updated_at?: string | null;
}

export interface AgentMessage {
    id: string;
    thread_id: string;
    run_id?: string | null;
    role: 'user' | 'assistant' | 'system' | 'tool';
    message_type: 'text' | 'tool_run' | 'report' | 'confirmation' | 'warning' | 'navigation';
    content: Record<string, any>;
    created_at?: string | null;
}

export interface AgentRun {
    id: string;
    thread_id: string;
    created_by_user_id: number;
    status: 'queued' | 'processing' | 'awaiting_confirmation' | 'completed' | 'failed' | 'cancelled';
    tool_name?: string | null;
    progress: Record<string, any>;
    result?: Record<string, any> | null;
    error_text?: string | null;
    requires_confirmation: boolean;
    created_at?: string | null;
    updated_at?: string | null;
}

export interface AgentNotification {
    id: string;
    scope: 'personal' | 'team';
    user_id?: number | null;
    report_id?: string | null;
    report_item_id?: string | null;
    type: string;
    payload: Record<string, any>;
    is_read: boolean;
    created_at?: string | null;
    read_at?: string | null;
}

export interface AgentReportItem {
    id: string;
    report_id: string;
    issue_type: string;
    severity: 'low' | 'medium' | 'high' | 'critical';
    entity_type: string;
    entity_id?: string | null;
    confidence?: number | null;
    status: 'open' | 'claimed' | 'released' | 'resolved';
    title: string;
    description?: string | null;
    suggested_action?: Record<string, any>;
    assignee_user_id?: number | null;
    claimed_at?: string | null;
    released_at?: string | null;
    resolved_at?: string | null;
    created_at?: string | null;
    updated_at?: string | null;
}

export interface AgentReport {
    id: string;
    created_by_user_id: number;
    thread_id?: string | null;
    scope: 'personal' | 'team';
    title: string;
    period_start?: string | null;
    period_end?: string | null;
    status: 'draft' | 'ready' | 'published' | 'archived';
    summary: Record<string, any>;
    payload: Record<string, any>;
    items: AgentReportItem[];
    created_at?: string | null;
    updated_at?: string | null;
}

export interface AgentThreadDetail extends AgentThread {
    messages: AgentMessage[];
    runs: AgentRun[];
}

export interface AgentLocateResult {
    exists: boolean;
    route: string;
    row_id?: number | null;
    column_id?: string | null;
    focus_mode: string;
    suggested_filters: Record<string, any>;
    sort_hint: Record<string, any>;
    page_hint?: number | null;
    cursor_hint?: Record<string, any> | null;
}

export const agentApi = {
    listThreads: async (): Promise<AgentThread[]> => {
        const response = await apiClient.get<AgentThread[]>('/api/agent/threads');
        return response.data;
    },
    createThread: async (payload?: { title?: string; context?: Record<string, any> }): Promise<AgentThread> => {
        const response = await apiClient.post<AgentThread>('/api/agent/threads', payload || {});
        return response.data;
    },
    getThread: async (threadId: string): Promise<AgentThreadDetail> => {
        const response = await apiClient.get<AgentThreadDetail>(`/api/agent/threads/${threadId}`);
        return response.data;
    },
    sendMessage: async (
        threadId: string,
        payload: { text: string; requested_tool?: string | null; metadata?: Record<string, any> },
    ): Promise<{ accepted: boolean; thread_id: string; message: { id: string; created_at?: string | null }; run: AgentRun }> => {
        const response = await apiClient.post(`/api/agent/threads/${threadId}/messages`, payload);
        return response.data;
    },
    listNotifications: async (params?: { scope?: 'team' | 'personal'; limit?: number }): Promise<AgentNotification[]> => {
        const response = await apiClient.get<AgentNotification[]>('/api/agent/notifications', { params });
        return response.data;
    },
    readNotification: async (notificationId: string): Promise<AgentNotification> => {
        const response = await apiClient.post<AgentNotification>(`/api/agent/notifications/${notificationId}/read`);
        return response.data;
    },
    readAllNotifications: async (): Promise<{ updated: number }> => {
        const response = await apiClient.post<{ updated: number }>('/api/agent/notifications/read-all');
        return response.data;
    },
    generateReport: async (payload?: {
        thread_id?: string | null;
        team?: boolean;
        period_start?: string | null;
        period_end?: string | null;
    }): Promise<AgentReport> => {
        const response = await apiClient.post<AgentReport>('/api/agent/reports/generate', payload || {});
        return response.data;
    },
    listReports: async (params?: { include_team?: boolean; limit?: number }): Promise<AgentReport[]> => {
        const response = await apiClient.get<AgentReport[]>('/api/agent/reports', { params });
        return response.data;
    },
    getReport: async (reportId: string): Promise<AgentReport> => {
        const response = await apiClient.get<AgentReport>(`/api/agent/reports/${reportId}`);
        return response.data;
    },
    previewReportActions: async (reportId: string): Promise<{ report_id: string; actions: Record<string, any>[]; count: number }> => {
        const response = await apiClient.post(`/api/agent/reports/${reportId}/actions/preview`);
        return response.data;
    },
    confirmReportActions: async (
        reportId: string,
        payload: { item_ids: string[]; action: string },
    ): Promise<{ report_id: string; updated: number; action: string }> => {
        const response = await apiClient.post(`/api/agent/reports/${reportId}/actions/confirm`, payload);
        return response.data;
    },
    claimReportItem: async (itemId: string): Promise<AgentReportItem> => {
        const response = await apiClient.post<AgentReportItem>(`/api/agent/report-items/${itemId}/claim`);
        return response.data;
    },
    releaseReportItem: async (itemId: string): Promise<AgentReportItem> => {
        const response = await apiClient.post<AgentReportItem>(`/api/agent/report-items/${itemId}/release`);
        return response.data;
    },
    reassignReportItem: async (itemId: string, assigneeUserId: number): Promise<AgentReportItem> => {
        const response = await apiClient.post<AgentReportItem>(`/api/agent/report-items/${itemId}/reassign`, {
            assignee_user_id: assigneeUserId,
        });
        return response.data;
    },
    confirmRun: async (runId: string): Promise<AgentRun> => {
        const response = await apiClient.post<AgentRun>(`/api/agent/runs/${runId}/confirm`);
        return response.data;
    },
    locateTransaction: async (params: {
        transaction_id?: number;
        search?: string;
        sort_by?: string;
        sort_dir?: string;
        page_size?: number;
    }): Promise<AgentLocateResult> => {
        const response = await apiClient.get<AgentLocateResult>('/api/transactions/locate', { params });
        return response.data;
    },
};

export const auditApi = {
    list: async (params?: {
        action?: string;
        user_id?: number;
        date_from?: string;
        date_to?: string;
        limit?: number;
        offset?: number;
    }): Promise<AuditRecord[]> => {
        const response = await apiClient.get<AuditRecord[]>('/api/audit', { params });
        return response.data;
    },
};
