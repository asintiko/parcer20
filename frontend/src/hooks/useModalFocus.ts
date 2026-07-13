import { useEffect, useRef, type RefObject } from 'react';

const FOCUSABLE_SELECTOR = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[contenteditable="true"]',
    '[tabindex]:not([tabindex="-1"])',
].join(',');

let bodyLockCount = 0;
let previousBodyOverflow = '';

function getFocusableElements(container: HTMLElement): HTMLElement[] {
    return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
        (element) =>
            !element.hidden &&
            element.getAttribute('aria-hidden') !== 'true' &&
            element.getAttribute('aria-disabled') !== 'true' &&
            element.getClientRects().length > 0,
    );
}

export function useModalFocus<T extends HTMLElement>(
    open: boolean,
    containerRef: RefObject<T>,
    onClose: () => void,
) {
    const onCloseRef = useRef(onClose);
    useEffect(() => {
        onCloseRef.current = onClose;
    }, [onClose]);

    useEffect(() => {
        if (!open) return;

        const previouslyFocused = document.activeElement instanceof HTMLElement
            ? document.activeElement
            : null;
        const container = containerRef.current;
        if (!container) return;

        if (bodyLockCount === 0) {
            previousBodyOverflow = document.body.style.overflow;
            document.body.style.overflow = 'hidden';
        }
        bodyLockCount += 1;

        const focusFrame = window.requestAnimationFrame(() => {
            const autofocusTarget = container.querySelector<HTMLElement>('[autofocus]');
            const target = autofocusTarget || getFocusableElements(container)[0] || container;
            target.focus({ preventScroll: true });
        });

        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                onCloseRef.current();
                return;
            }
            if (event.key !== 'Tab') return;

            const focusable = getFocusableElements(container);
            if (focusable.length === 0) {
                event.preventDefault();
                container.focus({ preventScroll: true });
                return;
            }

            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && (document.activeElement === first || document.activeElement === container)) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        };

        document.addEventListener('keydown', handleKeyDown);
        return () => {
            window.cancelAnimationFrame(focusFrame);
            document.removeEventListener('keydown', handleKeyDown);
            bodyLockCount = Math.max(0, bodyLockCount - 1);
            if (bodyLockCount === 0) {
                document.body.style.overflow = previousBodyOverflow;
            }
            if (previouslyFocused?.isConnected) {
                previouslyFocused.focus({ preventScroll: true });
            }
        };
    }, [open, containerRef]);
}
