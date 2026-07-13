const path = require('path');
const { fileURLToPath } = require('url');

const API_METHODS = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']);
const API_PREFIXES = [
    '/api/admin',
    '/api/agent',
    '/api/ai-agent',
    '/api/analytics',
    '/api/audit',
    '/api/auth',
    '/api/automation',
    '/api/logs',
    '/api/periods',
    '/api/reconciliation',
    '/api/reference',
    '/api/security',
    '/api/sync',
    '/api/system-settings',
    '/api/tg',
    '/api/transactions',
    '/api/two-factor',
    '/api/userbot',
];
const DEFAULT_EXTERNAL_HTTPS_HOSTS = new Set(['t.me', 'telegram.me']);
const DEFAULT_EXTERNAL_TG_HOSTS = new Set(['join', 'resolve', 'share']);

function canonicalApiBaseUrl(rawUrl) {
    const parsed = new URL(String(rawUrl || 'http://127.0.0.1:8000'));
    const isLoopback = parsed.hostname === '127.0.0.1' || parsed.hostname === 'localhost';
    if ((parsed.protocol !== 'https:' && !isLoopback) || !['http:', 'https:'].includes(parsed.protocol)) {
        throw new Error('API base URL must use HTTPS or loopback HTTP');
    }
    if (parsed.username || parsed.password || parsed.search || parsed.hash) {
        throw new Error('API base URL cannot contain credentials, query, or fragment');
    }
    parsed.hostname = parsed.hostname === 'localhost' ? '127.0.0.1' : parsed.hostname;
    parsed.pathname = parsed.pathname.replace(/\/+$/, '') || '/';
    return parsed.toString().replace(/\/$/, '');
}

function isAllowedApiRequest(baseUrl, requestUrl, method) {
    try {
        const base = new URL(`${canonicalApiBaseUrl(baseUrl)}/`);
        const target = new URL(String(requestUrl));
        const normalizedMethod = String(method || 'GET').toUpperCase();
        if (!API_METHODS.has(normalizedMethod) || target.origin !== base.origin) return false;
        if (/%2f|%5c|\.\./i.test(target.pathname)) return false;
        if (target.pathname.startsWith('/api/tg/files/')) return false;
        return API_PREFIXES.some((prefix) => target.pathname === prefix || target.pathname.startsWith(`${prefix}/`));
    } catch {
        return false;
    }
}

function isTrustedRendererUrl(rawUrl, distDirectory, devOrigin) {
    try {
        const parsed = new URL(String(rawUrl));
        if (parsed.protocol === 'file:') {
            const resolved = path.resolve(fileURLToPath(parsed));
            const distRoot = `${path.resolve(distDirectory)}${path.sep}`;
            return resolved.startsWith(distRoot) && path.basename(resolved) === 'index.html';
        }
        if (devOrigin) {
            const allowed = new URL(devOrigin).origin;
            return parsed.origin === allowed;
        }
        return false;
    } catch {
        return false;
    }
}

function isSafeMiniAppUrl(rawUrl) {
    try {
        const parsed = new URL(String(rawUrl));
        return parsed.protocol === 'https:' && !parsed.username && !parsed.password && !parsed.hash;
    } catch {
        return false;
    }
}

function hasSameOrigin(firstUrl, secondUrl) {
    try {
        return new URL(String(firstUrl)).origin === new URL(String(secondUrl)).origin;
    } catch {
        return false;
    }
}

function parseHostAllowlist(rawValue) {
    return new Set(
        String(rawValue || '')
            .split(',')
            .map((value) => value.trim().toLowerCase())
            .filter(Boolean),
    );
}

function classifyExternalUrl(rawUrl, extraHttpsHosts = '') {
    try {
        const parsed = new URL(String(rawUrl));
        if (parsed.username || parsed.password) return null;
        if (parsed.protocol === 'https:') {
            const hosts = new Set([...DEFAULT_EXTERNAL_HTTPS_HOSTS, ...parseHostAllowlist(extraHttpsHosts)]);
            if (!hosts.has(parsed.hostname.toLowerCase()) || (parsed.port && parsed.port !== '443')) return null;
            return { url: parsed.toString(), protocol: 'https:', host: parsed.hostname.toLowerCase() };
        }
        if (parsed.protocol === 'tg:') {
            const host = parsed.hostname.toLowerCase();
            if (!DEFAULT_EXTERNAL_TG_HOSTS.has(host)) return null;
            return { url: parsed.toString(), protocol: 'tg:', host };
        }
        return null;
    } catch {
        return null;
    }
}

function parsePublisherNamesFromUpdaterConfig(rawConfig) {
    const lines = String(rawConfig || '').split(/\r?\n/);
    const names = [];
    let inPublisherBlock = false;
    let publisherIndent = -1;
    for (const line of lines) {
        const indent = line.match(/^\s*/)?.[0].length || 0;
        const publisherMatch = line.match(/^\s*publisherName:\s*(.*?)\s*$/);
        if (publisherMatch) {
            inPublisherBlock = true;
            publisherIndent = indent;
            const inline = publisherMatch[1].replace(/^['"]|['"]$/g, '').trim();
            if (inline && inline !== '[]') names.push(inline);
            continue;
        }
        if (inPublisherBlock && indent > publisherIndent) {
            const item = line.match(/^\s*-\s*['"]?(.*?)['"]?\s*$/)?.[1]?.trim();
            if (item) names.push(item);
            continue;
        }
        if (inPublisherBlock && line.trim() && indent <= publisherIndent) break;
    }
    return [...new Set(names.filter(Boolean))];
}

function importLegacyRefreshToken({ legacyValue, readExisting, writeValue }) {
    const normalized = String(legacyValue || '').trim();
    if (!normalized || normalized.length > 16384) {
        throw new Error('Invalid legacy refresh token');
    }
    if (typeof readExisting !== 'function' || typeof writeValue !== 'function') {
        throw new Error('Invalid secure storage adapter');
    }
    if (readExisting()) {
        return { status: 'existing' };
    }
    writeValue(normalized);
    return { status: 'migrated' };
}

module.exports = {
    API_PREFIXES,
    canonicalApiBaseUrl,
    classifyExternalUrl,
    hasSameOrigin,
    importLegacyRefreshToken,
    isAllowedApiRequest,
    isSafeMiniAppUrl,
    isTrustedRendererUrl,
    parsePublisherNamesFromUpdaterConfig,
};
