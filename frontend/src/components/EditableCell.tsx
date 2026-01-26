import React, { useState, useEffect, useRef, KeyboardEvent, useMemo } from 'react';
import { formatDate, formatTime, formatDateTime, EMPTY_VALUE } from '../utils/dateTimeFormatters';

// Type mappings for different columns
export type CellType = 'text' | 'number' | 'date' | 'time' | 'datetime' | 'select' | 'checkbox';
export type SelectOption = string | { value: string; label: string };

export interface EditableCellProps {
    value: any;
    displayValue?: any;
    rowId: number;
    columnId: string;
    cellType: CellType;
    options?: SelectOption[]; // For select type
    onSave: (rowId: number, columnId: string, newValue: any) => Promise<void>;
    onCancel: () => void;
    isEditing: boolean;
    onStartEdit: () => void;
}

export const EditableCell: React.FC<EditableCellProps> = ({
    value,
    displayValue,
    rowId,
    columnId,
    cellType,
    options = [],
    onSave,
    onCancel,
    isEditing,
    onStartEdit,
}) => {
    const [editValue, setEditValue] = useState(value);
    const [isSaving, setIsSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const inputRef = useRef<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(null);

    const normalizedOptions = useMemo(
        () => (options || []).map(opt => typeof opt === 'string' ? { value: opt, label: opt } : opt),
        [options]
    );

    useEffect(() => {
        if (isEditing && inputRef.current) {
            inputRef.current.focus();
            if (inputRef.current instanceof HTMLInputElement || inputRef.current instanceof HTMLTextAreaElement) {
                inputRef.current.select();
            }
        }
    }, [isEditing]);

    const toDateString = (val: any) => {
        if (val instanceof Date && !isNaN(val.getTime())) {
            const y = val.getFullYear();
            const m = String(val.getMonth() + 1).padStart(2, '0');
            const d = String(val.getDate()).padStart(2, '0');
            return `${y}-${m}-${d}`;
        }
        if (typeof val === 'string') return val;
        return '';
    };

    const toTimeString = (val: any) => {
        if (val instanceof Date && !isNaN(val.getTime())) {
            const hh = String(val.getHours()).padStart(2, '0');
            const mm = String(val.getMinutes()).padStart(2, '0');
            return `${hh}:${mm}`;
        }
        if (typeof val === 'string') return val;
        return '';
    };

    const toDateTimeString = (val: any) => {
        if (val instanceof Date && !isNaN(val.getTime())) {
            const y = val.getFullYear();
            const m = String(val.getMonth() + 1).padStart(2, '0');
            const d = String(val.getDate()).padStart(2, '0');
            const hh = String(val.getHours()).padStart(2, '0');
            const mm = String(val.getMinutes()).padStart(2, '0');
            return `${y}-${m}-${d}T${hh}:${mm}`;
        }
        if (typeof val === 'string') return val;
        return '';
    };

    useEffect(() => {
        if (cellType === 'date') {
            setEditValue(toDateString(value));
        } else if (cellType === 'time') {
            setEditValue(toTimeString(value));
        } else if (cellType === 'datetime') {
            setEditValue(toDateTimeString(value));
        } else {
            setEditValue(value);
        }
    }, [value, cellType]);

    const handleSave = async () => {
        if (editValue === value) {
            onCancel();
            return;
        }

        setIsSaving(true);
        setError(null);

        try {
            let payload = editValue;
            if (cellType === 'date') {
                payload = toDateString(editValue);
            } else if (cellType === 'time') {
                payload = toTimeString(editValue);
            } else if (cellType === 'datetime') {
                payload = toDateTimeString(editValue);
            }
            await onSave(rowId, columnId, payload);
            onCancel(); // Exit edit mode
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Save failed');
            // Keep editing mode open on error
        } finally {
            setIsSaving(false);
        }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSave();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            setEditValue(value); // Reset
            onCancel();
        }
    };

    const formatDisplayValue = (val: any): string => {
        if (val === null || val === undefined) return EMPTY_VALUE;

        // Handle Date objects
        if (val instanceof Date) {
            if (isNaN(val.getTime())) return EMPTY_VALUE;
            
            if (cellType === 'datetime') {
                return formatDateTime(val);
            }
            if (cellType === 'time') {
                return formatTime(val);
            }
            // Default to date format for Date objects
            return formatDate(val);
        }

        // Handle date strings
        if ((cellType === 'date' || cellType === 'datetime') && typeof val === 'string') {
            try {
                const date = new Date(val);
                if (!isNaN(date.getTime())) {
                    return cellType === 'datetime' ? formatDateTime(date) : formatDate(date);
                }
            } catch {}
            return EMPTY_VALUE;
        }

        // Handle time strings
        if (cellType === 'time' && typeof val === 'string') {
            // If it's a full date string, extract time
            try {
                const date = new Date(val);
                if (!isNaN(date.getTime())) {
                    return formatTime(date);
                }
            } catch {}
            // Return the value as-is if it's already in HH:MM format
            return val;
        }

        // Handle booleans - display "1" instead of checkmark
        if (typeof val === 'boolean') {
            return val ? '1' : '';
        }

        // Handle numbers - always show absolute value (no minus sign)
        if (cellType === 'number') {
            const num = typeof val === 'number' ? val : parseFloat(String(val));
            if (!isNaN(num)) {
                return Math.abs(num).toFixed(2).replace('.', ',');
            }
            return EMPTY_VALUE;
        }

        // Select labels
        if (cellType === 'select' && normalizedOptions.length) {
            const match = normalizedOptions.find(opt => opt.value === val);
            if (match) return match.label;
        }

        // Convert to string
        return String(val);
    };

    const renderInput = () => {
        const baseClass = `w-full px-2 py-1 border-2 rounded outline-none text-sm bg-editable-cell-bg text-editable-cell-text ${
            error ? 'border-editable-cell-border-error' : 'border-editable-cell-border'
        } ${isSaving ? 'opacity-50' : ''}`;

        switch (cellType) {
            case 'text':
                return (
                    <input
                        ref={inputRef as React.RefObject<HTMLInputElement>}
                        type="text"
                        value={editValue || ''}
                        onChange={(e) => setEditValue(e.target.value)}
                        onBlur={handleSave}
                        onKeyDown={handleKeyDown}
                        className={baseClass}
                        disabled={isSaving}
                    />
                );

            case 'number':
                return (
                    <input
                        ref={inputRef as React.RefObject<HTMLInputElement>}
                        type="number"
                        step="0.01"
                        value={editValue || ''}
                        onChange={(e) => setEditValue(e.target.value)}
                        onBlur={handleSave}
                        onKeyDown={handleKeyDown}
                        className={baseClass}
                        disabled={isSaving}
                    />
                );

            case 'date':
                return (
                    <input
                        ref={inputRef as React.RefObject<HTMLInputElement>}
                        type="date"
                        value={toDateString(editValue)}
                        onChange={(e) => setEditValue(e.target.value)}
                        onBlur={handleSave}
                        onKeyDown={handleKeyDown}
                        className={baseClass}
                        disabled={isSaving}
                    />
                );

            case 'time':
                return (
                    <input
                        ref={inputRef as React.RefObject<HTMLInputElement>}
                        type="time"
                        value={toTimeString(editValue)}
                        onChange={(e) => setEditValue(e.target.value)}
                        onBlur={handleSave}
                        onKeyDown={handleKeyDown}
                        className={baseClass}
                        disabled={isSaving}
                    />
                );

            case 'datetime':
                return (
                    <input
                        ref={inputRef as React.RefObject<HTMLInputElement>}
                        type="datetime-local"
                        value={toDateTimeString(editValue)}
                        onChange={(e) => setEditValue(e.target.value)}
                        onBlur={handleSave}
                        onKeyDown={handleKeyDown}
                        className={baseClass}
                        disabled={isSaving}
                    />
                );

            case 'select':
                return (
                    <select
                        ref={inputRef as React.RefObject<HTMLSelectElement>}
                        value={editValue || ''}
                        onChange={(e) => setEditValue(e.target.value)}
                        onBlur={handleSave}
                        onKeyDown={handleKeyDown}
                        className={baseClass}
                        disabled={isSaving}
                    >
                        {normalizedOptions.map((opt) => (
                            <option key={opt.value} value={opt.value}>
                                {opt.label}
                            </option>
                        ))}
                    </select>
                );

            case 'checkbox':
                return (
                    <input
                        ref={inputRef as React.RefObject<HTMLInputElement>}
                        type="checkbox"
                        checked={Boolean(editValue)}
                        onChange={(e) => {
                            setEditValue(e.target.checked);
                            // Auto-save checkbox immediately
                            setTimeout(() => handleSave(), 50);
                        }}
                        className="w-4 h-4"
                        disabled={isSaving}
                    />
                );

            default:
                return null;
        }
    };

    const renderedValue = displayValue !== undefined ? displayValue : value;

    if (!isEditing) {
        return (
            <div
                className="w-full h-full cursor-text hover:bg-editable-cell-hover px-2 py-1 text-editable-cell-text"
                onDoubleClick={onStartEdit}
                title="Double-click to edit"
            >
                {formatDisplayValue(renderedValue)}
            </div>
        );
    }

    return (
        <div className="relative w-full">
            {renderInput()}
            {isSaving && (
                <div className="absolute top-0 right-0 mt-1 mr-1">
                    <div className="w-3 h-3 border-2 border-primary border-t-transparent rounded-full animate-spin"></div>
                </div>
            )}
            {error && (
                <div className="absolute top-full left-0 mt-1 text-xs text-danger bg-danger-light px-2 py-1 rounded shadow-md z-50 whitespace-nowrap">
                    {error}
                </div>
            )}
        </div>
    );
};
