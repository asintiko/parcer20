import { useEffect, useState, useCallback } from 'react';

type UpdateStatus =
    | 'idle'
    | 'checking'
    | 'available'
    | 'not-available'
    | 'downloading'
    | 'downloaded'
    | 'error';

type UpdateEvent =
    | { status: 'checking' }
    | { status: 'available'; info?: any }
    | { status: 'not-available'; info?: any }
    | { status: 'downloading'; progress?: any }
    | { status: 'downloaded'; info?: any }
    | { status: 'error'; error?: string };

type ElectronUpdatesBridge = {
    getVersion: () => Promise<string>;
    check: () => Promise<unknown>;
    download: () => Promise<unknown>;
    install: (options?: { isSilent?: boolean; isForceRunAfter?: boolean }) => Promise<unknown> | unknown;
    onEvent: (callback: (evt: UpdateEvent) => void) => (() => void) | void;
};

function resolveUpdaterBridge(): { isDesktopRuntime: boolean; bridge: ElectronUpdatesBridge | null } {
    if (typeof window === 'undefined') {
        return { isDesktopRuntime: false, bridge: null };
    }

    const electronApi = (window as any).electronAPI;
    const isDesktopRuntime =
        Boolean(electronApi?.isElectron) || navigator.userAgent.toLowerCase().includes('electron');
    const candidate = electronApi?.updates as Partial<ElectronUpdatesBridge> | undefined;

    const bridge =
        candidate &&
        typeof candidate.getVersion === 'function' &&
        typeof candidate.check === 'function' &&
        typeof candidate.download === 'function' &&
        typeof candidate.install === 'function' &&
        typeof candidate.onEvent === 'function'
            ? (candidate as ElectronUpdatesBridge)
            : null;

    return { isDesktopRuntime, bridge };
}

export function useUpdater() {
    const { isDesktopRuntime, bridge } = resolveUpdaterBridge();
    const isElectron = Boolean(isDesktopRuntime && bridge);
    const [status, setStatus] = useState<UpdateStatus>('idle');
    const [version, setVersion] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [progress, setProgress] = useState<any>(null);

    useEffect(() => {
        if (!isElectron || !bridge) return;
        (async () => {
            try {
                const v = await bridge.getVersion();
                setVersion(v);
            } catch {
                /* ignore */
            }
        })();

        const off = bridge.onEvent((evt: UpdateEvent) => {
            setError(null);
            setProgress(null);
            switch (evt.status) {
                case 'checking':
                    setStatus('checking');
                    break;
                case 'available':
                    setStatus('available');
                    break;
                case 'not-available':
                    setStatus('not-available');
                    break;
                case 'downloading':
                    setStatus('downloading');
                    setProgress(evt.progress);
                    break;
                case 'downloaded':
                    setStatus('downloaded');
                    break;
                case 'error':
                    setStatus('error');
                    setError(evt.error || 'Ошибка обновления');
                    break;
                default:
                    setStatus('idle');
            }
        });
        return () => {
            off && off();
        };
    }, [isElectron, bridge]);

    const check = useCallback(async () => {
        if (!isElectron || !bridge) return;
        setStatus('checking');
        setError(null);
        await bridge.check();
    }, [isElectron, bridge]);

    const download = useCallback(async () => {
        if (!isElectron || !bridge) return;
        setError(null);
        setStatus('downloading');
        await bridge.download();
    }, [isElectron, bridge]);

    const install = useCallback(() => {
        if (!isElectron || !bridge) return;
        bridge.install({ isSilent: false, isForceRunAfter: false });
    }, [isElectron, bridge]);

    return {
        isElectron,
        status,
        version,
        error,
        progress,
        check,
        download,
        install,
    };
}
