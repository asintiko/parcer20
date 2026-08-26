import { useState, useCallback, useRef } from 'react';

export type HistoryAction =
    | { type: 'EDIT'; rowId: number; columnId: string; oldValue: any; newValue: any }
    | { type: 'DELETE'; rowId: number; rowData: any }
    | { type: 'BULK_DELETE'; rows: Array<{ rowId: number; rowData: any }> }
    | { type: 'PASTE'; cells: Array<{ rowId: number; columnId: string; oldValue: any; newValue: any }> };

export interface UseHistoryOptions {
    maxHistory?: number;
    onUndo?: (action: HistoryAction) => Promise<void>;
    onRedo?: (action: HistoryAction) => Promise<void>;
}

export const useHistory = (options: UseHistoryOptions = {}) => {
    const { maxHistory = 50, onUndo, onRedo } = options;

    const [history, setHistory] = useState<HistoryAction[]>([]);
    const [currentIndex, setCurrentIndex] = useState(-1);
    const isUndoingRef = useRef(false);

    const addAction = useCallback(
        (action: HistoryAction) => {
            if (isUndoingRef.current) return;

            setHistory((prev) => {
                // Remove any actions after current index (redo history)
                const newHistory = prev.slice(0, currentIndex + 1);
                // Add new action
                newHistory.push(action);
                // Limit history size
                if (newHistory.length > maxHistory) {
                    newHistory.shift();
                    return newHistory;
                }
                return newHistory;
            });
            setCurrentIndex((prev) => Math.min(prev + 1, maxHistory - 1));
        },
        [currentIndex, maxHistory]
    );

    const undo = useCallback(async () => {
        if (currentIndex < 0) return;

        const action = history[currentIndex];
        isUndoingRef.current = true;

        try {
            await onUndo?.(action);
            setCurrentIndex((prev) => prev - 1);
        } catch (error) {
            console.error('Undo failed:', error);
            throw error;
        } finally {
            isUndoingRef.current = false;
        }
    }, [currentIndex, history, onUndo]);

    const redo = useCallback(async () => {
        if (currentIndex >= history.length - 1) return;

        const action = history[currentIndex + 1];
        isUndoingRef.current = true;

        try {
            await onRedo?.(action);
            setCurrentIndex((prev) => prev + 1);
        } catch (error) {
            console.error('Redo failed:', error);
            throw error;
        } finally {
            isUndoingRef.current = false;
        }
    }, [currentIndex, history, onRedo]);

    const clearHistory = useCallback(() => {
        setHistory([]);
        setCurrentIndex(-1);
    }, []);

    const canUndo = currentIndex >= 0;
    const canRedo = currentIndex < history.length - 1;

    return {
        addAction,
        undo,
        redo,
        clearHistory,
        canUndo,
        canRedo,
        history,
        currentIndex,
    };
};
