import { useEffect, useMemo, useState } from 'react';

export type TableViewState = {
    columnOrder: string[];
    columnSizing: Record<string, number>;
    columnVisibility: Record<string, boolean>;
    density: 'ultra-compact' | 'compact' | 'standard' | 'comfortable';
    pinnedCount?: 0 | 1 | 2 | 3;
    activeFilters: any;
    globalFilter: string;
    columnStyles: Record<string, any>;
    cellStyles: Record<string, any>;
};

export type TableViewPreset = {
    name: string;
    state: TableViewState;
    isDefault?: boolean;
    createdAt: number;
};

const STORAGE_KEY_PREFIX = 'transactionTablePresets:v4';
const DEFAULT_SCOPE = 'anonymous@unknown-host';

const loadFromStorage = (storageKey: string): TableViewPreset[] => {
    try {
        const raw = localStorage.getItem(storageKey);
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return [];
        return parsed;
    } catch {
        return [];
    }
};

const persist = (storageKey: string, presets: TableViewPreset[]) => {
    localStorage.setItem(storageKey, JSON.stringify(presets));
};

export const useTableViewPresets = (scopeKey?: string) => {
    const resolvedScope = (scopeKey || '').trim() || DEFAULT_SCOPE;
    const storageKey = useMemo(() => `${STORAGE_KEY_PREFIX}:${resolvedScope}`, [resolvedScope]);
    const [presets, setPresets] = useState<TableViewPreset[]>(() => loadFromStorage(storageKey));
    const [hydratedKey, setHydratedKey] = useState(storageKey);
    const isHydrated = hydratedKey === storageKey;

    useEffect(() => {
        setPresets(loadFromStorage(storageKey));
        setHydratedKey(storageKey);
    }, [storageKey]);

    useEffect(() => {
        if (hydratedKey !== storageKey) return;
        persist(storageKey, presets);
    }, [storageKey, presets, hydratedKey]);

    const defaultPreset = useMemo(() => presets.find(p => p.isDefault), [presets]);

    const savePreset = (name: string, state: TableViewState, markDefault = false) => {
        setPresets(prev => {
            const existingIdx = prev.findIndex(p => p.name === name);
            const next = [...prev];
            const newPreset: TableViewPreset = {
                name,
                state,
                isDefault: markDefault || (existingIdx >= 0 ? prev[existingIdx].isDefault : false),
                createdAt: Date.now(),
            };
            if (existingIdx >= 0) {
                next[existingIdx] = newPreset;
            } else {
                next.push(newPreset);
            }
            if (markDefault) {
                return next.map(p => ({ ...p, isDefault: p.name === name }));
            }
            return next;
        });
    };

    const deletePreset = (name: string) => {
        setPresets(prev => prev.filter(p => p.name !== name));
    };

    const renamePreset = (oldName: string, newName: string) => {
        setPresets(prev =>
            prev.map(p => (p.name === oldName ? { ...p, name: newName } : p))
        );
    };

    const setDefaultPreset = (name: string) => {
        setPresets(prev => prev.map(p => ({ ...p, isDefault: p.name === name })));
    };

    const getPreset = (name: string) => presets.find(p => p.name === name);

    return {
        presets,
        defaultPreset,
        isHydrated,
        savePreset,
        deletePreset,
        renamePreset,
        setDefaultPreset,
        getPreset,
    };
};
