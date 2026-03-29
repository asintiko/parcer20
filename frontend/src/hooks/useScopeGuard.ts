/**
 * Resets scope token only after inactivity.
 * Route-to-route navigation must not clear access state.
 */
import { useEffect, useRef } from 'react';
import { securityApi } from '../services/api';

const SCOPE_EXIT_KEY = 'scope_exited_at';
const INACTIVITY_TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes

export function markScopeExited(): void {
    try {
        sessionStorage.setItem(SCOPE_EXIT_KEY, new Date().toISOString());
    } catch { /* ignore */ }
}

export function clearScopeExitedMarker(): void {
    try {
        sessionStorage.removeItem(SCOPE_EXIT_KEY);
    } catch { /* ignore */ }
}

export function hasScopeExitedMarker(): boolean {
    try {
        return Boolean(sessionStorage.getItem(SCOPE_EXIT_KEY));
    } catch {
        return false;
    }
}

export function useScopeGuard(): void {
    const inactivityTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    // Inactivity timer: reset scope token after 5 min of no interaction
    useEffect(() => {
        function resetTimer() {
            if (inactivityTimerRef.current) {
                clearTimeout(inactivityTimerRef.current);
            }
            inactivityTimerRef.current = setTimeout(() => {
                markScopeExited();
                securityApi.clearScopeToken();
                securityApi.clearTelegramAccessToken();
            }, INACTIVITY_TIMEOUT_MS);
        }

        const events = ['mousedown', 'keydown', 'scroll', 'touchstart'] as const;
        events.forEach((ev) => window.addEventListener(ev, resetTimer, { passive: true }));
        resetTimer(); // start timer

        return () => {
            events.forEach((ev) => window.removeEventListener(ev, resetTimer));
            if (inactivityTimerRef.current) {
                clearTimeout(inactivityTimerRef.current);
            }
        };
    }, []);
}
