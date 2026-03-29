// Preload script for Electron
// This runs before the renderer process is loaded

const { contextBridge, ipcRenderer } = require('electron');

// Expose any needed APIs to the renderer process
contextBridge.exposeInMainWorld('electronAPI', {
    platform: process.platform,
    isElectron: true,
    systemAccess: {
        getStatus: () => ipcRenderer.invoke('system-access:get-status'),
        getToken: () => ipcRenderer.invoke('system-access:get-token'),
        getApiBaseUrl: () => ipcRenderer.invoke('system-access:get-api-base-url'),
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
});
