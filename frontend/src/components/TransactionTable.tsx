/**
 * Strict Table Design Component for Transactions
 * Uses TanStack Table for data-dense display
 * Features: Resize, Reorder (@dnd-kit), Context Menu (Color/Align), Excel-like grid, Multi-Selection, Drag-to-Select
 */
import React, { useMemo, useState, useCallback, useEffect, CSSProperties, useRef } from 'react';
import {
    useReactTable,
    getCoreRowModel,
    flexRender,
    ColumnDef,
    SortingState,
    ColumnFiltersState,
    ColumnOrderState,
    Header,
    PaginationState,
} from '@tanstack/react-table';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Transaction } from '../services/api';
import { formatDate, formatTime, formatDateTime, EMPTY_VALUE as DATE_EMPTY } from '../utils/dateTimeFormatters';
import { ChevronUp, ChevronDown, Search, FileText, Filter, Eye, Undo2, Redo2, X } from 'lucide-react';
import { ContextMenu } from './ContextMenu';
import { FilterDrawer } from './FilterDrawer';
import { EditableCell, CellType } from './EditableCell';
import { useInlineEdit } from '../hooks/useInlineEdit';
import { useHistory, HistoryAction } from '../hooks/useHistory';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import { useToast } from './Toast';
import { transactionsApi } from '../services/api';
import { useTableViewPresets, type TableViewState } from '../hooks/useTableViewPresets';
import { exportTransactionsToExcel } from '../services/excelExport';

// DnD Imports
import {
    DndContext,
    closestCenter,
    KeyboardSensor,
    PointerSensor,
    useSensor,
    useSensors,
    DragEndEvent,
} from '@dnd-kit/core';
import {
    arrayMove,
    SortableContext,
    sortableKeyboardCoordinates,
    horizontalListSortingStrategy,
    useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';

interface TransactionTableProps {
    data: Transaction[];
    total: number;
    page: number;
    pageSize: number;
    isLoading?: boolean;
    exportViewRows?: Transaction[];
    exportAllRows?: Transaction[];
    highlightRowId?: number | null;
    onAddClick?: () => void;
    onTransactionsUpdated?: (txs: Transaction[]) => void;
    onTransactionsDeleted?: (ids: number[]) => void;
    onTransactionsFieldsUpdated?: (updates: Array<{ id: number; fields: Record<string, any> }>) => void;
    onQueryChange: (query: Partial<{
        search: string;
        filters: ActiveFilters;
        sort_by: string;
        sort_dir: 'asc' | 'desc';
    }>) => void;
    onPageChange: (page: number) => void;
    onPageSizeChange: (size: number) => void;
}

// Types for Styling
type Alignment = 'left' | 'center' | 'right';
interface CellStyle {
    backgroundColor?: string;
    textAlign?: Alignment;
    fontWeight?: 'normal' | 'bold';
}

const ROW_HEIGHT_BY_DENSITY: Record<'compact' | 'standard' | 'comfortable', number> = {
    compact: 28,
    standard: 40,
    comfortable: 52,
};
const VIRTUAL_WARN_THRESHOLD = 2000;
const LOW_CONFIDENCE_THRESHOLD = 0.6;
const LOCKED_COLUMNS = new Set(['row_number', 'day']);
const TABLE_STATE_STORAGE_KEY = 'transactionsTableState:v1';

type ActiveFilters = {
    dateFrom?: string;
    dateTo?: string;
    daysOfWeek?: number[];
    amountMin?: string;
    amountMax?: string;
    currency?: 'UZS' | 'USD';
    transactionTypes?: string[];
    operators?: string[];
    apps?: string[];
    sourceType?: 'ALL' | 'AUTO' | 'MANUAL';
    cardId?: string;
};

// Draggable Header Component
const DraggableTableHeader = ({
    header,
    children,
    onContextMenu,
}: {
    header: Header<Transaction, unknown>;
    children: React.ReactNode;
    onContextMenu: (e: React.MouseEvent) => void;
}) => {
    const {
        attributes,
        listeners,
        setNodeRef,
        transform,
        transition,
        isDragging,
    } = useSortable({
        id: header.column.id,
    });

    const style: React.CSSProperties = {
        transform: CSS.Translate.toString(transform),
        transition,
        width: header.getSize(),
        zIndex: isDragging ? 100 : 'auto',
        opacity: isDragging ? 0.8 : 1,
    };

    return (
        <th
            ref={setNodeRef}
            style={style}
            className={`relative group bg-table-header font-semibold text-foreground border border-table-border select-none ${isDragging ? 'shadow-xl bg-primary-light border-primary z-50' : ''}`}
            onContextMenu={onContextMenu}
        >
            <div
                {...attributes}
                {...listeners}
                className="px-2 py-1 h-full w-full cursor-grab active:cursor-grabbing"
            >
                {children}
            </div>

            <div
                onMouseDown={header.getResizeHandler()}
                onTouchStart={header.getResizeHandler()}
                className={`resizer ${header.column.getIsResizing() ? 'isResizing' : ''}`}
                onPointerDown={(e) => e.stopPropagation()}
            />
        </th>
    );
};


export const TransactionTable: React.FC<TransactionTableProps> = ({
    data,
    total,
    page,
    pageSize,
    isLoading,
    exportViewRows,
    exportAllRows,
    highlightRowId,
    onAddClick,
    onTransactionsUpdated,
    onTransactionsDeleted,
    onTransactionsFieldsUpdated,
    onQueryChange,
    onPageChange,
    onPageSizeChange,
}) => {
    const [sorting, setSorting] = useState<SortingState>([{ id: 'transaction_date', desc: false }]);
    const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
    const [columnOrder, setColumnOrder] = useState<ColumnOrderState>([]);
    const [columnVisibility, setColumnVisibility] = useState<Record<string, boolean>>({});
    const [columnSizing, setColumnSizing] = useState<Record<string, number>>({});

    // Search State
    const [globalFilter, setGlobalFilter] = useState('');
    const [searchValue, setSearchValue] = useState('');
    const [density, setDensity] = useState<'compact' | 'standard' | 'comfortable'>('standard');
    const [viewMenuOpen, setViewMenuOpen] = useState(false);
    const [exportMenuOpen, setExportMenuOpen] = useState(false);
    const [presetName, setPresetName] = useState('');

    // Advanced Filters State
    const [filterDrawerOpen, setFilterDrawerOpen] = useState(false);
    const [activeFilters, setActiveFilters] = useState<ActiveFilters>({ currency: 'UZS' }); // Default to UZS
    const activeFilterCount = Object.keys(activeFilters).filter(k => {
        const v = (activeFilters as any)[k];
        if (k === 'currency') return false; // Don't count currency as active filter
        if (!v) return false;
        if (Array.isArray(v)) return v.length > 0;
        if (k === 'sourceType') return v !== 'ALL';
        return true;
    }).length;

    const appliedDefaultStateRef = React.useRef(false);
    const restoredStateRef = React.useRef(false);
    const loadAttemptedRef = React.useRef(false);
    const saveTimeoutRef = React.useRef<number | null>(null);

    const ensureLockedVisibility = useCallback((visibility: Record<string, boolean>) => {
        const next = { ...visibility };
        LOCKED_COLUMNS.forEach(col => {
            next[col] = true;
        });
        return next;
    }, []);

    // Debounce Search
    useEffect(() => {
        const timeout = setTimeout(() => {
            setGlobalFilter(searchValue);
        }, 300);
        return () => clearTimeout(timeout);
    }, [searchValue]);

    const sortFieldMap = useMemo<Record<string, string>>(() => ({
        date_time: 'transaction_date',
        transaction_date: 'transaction_date',
        amount: 'amount',
        created_at: 'created_at',
        parsing_confidence: 'parsing_confidence',
    }), []);

    useEffect(() => {
        const sortState = sorting[0];
        const backendSort = sortState ? (sortFieldMap[sortState.id] || sortState.id) : undefined;
        onQueryChange({
            search: globalFilter,
            filters: activeFilters,
            sort_by: backendSort,
            sort_dir: sortState?.desc ? 'desc' : 'asc',
        });
    }, [sorting, globalFilter, activeFilters, onQueryChange, sortFieldMap]);

    // Styling State
    const [columnStyles, setColumnStyles] = useState<Record<string, CellStyle>>({});
    const [cellStyles, setCellStyles] = useState<Record<string, CellStyle>>({}); // Key: "rowId:colId"

    // Selection State
    const [selectedCells, setSelectedCells] = useState<Set<string>>(new Set()); // Set of "rowId:colId"
    const [isSelecting, setIsSelecting] = useState(false);
    const [selectionStart, setSelectionStart] = useState<{ rowId: string; colId: string; rowPos: number; colPos: number } | null>(null);
    const [detailRow, setDetailRow] = useState<Transaction | null>(null);

    // Context Menu State
    const [contextMenu, setContextMenu] = useState<{ x: number; y: number; targetIdx: string; type: 'header' | 'cell' } | null>(null);

    // Toast for notifications
    const { showToast } = useToast();

    // Inline Editing Hooks
    const { editingCell, startEdit, cancelEdit, saveEdit: originalSaveEdit, isSaving } = useInlineEdit({
        onSuccess: ({ updated }) => {
            if (updated && onTransactionsUpdated) {
                onTransactionsUpdated([updated]);
            }
        },
    });
    const { presets, defaultPreset, savePreset, deletePreset, renamePreset, setDefaultPreset, getPreset } = useTableViewPresets();

    const captureCurrentViewState = useCallback((): TableViewState => ({
        columnOrder,
        columnSizing,
        columnVisibility: ensureLockedVisibility(columnVisibility),
        density,
        activeFilters,
        globalFilter,
        columnStyles,
        cellStyles,
    }), [activeFilters, cellStyles, columnOrder, columnSizing, columnStyles, columnVisibility, density, ensureLockedVisibility, globalFilter]);

    const applyPresetState = useCallback((state: TableViewState) => {
        setColumnOrder(state.columnOrder || []);
        setColumnVisibility(ensureLockedVisibility(state.columnVisibility || {}));
        setColumnSizing(state.columnSizing || {});
        setDensity(state.density || 'standard');
        setActiveFilters(state.activeFilters || {});
        setSearchValue(state.globalFilter || '');
        setGlobalFilter(state.globalFilter || '');
        setColumnStyles(state.columnStyles || {});
        setCellStyles(state.cellStyles || {});
    }, [ensureLockedVisibility]);

    // History Hook (Undo/Redo)
    const { addAction, undo, redo, canUndo, canRedo } = useHistory({
        maxHistory: 50,
        onUndo: async (action: HistoryAction) => {
            // Handle undo for different action types
            if (action.type === 'EDIT') {
                await originalSaveEdit(action.rowId, action.columnId, action.oldValue);
            } else if (action.type === 'DELETE') {
                showToast('warning', 'Невозможно восстановить удаленную запись');
            } else if (action.type === 'BULK_DELETE') {
                showToast('warning', 'Невозможно восстановить удаленные записи');
            }
        },
        onRedo: async (action: HistoryAction) => {
            // Handle redo for different action types
            if (action.type === 'EDIT') {
                await originalSaveEdit(action.rowId, action.columnId, action.newValue);
            } else if (action.type === 'DELETE') {
                await transactionsApi.deleteTransaction(action.rowId);
                onTransactionsDeleted?.([action.rowId]);
            } else if (action.type === 'BULK_DELETE') {
                const ids = action.rows.map(r => r.rowId);
                await transactionsApi.bulkDeleteTransactions(ids);
                onTransactionsDeleted?.(ids);
            }
        },
    });

    const tableContainerRef = useRef<HTMLDivElement>(null);

    // Wrap saveEdit to track history
    const saveEdit = useCallback(
        async (rowId: number, columnId: string, newValue: any) => {
            const row = data.find(r => r.id === rowId);
            if (!row) return;

            const fieldMap: Record<string, keyof Transaction> = {
                transaction_date: 'transaction_date',
                operator_raw: 'operator_raw',
                application_mapped: 'application_mapped',
                amount: 'amount',
                balance_after: 'balance_after',
                card_last_4: 'card_last_4',
                is_p2p: 'is_p2p',
                transaction_type: 'transaction_type',
                currency: 'currency',
                source_type: 'source_type',
            };

            const field = fieldMap[columnId];
            const oldValue = field ? row[field] : undefined;

            await originalSaveEdit(rowId, columnId, newValue, row);
            addAction({ type: 'EDIT', rowId, columnId, oldValue, newValue });
        },
        [data, originalSaveEdit, addAction]
    );

    const columns = useMemo<ColumnDef<Transaction>[]>(
        () => [
            {
                id: 'row_number',
                header: '№',
                size: 60,
                cell: (info) => <div className="font-mono text-table-xs">{(page - 1) * pageSize + info.row.index + 1}</div>,
            },
            {
                accessorFn: (row) => row.transaction_date ? new Date(row.transaction_date) : null,
                id: 'date_time',
                header: 'Дата и Время',
                size: 140,
                cell: (info) => {
                    const date = info.getValue();
                    return <div className="font-mono text-table-xs">{formatDateTime(date)}</div>;
                },
            },
            {
                accessorFn: (row) => row.transaction_date ? new Date(row.transaction_date) : null,
                id: 'transaction_date',
                header: 'Дата',
                size: 100,
                cell: (info) => {
                    const date = info.getValue();
                    return <div className="font-mono text-table-xs">{formatDate(date)}</div>;
                },
            },
            {
                accessorFn: (row) => row.transaction_date ? new Date(row.transaction_date) : null,
                id: 'time',
                header: 'Время',
                size: 70,
                cell: (info) => {
                    const date = info.getValue();
                    return <div className="font-mono text-table-xs">{formatTime(date)}</div>;
                },
            },
            {
                accessorFn: (row) => row.transaction_date ? new Date(row.transaction_date) : null,
                id: 'day',
                header: 'День',
                size: 50,
                cell: (info) => {
                    const date = info.getValue() as Date | null;
                    if (!date || !(date instanceof Date) || isNaN(date.getTime())) {
                        return <div className="text-table-xs">{DATE_EMPTY}</div>;
                    }
                    const days = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
                    return <div className="text-table-xs">{days[date.getDay()]}</div>;
                },
            },
            {
                accessorKey: 'operator_raw',
                id: 'operator_raw',
                header: 'Оператор/Продавец',
                size: 200,
                cell: (info) => (
                    <div className="truncate text-table-xs" title={info.getValue() as string}>
                        {info.getValue() as string || '—'}
                    </div>
                ),
            },
            {
                accessorKey: 'application_mapped',
                id: 'application_mapped',
                header: 'Приложение',
                size: 120,
                cell: (info) => (
                    <div className="font-medium">
                        {info.getValue() as string || '—'}
                    </div>
                ),
            },
            {
                accessorKey: 'amount',
                id: 'amount',
                header: 'Сумма',
                size: 120,
                cell: (info) => {
                    const amount = parseFloat(info.getValue() as string);
                    if (isNaN(amount)) return <div className="font-mono font-medium">—</div>;

                    return (
                        <div className="font-mono font-medium">
                            {Math.abs(amount).toFixed(2).replace('.', ',')}
                        </div>
                    );
                },
            },
            {
                accessorKey: 'balance_after',
                id: 'balance_after',
                header: 'Остаток',
                size: 120,
                cell: (info) => {
                    const balance = info.getValue() as string | null;
                    if (!balance) return <div className="text-foreground-muted">—</div>;
                    const balanceNum = parseFloat(balance);
                    if (isNaN(balanceNum)) return <div className="text-foreground-muted">—</div>;
                    return (
                        <div className="font-mono text-table-xs">
                            {Math.abs(balanceNum).toFixed(2).replace('.', ',')}
                        </div>
                    );
                },
            },
            {
                accessorKey: 'card_last_4',
                id: 'card_last_4',
                header: 'ПК',
                size: 60,
                cell: (info) => (
                    <div className="font-mono">
                        {info.getValue() as string || '—'}
                    </div>
                ),
            },
            {
                accessorKey: 'is_p2p',
                id: 'is_p2p',
                header: 'П2П',
                size: 50,
                cell: (info) => (
                    <div className="font-mono text-center">
                        {info.getValue() ? '1' : ''}
                    </div>
                ),
            },
            {
                accessorKey: 'transaction_type',
                id: 'transaction_type',
                header: 'Тип',
                size: 80,
                cell: (info) => {
                    const typeMap: Record<string, string> = {
                        DEBIT: 'Списание',
                        CREDIT: 'Пополнение',
                        CONVERSION: 'Конверсия',
                        REVERSAL: 'Отмена',
                    };
                    return <div className="text-table-xs">{typeMap[info.getValue() as string] || String(info.getValue())}</div>;
                },
            },
            {
                accessorKey: 'currency',
                id: 'currency',
                header: 'Валюта',
                size: 60,
                cell: (info) => <div className="font-mono">{info.getValue() as string}</div>,
            },
            {
                accessorKey: 'source_type',
                id: 'source_type',
                header: 'Источник',
                size: 80,
                cell: (info) => {
                    const source = info.getValue() as string;
                    return (
                        <div className="text-table-xs">
                            {source === 'AUTO' ? 'Авто' : 'Ручной'}
                        </div>
                    );
                },
            },
            {
                id: 'details',
                header: '',
                size: 80,
                cell: (info) => (
                    <button
                        className="px-2 py-1 text-xs bg-surface-2 border border-border rounded hover:bg-surface-3 focus:outline-none focus:ring-2 focus:ring-primary"
                        onClick={() => setDetailRow(info.row.original)}
                    >
                        Детали
                    </button>
                ),
            },
        ],
        [page, pageSize]
    );

    // Column Type Mapping for Inline Editing
    const columnTypeMap: Record<string, CellType> = useMemo(() => ({
        date_time: 'datetime',
        transaction_date: 'date',
        time: 'time',
        operator_raw: 'text',
        application_mapped: 'text',
        amount: 'number',
        balance_after: 'number',
        card_last_4: 'text',
        is_p2p: 'checkbox',
        transaction_type: 'select',
        currency: 'select',
        source_type: 'select',
    }), []);

    const columnOptionsMap: Record<string, string[]> = useMemo(() => ({
        transaction_type: ['DEBIT', 'CREDIT', 'CONVERSION', 'REVERSAL'],
        currency: ['UZS', 'USD'],
        source_type: ['AUTO', 'MANUAL'],
    }), []);

    // Initial load column order
    React.useEffect(() => {
        if (columnOrder.length === 0) {
            setColumnOrder(columns.map(c => c.id as string));
        }
    }, [columns, columnOrder.length]);

    // Apply default preset on mount
    React.useEffect(() => {
        if (defaultPreset && !restoredStateRef.current) {
            applyPresetState(defaultPreset.state);
        }
    }, [defaultPreset, applyPresetState]);

    // Restore from localStorage
    React.useEffect(() => {
        if (loadAttemptedRef.current) return;
        loadAttemptedRef.current = true;
        try {
            const raw = localStorage.getItem(TABLE_STATE_STORAGE_KEY);
            if (!raw) return;
            const stored = JSON.parse(raw);
            if (stored.sorting) setSorting(stored.sorting);
            if (stored.columnOrder) setColumnOrder(stored.columnOrder);
            if (stored.columnVisibility) setColumnVisibility(ensureLockedVisibility(stored.columnVisibility));
            if (stored.columnSizing) setColumnSizing(stored.columnSizing);
            if (stored.density) setDensity(stored.density);
            if (stored.globalFilter !== undefined) {
                setGlobalFilter(stored.globalFilter);
                setSearchValue(stored.globalFilter);
            }
            if (stored.activeFilters) {
                const restoredFilters = { currency: 'UZS', ...stored.activeFilters };
                setActiveFilters(restoredFilters);
            }
            if (stored.columnStyles) setColumnStyles(stored.columnStyles);
            if (stored.cellStyles) setCellStyles(stored.cellStyles);
            if (stored.pageSize && stored.pageSize !== pageSize) {
                onPageSizeChange(stored.pageSize);
            }
            if (stored.pageIndex !== undefined) {
                onPageChange((stored.pageIndex || 0) + 1);
            }
            restoredStateRef.current = true;
            appliedDefaultStateRef.current = true;
        } catch (error) {
            console.warn('Failed to restore table state', error);
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Manual Global Filter & Advanced Filters
    const paginationState = useMemo(() => ({ pageIndex: Math.max(page - 1, 0), pageSize }), [page, pageSize]);

    const table = useReactTable({
        data,
        columns,
        state: {
            sorting,
            columnFilters,
            columnOrder,
            columnVisibility,
            columnSizing,
            pagination: paginationState,
        },
        getRowId: (row) => String(row.id),
        manualPagination: true,
        manualSorting: true,
        manualFiltering: true,
        columnResizeMode: 'onChange',
        onSortingChange: setSorting,
        onColumnFiltersChange: setColumnFilters,
        onColumnOrderChange: setColumnOrder,
        onColumnVisibilityChange: setColumnVisibility,
        onColumnSizingChange: setColumnSizing,
        onPaginationChange: (updater) => {
            const next = typeof updater === 'function'
                ? (updater as (old: PaginationState) => PaginationState)(paginationState)
                : updater as PaginationState;

            if (next.pageSize !== pageSize) {
                onPageSizeChange(next.pageSize);
            }
            if (next.pageIndex !== paginationState.pageIndex) {
                onPageChange(next.pageIndex + 1);
            }
        },
        getCoreRowModel: getCoreRowModel(),
        pageCount: Math.max(Math.ceil(total / pageSize), 1),
    });

    const toggleColumnVisibility = useCallback((columnId: string, isVisible: boolean) => {
        if (LOCKED_COLUMNS.has(columnId)) return;
        setColumnVisibility(prev => ensureLockedVisibility({ ...prev, [columnId]: isVisible }));
    }, [ensureLockedVisibility]);

    const hideAllColumns = useCallback(() => {
        const next: Record<string, boolean> = {};
        table.getAllLeafColumns().forEach(col => {
            if (!LOCKED_COLUMNS.has(col.id)) {
                next[col.id] = false;
            }
        });
        setColumnVisibility(prev => ensureLockedVisibility({ ...prev, ...next }));
    }, [table, ensureLockedVisibility]);

    const showAllColumns = useCallback(() => {
        const next: Record<string, boolean> = {};
        table.getAllLeafColumns().forEach(col => {
            if (!LOCKED_COLUMNS.has(col.id)) {
                next[col.id] = true;
            }
        });
        setColumnVisibility(prev => ensureLockedVisibility({ ...prev, ...next }));
    }, [table, ensureLockedVisibility]);

    const handleLoadPreset = useCallback((name: string) => {
        const preset = getPreset(name);
        if (!preset) return;
        applyPresetState(preset.state);
        setViewMenuOpen(false);
    }, [applyPresetState, getPreset]);

    const handleSavePreset = useCallback((markDefault = false) => {
        const name = (presetName || '').trim() || 'Текущий вид';
        savePreset(name, captureCurrentViewState(), markDefault);
        setPresetName('');
        if (markDefault) {
            setViewMenuOpen(false);
        }
    }, [captureCurrentViewState, presetName, savePreset]);

    const handleRenamePreset = useCallback((name: string) => {
        const newName = prompt('Новое имя вида', name);
        if (!newName || !newName.trim()) return;
        renamePreset(name, newName.trim());
    }, [renamePreset]);

    const handleDeletePreset = useCallback((name: string) => {
        if (!confirm(`Удалить вид "${name}"?`)) return;
        deletePreset(name);
    }, [deletePreset]);

    const handleSetDefaultPreset = useCallback((name: string) => {
        setDefaultPreset(name);
    }, [setDefaultPreset]);

    const rowHeight = useMemo(() => ROW_HEIGHT_BY_DENSITY[density] || ROW_HEIGHT_BY_DENSITY.standard, [density]);
    const rows = table.getRowModel().rows;
    const rowCount = rows.length;

    // Clamp/initialize pagination
    React.useEffect(() => {
        const maxPage = Math.max(1, Math.ceil(total / pageSize));
        if (page > maxPage) {
            onPageChange(maxPage);
            return;
        }
        if (!restoredStateRef.current && !appliedDefaultStateRef.current && total > 0) {
            onPageChange(maxPage);
            appliedDefaultStateRef.current = true;
        }
    }, [total, pageSize, page, onPageChange]);

    // Persist state
    React.useEffect(() => {
        if (saveTimeoutRef.current) {
            clearTimeout(saveTimeoutRef.current);
        }
        const stateToSave = {
            sorting,
            pageIndex: Math.max(0, page - 1),
            pageSize,
            columnOrder,
            columnSizing,
            columnVisibility,
            density,
            globalFilter,
            activeFilters: { currency: activeFilters.currency || 'UZS', ...activeFilters },
            columnStyles,
            cellStyles,
        };
        saveTimeoutRef.current = window.setTimeout(() => {
            try {
                localStorage.setItem(TABLE_STATE_STORAGE_KEY, JSON.stringify(stateToSave));
            } catch (error) {
                console.warn('Failed to persist table state', error);
            }
        }, 300);

        return () => {
            if (saveTimeoutRef.current) {
                clearTimeout(saveTimeoutRef.current);
                saveTimeoutRef.current = null;
            }
        };
    }, [sorting, page, pageSize, columnOrder, columnSizing, columnVisibility, density, globalFilter, activeFilters, columnStyles, cellStyles]);

    const rowVirtualizer = useVirtualizer({
        count: rowCount,
        getScrollElement: () => tableContainerRef.current,
        estimateSize: () => rowHeight,
        overscan: 10,
        getItemKey: (index) => rows[index]?.id ?? index,
    });

    const virtualRows = rowVirtualizer.getVirtualItems();
    const totalSize = rowVirtualizer.getTotalSize();
    const paddingTop = virtualRows.length > 0 ? virtualRows[0].start : 0;
    const paddingBottom = virtualRows.length > 0 ? totalSize - virtualRows[virtualRows.length - 1].end : 0;
    const virtualizationActive = virtualRows.length < rowCount;

    const isDev = (import.meta as any)?.env?.DEV ?? false;

    useEffect(() => {
        if (isDev && rowCount > VIRTUAL_WARN_THRESHOLD && !virtualizationActive) {
            console.warn(`[TransactionTable] Rendering ${rowCount} rows without virtualization enabled`);
        }
    }, [rowCount, virtualizationActive, isDev]);

    // DnD Sensors
    const sensors = useSensors(
        useSensor(PointerSensor, {
            activationConstraint: {
                distance: 8,
            },
        }),
        useSensor(KeyboardSensor, {
            coordinateGetter: sortableKeyboardCoordinates,
        })
    );

    function handleDragEnd(event: DragEndEvent) {
        const { active, over } = event;
        if (active && over && active.id !== over.id) {
            setColumnOrder((items) => {
                const oldIndex = items.indexOf(active.id as string);
                const newIndex = items.indexOf(over.id as string);
                return arrayMove(items, oldIndex, newIndex);
            });
        }
    }

    const handleDragOver = (event: DragEndEvent) => {
        const { active, over } = event;
        if (active && over && active.id !== over.id) {
            setColumnOrder((items) => {
                const oldIndex = items.indexOf(active.id as string);
                const newIndex = items.indexOf(over.id as string);
                return arrayMove(items, oldIndex, newIndex);
            });
        }
    };

    // Styling & Selection Logic
    const toggleCellSelection = useCallback((cellId: string, multi: boolean) => {
        setSelectedCells(prev => {
            const newSet = new Set(multi ? prev : []);
            if (newSet.has(cellId)) {
                newSet.delete(cellId);
            } else {
                newSet.add(cellId);
            }
            return newSet;
        });
    }, []);

    // Drag to Select Handlers
    useEffect(() => {
        const handleGlobalMouseUp = () => {
            setIsSelecting(false);
            setSelectionStart(null);
        };
        window.addEventListener('mouseup', handleGlobalMouseUp);
        return () => window.removeEventListener('mouseup', handleGlobalMouseUp);
    }, []);

    const handleCellMouseDown = (e: React.MouseEvent, rowId: string, colId: string, rowPos: number, colPos: number) => {
        // Left click only
        if (e.button !== 0) return;

        // If Ctrl is pressed, handled by click event for toggle
        if (e.ctrlKey || e.metaKey) return;

        setIsSelecting(true);
        setSelectionStart({ rowId, colId, rowPos, colPos });
        setSelectedCells(new Set([`${rowId}:${colId}`]));
    };

    const handleCellMouseEnter = (rowPos: number, colPos: number) => {
        if (!isSelecting || !selectionStart) return;

        const startRow = Math.min(selectionStart.rowPos, rowPos);
        const endRow = Math.max(selectionStart.rowPos, rowPos);

        const startColIdx = Math.min(selectionStart.colPos, colPos);
        const endColIdx = Math.max(selectionStart.colPos, colPos);

        // Get visible columns based on current order
        const visibleColumns = table.getVisibleLeafColumns();

        // Calculate all cells in box
        const newSelection = new Set<string>();
        const rowList = rows;

        for (let r = startRow; r <= endRow; r++) {
            const row = rowList[r];
            if (!row) continue;
            for (let c = startColIdx; c <= endColIdx; c++) {
                const col = visibleColumns[c];
                if (col) {
                    newSelection.add(`${row.id}:${col.id}`);
                }
            }
        }
        setSelectedCells(newSelection);
    };


    const handleHeaderContextMenu = (e: React.MouseEvent, columnId: string) => {
        e.preventDefault();
        setContextMenu({ x: e.clientX, y: e.clientY, targetIdx: columnId, type: 'header' });
    };

    const handleHideColumn = useCallback((columnId: string) => {
        if (LOCKED_COLUMNS.has(columnId)) return;
        setColumnVisibility(prev => ensureLockedVisibility({ ...prev, [columnId]: false }));
    }, [ensureLockedVisibility]);

    const handleCellContextMenu = (e: React.MouseEvent, cellId: string) => {
        e.preventDefault();
        // If the right-clicked cell isn't selected, select it (and clear others if not multi)
        if (!selectedCells.has(cellId)) {
            toggleCellSelection(cellId, false);
        }
        setContextMenu({ x: e.clientX, y: e.clientY, targetIdx: cellId, type: 'cell' });
    };

    const handleCellClick = (e: React.MouseEvent, cellId: string) => {
        const isMulti = e.ctrlKey || e.metaKey;
        if (isMulti) {
            toggleCellSelection(cellId, true);
        }
        // Single click logic is handled by MouseDown basically (clears and sets one),
        // but Click ensures we toggle if Ctrl is held.
        // For non-Ctrl click, mouse down already set exact cell.
    };

    const handleAlign = (alignment: Alignment) => {
        if (!contextMenu) return;

        if (contextMenu.type === 'header') {
            const colId = contextMenu.targetIdx;
            setColumnStyles(prev => ({
                ...prev,
                [colId]: { ...prev[colId], textAlign: alignment }
            }));
        } else {
            // Apply to ALL selected cells
            const newStyles = { ...cellStyles };
            selectedCells.forEach(cellId => {
                newStyles[cellId] = { ...newStyles[cellId], textAlign: alignment };
            });
            setCellStyles(newStyles);
        }
        setContextMenu(null);
    };

    const handleColor = (color: string) => {
        if (!contextMenu) return;

        if (contextMenu.type === 'header') {
            const colId = contextMenu.targetIdx;
            setColumnStyles(prev => ({
                ...prev,
                [colId]: { ...prev[colId], backgroundColor: color }
            }));
        } else {
            // Apply to ALL selected cells
            const newStyles = { ...cellStyles };
            selectedCells.forEach(cellId => {
                newStyles[cellId] = { ...newStyles[cellId], backgroundColor: color };
            });
            setCellStyles(newStyles);
        }
        setContextMenu(null);
    };

    // Copy/Paste/Delete Handlers
    const fieldMap: Record<string, string> = useMemo(() => ({
        date_time: 'transaction_date',
        transaction_date: 'transaction_date',
        time: 'transaction_date',
        operator_raw: 'operator_raw',
        application_mapped: 'application_mapped',
        amount: 'amount',
        balance_after: 'balance_after',
        card_last_4: 'card_last_4',
        is_p2p: 'is_p2p',
        transaction_type: 'transaction_type',
        currency: 'currency',
        source_type: 'source_type',
    }), []);

    const handleCopy = useCallback(() => {
        if (selectedCells.size === 0) return;

        // Sort cells by row and column
        const cellsArray = Array.from(selectedCells);
        const cellsData: { rowIndex: number; colIndex: number; value: any }[] = [];

        cellsArray.forEach(cellKey => {
            const [rowId, colId] = cellKey.split(':');
            const row = data.find(r => String(r.id) === rowId);
            if (!row) return;

            const rowIndex = data.indexOf(row);
            const colIndex = table.getVisibleLeafColumns().findIndex(c => c.id === colId);

            const field = fieldMap[colId] || colId;
            const value = (row as any)[field];

            cellsData.push({ rowIndex, colIndex, value });
        });

        // Sort by row then column
        cellsData.sort((a, b) => a.rowIndex - b.rowIndex || a.colIndex - b.colIndex);

        // Group by rows
        const rows = new Map<number, any[]>();
        cellsData.forEach(cell => {
            if (!rows.has(cell.rowIndex)) {
                rows.set(cell.rowIndex, []);
            }
            rows.get(cell.rowIndex)!.push(cell.value);
        });

        // Convert to TSV
        const tsv = Array.from(rows.values())
            .map(row => row.map(v => String(v ?? '')).join('\t'))
            .join('\n');

        navigator.clipboard.writeText(tsv).then(
            () => showToast('success', 'Скопировано в буфер обмена'),
            () => showToast('error', 'Не удалось скопировать')
        );
    }, [selectedCells, data, table, showToast, fieldMap]);

    const handlePaste = useCallback(async () => {
        if (selectedCells.size === 0) return;

        try {
            const text = await navigator.clipboard.readText();
            const rows = text.split('\n').map(row => row.split('\t'));

            // Find anchor cell (first selected)
            const firstCell = Array.from(selectedCells)[0];
            const [anchorRowId, anchorColId] = firstCell.split(':');
            const anchorRow = data.find(r => String(r.id) === anchorRowId);
            if (!anchorRow) return;

            const anchorRowIndex = data.indexOf(anchorRow);
            const anchorColIndex = table.getVisibleLeafColumns().findIndex(c => c.id === anchorColId);

            const updates: Record<number, Record<string, any>> = {};

            for (let i = 0; i < rows.length; i++) {
                const targetRowIndex = anchorRowIndex + i;
                if (targetRowIndex >= data.length) break;

                const targetRow = data[targetRowIndex];

                for (let j = 0; j < rows[i].length; j++) {
                    const targetColIndex = anchorColIndex + j;
                    const columns = table.getVisibleLeafColumns();
                    if (targetColIndex >= columns.length) break;

                    const targetCol = columns[targetColIndex];
                    if (targetCol.id === 'row_number' || targetCol.id === 'day') continue;

                    const newValue = rows[i][j];
                    const field = fieldMap[targetCol.id] || targetCol.id;
                    const oldValue = (targetRow as any)[field];

                    if (newValue !== String(oldValue)) {
                        if (!updates[targetRow.id]) updates[targetRow.id] = {};
                        updates[targetRow.id][field] = newValue;
                    }
                }
            }

            const payload = {
                updates: Object.entries(updates).map(([id, fields]) => ({
                    id: Number(id),
                    fields,
                })),
            };

            if (payload.updates.length === 0) return;

            await transactionsApi.bulkUpdateTransactions(payload);
            addAction({ type: 'PASTE', cells: [] });
            onTransactionsFieldsUpdated?.(payload.updates);
            showToast('success', `Вставлено ${payload.updates.length} строк`);
        } catch (error) {
            showToast('error', 'Не удалось вставить из буфера обмена');
        }
    }, [selectedCells, data, table, addAction, showToast, fieldMap, onTransactionsFieldsUpdated]);

    const handleDeleteSelected = useCallback(async () => {
        if (selectedCells.size === 0) return;

        // Extract unique row IDs
        const rowIds = new Set<number>();
        selectedCells.forEach(cellKey => {
            const [rowId] = cellKey.split(':');
            rowIds.add(Number(rowId));
        });

        const idsArray = Array.from(rowIds);

        if (!confirm(`Удалить ${idsArray.length} записей?`)) return;

        try {
            await transactionsApi.bulkDeleteTransactions(idsArray);

            // Track for history
            const deletedRows = idsArray.map(id => {
                const row = data.find(r => r.id === id);
                return { rowId: id, rowData: row };
            });
            addAction({ type: 'BULK_DELETE', rows: deletedRows });
            onTransactionsDeleted?.(idsArray);

            setSelectedCells(new Set());
            showToast('success', `Удалено ${idsArray.length} записей`);
        } catch (error) {
            showToast('error', 'Ошибка при удалении');
        }
    }, [selectedCells, data, addAction, showToast, onTransactionsDeleted]);

    // Keyboard Shortcuts
    useKeyboardShortcuts({
        shortcuts: [
            { key: 'z', ctrl: true, handler: () => undo(), description: 'Отменить' },
            { key: 'y', ctrl: true, handler: () => redo(), description: 'Повторить' },
            { key: 'Delete', handler: () => handleDeleteSelected(), description: 'Удалить' },
            { key: 'Backspace', handler: () => handleDeleteSelected(), description: 'Удалить' },
            { key: 'c', ctrl: true, handler: () => handleCopy(), description: 'Копировать' },
            { key: 'v', ctrl: true, handler: () => handlePaste(), description: 'Вставить' },
            { key: 'Escape', handler: () => {
                if (editingCell) cancelEdit();
            }, description: 'Отмена редактирования' },
        ],
        enabled: true,
    });

    const buildExportColumns = useCallback(() => {
        const columnsToExport = table.getVisibleLeafColumns().filter(col => col.id !== 'details');
        return columnsToExport.map((column) => {
            const header = column.columnDef.header;
            return {
                id: column.id,
                header: typeof header === 'string' ? header : column.id,
                widthPx: columnSizing[column.id] || column.getSize(),
                textAlign: (columnStyles[column.id]?.textAlign as Alignment) || undefined,
            };
        });
    }, [table, columnSizing, columnStyles]);

    const exportCurrentView = useCallback(() => {
        const rowsToUse = exportViewRows || table.getPrePaginationRowModel().rows.map(r => r.original);
        if (!rowsToUse.length) {
            alert('Нет данных для экспорта.');
            return;
        }
        exportTransactionsToExcel({
            rows: rowsToUse,
            columns: buildExportColumns(),
            columnStyles: columnStyles as any,
            cellStyles: cellStyles as any,
            fileName: `transactions_view_${new Date().toISOString().slice(0, 10)}.xlsx`,
            includeAlternating: true,
        });
    }, [exportViewRows, table, columnStyles, cellStyles, buildExportColumns]);

    const exportAll = useCallback(() => {
        const rowsToUse = exportAllRows || exportViewRows || table.getPrePaginationRowModel().rows.map(r => r.original);
        if (!rowsToUse.length) {
            alert('Нет данных для экспорта.');
            return;
        }
        exportTransactionsToExcel({
            rows: rowsToUse,
            columns: buildExportColumns(),
            columnStyles: columnStyles as any,
            cellStyles: cellStyles as any,
            fileName: `transactions_all_${new Date().toISOString().slice(0, 10)}.xlsx`,
            includeAlternating: true,
        });
    }, [exportAllRows, exportViewRows, table, columnStyles, cellStyles, buildExportColumns]);

    if (isLoading) {
        return (
            <div className="flex items-center justify-center py-12">
                <div className="text-foreground-secondary">Загрузка данных...</div>
            </div>
        );
    }

    return (
        <div className="flex flex-col h-full space-y-4 p-4" onClick={() => {
            // Optional: click background to clear selection?
        }}>
            {contextMenu && (
                <ContextMenu
                    x={contextMenu.x}
                    y={contextMenu.y}
                    onClose={() => setContextMenu(null)}
                    onAlign={handleAlign}
                    onColor={handleColor}
                    onHideColumn={contextMenu.type === 'header' && !LOCKED_COLUMNS.has(contextMenu.targetIdx)
                        ? () => handleHideColumn(contextMenu.targetIdx)
                        : undefined}
                />
            )}

            {/* Currency Tabs */}
            <div className="flex space-x-1 bg-surface-2 p-1 rounded-lg w-fit mb-4">
                <button
                    onClick={() => setActiveFilters({ ...activeFilters, currency: 'UZS' })}
                    className={`px-4 py-2 text-sm font-medium rounded-md transition-all focus:outline-none focus:ring-2 focus:ring-primary ${activeFilters.currency === 'UZS'
                        ? 'bg-surface text-foreground shadow-sm'
                        : 'text-foreground-secondary hover:text-foreground'
                        }`}
                >
                    Основной (UZS)
                </button>
                <button
                    onClick={() => setActiveFilters({ ...activeFilters, currency: 'USD' })}
                    className={`px-4 py-2 text-sm font-medium rounded-md transition-all focus:outline-none focus:ring-2 focus:ring-primary ${activeFilters.currency === 'USD'
                        ? 'bg-surface text-foreground shadow-sm'
                        : 'text-foreground-secondary hover:text-foreground'
                        }`}
                >
                    Валютный (USD)
                </button>
            </div>

            {/* Smart Search Bar */}
            <div className="relative mb-4">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <Search className="h-5 w-5 text-foreground-muted" />
                </div>
                <input
                    type="text"
                    value={searchValue}
                    onChange={(e) => setSearchValue(e.target.value)}
                    className="block w-full pl-10 pr-3 py-2 border border-border rounded-md leading-5 bg-surface placeholder-text-muted text-foreground focus:outline-none focus:placeholder-text-secondary focus:ring-1 focus:ring-primary focus:border-primary sm:text-sm transition duration-150 ease-in-out shadow-sm"
                    placeholder="Поиск по всем колонкам (сумма, продавец, дата)..."
                />
            </div>

            {/* Toolbar */}
            <div className="flex items-center gap-2 mb-4">
                <div className="relative">
                    <button
                        onClick={() => setExportMenuOpen(prev => !prev)}
                        className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-foreground bg-surface border border-border rounded hover:bg-surface-2 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary"
                    >
                        <FileText className="w-4 h-4" />
                        Экспорт
                    </button>
                    {exportMenuOpen && (
                        <div className="absolute top-full left-0 mt-1 w-52 bg-surface border border-border rounded-md shadow-lg z-50">
                            <button
                                onClick={() => { exportCurrentView(); setExportMenuOpen(false); }}
                                className="w-full text-left px-3 py-2 text-sm hover:bg-surface-2"
                            >
                                Экспорт текущего вида
                            </button>
                            <button
                                onClick={() => { exportAll(); setExportMenuOpen(false); }}
                                className="w-full text-left px-3 py-2 text-sm hover:bg-surface-2"
                            >
                                Экспорт всех транзакций
                            </button>
                        </div>
                    )}
                </div>
                <button
                    onClick={onAddClick}
                    className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-foreground bg-primary text-white border border-primary rounded hover:bg-primary-dark focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary"
                >
                    Добавить
                </button>
                <button
                    onClick={() => setFilterDrawerOpen(true)}
                    className={`flex items-center gap-2 px-3 py-1.5 text-sm font-medium border rounded hover:bg-surface-2 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary ${activeFilterCount > 0 ? 'bg-primary-light text-primary border-primary/30' : 'text-foreground bg-surface border-border'}`}
                >
                    <Filter className="w-4 h-4" />
                    Фильтры
                    {activeFilterCount > 0 && (
                        <span className="flex items-center justify-center w-5 h-5 ml-1 text-xs font-bold text-foreground-inverse bg-primary rounded-full">
                            {activeFilterCount}
                        </span>
                    )}
                </button>
                <div className="relative">
                    <button
                        onClick={() => setViewMenuOpen(!viewMenuOpen)}
                        className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-foreground bg-surface border border-border rounded hover:bg-surface-2 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary"
                    >
                        <Eye className="w-4 h-4" />
                        Вид
                    </button>
                    {viewMenuOpen && (
                        <div className="absolute top-full left-0 mt-1 w-96 bg-surface border border-border rounded-md shadow-lg z-50">
                            <div className="p-2 border-b border-border">
                                <div className="text-xs font-semibold text-foreground-muted mb-2 px-2">Столбцы</div>
                                <div className="flex items-center gap-2 px-2 mb-2">
                                    <button
                                        className="px-2 py-1 text-xs border border-border rounded hover:bg-surface-2"
                                        onClick={showAllColumns}
                                    >
                                        Показать все
                                    </button>
                                    <button
                                        className="px-2 py-1 text-xs border border-border rounded hover:bg-surface-2"
                                        onClick={hideAllColumns}
                                    >
                                        Скрыть все
                                    </button>
                                </div>
                                <div className="max-h-44 overflow-auto px-2 space-y-1 pb-1">
                                    {table.getAllLeafColumns().map((col) => {
                                        const label = typeof col.columnDef.header === 'string'
                                            ? col.columnDef.header
                                            : (col.id === 'details' ? 'Детали' : col.id);
                                        const disabled = LOCKED_COLUMNS.has(col.id);
                                        return (
                                            <label key={col.id} className="flex items-center gap-2 text-sm text-foreground">
                                                <input
                                                    type="checkbox"
                                                    checked={col.getIsVisible()}
                                                    disabled={disabled}
                                                    onChange={(e) => toggleColumnVisibility(col.id, e.target.checked)}
                                                />
                                                <span className={disabled ? 'text-foreground-muted' : ''}>{label}</span>
                                            </label>
                                        );
                                    })}
                                </div>
                            </div>
                            <div className="p-2 border-b border-border">
                                <div className="text-xs font-semibold text-foreground-muted mb-2 px-2">Плотность строк</div>
                                <button
                                    onClick={() => { setDensity('compact'); setViewMenuOpen(false); }}
                                    className={`w-full text-left px-2 py-1 text-sm rounded focus:outline-none focus:ring-2 focus:ring-primary ${density === 'compact' ? 'bg-primary-light text-primary' : 'hover:bg-surface-2'}`}
                                >
                                    Компактный
                                </button>
                                <button
                                    onClick={() => { setDensity('standard'); setViewMenuOpen(false); }}
                                    className={`w-full text-left px-2 py-1 text-sm rounded focus:outline-none focus:ring-2 focus:ring-primary ${density === 'standard' ? 'bg-primary-light text-primary' : 'hover:bg-surface-2'}`}
                                >
                                    Средний
                                </button>
                                <button
                                    onClick={() => { setDensity('comfortable'); setViewMenuOpen(false); }}
                                    className={`w-full text-left px-2 py-1 text-sm rounded focus:outline-none focus:ring-2 focus:ring-primary ${density === 'comfortable' ? 'bg-primary-light text-primary' : 'hover:bg-surface-2'}`}
                                >
                                    Крупный
                                </button>
                            </div>
                            <div className="p-2 border-b border-border">
                                <div className="text-xs font-semibold text-foreground-muted mb-2 px-2">Сохраненные виды</div>
                                <div className="flex items-center gap-2 px-2 mb-2">
                                    <input
                                        type="text"
                                        value={presetName}
                                        onChange={(e) => setPresetName(e.target.value)}
                                        placeholder="Название вида"
                                        className="flex-1 px-2 py-1 text-sm border border-border rounded bg-surface"
                                    />
                                    <button
                                        className="px-2 py-1 text-xs border border-border rounded hover:bg-surface-2"
                                        onClick={() => handleSavePreset(false)}
                                    >
                                        Сохранить
                                    </button>
                                    <button
                                        className="px-2 py-1 text-xs border border-border rounded hover:bg-surface-2"
                                        onClick={() => handleSavePreset(true)}
                                    >
                                        Сохранить и по умолчанию
                                    </button>
                                </div>
                                <div className="max-h-48 overflow-auto flex flex-col gap-2 px-2">
                                    {presets.length === 0 ? (
                                        <div className="text-xs text-foreground-muted px-1">Пока нет сохраненных видов</div>
                                    ) : (
                                        presets.map((preset) => (
                                            <div key={preset.name} className="flex items-center justify-between gap-2 px-2 py-1 rounded hover:bg-surface-2 border border-transparent hover:border-border">
                                                <div className="flex flex-col">
                                                    <span className="text-sm font-medium text-foreground">{preset.name}</span>
                                                    {preset.isDefault && <span className="text-[11px] text-primary">По умолчанию</span>}
                                                </div>
                                                <div className="flex items-center gap-1">
                                                    <button
                                                        className="px-2 py-1 text-xs border border-border rounded hover:bg-surface-3"
                                                        onClick={() => handleLoadPreset(preset.name)}
                                                    >
                                                        Загрузить
                                                    </button>
                                                    <button
                                                        className="px-2 py-1 text-xs border border-border rounded hover:bg-surface-3"
                                                        onClick={() => handleRenamePreset(preset.name)}
                                                    >
                                                        Имя
                                                    </button>
                                                    <button
                                                        className={`px-2 py-1 text-xs border rounded ${preset.isDefault ? 'border-primary text-primary' : 'border-border hover:bg-surface-3'}`}
                                                        onClick={() => handleSetDefaultPreset(preset.name)}
                                                    >
                                                        По умолчанию
                                                    </button>
                                                    <button
                                                        className="px-2 py-1 text-xs border border-border rounded hover:bg-danger-light text-danger"
                                                        onClick={() => handleDeletePreset(preset.name)}
                                                    >
                                                        Удалить
                                                    </button>
                                                </div>
                                            </div>
                                        ))
                                    )}
                                </div>
                            </div>
                            <div className="p-2">
                                <button
                                    onClick={() => {
                                        setColumnFilters([]);
                                        setGlobalFilter('');
                                        setSearchValue('');
                                        setSorting([]);
                                        setActiveFilters({});
                                        setViewMenuOpen(false);
                                    }}
                                    className="w-full text-left px-2 py-1 text-sm text-danger rounded hover:bg-danger-light"
                                >
                                    Сбросить все фильтры
                                </button>
                            </div>
                        </div>
                    )}
                </div>

                {/* Undo/Redo Buttons */}
                <div className="flex items-center gap-1 ml-2 border-l pl-2 border-border">
                    <button
                        onClick={() => undo()}
                        disabled={!canUndo}
                        className="flex items-center gap-1 px-2 py-1.5 text-sm font-medium text-foreground bg-surface border border-border rounded hover:bg-surface-2 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary disabled:opacity-50 disabled:cursor-not-allowed"
                        title="Отменить (Ctrl+Z)"
                    >
                        <Undo2 className="w-4 h-4" />
                    </button>
                    <button
                        onClick={() => redo()}
                        disabled={!canRedo}
                        className="flex items-center gap-1 px-2 py-1.5 text-sm font-medium text-foreground bg-surface border border-border rounded hover:bg-surface-2 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary disabled:opacity-50 disabled:cursor-not-allowed"
                        title="Повторить (Ctrl+Y)"
                    >
                        <Redo2 className="w-4 h-4" />
                    </button>
                </div>

                {/* Saving Indicator */}
                {isSaving && (
                    <div className="flex items-center gap-2 ml-auto text-sm text-foreground-secondary">
                        <div className="animate-spin h-4 w-4 border-2 border-primary border-t-transparent rounded-full"></div>
                        <span>Сохранение...</span>
                    </div>
                )}
            </div>

            <FilterDrawer
                isOpen={filterDrawerOpen}
                onClose={() => setFilterDrawerOpen(false)}
                onApply={(filters) => setActiveFilters(filters)}
                initialFilters={activeFilters}
            />

            <DndContext
                collisionDetection={closestCenter}
                modifiers={[]}
                onDragOver={handleDragOver}
                onDragEnd={handleDragEnd}
                sensors={sensors}
            >
                <div
                    className="flex-1 overflow-auto border border-table-border bg-surface shadow-sm"
                    ref={tableContainerRef}
                >
                    <table className="strict-table w-full relative" style={{ minWidth: table.getTotalSize() }}>
                        <thead className="sticky top-0 z-10 bg-table-header shadow-sm">
                            {table.getHeaderGroups().map((headerGroup) => (
                                <tr key={headerGroup.id}>
                                    <SortableContext
                                        items={columnOrder}
                                        strategy={horizontalListSortingStrategy}
                                    >
                                        {headerGroup.headers.map((header) => (
                                            <DraggableTableHeader
                                                key={header.id}
                                                header={header}
                                                onContextMenu={(e) => handleHeaderContextMenu(e, header.column.id)}
                                            >
                                                <div
                                                    className={`flex items-center gap-1 ${header.column.getCanSort() ? 'cursor-pointer hover:text-foreground' : ''}`}
                                                    onClick={header.column.getToggleSortingHandler()}
                                                >
                                                    {flexRender(header.column.columnDef.header, header.getContext())}
                                                    {header.column.getIsSorted() ? (
                                                        header.column.getIsSorted() === 'asc' ? (
                                                            <ChevronUp className="w-3 h-3" />
                                                        ) : (
                                                            <ChevronDown className="w-3 h-3" />
                                                        )
                                                    ) : null}
                                                </div>
                                            </DraggableTableHeader>
                                        ))}
                                    </SortableContext>
                                </tr>
                            ))}
                        </thead>
                        <tbody style={{ position: 'relative' }}>
                            {paddingTop > 0 && (
                                <tr style={{ height: `${paddingTop}px` }}>
                                    <td colSpan={table.getVisibleLeafColumns().length} />
                                </tr>
                            )}
                            {virtualRows.map((virtualRow) => {
                                const row = rows[virtualRow.index];
                                if (!row) return null;
                                const rowData = row.original;
                                const lowConf = (rowData.parsing_confidence ?? 1) < LOW_CONFIDENCE_THRESHOLD;
                                const highlighted = highlightRowId && Number(row.id) === highlightRowId;
                                const rowClass = `${lowConf ? 'bg-amber-50/60' : ''} ${highlighted ? 'ring-2 ring-primary/70' : ''}`;

                                return (
                                    <tr
                                        key={row.id}
                                        data-index={virtualRow.index}
                                        ref={rowVirtualizer.measureElement}
                                        style={{ height: `${virtualRow.size}px` }}
                                        className={rowClass}
                                    >
                                        {row.getVisibleCells().map((cell) => {
                                            const cellKey = `${row.id}:${cell.column.id}`;
                                            const isSelected = selectedCells.has(cellKey);

                                            // Use index from list of visible columns to ensure drag selection works with reorder
                                            const colIndex = table.getVisibleLeafColumns().findIndex(c => c.id === cell.column.id);

                                            // Style Resolution: Cell Style > Column Style > Default
                                            const colStyle = columnStyles[cell.column.id] || {};
                                            const cStyle = cellStyles[cellKey] || {};

                                            const finalStyle: CSSProperties = {
                                                width: cell.column.getSize(),
                                                textAlign: cStyle.textAlign || colStyle.textAlign || 'left',
                                                backgroundColor: cStyle.backgroundColor || colStyle.backgroundColor || undefined,
                                            };

                                            const densityClasses = {
                                                compact: '!py-0.5',
                                                standard: '!py-2',
                                                comfortable: '!py-4',
                                            };

                                            const isDetailsCell = cell.column.id === 'details';

                                            return (
                                                <td
                                                    key={cell.id}
                                                    style={finalStyle}
                                                    className={`cursor-default select-none border border-table-border px-2 text-table-text ${densityClasses[density]} ${isSelected ? 'ring-2 ring-inset ring-primary z-10 bg-table-row-selected' : ''}`}
                                                    onClick={(e) => handleCellClick(e, cellKey)}
                                                    onMouseDown={(e) => handleCellMouseDown(e, row.id, cell.column.id, virtualRow.index, colIndex)}
                                                    onMouseEnter={() => handleCellMouseEnter(virtualRow.index, colIndex)}
                                                    onContextMenu={(e) => handleCellContextMenu(e, cellKey)}
                                                >
                                                    {isDetailsCell ? (
                                                        <button
                                                            className="px-2 py-1 text-xs bg-surface-2 border border-border rounded hover:bg-surface-3 focus:outline-none focus:ring-2 focus:ring-primary w-full"
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                setDetailRow(row.original);
                                                            }}
                                                        >
                                                            Детали
                                                        </button>
                                                    ) : cell.column.id === 'row_number' || cell.column.id === 'day' ? (
                                                        flexRender(cell.column.columnDef.cell, cell.getContext())
                                                    ) : (
                                                        <EditableCell
                                                            value={cell.getValue()}
                                                            rowId={Number(row.id)}
                                                            columnId={cell.column.id}
                                                            cellType={columnTypeMap[cell.column.id] || 'text'}
                                                            options={columnOptionsMap[cell.column.id]}
                                                            onSave={saveEdit}
                                                            onCancel={cancelEdit}
                                                            isEditing={editingCell?.rowId === Number(row.id) && editingCell?.columnId === cell.column.id}
                                                            onStartEdit={() => startEdit(Number(row.id), cell.column.id)}
                                                        />
                                                    )}
                                                </td>
                                            );
                                        })}
                                    </tr>
                                );
                            })}
                            {paddingBottom > 0 && (
                                <tr style={{ height: `${paddingBottom}px` }}>
                                    <td colSpan={table.getVisibleLeafColumns().length} />
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </DndContext>

            {/* Pagination */}
            <div className="flex items-center justify-between text-sm text-foreground-secondary px-1">
                <div>
                    Rows: {rowCount}
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => table.previousPage()}
                        disabled={!table.getCanPreviousPage()}
                        className="px-3 py-1 border border-border rounded disabled:opacity-50 disabled:cursor-not-allowed hover:bg-surface-2 bg-surface text-foreground"
                    >
                        ← Prev
                    </button>
                    <span>
                        Page {table.getState().pagination.pageIndex + 1} of {' '}
                        {table.getPageCount()}
                    </span>
                    <button
                        onClick={() => table.nextPage()}
                        disabled={!table.getCanNextPage()}
                        className="px-3 py-1 border border-border rounded disabled:opacity-50 disabled:cursor-not-allowed hover:bg-surface-2 bg-surface text-foreground"
                    >
                        Next →
                    </button>
                </div>
            </div>

            {/* Details Drawer */}
            {detailRow && (
                <div className="fixed inset-0 z-50 flex justify-end">
                    <div className="absolute inset-0 bg-black/30" onClick={() => setDetailRow(null)} />
                    <div className="relative w-full max-w-4xl h-full bg-surface shadow-xl border-l border-border overflow-y-auto">
                        <div className="flex items-center justify-between p-4 border-b border-border">
                            <div>
                                <div className="text-lg font-semibold text-foreground">Детали транзакции #{detailRow.id}</div>
                                <div className="text-xs text-foreground-secondary">Метод: {detailRow.parsing_method || '—'} · Уверенность: {detailRow.parsing_confidence !== null && detailRow.parsing_confidence !== undefined ? `${Math.round(detailRow.parsing_confidence * 100)}%` : '—'}</div>
                            </div>
                            <button
                                className="p-2 rounded-full hover:bg-surface-2 border border-border text-foreground-secondary"
                                onClick={() => setDetailRow(null)}
                            >
                                <X className="w-4 h-4" />
                            </button>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4">
                            <div className="space-y-2">
                                <div className="text-sm font-medium text-foreground">Исходный текст</div>
                                <div className="border border-border rounded-md bg-surface-2 p-3 text-sm text-foreground max-h-[300px] overflow-auto whitespace-pre-wrap">
                                    {detailRow.raw_message || '—'}
                                </div>
                            </div>
                            <div className="space-y-2">
                                <div className="text-sm font-medium text-foreground">Распарсенные поля</div>
                                <div className="border border-border rounded-md bg-surface-2 p-3 text-sm text-foreground space-y-2">
                                    {[
                                        { label: 'Дата', value: formatDateTime(new Date(detailRow.transaction_date)) },
                                        { label: 'Сумма', value: detailRow.amount },
                                        { label: 'Валюта', value: detailRow.currency },
                                        { label: 'Оператор', value: detailRow.operator_raw || '—' },
                                        { label: 'Приложение', value: detailRow.application_mapped || '—' },
                                        { label: 'Тип', value: detailRow.transaction_type },
                                        { label: 'Карта', value: detailRow.card_last_4 || '—' },
                                        { label: 'Источник', value: detailRow.source_type },
                                        { label: 'Остаток', value: detailRow.balance_after || '—' },
                                    ].map((item) => (
                                        <div key={item.label} className="flex justify-between gap-4">
                                            <span className="text-foreground-muted">{item.label}</span>
                                            <span className="font-mono text-right">{item.value}</span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};
