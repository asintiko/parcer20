/**
 * Real-time subscription to system settings changes via WebSocket.
 *
 * Design sandbox build: the real backend isn't running here, so the live
 * WebSocket connection is intentionally disabled to keep the dev console
 * clean. The hook stays exported so call sites continue to work.
 */
export function useSettingsSubscription(): void {
    // no-op in design sandbox
}
