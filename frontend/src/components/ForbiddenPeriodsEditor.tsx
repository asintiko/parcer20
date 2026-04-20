import React from 'react';

export type ForbiddenPeriod = { from: string; to: string };

interface ForbiddenPeriodsEditorProps {
    value: ForbiddenPeriod[];
    onChange: (periods: ForbiddenPeriod[]) => void;
}

export const ForbiddenPeriodsEditor: React.FC<ForbiddenPeriodsEditorProps> = ({ value, onChange }) => {
    const updateRow = (index: number, patch: Partial<ForbiddenPeriod>) => {
        const next = [...value];
        next[index] = { ...next[index], ...patch };
        onChange(next);
    };

    const removeRow = (index: number) => {
        onChange(value.filter((_, i) => i !== index));
    };

    return (
        <div className="space-y-2">
            {(value || []).map((row, index) => (
                <div key={`${row.from}-${row.to}-${index}`} className="grid grid-cols-1 md:grid-cols-3 gap-2">
                    <input
                        value={row.from || ''}
                        onChange={(e) => updateRow(index, { from: e.target.value })}
                        placeholder="from (YYYY-MM-DD)"
                        className="px-3 py-2 border border-border rounded-md bg-input-bg text-input-text"
                    />
                    <input
                        value={row.to || ''}
                        onChange={(e) => updateRow(index, { to: e.target.value })}
                        placeholder="to (YYYY-MM-DD)"
                        className="px-3 py-2 border border-border rounded-md bg-input-bg text-input-text"
                    />
                    <button
                        type="button"
                        onClick={() => removeRow(index)}
                        className="px-3 py-2 rounded-md border border-danger/40 text-danger hover:bg-danger/10"
                    >
                        Удалить
                    </button>
                </div>
            ))}
            <button
                type="button"
                onClick={() => onChange([...(value || []), { from: '', to: '' }])}
                className="px-3 py-2 rounded-md border border-border bg-surface hover:bg-surface-2"
            >
                Добавить период
            </button>
        </div>
    );
};
