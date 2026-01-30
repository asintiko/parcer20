const { app, BrowserWindow, ipcMain } = require('electron');
const { autoUpdater } = require('electron-updater');
const path = require('path');

let mainWindow;

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1400,
        height: 900,
        minWidth: 1024,
        minHeight: 700,
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.cjs'),
        },
        icon: path.join(__dirname, 'build/icon.png'),
        title: 'TBSparcer',
        show: false,
    });

    // Load the built React app
    mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));

    // Show window when ready
    mainWindow.once('ready-to-show', () => {
        mainWindow.show();
    });

    // Open DevTools in development
    if (process.env.NODE_ENV === 'development') {
        mainWindow.webContents.openDevTools();
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
    if (!app.isPackaged) return; // в dev не дергаем апдейтер
    autoUpdater.autoDownload = false;

    const sendToRenderer = (channel, payload) => {
        if (mainWindow) {
            mainWindow.webContents.send(channel, payload);
        }
    };

    autoUpdater.on('checking-for-update', () => sendToRenderer('updates:event', { status: 'checking' }));
    autoUpdater.on('update-available', (info) => sendToRenderer('updates:event', { status: 'available', info }));
    autoUpdater.on('update-not-available', (info) => sendToRenderer('updates:event', { status: 'not-available', info }));
    autoUpdater.on('download-progress', (progressObj) =>
        sendToRenderer('updates:event', { status: 'downloading', progress: progressObj })
    );
    autoUpdater.on('update-downloaded', (info) => sendToRenderer('updates:event', { status: 'downloaded', info }));
    autoUpdater.on('error', (err) => sendToRenderer('updates:event', { status: 'error', error: err?.message || String(err) }));

    ipcMain.handle('updates:get-version', () => app.getVersion());
    ipcMain.handle('updates:check', async () => {
        await autoUpdater.checkForUpdates();
        return true;
    });
    ipcMain.handle('updates:download', async () => {
        await autoUpdater.downloadUpdate();
        return true;
    });
    ipcMain.handle('updates:install', (_event, opts = {}) => {
        const { isSilent = false, isForceRunAfter = false } = opts;
        autoUpdater.quitAndInstall(isSilent, isForceRunAfter);
        return true;
    });

    // авто-проверка каждые 6 часов
    const intervalMinutes = parseInt(process.env.APP_UPDATE_INTERVAL_MIN || '360', 10);
    setInterval(() => {
        autoUpdater.checkForUpdates();
    }, intervalMinutes * 60 * 1000);
}
