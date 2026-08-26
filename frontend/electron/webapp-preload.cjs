// Preload for the Mini App <webview>. Runs in the guest page (the loaded mini app),
// BEFORE telegram-web-app.js. Its only job is to install the "mobile" transport that
// telegram-web-app.js probes for: window.TelegramWebviewProxy.postEvent(type, data).
//
// When that global exists, telegram-web-app.js routes every app -> host event through
// it INSTEAD of the iframe window.parent.postMessage path. We forward those to the host
// (MiniAppHost) via ipcRenderer.sendToHost on the 'tg-webapp-event' channel.
//
// Host -> app delivery does NOT go through this preload: the host calls
// window.Telegram.WebView.receiveEvent(type, data) directly via webview.executeJavaScript().
// telegram-web-app.js creates window.Telegram.WebView itself, so we must NOT touch it here.
//
// The guest is sandboxed with context isolation enabled. contextBridge exposes only
// the fixed Telegram transport surface to the page's main world.

const { contextBridge, ipcRenderer } = require('electron');

try {
    // Some builds of telegram-web-app.js check for a string return value from postEvent
    // (older Android). Returning undefined is fine for the JSON transport.
    contextBridge.exposeInMainWorld('TelegramWebviewProxy', {
        postEvent(eventType, eventData) {
            if (typeof eventType !== 'string' || eventType.length > 128) return;
            ipcRenderer.sendToHost('tg-webapp-event', {
                eventType,
                eventData,
            });
        },
    });
} catch (_e) {
    // If the property is already defined for any reason, do not clobber.
}
