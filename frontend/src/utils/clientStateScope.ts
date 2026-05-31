import { API_BASE_URL } from '../services/api';

const FALLBACK_HOST = 'unknown-host';
const FALLBACK_USER = 'anonymous';

const normalizeHost = (rawUrl?: string | null): string => {
    const input = String(rawUrl || '').trim();
    if (!input) return FALLBACK_HOST;
    try {
        const parsed = new URL(input.includes('://') ? input : `http://${input}`);
        return parsed.host.toLowerCase() || FALLBACK_HOST;
    } catch {
        return input.replace(/^https?:\/\//i, '').replace(/\/+$/, '').toLowerCase() || FALLBACK_HOST;
    }
};

const normalizeUsername = (rawUsername?: string | null): string => {
    const value = String(rawUsername || '').trim().toLowerCase();
    return value || FALLBACK_USER;
};

export const buildClientStateScope = (
    username?: string | null,
    apiBaseUrl: string | null = API_BASE_URL,
): string => {
    const host = normalizeHost(apiBaseUrl);
    const user = normalizeUsername(username);
    return `${user}@${host}`;
};

export const buildScopedStorageKey = (prefix: string, scope: string): string => `${prefix}:${scope}`;
