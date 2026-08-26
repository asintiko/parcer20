import { useEffect, useCallback, RefObject } from 'react';

export interface KeyboardShortcut {
    key: string;
    ctrl?: boolean;
    shift?: boolean;
    alt?: boolean;
    handler: (e: KeyboardEvent) => void;
    description?: string;
    preventDefault?: boolean;
}

export interface UseKeyboardShortcutsOptions {
    shortcuts: KeyboardShortcut[];
    enabled?: boolean;
    containerRef?: RefObject<HTMLElement>;
}

export const useKeyboardShortcuts = ({ shortcuts, enabled = true, containerRef }: UseKeyboardShortcutsOptions) => {
    const handleKeyDown = useCallback(
        (e: KeyboardEvent) => {
            if (!enabled) return;

            // Check if we're in an input element (unless it's the table)
            const target = e.target as HTMLElement;
            const isInput =
                target.tagName === 'INPUT' ||
                target.tagName === 'TEXTAREA' ||
                target.tagName === 'SELECT' ||
                target.isContentEditable;

            for (const shortcut of shortcuts) {
                const keyMatch = e.key.toLowerCase() === shortcut.key.toLowerCase();
                const ctrlMatch = shortcut.ctrl ? (e.ctrlKey || e.metaKey) : !e.ctrlKey && !e.metaKey;
                const shiftMatch = shortcut.shift ? e.shiftKey : !e.shiftKey;
                const altMatch = shortcut.alt ? e.altKey : !e.altKey;

                if (keyMatch && ctrlMatch && shiftMatch && altMatch) {
                    // Skip if in input and not explicitly allowed
                    if (isInput && !shortcut.key.startsWith('Escape')) {
                        continue;
                    }

                    if (shortcut.preventDefault !== false) {
                        e.preventDefault();
                    }

                    shortcut.handler(e);
                    break;
                }
            }
        },
        [shortcuts, enabled]
    );

    useEffect(() => {
        const element = containerRef?.current || document;
        element.addEventListener('keydown', handleKeyDown as any);

        return () => {
            element.removeEventListener('keydown', handleKeyDown as any);
        };
    }, [handleKeyDown, containerRef]);
};
