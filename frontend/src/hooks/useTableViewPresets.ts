import { useEffect, useMemo, useState } from 'react';

export type TableViewState = {
    columnOrder: string[];
    columnSizing: Record<string, number>;
    columnVisibility: Record<string, boolean>;
    density: 'compact' | 'standard' | 'comfortable';
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

const STORAGE_KEY = 'transactionTablePresets';

const loadFromStorage = (): TableViewPreset[] => {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return [];
        return parsed;
    } catch {
        return [];
    }
};

const persist = (presets: TableViewPreset[]) => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(presets));
};

export const useTableViewPresets = () => {
    const [presets, setPresets] = useState<TableViewPreset[]>(() => loadFromStorage());

    useEffect(() => {
        persist(presets);
    }, [presets]);

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
        savePreset,
        deletePreset,
        renamePreset,
        setDefaultPreset,
        getPreset,
    };
};
