// Preload script for Electron
// This runs before the renderer process is loaded

const { contextBridge, ipcRenderer } = require('electron');

const LEGACY_REFRESH_TOKEN_KEYS = ['auth_refresh_token', 'refresh_token'];
const LEGACY_REFRESH_MIGRATION_TIMEOUT_MS = 5000;

function removeLegacyRefreshTokens() {
    for (const storage of [window.localStorage, window.sessionStorage]) {
        for (const key of LEGACY_REFRESH_TOKEN_KEYS) {
            try {
                storage.removeItem(key);
            } catch {
                // The renderer performs the same fail-safe cleanup after this
                // migration promise settles.
            }
        }
    }
}

function readLegacyRefreshToken() {
    for (const storage of [window.localStorage, window.sessionStorage]) {
        for (const key of LEGACY_REFRESH_TOKEN_KEYS) {
            try {
                const value = String(storage.getItem(key) || '').trim();
                if (value) return value;
            } catch {
                // Continue to the other legacy storage location.
            }
        }
    }
    return null;
}

const legacyRefreshMigration = (async () => {
    const legacyValue = readLegacyRefreshToken();
    if (!legacyValue) {
        removeLegacyRefreshTokens();
        return true;
    }
    try {
        let timeoutId;
        const result = await Promise.race([
            ipcRenderer.invoke('secure-storage:migrate-legacy-refresh-token', legacyValue),
            new Promise((resolve) => {
                timeoutId = setTimeout(() => resolve(null), LEGACY_REFRESH_MIGRATION_TIMEOUT_MS);
            }),
        ]).finally(() => clearTimeout(timeoutId));
        return result?.status === 'migrated' || result?.status === 'existing';
    } catch {
        return false;
    } finally {
        // The plaintext is removed only after main confirms the encrypted write
        // (or after a fail-closed error that forces a fresh login).
        removeLegacyRefreshTokens();
    }
})();

// Expose any needed APIs to the renderer process
contextBridge.exposeInMainWorld('electronAPI', {
    platform: process.platform,
    isElectron: true,
    systemAccess: {
        getStatus: () => ipcRenderer.invoke('system-access:get-status'),
    },
    secureStorage: {
        migrateLegacyRefreshToken: () => legacyRefreshMigration,
        get: (key) => ipcRenderer.invoke('secure-storage:get', key),
        set: (key, value) => ipcRenderer.invoke('secure-storage:set', key, value),
        remove: (key) => ipcRenderer.invoke('secure-storage:remove', key),
    },
    updates: {
        getVersion: () => ipcRenderer.invoke('updates:get-version'),
        check: () => ipcRenderer.invoke('updates:check'),
        download: () => ipcRenderer.invoke('updates:download'),
        install: (options) => ipcRenderer.invoke('updates:install', options || {}),
        onEvent: (callback) => {
            const listener = (_event, payload) => callback(payload);
            ipcRenderer.on('updates:event', listener);
            return () => ipcRenderer.removeListener('updates:event', listener);
        },
    },
    miniApp: {
        // Absolute path to the <webview> preload (file path, not URL). MiniAppHost
        // resolves it once and passes it to the <webview preload> attribute.
        getPreloadPath: () => ipcRenderer.invoke('miniapp:get-preload-path'),
        // Open a link in the OS browser (validated http/https/tg in main).
        openExternal: (url) => ipcRenderer.invoke('miniapp:open-external', url),
    },
});
