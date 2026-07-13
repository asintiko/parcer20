import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence, type Variants } from 'motion/react';
import { X, ChevronLeft, Loader2 } from 'lucide-react';
import { useMiniApp } from '../../hooks/useMiniApp';
import { telegramClientApi } from '../../services/api';

// The <webview> JSX intrinsic + electronAPI.miniApp Window augmentation come from
// the ambient ./miniapp.d.ts (picked up via tsconfig include). These two shapes are
// only referenced here, so we keep them local to avoid importing from a .d.ts by path.
interface ElectronWebviewTag extends HTMLElement {
    src: string;
    getWebContentsId(): number;
    executeJavaScript(code: string, userGesture?: boolean): Promise<unknown>;
    addEventListener(type: string, listener: (event: Event) => void): void;
    removeEventListener(type: string, listener: (event: Event) => void): void;
}

interface WebviewIpcMessageEvent extends Event {
    channel: string;
    args: unknown[];
}

/**
 * MiniAppHost — the modal surface that loads a Telegram Mini App and speaks the
 * Telegram WebApp postMessage protocol on its behalf.
 *
 * Transport:
 *  - Electron: an <webview> with electron/webapp-preload.cjs. The preload installs
 *    window.TelegramWebviewProxy so telegram-web-app.js uses the "mobile" transport;
 *    app -> host events arrive as webview 'ipc-message' (channel 'tg-webapp-event').
 *    host -> app events are delivered via webview.executeJavaScript(...) calling
 *    window.Telegram.WebView.receiveEvent(eventType, eventData).
 *  - Web (dev fallback): an <iframe>; app posts JSON.stringify({eventType,eventData})
 *    to window.parent; host posts back to iframe.contentWindow.
 *
 * Rendered ONCE inside <MiniAppProvider>. Reads useMiniApp().current.
 */

const isElectron =
    typeof window !== 'undefined' &&
    (Boolean(window.electronAPI?.isElectron) ||
        navigator.userAgent.toLowerCase().includes('electron'));

// Dark theme params delivered to the mini app (hex strings, snake_case keys).
const THEME_PARAMS = {
    bg_color: '#101010',
    secondary_bg_color: '#181818',
    text_color: '#f2f2f2',
    hint_color: '#8a8a8a',
    link_color: '#d0d0d0',
    button_color: '#f2f2f2',
    button_text_color: '#101010',
    header_bg_color: '#101010',
    accent_text_color: '#f2f2f2',
    section_bg_color: '#181818',
    section_header_text_color: '#8a8a8a',
    subtitle_text_color: '#8a8a8a',
    destructive_text_color: '#ff5a52',
} as const;

interface MainButtonState {
    isVisible: boolean;
    isActive: boolean;
    text: string;
    color: string | null;
    textColor: string | null;
    isProgressVisible: boolean;
}

interface PopupButton {
    id?: string;
    type?: 'default' | 'ok' | 'close' | 'cancel' | 'destructive';
    text?: string;
}

interface PopupState {
    title?: string;
    message: string;
    buttons: PopupButton[];
}

interface ClipboardConsent {
    reqId: string;
    origin: string;
    navigationEpoch: number;
}

const overlayVariants: Variants = {
    hidden: { opacity: 0 },
    visible: { opacity: 1, transition: { duration: 0.24, ease: [0.16, 1, 0.3, 1] } },
    exit: { opacity: 0, transition: { duration: 0.16, ease: [0.4, 0, 1, 1] } },
};

const panelVariants: Variants = {
    hidden: { opacity: 0, scale: 0.98, y: 8 },
    visible: { opacity: 1, scale: 1, y: 0, transition: { duration: 0.26, ease: [0.16, 1, 0.3, 1] } },
    exit: { opacity: 0, scale: 0.99, y: 4, transition: { duration: 0.16, ease: [0.4, 0, 1, 1] } },
};

/** Coerce an inbound eventData (JSON string, object, or undefined) into an object. */
function parseEventData(raw: unknown): Record<string, unknown> {
    if (raw == null) return {};
    if (typeof raw === 'object') return raw as Record<string, unknown>;
    if (typeof raw === 'string') {
        const trimmed = raw.trim();
        if (!trimmed) return {};
        try {
            const parsed = JSON.parse(trimmed);
            return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : {};
        } catch {
            return {};
        }
    }
    return {};
}

function openExternal(url: string): void {
    if (!url) return;
    if (isElectron && window.electronAPI?.miniApp?.openExternal) {
        window.electronAPI.miniApp.openExternal(url).catch(() => {
            window.open(url, '_blank', 'noopener');
        });
        return;
    }
    // Web fallback / Electron setWindowOpenHandler route.
    window.open(url, '_blank', 'noopener');
}

export const MiniAppHost: React.FC = () => {
    const { current, isResolving, error, close } = useMiniApp();
    const isOpen = current !== null || isResolving;

    const webviewRef = useRef<ElectronWebviewTag | null>(null);
    const iframeRef = useRef<HTMLIFrameElement | null>(null);
    const bodyRef = useRef<HTMLDivElement | null>(null);
    // Set false on unmount / teardown so no host->app send fires into a dead frame.
    const aliveRef = useRef(true);
    // Guards executeJavaScript against a webview that hasn't attached / was destroyed.
    const webviewReadyRef = useRef(false);
    const navigationEpochRef = useRef(0);
    const clipboardConsentRef = useRef<ClipboardConsent | null>(null);

    const [loading, setLoading] = useState(true);
    const [mainButton, setMainButton] = useState<MainButtonState | null>(null);
    const [backButtonVisible, setBackButtonVisible] = useState(false);
    const [popup, setPopup] = useState<PopupState | null>(null);
    const needConfirmRef = useRef(false);

    // Reset per-launch chrome whenever a new mini app opens.
    useEffect(() => {
        aliveRef.current = true;
        webviewReadyRef.current = false;
        setLoading(true);
        setMainButton(null);
        setBackButtonVisible(false);
        setPopup(null);
        navigationEpochRef.current += 1;
        clipboardConsentRef.current = null;
        needConfirmRef.current = false;
        return () => {
            aliveRef.current = false;
        };
    }, [current?.url]);

    // --- host -> app delivery ------------------------------------------------
    const sendToApp = useCallback((eventType: string, eventData: unknown) => {
        if (!aliveRef.current) return;
        if (isElectron) {
            const wv = webviewRef.current;
            if (!wv || !webviewReadyRef.current) return;
            const payload = JSON.stringify(eventData ?? {});
            const js =
                'try{window.Telegram&&window.Telegram.WebView&&window.Telegram.WebView.receiveEvent(' +
                JSON.stringify(eventType) +
                ',' +
                payload +
                ')}catch(e){}';
            wv.executeJavaScript(js, false).catch(() => undefined);
        } else {
            const frame = iframeRef.current;
            const win = frame?.contentWindow;
            if (!win) return;
            try {
                const targetOrigin = current ? new URL(current.url).origin : '';
                if (!targetOrigin) return;
                win.postMessage(JSON.stringify({ eventType, eventData: eventData ?? {} }), targetOrigin);
            } catch {
                /* cross-origin post can throw synchronously in odd cases */
            }
        }
    }, [current]);

    const viewportSize = useCallback(() => {
        const el = bodyRef.current;
        const width = el?.clientWidth ?? window.innerWidth;
        const height = el?.clientHeight ?? window.innerHeight;
        return { width, height };
    }, []);

    // --- teardown ------------------------------------------------------------
    const requestClose = useCallback(() => {
        if (needConfirmRef.current) {
            setPopup({
                message: 'Закрыть приложение? Несохранённые данные будут потеряны.',
                buttons: [
                    { id: '__confirm_close_no', type: 'cancel', text: 'Отмена' },
                    { id: '__confirm_close_yes', type: 'destructive', text: 'Закрыть' },
                ],
            });
            return;
        }
        aliveRef.current = false;
        webviewReadyRef.current = false;
        close();
    }, [close]);

    // --- app -> host dispatch ------------------------------------------------
    const handleEvent = useCallback(
        (eventType: string, rawData: unknown) => {
            if (!aliveRef.current) return;
            const data = parseEventData(rawData);

            switch (eventType) {
                case 'web_app_ready':
                case 'iframe_ready': {
                    setLoading(false);
                    // Prime the app with theme + viewport so it lays out correctly.
                    sendToApp('theme_changed', { theme_params: THEME_PARAMS });
                    const vp = viewportSize();
                    sendToApp('viewport_changed', {
                        ...vp,
                        is_expanded: true,
                        is_state_stable: true,
                    });
                    sendToApp('safe_area_changed', { top: 0, bottom: 0, left: 0, right: 0 });
                    sendToApp('content_safe_area_changed', { top: 0, bottom: 0, left: 0, right: 0 });
                    break;
                }
                case 'web_app_request_theme':
                    sendToApp('theme_changed', { theme_params: THEME_PARAMS });
                    break;
                case 'web_app_request_viewport': {
                    const vp = viewportSize();
                    sendToApp('viewport_changed', {
                        ...vp,
                        is_expanded: true,
                        is_state_stable: true,
                    });
                    break;
                }
                case 'web_app_request_safe_area':
                    sendToApp('safe_area_changed', { top: 0, bottom: 0, left: 0, right: 0 });
                    break;
                case 'web_app_request_content_safe_area':
                    sendToApp('content_safe_area_changed', { top: 0, bottom: 0, left: 0, right: 0 });
                    break;
                case 'web_app_expand': {
                    const vp = viewportSize();
                    sendToApp('viewport_changed', {
                        ...vp,
                        is_expanded: true,
                        is_state_stable: true,
                    });
                    break;
                }
                case 'web_app_setup_main_button': {
                    setMainButton({
                        isVisible: Boolean(data.is_visible),
                        isActive: data.is_active !== false,
                        text: typeof data.text === 'string' ? data.text : '',
                        color: typeof data.color === 'string' ? data.color : null,
                        textColor: typeof data.text_color === 'string' ? data.text_color : null,
                        isProgressVisible: Boolean(data.is_progress_visible),
                    });
                    break;
                }
                case 'web_app_setup_back_button':
                    setBackButtonVisible(Boolean(data.is_visible));
                    break;
                case 'web_app_setup_settings_button':
                    // Optional chrome; press would send 'settings_button_pressed'. We render
                    // no settings button, so nothing to show.
                    break;
                case 'web_app_setup_closing_behavior':
                    needConfirmRef.current = Boolean(data.need_confirmation);
                    break;
                case 'web_app_set_background_color':
                case 'web_app_set_header_color':
                case 'web_app_set_bottom_bar_color':
                    // Host chrome is fixed to the editorial dark palette; acknowledge silently.
                    break;
                case 'web_app_open_link': {
                    const url = typeof data.url === 'string' ? data.url : '';
                    if (url) openExternal(url);
                    break;
                }
                case 'web_app_open_tg_link': {
                    const pathFull = typeof data.path_full === 'string' ? data.path_full : '';
                    if (pathFull) openExternal(`https://t.me${pathFull}`);
                    break;
                }
                case 'web_app_open_popup': {
                    const buttons = Array.isArray(data.buttons)
                        ? (data.buttons as PopupButton[])
                        : [];
                    setPopup({
                        title: typeof data.title === 'string' ? data.title : undefined,
                        message: typeof data.message === 'string' ? data.message : '',
                        buttons: buttons.length
                            ? buttons
                            : [{ id: 'ok', type: 'ok', text: 'OK' }],
                    });
                    break;
                }
                case 'web_app_close':
                    requestClose();
                    break;
                case 'web_app_data_send': {
                    if (!current) break;
                    const payload = typeof data.data === 'string' ? data.data : '';
                    const { req } = current;
                    telegramClientApi
                        .sendWebAppData(req.chatId, {
                            bot_user_id: req.botUserId ?? null,
                            button_text: req.buttonText ?? '',
                            data: payload,
                        })
                        .catch(() => undefined)
                        .finally(() => {
                            aliveRef.current = false;
                            close();
                        });
                    break;
                }
                case 'web_app_read_text_from_clipboard': {
                    const reqId = typeof data.req_id === 'string' ? data.req_id : '';
                    if (!reqId || !current) break;
                    const prior = clipboardConsentRef.current;
                    if (prior) {
                        sendToApp('clipboard_text_received', { req_id: prior.reqId, data: '' });
                    }
                    clipboardConsentRef.current = {
                        reqId,
                        origin: new URL(current.url).origin,
                        navigationEpoch: navigationEpochRef.current,
                    };
                    setPopup({
                        title: 'Доступ к буферу обмена',
                        message: `${new URL(current.url).hostname} запрашивает однократное чтение буфера обмена.`,
                        buttons: [
                            { id: '__clipboard_deny', type: 'cancel', text: 'Запретить' },
                            { id: '__clipboard_allow', type: 'ok', text: 'Разрешить один раз' },
                        ],
                    });
                    break;
                }
                case 'web_app_request_write_access':
                    // Our own client — auto-allow.
                    sendToApp('write_access_requested', { status: 'allowed' });
                    break;
                case 'web_app_request_phone':
                    // We do not share the phone number.
                    sendToApp('phone_requested', { status: 'cancelled' });
                    break;
                case 'web_app_trigger_haptic_feedback':
                    // No haptics on desktop.
                    break;
                default:
                    // web_app_switch_inline_query, secondary/settings button setup, swipe
                    // behavior, sensors, storage, biometry, etc. — safe no-op.
                    break;
            }
        },
        [close, current, requestClose, sendToApp, viewportSize]
    );

    // --- Electron: webview ipc-message + lifecycle ---------------------------
    useEffect(() => {
        if (!isElectron || !current) return;
        const wv = webviewRef.current;
        if (!wv) return;

        const onIpcMessage = (event: Event) => {
            const e = event as WebviewIpcMessageEvent;
            if (e.channel !== 'tg-webapp-event') return;
            const arg = (e.args && e.args[0]) as
                | { eventType?: string; eventData?: unknown }
                | undefined;
            if (!arg || typeof arg.eventType !== 'string') return;
            handleEvent(arg.eventType, arg.eventData);
        };

        const onDomReady = () => {
            webviewReadyRef.current = true;
        };
        const onDidFinishLoad = () => {
            webviewReadyRef.current = true;
            // Some apps never emit web_app_ready promptly; drop the spinner on load.
            setLoading(false);
        };
        const onDidFailLoad = (event: Event) => {
            const e = event as unknown as { errorCode?: number; isMainFrame?: boolean };
            // -3 == ERR_ABORTED (navigation cancelled) — ignore.
            if (e.isMainFrame && e.errorCode !== -3) {
                setLoading(false);
            }
        };
        const onDestroyed = () => {
            webviewReadyRef.current = false;
        };
        const onNavigation = (event: Event) => {
            const e = event as unknown as { isMainFrame?: boolean };
            if (e.isMainFrame === false) return;
            navigationEpochRef.current += 1;
            const pending = clipboardConsentRef.current;
            clipboardConsentRef.current = null;
            if (pending) {
                sendToApp('clipboard_text_received', { req_id: pending.reqId, data: '' });
                setPopup(null);
            }
            webviewReadyRef.current = false;
        };

        wv.addEventListener('ipc-message', onIpcMessage);
        wv.addEventListener('dom-ready', onDomReady);
        wv.addEventListener('did-finish-load', onDidFinishLoad);
        wv.addEventListener('did-fail-load', onDidFailLoad);
        wv.addEventListener('destroyed', onDestroyed);
        wv.addEventListener('did-start-navigation', onNavigation);
        wv.addEventListener('did-navigate-in-page', onNavigation);
        return () => {
            wv.removeEventListener('ipc-message', onIpcMessage);
            wv.removeEventListener('dom-ready', onDomReady);
            wv.removeEventListener('did-finish-load', onDidFinishLoad);
            wv.removeEventListener('did-fail-load', onDidFailLoad);
            wv.removeEventListener('destroyed', onDestroyed);
            wv.removeEventListener('did-start-navigation', onNavigation);
            wv.removeEventListener('did-navigate-in-page', onNavigation);
        };
    }, [current, handleEvent, sendToApp]);

    // --- Web fallback: window message listener -------------------------------
    useEffect(() => {
        if (isElectron || !current) return;
        const onMessage = (event: MessageEvent) => {
            const frame = iframeRef.current;
            if (!frame || event.source !== frame.contentWindow) return;
            let expectedOrigin = '';
            try {
                expectedOrigin = new URL(current.url).origin;
            } catch {
                return;
            }
            if (event.origin !== expectedOrigin) return;
            let parsed: { eventType?: string; eventData?: unknown } | null = null;
            if (typeof event.data === 'string') {
                try {
                    parsed = JSON.parse(event.data);
                } catch {
                    return;
                }
            } else if (event.data && typeof event.data === 'object') {
                parsed = event.data as { eventType?: string; eventData?: unknown };
            }
            if (!parsed || typeof parsed.eventType !== 'string') return;
            handleEvent(parsed.eventType, parsed.eventData);
        };
        window.addEventListener('message', onMessage);
        return () => window.removeEventListener('message', onMessage);
    }, [current, handleEvent]);

    // --- Resolve the webview preload path (Electron) --------------------------
    const [preloadUrl, setPreloadUrl] = useState<string | null>(null);
    useEffect(() => {
        if (!isElectron) return;
        let cancelled = false;
        const bridge = window.electronAPI?.miniApp;
        if (bridge?.getPreloadPath) {
            bridge
                .getPreloadPath()
                .then((p) => {
                    if (cancelled || !p) return;
                    // main.cjs will_attach_webview pins the real preload regardless, but
                    // the <webview> still needs a valid file URL on the attribute.
                    setPreloadUrl(p.startsWith('file:') ? p : `file://${p}`);
                })
                .catch(() => undefined);
        }
        return () => {
            cancelled = true;
        };
    }, []);

    // --- popup resolution ----------------------------------------------------
    const resolvePopup = useCallback(
        (button: PopupButton | null) => {
            const id = button?.id ?? '';
            setPopup(null);
            if (id === '__clipboard_allow' || id === '__clipboard_deny' || clipboardConsentRef.current) {
                const consent = clipboardConsentRef.current;
                clipboardConsentRef.current = null;
                if (!consent) return;
                const respond = (text: string) =>
                    sendToApp('clipboard_text_received', { req_id: consent.reqId, data: text });
                if (id !== '__clipboard_allow') {
                    respond('');
                    return;
                }
                let currentOrigin = '';
                try {
                    currentOrigin = current ? new URL(current.url).origin : '';
                } catch {
                    respond('');
                    return;
                }
                if (
                    currentOrigin !== consent.origin ||
                    navigationEpochRef.current !== consent.navigationEpoch ||
                    !navigator.clipboard?.readText
                ) {
                    respond('');
                    return;
                }
                void navigator.clipboard.readText().then((text) => {
                    let liveOrigin = '';
                    try {
                        liveOrigin = current ? new URL(current.url).origin : '';
                    } catch {
                        // The empty origin below keeps the response fail-closed.
                    }
                    respond(
                        liveOrigin === consent.origin &&
                        navigationEpochRef.current === consent.navigationEpoch
                            ? (text ?? '')
                            : '',
                    );
                }).catch(() => respond(''));
                return;
            }
            if (id === '__confirm_close_yes') {
                needConfirmRef.current = false;
                aliveRef.current = false;
                webviewReadyRef.current = false;
                close();
                return;
            }
            if (id === '__confirm_close_no') {
                return;
            }
            // Regular popup dismissal → notify the app.
            sendToApp('popup_closed', { button_id: id });
        },
        [close, current, sendToApp]
    );

    // --- Esc to close --------------------------------------------------------
    useEffect(() => {
        if (!isOpen) return;
        const onKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                if (popup) {
                    // Esc dismisses a popup first (as a cancel), not the whole app.
                    resolvePopup(null);
                } else {
                    requestClose();
                }
            }
        };
        window.addEventListener('keydown', onKey);
        const prevOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        return () => {
            window.removeEventListener('keydown', onKey);
            document.body.style.overflow = prevOverflow;
        };
    }, [isOpen, popup, requestClose, resolvePopup]);

    const title = useMemo(() => {
        if (!current) return 'Мини-приложение';
        try {
            const u = new URL(current.url);
            return u.hostname.replace(/^www\./, '');
        } catch {
            return 'Мини-приложение';
        }
    }, [current]);

    const onMainButtonPress = useCallback(() => {
        if (!mainButton?.isActive) return;
        sendToApp('main_button_pressed', {});
    }, [mainButton, sendToApp]);

    const onBackButtonPress = useCallback(() => {
        sendToApp('back_button_pressed', {});
    }, [sendToApp]);

    const onIframeLoad = useCallback(() => {
        navigationEpochRef.current += 1;
        const pending = clipboardConsentRef.current;
        clipboardConsentRef.current = null;
        if (pending) {
            sendToApp('clipboard_text_received', { req_id: pending.reqId, data: '' });
            setPopup(null);
        }
    }, [sendToApp]);

    if (!isOpen) return null;

    return (
        <AnimatePresence>
            <motion.div
                key="miniapp-overlay"
                className="sp-sheet-overlay"
                variants={overlayVariants}
                initial="hidden"
                animate="visible"
                exit="exit"
                onClick={requestClose}
                aria-hidden
                style={{ zIndex: 1200 }}
            />
            <motion.div
                key="miniapp-panel"
                role="dialog"
                aria-modal="true"
                aria-label={title}
                variants={panelVariants}
                initial="hidden"
                animate="visible"
                exit="exit"
                style={{
                    position: 'fixed',
                    inset: 0,
                    zIndex: 1201,
                    display: 'flex',
                    flexDirection: 'column',
                    width: 'min(560px, 100vw)',
                    height: 'min(860px, 100vh)',
                    maxHeight: '100vh',
                    margin: 'auto',
                    background: 'var(--sp-bg, #101010)',
                    color: 'var(--sp-ink, #f2f2f2)',
                    border: '1px solid var(--sp-border, #2a2a2a)',
                    borderRadius: 'var(--sp-radius, 6px)',
                    overflow: 'hidden',
                    boxShadow: '0 24px 64px -12px rgba(0,0,0,0.6)',
                }}
                onClick={(e) => e.stopPropagation()}
            >
                {/* header */}
                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        height: 48,
                        padding: '0 8px 0 6px',
                        borderBottom: '1px solid var(--sp-border, #2a2a2a)',
                        flex: '0 0 auto',
                        background: 'var(--sp-surface, #181818)',
                    }}
                >
                    {backButtonVisible ? (
                        <button
                            type="button"
                            className="sp-btn sp-btn-icon sp-btn-ghost"
                            onClick={onBackButtonPress}
                            aria-label="Назад"
                        >
                            <ChevronLeft size={16} />
                        </button>
                    ) : (
                        <span style={{ width: 30 }} aria-hidden />
                    )}
                    <div
                        style={{
                            flex: 1,
                            minWidth: 0,
                            fontSize: 13,
                            fontWeight: 600,
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            color: 'var(--sp-ink, #f2f2f2)',
                        }}
                    >
                        {title}
                    </div>
                    <button
                        type="button"
                        className="sp-btn sp-btn-icon sp-btn-ghost"
                        onClick={requestClose}
                        aria-label="Закрыть"
                    >
                        <X size={16} />
                    </button>
                </div>

                {/* body */}
                <div
                    ref={bodyRef}
                    style={{
                        position: 'relative',
                        flex: '1 1 auto',
                        minHeight: 0,
                        background: 'var(--sp-bg, #101010)',
                    }}
                >
                    {error ? (
                        <div
                            style={{
                                position: 'absolute',
                                inset: 0,
                                display: 'flex',
                                flexDirection: 'column',
                                alignItems: 'center',
                                justifyContent: 'center',
                                gap: 8,
                                padding: 24,
                                textAlign: 'center',
                                color: 'var(--sp-ink-muted, #8a8a8a)',
                                fontSize: 13,
                            }}
                        >
                            <span>{error}</span>
                            <button
                                type="button"
                                className="sp-btn sp-btn-sm sp-btn-ghost"
                                onClick={requestClose}
                            >
                                Закрыть
                            </button>
                        </div>
                    ) : current ? (
                        isElectron ? (
                            <webview
                                ref={webviewRef as unknown as React.Ref<ElectronWebviewTag>}
                                src={current.url}
                                {...(preloadUrl ? { preload: preloadUrl } : {})}
                                partition="persist:miniapp"
                                allowpopups={false}
                                style={{
                                    display: 'inline-flex',
                                    width: '100%',
                                    height: '100%',
                                    border: 'none',
                                    background: '#101010',
                                }}
                            />
                        ) : (
                            <iframe
                                ref={iframeRef}
                                src={current.url}
                                title={title}
                                onLoad={onIframeLoad}
                                sandbox="allow-scripts allow-forms allow-same-origin allow-modals"
                                style={{
                                    width: '100%',
                                    height: '100%',
                                    border: 'none',
                                    background: '#101010',
                                }}
                            />
                        )
                    ) : null}

                    {(loading || isResolving) && !error ? (
                        <div
                            style={{
                                position: 'absolute',
                                inset: 0,
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                background: 'var(--sp-bg, #101010)',
                                pointerEvents: 'none',
                            }}
                        >
                            <Loader2
                                size={22}
                                style={{
                                    color: 'var(--sp-ink-muted, #8a8a8a)',
                                    animation: 'sp-miniapp-spin 0.9s linear infinite',
                                }}
                            />
                        </div>
                    ) : null}
                </div>

                {/* main button */}
                {mainButton?.isVisible ? (
                    <div
                        style={{
                            flex: '0 0 auto',
                            padding: 10,
                            borderTop: '1px solid var(--sp-border, #2a2a2a)',
                            background: 'var(--sp-surface, #181818)',
                        }}
                    >
                        <button
                            type="button"
                            onClick={onMainButtonPress}
                            disabled={!mainButton.isActive}
                            className="sp-btn sp-btn-lg sp-btn-primary"
                            style={{
                                width: '100%',
                                ...(mainButton.color
                                    ? { background: mainButton.color, borderColor: mainButton.color }
                                    : {}),
                                ...(mainButton.textColor ? { color: mainButton.textColor } : {}),
                            }}
                        >
                            {mainButton.isProgressVisible ? (
                                <Loader2
                                    size={15}
                                    style={{ animation: 'sp-miniapp-spin 0.9s linear infinite' }}
                                />
                            ) : null}
                            {mainButton.text || 'Продолжить'}
                        </button>
                    </div>
                ) : null}
            </motion.div>

            {/* popup */}
            {popup ? (
                <motion.div
                    key="miniapp-popup"
                    className="sp-sheet-overlay"
                    variants={overlayVariants}
                    initial="hidden"
                    animate="visible"
                    exit="exit"
                    style={{
                        zIndex: 1300,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        padding: 16,
                    }}
                    onClick={() => resolvePopup(null)}
                >
                    <div
                        role="alertdialog"
                        aria-modal="true"
                        onClick={(e) => e.stopPropagation()}
                        style={{
                            width: 'min(360px, calc(100vw - 32px))',
                            background: 'var(--sp-surface, #181818)',
                            border: '1px solid var(--sp-border, #2a2a2a)',
                            borderRadius: 'var(--sp-radius, 6px)',
                            padding: 16,
                            color: 'var(--sp-ink, #f2f2f2)',
                            boxShadow: '0 24px 64px -12px rgba(0,0,0,0.6)',
                        }}
                    >
                        {popup.title ? (
                            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6 }}>
                                {popup.title}
                            </div>
                        ) : null}
                        <div
                            style={{
                                fontSize: 13,
                                lineHeight: 1.5,
                                color: 'var(--sp-ink-muted, #b5b5b5)',
                                marginBottom: 14,
                                whiteSpace: 'pre-wrap',
                            }}
                        >
                            {popup.message}
                        </div>
                        <div
                            style={{
                                display: 'flex',
                                gap: 8,
                                justifyContent: 'flex-end',
                                flexWrap: 'wrap',
                            }}
                        >
                            {popup.buttons.map((btn, idx) => {
                                const isDestructive = btn.type === 'destructive';
                                const isCancel = btn.type === 'cancel' || btn.type === 'close';
                                const cls = isDestructive
                                    ? 'sp-btn sp-btn-sm sp-btn-danger sp-btn-solid'
                                    : isCancel
                                      ? 'sp-btn sp-btn-sm sp-btn-ghost'
                                      : 'sp-btn sp-btn-sm sp-btn-primary';
                                return (
                                    <button
                                        key={btn.id ?? `${btn.type ?? 'btn'}-${idx}`}
                                        type="button"
                                        className={cls}
                                        onClick={() => resolvePopup(btn)}
                                    >
                                        {btn.text || (btn.type === 'ok' ? 'OK' : 'Закрыть')}
                                    </button>
                                );
                            })}
                        </div>
                    </div>
                </motion.div>
            ) : null}

            <style key="miniapp-spin-kf">{`@keyframes sp-miniapp-spin{to{transform:rotate(360deg)}}`}</style>
        </AnimatePresence>
    );
};

export default MiniAppHost;
