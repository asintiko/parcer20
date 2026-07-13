import React, {
    createContext,
    useCallback,
    useContext,
    useMemo,
    useRef,
    useState,
} from 'react';
import { telegramClientApi } from '../services/api';

/**
 * Mini App launch/lifecycle context.
 *
 * `MiniAppProvider` wraps the userbot chat subtree; a single `<MiniAppHost/>` is
 * rendered inside it and reads `useMiniApp().current` to know what to load.
 *
 * open()  -> resolves the launch URL via telegramClientApi.openWebApp, stores
 *            {req, url, launchId}, flips isOpen.
 * close() -> calls telegramClientApi.closeWebApp(chatId, launchId) if we hold a
 *            launch_id, then clears state.
 */

export interface MiniAppOpenReq {
    chatId: number;
    botUserId?: number | null;
    url: string;
    buttonKind: 'inline' | 'keyboard' | 'menu';
    buttonText?: string;
}

export interface MiniAppCurrent {
    req: MiniAppOpenReq;
    /** Resolved launch URL returned by the backend (webAppInfo.url / webAppUrl.url). */
    url: string;
    /** int64-as-string launch id, or null for keyboard/simple web apps. */
    launchId: string | null;
}

export interface MiniAppApi {
    open(req: MiniAppOpenReq): void;
    close(): void;
    isOpen: boolean;
    current: MiniAppCurrent | null;
    /** Set while open() is resolving the launch URL (before the webview loads). */
    isResolving: boolean;
    /** Non-null when the last open() failed to resolve. */
    error: string | null;
}

const MiniAppContext = createContext<MiniAppApi | null>(null);

export const MiniAppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [current, setCurrent] = useState<MiniAppCurrent | null>(null);
    const [isResolving, setIsResolving] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Monotonic token so a stale open() resolution can't clobber a newer request.
    const openTokenRef = useRef(0);
    // Snapshot of the currently-open request, read by close() without a state race.
    const currentRef = useRef<MiniAppCurrent | null>(null);
    currentRef.current = current;

    const close = useCallback(() => {
        // Invalidate any in-flight open().
        openTokenRef.current += 1;
        const active = currentRef.current;
        currentRef.current = null;
        setCurrent(null);
        setIsResolving(false);
        setError(null);
        if (active && active.launchId) {
            // Fire-and-forget; a failed close must not block teardown.
            telegramClientApi
                .closeWebApp(active.req.chatId, active.launchId)
                .catch(() => undefined);
        }
    }, []);

    const open = useCallback(
        (req: MiniAppOpenReq) => {
            const token = ++openTokenRef.current;
            // If something is already open, close it (best-effort) before switching.
            const prev = currentRef.current;
            if (prev && prev.launchId) {
                telegramClientApi
                    .closeWebApp(prev.req.chatId, prev.launchId)
                    .catch(() => undefined);
            }
            currentRef.current = null;
            setCurrent(null);
            setError(null);
            setIsResolving(true);

            telegramClientApi
                .openWebApp(req.chatId, {
                    url: req.url,
                    bot_user_id: req.botUserId ?? null,
                    button_kind: req.buttonKind,
                })
                .then((res) => {
                    if (openTokenRef.current !== token) {
                        // Superseded / cancelled while resolving. If the backend handed
                        // us a launch_id we'll never use, close it so it doesn't leak.
                        if (res.launch_id) {
                            telegramClientApi
                                .closeWebApp(req.chatId, res.launch_id)
                                .catch(() => undefined);
                        }
                        return;
                    }
                    const next: MiniAppCurrent = {
                        req,
                        url: res.url,
                        launchId: res.launch_id,
                    };
                    currentRef.current = next;
                    setCurrent(next);
                    setIsResolving(false);
                })
                .catch((err: unknown) => {
                    if (openTokenRef.current !== token) return;
                    setIsResolving(false);
                    setError(
                        (err as { message?: string })?.message ||
                            'Не удалось открыть мини-приложение'
                    );
                });
        },
        []
    );

    const value = useMemo<MiniAppApi>(
        () => ({
            open,
            close,
            isOpen: current !== null || isResolving,
            current,
            isResolving,
            error,
        }),
        [open, close, current, isResolving, error]
    );

    return <MiniAppContext.Provider value={value}>{children}</MiniAppContext.Provider>;
};

export function useMiniApp(): MiniAppApi {
    const ctx = useContext(MiniAppContext);
    if (!ctx) {
        throw new Error('useMiniApp must be used within a <MiniAppProvider>');
    }
    return ctx;
}
