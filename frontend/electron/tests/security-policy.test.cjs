const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const policy = require('../security-policy.cjs');

const electronDir = path.resolve(__dirname, '..');
const frontendDir = path.resolve(electronDir, '..');

function createWebStorage(initial = {}) {
    const values = new Map(Object.entries(initial));
    return {
        getItem: (key) => values.get(String(key)) ?? null,
        setItem: (key, value) => values.set(String(key), String(value)),
        removeItem: (key) => values.delete(String(key)),
    };
}

function evaluatePreload({ localStorage, sessionStorage, invoke }) {
    let exposed;
    const source = fs.readFileSync(path.join(electronDir, 'preload.cjs'), 'utf8');
    vm.runInNewContext(source, {
        require: (name) => {
            assert.equal(name, 'electron');
            return {
                contextBridge: {
                    exposeInMainWorld: (_name, value) => {
                        exposed = value;
                    },
                },
                ipcRenderer: {
                    invoke,
                    on: () => undefined,
                    removeListener: () => undefined,
                },
            };
        },
        process,
        setTimeout,
        clearTimeout,
        window: { localStorage, sessionStorage },
    });
    return exposed;
}

test('API broker accepts only the configured origin and route allowlist', () => {
    assert.equal(
        policy.isAllowedApiRequest(
            'http://127.0.0.1:8000',
            'http://127.0.0.1:8000/api/transactions?page=1',
            'GET',
        ),
        true,
    );
    assert.equal(
        policy.isAllowedApiRequest('http://127.0.0.1:8000', 'http://127.0.0.1:8000/internal/secrets', 'GET'),
        false,
    );
    assert.equal(
        policy.isAllowedApiRequest('http://127.0.0.1:8000', 'http://127.0.0.1:8000/api/tg/files/12', 'GET'),
        false,
    );
    assert.equal(
        policy.isAllowedApiRequest('http://127.0.0.1:8000', 'https://evil.example/api/transactions', 'GET'),
        false,
    );
});

test('renderer trust is bound to packaged index file', () => {
    const dist = fs.mkdtempSync(path.join(os.tmpdir(), 'tbs-dist-'));
    const index = path.join(dist, 'index.html');
    fs.writeFileSync(index, '');
    assert.equal(policy.isTrustedRendererUrl(new URL(`file://${index}`).toString(), dist, ''), true);
    assert.equal(policy.isTrustedRendererUrl('https://evil.example/', dist, ''), false);
});

test('external navigation uses exact scheme and host allowlists', () => {
    assert.equal(policy.classifyExternalUrl('https://t.me/example')?.host, 't.me');
    assert.equal(policy.classifyExternalUrl('tg://resolve?domain=example')?.host, 'resolve');
    assert.equal(policy.classifyExternalUrl('http://t.me/example'), null);
    assert.equal(policy.classifyExternalUrl('https://t.me.evil.example/example'), null);
});

test('publisher parser requires a non-empty publisher allowlist', () => {
    assert.deepEqual(
        policy.parsePublisherNamesFromUpdaterConfig('publisherName:\n  - Example Publisher\nprovider: github\n'),
        ['Example Publisher'],
    );
    assert.deepEqual(policy.parsePublisherNamesFromUpdaterConfig('provider: github\n'), []);
});

test('legacy refresh import preserves an existing secure token and validates plaintext', () => {
    const writes = [];
    assert.deepEqual(
        policy.importLegacyRefreshToken({
            legacyValue: 'legacy-token',
            readExisting: () => 'current-secure-token',
            writeValue: (value) => writes.push(value),
        }),
        { status: 'existing' },
    );
    assert.deepEqual(writes, []);

    assert.deepEqual(
        policy.importLegacyRefreshToken({
            legacyValue: 'legacy-token',
            readExisting: () => null,
            writeValue: (value) => writes.push(value),
        }),
        { status: 'migrated' },
    );
    assert.deepEqual(writes, ['legacy-token']);
    assert.throws(
        () => policy.importLegacyRefreshToken({ legacyValue: '', readExisting: () => null, writeValue: () => {} }),
        /Invalid legacy refresh token/,
    );
});

test('preload migrates legacy refresh token before plaintext cleanup without returning it', async () => {
    const localStorage = createWebStorage({ auth_refresh_token: 'legacy-secret' });
    const sessionStorage = createWebStorage({ refresh_token: 'stale-session-secret' });
    let resolveImport;
    let importedValue = null;
    const pendingImport = new Promise((resolve) => {
        resolveImport = resolve;
    });
    const electronApi = evaluatePreload({
        localStorage,
        sessionStorage,
        invoke: (channel, value) => {
            if (channel === 'secure-storage:migrate-legacy-refresh-token') {
                importedValue = value;
                return pendingImport;
            }
            return Promise.resolve(null);
        },
    });

    assert.equal(importedValue, 'legacy-secret');
    assert.equal(localStorage.getItem('auth_refresh_token'), 'legacy-secret');
    resolveImport({ status: 'migrated' });
    assert.equal(await electronApi.secureStorage.migrateLegacyRefreshToken(), true);
    assert.equal(localStorage.getItem('auth_refresh_token'), null);
    assert.equal(localStorage.getItem('refresh_token'), null);
    assert.equal(sessionStorage.getItem('auth_refresh_token'), null);
    assert.equal(sessionStorage.getItem('refresh_token'), null);
});

test('preload clears legacy plaintext and returns only failure status when secure import fails', async () => {
    const localStorage = createWebStorage({ refresh_token: 'legacy-secret' });
    const sessionStorage = createWebStorage();
    const electronApi = evaluatePreload({
        localStorage,
        sessionStorage,
        invoke: () => Promise.reject(new Error('secure storage unavailable')),
    });

    assert.equal(await electronApi.secureStorage.migrateLegacyRefreshToken(), false);
    assert.equal(localStorage.getItem('refresh_token'), null);
});

test('renderer defers Electron refresh cleanup to migration and logout still removes secure state', () => {
    const api = fs.readFileSync(path.join(frontendDir, 'src/services/api.ts'), 'utf8');
    const main = fs.readFileSync(path.join(electronDir, 'main.cjs'), 'utf8');
    assert.match(api, /isElectronRuntime && LEGACY_REFRESH_TOKEN_KEYS\.has\(key\)/);
    assert.match(api, /await storageApi\.migrateLegacyRefreshToken\(\)/);
    assert.match(api, /finally \{[\s\S]*LEGACY_REFRESH_TOKEN_KEYS/);
    assert.match(api, /clearClientSecurityState[\s\S]*setRefreshToken\(null\)/);
    assert.match(api, /storageApi\?\.remove\?\.\('refresh_token'\)/);
    assert.match(main, /secure-storage:remove/);
});

test('packaged hardening has no renderer system-token IPC and enables sandbox/CSP', () => {
    const main = fs.readFileSync(path.join(electronDir, 'main.cjs'), 'utf8');
    const preload = fs.readFileSync(path.join(electronDir, 'preload.cjs'), 'utf8');
    const html = fs.readFileSync(path.join(frontendDir, 'index.html'), 'utf8');
    const miniApp = fs.readFileSync(path.join(frontendDir, 'src/components/telegram/MiniAppHost.tsx'), 'utf8');
    assert.doesNotMatch(main, /system-access:get-token/);
    assert.doesNotMatch(preload, /getToken/);
    assert.match(main, /sandbox:\s*true/);
    assert.match(main, /setPermissionRequestHandler/);
    assert.match(main, /callback\(false\)/);
    assert.doesNotMatch(main, /stripFramingHeaders|onHeadersReceived/);
    assert.match(html, /Content-Security-Policy/);
    assert.match(html, /object-src 'none'/);
    assert.match(miniApp, /__clipboard_allow/);
    assert.match(miniApp, /navigationEpochRef/);
    assert.doesNotMatch(miniApp, /postMessage\([^\n]+, '\*'\)/);
});

test('Telegram media uses only owner-bound authenticated file routes', () => {
    const api = fs.readFileSync(path.join(frontendDir, 'src/services/api.ts'), 'utf8');
    const bubble = fs.readFileSync(path.join(frontendDir, 'src/components/telegram/MessageBubble.tsx'), 'utf8');
    const legacyItem = fs.readFileSync(path.join(frontendDir, 'src/components/MessageItem.tsx'), 'utf8');
    assert.match(api, /\/api\/tg\/chats\/\$\{chatId\}\/messages\/\$\{messageId\}\/files\/\$\{fileId\}/);
    assert.doesNotMatch(api, /\/api\/tg\/files\//);
    assert.doesNotMatch(bubble, /download_url/);
    assert.doesNotMatch(legacyItem, /\/api\/tg\/files\//);
});

test('Windows release config supports the explicitly approved unsigned channel', () => {
    const configPath = path.join(electronDir, 'release-config.cjs');
    delete require.cache[require.resolve(configPath)];
    delete process.env.WINDOWS_PUBLISHER_NAME;
    delete process.env.CSC_LINK;
    delete process.env.CSC_KEY_PASSWORD;
    const config = require(configPath);
    assert.equal(config.forceCodeSigning, false);
    assert.equal(config.win.verifyUpdateCodeSignature, false);
    assert.equal(Object.hasOwn(config.win, 'publisherName'), false);
});

test('packaged updater checks after startup and continues periodic checks', () => {
    const main = fs.readFileSync(path.join(electronDir, 'main.cjs'), 'utf8');
    assert.match(main, /webContents\.once\('did-finish-load'[\s\S]*checkForUpdatesSafely/);
    assert.match(main, /setInterval\(\(\) => void checkForUpdatesSafely\(\)/);
    assert.match(main, /await autoUpdater\.checkForUpdates\(\)/);
    assert.doesNotMatch(main, /assertWindowsPublisherTrust|verifiedUpdateReady/);
});
