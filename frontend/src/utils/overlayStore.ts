import { useEffect } from 'react';
import { useSyncExternalStore } from 'react';

/**
 * Lightweight module-store tracking how many overlays (sheets, dialogs,
 * popovers, context menus) are currently open. Used to hide the AI-agent FAB
 * so it never covers overlay controls. No React context / provider needed.
 */

let count = 0;
const listeners = new Set<() => void>();

const emit = () => {
    listeners.forEach((listener) => listener());
};

export function pushOverlay(): void {
    count += 1;
    emit();
}

export function popOverlay(): void {
    count = Math.max(0, count - 1);
    emit();
}

function subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}

const getSnapshot = () => count > 0;
const getServerSnapshot = () => false;

export function useAnyOverlayOpen(): boolean {
    return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

/**
 * Registers an overlay as open while `active` is true. The cleanup balances
 * the counter, so StrictMode's double mount/unmount in dev stays consistent.
 */
export function useRegisterOverlay(active: boolean): void {
    useEffect(() => {
        if (!active) return;
        pushOverlay();
        return () => {
            popOverlay();
        };
    }, [active]);
}
