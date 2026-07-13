const { app, BrowserWindow, dialog, ipcMain, Menu, safeStorage, screen, session, shell } = require('electron');
const { autoUpdater } = require('electron-updater');
const fs = require('fs');
const path = require('path');
const {
    canonicalApiBaseUrl,
    classifyExternalUrl,
    hasSameOrigin,
    importLegacyRefreshToken,
    isAllowedApiRequest,
    isSafeMiniAppUrl,
    isTrustedRendererUrl,
    parsePublisherNamesFromUpdaterConfig,
} = require('./security-policy.cjs');

let mainWindow;

// Absolute file:// path to the Mini App <webview> preload. Exposed to the renderer
// via the 'miniapp:get-preload-path' ipc handler so <webview preload="..."> resolves
// regardless of packaged vs. dev layout.
const WEBAPP_PRELOAD_PATH = path.join(__dirname, 'webapp-preload.cjs');

// Partition used by the Mini App <webview>. Must match the renderer
// (MiniAppHost.tsx uses partition="persist:miniapp").
const MINIAPP_PARTITION = 'persist:miniapp';
const DIST_DIRECTORY = path.join(__dirname, '..', 'dist');
const SECURE_STORAGE_KEYS = new Set(['refresh_token']);

function isTrustedRendererEvent(event) {
    if (!mainWindow || event.sender.id !== mainWindow.webContents.id) return false;
    const senderUrl = event.senderFrame?.url || event.sender.getURL();
    return isTrustedRendererUrl(senderUrl, DIST_DIRECTORY, process.env.VITE_DEV_SERVER_URL || '');
}

function requireTrustedRenderer(event) {
    if (!isTrustedRendererEvent(event)) {
        throw new Error('Untrusted renderer IPC sender');
    }
}

function resolveClientAccessConfigCandidates() {
    const candidates = [];
    const pushCandidate = (candidatePath, source) => {
        if (!candidatePath) return;
        if (candidates.some((item) => item.path === candidatePath)) return;
        candidates.push({ path: candidatePath, source });
    };

    const explicitPath = process.env.CLIENT_ACCESS_CONFIG_PATH;
    if (explicitPath) {
        pushCandidate(explicitPath, 'env');
    }

    if (app.isPackaged) {
        pushCandidate(path.join(process.resourcesPath, 'security', 'client-access.json'), 'bundled-resource');
    }

    const portableDir = process.env.PORTABLE_EXECUTABLE_DIR;
    if (portableDir) {
        pushCandidate(path.join(portableDir, 'security', 'client-access.json'), 'portable');
    }

    if (process.platform === 'win32') {
        const programData = process.env.PROGRAMDATA || 'C:\\\\ProgramData';
        pushCandidate(path.join(programData, 'TBSparcer', 'security', 'client-access.json'), 'programdata');
    }

    const devCandidate = path.resolve(__dirname, '..', '..', 'security', 'client-access.json');
    if (!app.isPackaged && fs.existsSync(devCandidate)) {
        pushCandidate(devCandidate, 'repo-dev');
    }

    pushCandidate(path.join(app.getPath('userData'), 'security', 'client-access.json'), 'userData');
    return candidates;
}

function loadClientAccessConfig() {
    const candidates = resolveClientAccessConfigCandidates();
    let lastFailure = {
        ok: false,
        path: candidates[0]?.path || null,
        source: candidates[0]?.source || 'unknown',
        error: 'Client access config is missing',
        token: null,
        apiBaseUrl: null,
    };

    for (const resolved of candidates) {
        const configPath = resolved.path;
        try {
            if (!fs.existsSync(configPath)) {
                lastFailure = {
                    ok: false,
                    path: configPath,
                    source: resolved.source,
                    error: 'Client access config is missing',
                    token: null,
                    apiBaseUrl: null,
                };
                continue;
            }

            const raw = fs.readFileSync(configPath, 'utf-8');
            const payload = JSON.parse(raw);
            if (!payload || typeof payload !== 'object') {
                lastFailure = {
                    ok: false,
                    path: configPath,
                    source: resolved.source,
                    error: 'Client access config is invalid JSON object',
                    token: null,
                    apiBaseUrl: null,
                };
                continue;
            }

            const token = String(
                payload.system_access_token ||
                    payload.systemToken ||
                    payload.token ||
                    ''
            ).trim();

            const apiBaseUrl = String(
                payload.api_base_url ||
                    payload.apiBaseUrl ||
                    ''
            ).trim();

            if (!token) {
                lastFailure = {
                    ok: false,
                    path: configPath,
                    source: resolved.source,
                    error: 'Client access config has no system_access_token',
                    token: null,
                    apiBaseUrl: apiBaseUrl || null,
                };
                continue;
            }

            return {
                ok: true,
                path: configPath,
                source: resolved.source,
                error: null,
                token,
                apiBaseUrl: apiBaseUrl || null,
            };
        } catch (error) {
            lastFailure = {
                ok: false,
                path: configPath,
                source: resolved.source,
                error: error?.message || String(error),
                token: null,
                apiBaseUrl: null,
            };
        }
    }

    return lastFailure;
}

function publicClientAccessStatus() {
    const config = loadClientAccessConfig();
    let apiBaseUrl = null;
    try {
        apiBaseUrl = canonicalApiBaseUrl(config.apiBaseUrl || 'http://127.0.0.1:8000');
    } catch (error) {
        return {
            ok: false,
            source: config.source,
            error: error?.message || String(error),
            apiBaseUrl: null,
        };
    }
    return {
        ok: Boolean(config.ok),
        source: config.source,
        error: config.error,
        apiBaseUrl,
    };
}

function secureStorageFilePath() {
    return path.join(app.getPath('userData'), 'secure-storage.json');
}

function readSecureStorageFile() {
    const storagePath = secureStorageFilePath();
    if (!fs.existsSync(storagePath)) return {};
    const parsed = JSON.parse(fs.readFileSync(storagePath, 'utf8'));
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
}

function writeSecureStorageFile(payload) {
    const storagePath = secureStorageFilePath();
    fs.mkdirSync(path.dirname(storagePath), { recursive: true, mode: 0o700 });
    const temporaryPath = `${storagePath}.tmp`;
    fs.writeFileSync(temporaryPath, JSON.stringify(payload), { encoding: 'utf8', mode: 0o600 });
    fs.renameSync(temporaryPath, storagePath);
}

function assertSecureStorageKey(key) {
    const normalized = String(key || '');
    if (!SECURE_STORAGE_KEYS.has(normalized)) throw new Error('Unsupported secure storage key');
    if (!safeStorage.isEncryptionAvailable()) throw new Error('OS-backed secure storage is unavailable');
    return normalized;
}

function getSecureValue(key) {
    const normalized = assertSecureStorageKey(key);
    const encrypted = readSecureStorageFile()[normalized];
    if (!encrypted) return null;
    return safeStorage.decryptString(Buffer.from(String(encrypted), 'base64'));
}

function setSecureValue(key, value) {
    const normalized = assertSecureStorageKey(key);
    const plaintext = String(value || '');
    if (!plaintext || plaintext.length > 16384) throw new Error('Invalid secure storage value');
    const payload = readSecureStorageFile();
    payload[normalized] = safeStorage.encryptString(plaintext).toString('base64');
    writeSecureStorageFile(payload);
}

function removeSecureValue(key) {
    const normalized = String(key || '');
    if (!SECURE_STORAGE_KEYS.has(normalized)) throw new Error('Unsupported secure storage key');
    const payload = readSecureStorageFile();
    delete payload[normalized];
    writeSecureStorageFile(payload);
}

function setupApiHeaderBroker() {
    session.defaultSession.webRequest.onBeforeSendHeaders(
        { urls: ['http://*/*', 'https://*/*'] },
        (details, callback) => {
            const requestHeaders = { ...(details.requestHeaders || {}) };
            for (const headerName of Object.keys(requestHeaders)) {
                if (headerName.toLowerCase() === 'x-system-access') delete requestHeaders[headerName];
            }

            const config = loadClientAccessConfig();
            try {
                const apiBaseUrl = canonicalApiBaseUrl(config.apiBaseUrl || 'http://127.0.0.1:8000');
                const rendererTrusted = Boolean(
                    mainWindow &&
                    details.webContentsId === mainWindow.webContents.id &&
                    isTrustedRendererUrl(
                        mainWindow.webContents.getURL(),
                        DIST_DIRECTORY,
                        process.env.VITE_DEV_SERVER_URL || '',
                    ),
                );
                if (
                    config.ok &&
                    config.token &&
                    rendererTrusted &&
                    isAllowedApiRequest(apiBaseUrl, details.url, details.method)
                ) {
                    requestHeaders['X-System-Access'] = config.token;
                }
            } catch {
                // Invalid access config is fail-closed: no system header is attached.
            }
            callback({ requestHeaders });
        },
    );
}

function buildAppMenu() {
    const isMac = process.platform === 'darwin';
    const template = [
        ...(isMac ? [{ role: 'appMenu' }] : []),
        {
            label: 'Файл',
            submenu: [isMac ? { role: 'close' } : { role: 'quit' }],
        },
        {
            label: 'Правка',
            submenu: [
                { role: 'undo' },
                { role: 'redo' },
                { type: 'separator' },
                { role: 'cut' },
                { role: 'copy' },
                { role: 'paste' },
                { role: 'selectAll' },
            ],
        },
        {
            label: 'Вид',
            submenu: [
                { role: 'reload', label: 'Перезагрузить' },
                { role: 'forceReload', label: 'Принудительная перезагрузка' },
                { type: 'separator' },
                { role: 'resetZoom', label: 'Сброс масштаба' },
                { role: 'zoomIn', label: 'Увеличить' },
                { role: 'zoomOut', label: 'Уменьшить' },
                { type: 'separator' },
                { role: 'togglefullscreen', label: 'Полный экран' },
            ],
        },
        {
            label: 'Инструменты',
            submenu: [
                {
                    label: 'Открыть DevTools',
                    accelerator: 'F12',
                    click: () => {
                        if (mainWindow) {
                            mainWindow.webContents.openDevTools({ mode: 'detach' });
                        }
                    },
                },
                {
                    label: 'Закрыть DevTools',
                    accelerator: 'Shift+F12',
                    click: () => {
                        if (mainWindow) {
                            mainWindow.webContents.closeDevTools();
                        }
                    },
                },
                { type: 'separator' },
                {
                    label: 'Очистить кэш и перезагрузить',
                    accelerator: 'CmdOrCtrl+Shift+R',
                    click: async () => {
                        if (!mainWindow) return;
                        try {
                            await mainWindow.webContents.session.clearCache();
                            await mainWindow.webContents.session.clearStorageData({
                                storages: ['cookies', 'localstorage', 'indexdb', 'serviceworkers', 'cachestorage'],
                            });
                        } catch (e) {
                            // ignore
                        }
                        mainWindow.webContents.reloadIgnoringCache();
                    },
                },
            ],
        },
        {
            label: 'Помощь',
            submenu: [
                {
                    label: 'О программе',
                    click: () => {
                        if (mainWindow) {
                            mainWindow.webContents.send('app:show-about', { version: app.getVersion() });
                        }
                    },
                },
            ],
        },
    ];
    Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// --- Mini App host wiring ---------------------------------------------------

async function confirmAndOpenExternal(rawUrl) {
    const external = classifyExternalUrl(rawUrl, process.env.MINIAPP_EXTERNAL_HTTPS_HOSTS || '');
    if (!external) return false;
    const options = {
        type: 'question',
        title: 'Открыть внешнюю ссылку?',
        message: `Открыть ${external.host} вне TBSparcer?`,
        detail: external.url,
        buttons: ['Отмена', 'Открыть'],
        defaultId: 0,
        cancelId: 0,
        noLink: true,
    };
    const result = mainWindow
        ? await dialog.showMessageBox(mainWindow, options)
        : await dialog.showMessageBox(options);
    if (result.response !== 1) return false;
    await shell.openExternal(external.url);
    return true;
}

let miniAppHostReady = false;
function setupMiniAppHost() {
    if (miniAppHostReady) return;
    miniAppHostReady = true;

    try {
        const miniSession = session.fromPartition(MINIAPP_PARTITION);
        miniSession.setPermissionCheckHandler(() => false);
        miniSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));
    } catch (e) {
        console.warn('[miniapp] failed to harden partition:', e?.message || e);
    }

    // Renderer resolves <webview preload="..."> from this.
    ipcMain.handle('miniapp:get-preload-path', (event) => {
        requireTrustedRenderer(event);
        return WEBAPP_PRELOAD_PATH;
    });

    // Open a link outside the app (host chrome / bridge web_app_open_link).
    ipcMain.handle('miniapp:open-external', async (event, url) => {
        requireTrustedRenderer(event);
        return confirmAndOpenExternal(url);
    });

    // Pin the webview preload and route any window.open / target=_blank from inside a
    // mini app to the OS browser; never spawn an in-app popup window.
    app.on('web-contents-created', (_event, contents) => {
        if (contents.getType() === 'webview') {
            contents.setWindowOpenHandler(({ url }) => {
                if (isSafeMiniAppUrl(contents.getURL())) void confirmAndOpenExternal(url);
                return { action: 'deny' };
            });
            contents.on('will-navigate', (event, url) => {
                const currentUrl = contents.getURL();
                if (!isSafeMiniAppUrl(url) || (currentUrl && !hasSameOrigin(currentUrl, url))) {
                    event.preventDefault();
                    if (currentUrl && isSafeMiniAppUrl(currentUrl)) void confirmAndOpenExternal(url);
                }
            });
        }
    });

}

function createWindow() {
    const iconPath = path.join(__dirname, 'assets', 'icon.png');
    const workArea = screen.getPrimaryDisplay().workAreaSize;
    const initialWidth = Math.max(1024, Math.min(1400, workArea.width));
    const initialHeight = Math.max(680, Math.min(900, workArea.height));

    buildAppMenu();
    mainWindow = new BrowserWindow({
        width: initialWidth,
        height: initialHeight,
        minWidth: 960,
        minHeight: 640,
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            sandbox: true,
            webSecurity: true,
            allowRunningInsecureContent: false,
            navigateOnDragDrop: false,
            preload: path.join(__dirname, 'preload.cjs'),
            // Mini Apps render inside an Electron <webview> in the userbot chat.
            webviewTag: true,
        },
        icon: fs.existsSync(iconPath) ? iconPath : undefined,
        title: 'TBSparcer',
        autoHideMenuBar: true,
        show: false,
    });
    // Hide the native menu bar from the client (system strip top-left). DevTools
    // stays reachable for us via the F12 / Ctrl+Shift+I before-input-event handler.
    mainWindow.setMenuBarVisibility(false);
    mainWindow.setAutoHideMenuBar(true);

    mainWindow.webContents.on('will-attach-webview', (event, webPreferences, params) => {
        if (!isSafeMiniAppUrl(params.src)) {
            event.preventDefault();
            return;
        }
        webPreferences.preload = WEBAPP_PRELOAD_PATH;
        webPreferences.nodeIntegration = false;
        webPreferences.contextIsolation = true;
        webPreferences.sandbox = true;
        webPreferences.webSecurity = true;
        webPreferences.allowRunningInsecureContent = false;
        params.allowpopups = false;
        params.partition = MINIAPP_PARTITION;
    });

    mainWindow.webContents.setWindowOpenHandler(({ url }) => {
        void confirmAndOpenExternal(url);
        return { action: 'deny' };
    });
    mainWindow.webContents.on('will-navigate', (event, url) => {
        if (!isTrustedRendererUrl(url, DIST_DIRECTORY, process.env.VITE_DEV_SERVER_URL || '')) {
            event.preventDefault();
            void confirmAndOpenExternal(url);
        }
    });

    // Load the built React app
    mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));

    // Show window when ready
    mainWindow.once('ready-to-show', () => {
        if (workArea.width < 1366 || workArea.height < 860) {
            mainWindow.maximize();
        }
        mainWindow.show();
    });

    // Belt-and-suspenders: ensure F12 / Ctrl+Shift+I always toggle DevTools,
    // regardless of focus or what the page does with the keyboard.
    mainWindow.webContents.on('before-input-event', (event, input) => {
        if (input.type !== 'keyDown') return;
        const isF12 = input.key === 'F12';
        const isCtrlShiftI =
            (input.control || input.meta) && input.shift && (input.key === 'I' || input.key === 'i');
        if (isF12 || isCtrlShiftI) {
            event.preventDefault();
            if (mainWindow.webContents.isDevToolsOpened()) {
                mainWindow.webContents.closeDevTools();
            } else {
                mainWindow.webContents.openDevTools({ mode: 'detach' });
            }
        }
    });

    // Open DevTools in development
    if (process.env.NODE_ENV === 'development') {
        mainWindow.webContents.openDevTools({ mode: 'detach' });
    }

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

app.whenReady().then(() => {
    setupApiHeaderBroker();
    setupMiniAppHost();
    createWindow();
    setupAutoUpdates();

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) {
            createWindow();
        }
    });

});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

let verifiedUpdateReady = false;

function assertWindowsPublisherTrust() {
    if (process.platform !== 'win32' || !app.isPackaged) return [];
    const updaterConfigPath = path.join(process.resourcesPath, 'app-update.yml');
    if (!fs.existsSync(updaterConfigPath)) {
        throw new Error('Updater publisher configuration is missing');
    }
    const publisherNames = parsePublisherNamesFromUpdaterConfig(fs.readFileSync(updaterConfigPath, 'utf8'));
    if (!publisherNames.length) {
        throw new Error('Updater publisher allowlist is empty');
    }
    return publisherNames;
}

function setupAutoUpdates() {
    const sendToRenderer = (channel, payload) => {
        if (mainWindow) {
            mainWindow.webContents.send(channel, payload);
        }
    };

    ipcMain.handle('system-access:get-status', (event) => {
        requireTrustedRenderer(event);
        return publicClientAccessStatus();
    });
    ipcMain.handle('secure-storage:get', (event, key) => {
        requireTrustedRenderer(event);
        return getSecureValue(key);
    });
    ipcMain.handle('secure-storage:migrate-legacy-refresh-token', (event, legacyValue) => {
        requireTrustedRenderer(event);
        return importLegacyRefreshToken({
            legacyValue,
            readExisting: () => getSecureValue('refresh_token'),
            writeValue: (value) => setSecureValue('refresh_token', value),
        });
    });
    ipcMain.handle('secure-storage:set', (event, key, value) => {
        requireTrustedRenderer(event);
        setSecureValue(key, value);
        return true;
    });
    ipcMain.handle('secure-storage:remove', (event, key) => {
        requireTrustedRenderer(event);
        removeSecureValue(key);
        return true;
    });
    ipcMain.handle('updates:get-version', (event) => {
        requireTrustedRenderer(event);
        return app.getVersion();
    });
    ipcMain.handle('updates:check', async (event) => {
        requireTrustedRenderer(event);
        if (!app.isPackaged) {
            sendToRenderer('updates:event', { status: 'not-available', info: { reason: 'dev-mode' } });
            return true;
        }
        assertWindowsPublisherTrust();
        await autoUpdater.checkForUpdates();
        return true;
    });
    ipcMain.handle('updates:download', async (event) => {
        requireTrustedRenderer(event);
        if (!app.isPackaged) {
            sendToRenderer('updates:event', { status: 'not-available', info: { reason: 'dev-mode' } });
            return true;
        }
        assertWindowsPublisherTrust();
        await autoUpdater.downloadUpdate();
        return true;
    });
    ipcMain.handle('updates:install', (event, opts = {}) => {
        requireTrustedRenderer(event);
        if (!app.isPackaged) {
            sendToRenderer('updates:event', { status: 'not-available', info: { reason: 'dev-mode' } });
            return true;
        }
        if (!verifiedUpdateReady) throw new Error('No publisher-verified update is ready to install');
        const { isSilent = false, isForceRunAfter = false } = opts;
        autoUpdater.quitAndInstall(isSilent, isForceRunAfter);
        return true;
    });

    if (!app.isPackaged) return; // в dev не дергаем апдейтер

    autoUpdater.autoDownload = false;
    autoUpdater.autoInstallOnAppQuit = false;
    try {
        assertWindowsPublisherTrust();
    } catch (error) {
        sendToRenderer('updates:event', { status: 'error', error: error?.message || String(error) });
        return;
    }
    autoUpdater.on('checking-for-update', () => sendToRenderer('updates:event', { status: 'checking' }));
    autoUpdater.on('update-available', (info) => {
        verifiedUpdateReady = false;
        sendToRenderer('updates:event', { status: 'available', info });
    });
    autoUpdater.on('update-not-available', (info) => sendToRenderer('updates:event', { status: 'not-available', info }));
    autoUpdater.on('download-progress', (progressObj) =>
        sendToRenderer('updates:event', { status: 'downloading', progress: progressObj })
    );
    autoUpdater.on('update-downloaded', (info) => {
        verifiedUpdateReady = true;
        sendToRenderer('updates:event', { status: 'downloaded', info });
    });
    autoUpdater.on('error', (err) => {
        verifiedUpdateReady = false;
        sendToRenderer('updates:event', { status: 'error', error: err?.message || String(err) });
    });

    const checkForUpdatesSafely = async () => {
        try {
            assertWindowsPublisherTrust();
            await autoUpdater.checkForUpdates();
        } catch (error) {
            sendToRenderer('updates:event', { status: 'error', error: error?.message || String(error) });
        }
    };

    mainWindow?.webContents.once('did-finish-load', () => {
        setTimeout(() => void checkForUpdatesSafely(), 1500);
    });

    // авто-проверка каждые 6 часов
    const intervalMinutes = parseInt(process.env.APP_UPDATE_INTERVAL_MIN || '360', 10);
    setInterval(() => void checkForUpdatesSafely(), intervalMinutes * 60 * 1000);
}
