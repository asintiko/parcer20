const { app, BrowserWindow, ipcMain, Menu, screen } = require('electron');
const { autoUpdater } = require('electron-updater');
const fs = require('fs');
const path = require('path');

let mainWindow;

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
            preload: path.join(__dirname, 'preload.cjs'),
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
    createWindow();

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) {
            createWindow();
        }
    });

    setupAutoUpdates();
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

function setupAutoUpdates() {
    const sendToRenderer = (channel, payload) => {
        if (mainWindow) {
            mainWindow.webContents.send(channel, payload);
        }
    };

    ipcMain.handle('updates:get-version', () => app.getVersion());
    ipcMain.handle('system-access:get-status', () => loadClientAccessConfig());
    ipcMain.handle('system-access:get-token', () => loadClientAccessConfig().token || null);
    ipcMain.handle('system-access:get-api-base-url', () => loadClientAccessConfig().apiBaseUrl || null);
    ipcMain.handle('updates:check', async () => {
        if (!app.isPackaged) {
            sendToRenderer('updates:event', { status: 'not-available', info: { reason: 'dev-mode' } });
            return true;
        }
        await autoUpdater.checkForUpdates();
        return true;
    });
    ipcMain.handle('updates:download', async () => {
        if (!app.isPackaged) {
            sendToRenderer('updates:event', { status: 'not-available', info: { reason: 'dev-mode' } });
            return true;
        }
        await autoUpdater.downloadUpdate();
        return true;
    });
    ipcMain.handle('updates:install', (_event, opts = {}) => {
        if (!app.isPackaged) {
            sendToRenderer('updates:event', { status: 'not-available', info: { reason: 'dev-mode' } });
            return true;
        }
        const { isSilent = false, isForceRunAfter = false } = opts;
        autoUpdater.quitAndInstall(isSilent, isForceRunAfter);
        return true;
    });

    if (!app.isPackaged) return; // в dev не дергаем апдейтер

    autoUpdater.autoDownload = false;
    autoUpdater.on('checking-for-update', () => sendToRenderer('updates:event', { status: 'checking' }));
    autoUpdater.on('update-available', (info) => sendToRenderer('updates:event', { status: 'available', info }));
    autoUpdater.on('update-not-available', (info) => sendToRenderer('updates:event', { status: 'not-available', info }));
    autoUpdater.on('download-progress', (progressObj) =>
        sendToRenderer('updates:event', { status: 'downloading', progress: progressObj })
    );
    autoUpdater.on('update-downloaded', (info) => sendToRenderer('updates:event', { status: 'downloaded', info }));
    autoUpdater.on('error', (err) => sendToRenderer('updates:event', { status: 'error', error: err?.message || String(err) }));

    // авто-проверка каждые 6 часов
    const intervalMinutes = parseInt(process.env.APP_UPDATE_INTERVAL_MIN || '360', 10);
    setInterval(() => {
        autoUpdater.checkForUpdates();
    }, intervalMinutes * 60 * 1000);
}
