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

export function useUpdater() {
    const isElectron = typeof window !== 'undefined' && (window as any).electronAPI?.updates;
    const [status, setStatus] = useState<UpdateStatus>('idle');
    const [version, setVersion] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [progress, setProgress] = useState<any>(null);

    useEffect(() => {
        if (!isElectron) return;
        (async () => {
            try {
                const v = await (window as any).electronAPI.updates.getVersion();
                setVersion(v);
            } catch {
                /* ignore */
            }
        })();

        const off = (window as any).electronAPI.updates.onEvent((evt: UpdateEvent) => {
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
    }, [isElectron]);

    const check = useCallback(async () => {
        if (!isElectron) return;
        setStatus('checking');
        setError(null);
        await (window as any).electronAPI.updates.check();
    }, [isElectron]);

    const download = useCallback(async () => {
        if (!isElectron) return;
        setError(null);
        setStatus('downloading');
        await (window as any).electronAPI.updates.download();
    }, [isElectron]);

    const install = useCallback(() => {
        if (!isElectron) return;
        (window as any).electronAPI.updates.install();
    }, [isElectron]);

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
