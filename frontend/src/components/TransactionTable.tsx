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
    type ColumnPinningState,
} from '@tanstack/react-table';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Transaction } from '../services/api';
import { formatDate, formatTime, formatDateTime, EMPTY_VALUE as DATE_EMPTY } from '../utils/dateTimeFormatters';
import { ChevronUp, ChevronDown, Search, FileText, Filter, Eye, Undo2, Redo2, Trash2 } from 'lucide-react';
import { ContextMenu } from './ContextMenu';
import { FilterDrawer } from './FilterDrawer';
import { Sheet } from './motion/Sheet';
import { Dialog } from './motion/Dialog';
import { ConfirmDialog } from './motion/ConfirmDialog';
import { EditableCell, CellType, SelectOption } from './EditableCell';
import { EmptyState } from './ui';
import { useInlineEdit } from '../hooks/useInlineEdit';
import { useHistory, HistoryAction } from '../hooks/useHistory';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import { useToast } from './Toast';
import { transactionsApi } from '../services/api';
import { useTableViewPresets, type TableViewState } from '../hooks/useTableViewPresets';
import { exportTransactionsToExcel } from '../services/excelExport';
import { formatAmount } from '../utils/formatAmount';
import { OverflowTooltip } from './OverflowTooltip';

// DnD Imports
import {
    DndContext,
    closestCenter,
    KeyboardSensor,
    PointerSensor,
    useSensor,
    useSensors,
    DragEndEvent,
    DragOverEvent,
} from '@dnd-kit/core';
import {
    arrayMove,
    SortableContext,
    sortableKeyboardCoordinates,
    horizontalListSortingStrategy,
    useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';

type TableDensity = 'ultra-compact' | 'compact' | 'standard' | 'comfortable';

const describeDeleteError = (errors?: string[]): string => {
    const first = errors?.find(Boolean) ?? '';
    const text = first.toLowerCase();
    if (text.includes('locked period')) return 'период заблокирован';
    if (text.includes('outside current scope')) return 'вне доступного периода';
    if (text.includes('forbidden for current user')) return 'дата запрещена для пользователя';
    if (text.includes('not found')) return 'запись не найдена';
    return first;
};

interface TransactionTableProps {
    data: Transaction[];
    total: number;
    page: number;
    pageSize: number;
    stateScopeKey: string;
    resetViewStateToken?: number;
    selectedYear: number | null;
    availableYears: number[];
    onYearChange: (year: number | null) => void;
    serverModeActive?: boolean;
    scrollToLastRowToken?: number;
    isLoading?: boolean;
    exportViewRows?: Transaction[];
    exportAllRows?: Transaction[];
    onServerExportAll?: (columns?: string[]) => Promise<void> | void;
    onServerExportByPeriod?: (dateFrom: string, dateTo: string, columns?: string[]) => Promise<void> | void;
    highlightRowId?: number | null;
    highlightRowIds?: number[] | null;
    focusColumnId?: string | null;
    focusColumnToken?: number;
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
    operatorOptions?: string[];
    appOptions?: string[];
    telegramSourceOptions?: Array<{ chat_id: number; title: string; chat_type?: 'bot' | 'group' | 'supergroup' | 'channel' | 'private' | null; count: number }>;
    syncState?: {
        isSyncing?: boolean;
        progress?: { downloaded?: number; total?: number; status?: string };
        lastSyncAt?: number | null;
        isOfflineReady?: boolean;
        onSync?: () => void;
        freshness?: {
            serverLatestTransactionAt?: number | null;
            serverOldestTransactionAt?: number | null;
            localLatestTransactionAt?: number | null;
            desktopLagging?: boolean;
        };
    };
}

// Types for Styling
type Alignment = 'left' | 'center' | 'right';
interface CellStyle {
    backgroundColor?: string;
    textAlign?: Alignment;
    fontWeight?: 'normal' | 'bold';
}

const VALID_DENSITIES: TableDensity[] = ['ultra-compact', 'compact', 'standard', 'comfortable'];
const DEFAULT_TABLE_DENSITY: TableDensity = 'compact';
const DEFAULT_PINNED_COUNT: 0 | 1 | 2 | 3 = 3;
const MIN_PERSISTED_COLUMN_WIDTH = 20;
const MAX_PERSISTED_COLUMN_WIDTH = 6000;
const ROW_HEIGHT_BY_DENSITY: Record<TableDensity, number> = {
    'ultra-compact': 22,
    compact: 28,
    standard: 40,
    comfortable: 52,
};
const LOW_CONFIDENCE_THRESHOLD = 0.6;
const LOCKED_COLUMNS = new Set(['row_number']);
const TABLE_STATE_STORAGE_VERSION = 'transactionsTableState:v6';
const OPERATION_NUMBER_COLUMN_ID = 'operation_number';
const OPERATION_NUMBER_ANCHOR_ID = 'row_number';
const DEFAULT_SORTING_STATE: SortingState = [{ id: 'transaction_date', desc: false }];
const DEFAULT_ACTIVE_FILTERS: ActiveFilters = { currency: 'ALL' };
const DEFAULT_COLUMN_ORDER: string[] = [
    'row_number',
    'operation_number',
    'date_time',
    'transaction_date',
    'time',
    'day',
    'operator_raw',
    'application_mapped',
    'description',
    'receiver_name',
    'receiver_card',
    'amount',
    'balance_after',
    'card_last_4',
    'is_p2p',
    'transaction_type',
    'currency',
    'source_type',
];
const AVAILABLE_COLUMN_IDS = new Set(DEFAULT_COLUMN_ORDER);
const TRANSACTION_TYPE_LABELS: Record<string, string> = {
    DEBIT: 'Списание',
    CREDIT: 'Пополнение',
    CONVERSION: 'Конверсия',
    REVERSAL: 'Отмена',
};
const SOURCE_CHANNEL_LABELS: Record<string, string> = {
    TELEGRAM: 'Телеграм',
    SMS: 'СМС',
    MANUAL: 'Ручной',
};

const resolveTransactionTypeDisplay = (tx: Transaction) =>
    tx.transaction_type_display || TRANSACTION_TYPE_LABELS[tx.transaction_type] || tx.transaction_type;

const resolveSourceDisplay = (tx: Transaction) => {
    if (tx.source_chat_title) return tx.source_chat_title;
    if (tx.source_display) return tx.source_display;
    if (tx.source_channel && SOURCE_CHANNEL_LABELS[tx.source_channel]) return SOURCE_CHANNEL_LABELS[tx.source_channel];
    if (tx.source_type === 'MANUAL') return SOURCE_CHANNEL_LABELS.MANUAL;
    return SOURCE_CHANNEL_LABELS.SMS;
};

const buildDefaultColumnVisibility = (): Record<string, boolean> => {
    const next: Record<string, boolean> = {};
    LOCKED_COLUMNS.forEach((col) => {
        next[col] = true;
    });
    next[OPERATION_NUMBER_COLUMN_ID] = true;
    return next;
};

const buildDefaultSortingState = (): SortingState => DEFAULT_SORTING_STATE.map((item) => ({ ...item }));
const buildDefaultColumnOrder = (): ColumnOrderState => [...DEFAULT_COLUMN_ORDER];
const buildDefaultActiveFilters = (): ActiveFilters => ({ ...DEFAULT_ACTIVE_FILTERS });

type ActiveFilters = {
    dateFrom?: string;
    dateTo?: string;
    daysOfWeek?: number[];
    amountMin?: string;
    amountMax?: string;
    currency?: 'ALL' | 'UZS' | 'USD';
    transactionTypes?: string[];
    operators?: string[];
    apps?: string[];
    sourceType?: 'ALL' | 'TELEGRAM' | 'SMS' | 'MANUAL';
    telegramSourceIds?: number[];
    cardId?: string;
    parsingMethod?: string;
    confidenceMin?: number;
    confidenceMax?: number;
};

// Draggable Header Component
const DraggableTableHeader = ({
    header,
    children,
    onContextMenu,
    paddingClass,
    pinnedStyle,
}: {
    header: Header<Transaction, unknown>;
    children: React.ReactNode;
    onContextMenu: (e: React.MouseEvent) => void;
    paddingClass: string;
    pinnedStyle?: CSSProperties;
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
        transform: isDragging && transform ? CSS.Translate.toString(transform) : undefined,
        transition,
        width: header.getSize(),
        minWidth: typeof header.column.columnDef.minSize === 'number' ? header.column.columnDef.minSize : undefined,
        maxWidth: typeof header.column.columnDef.maxSize === 'number' ? header.column.columnDef.maxSize : undefined,
        zIndex: isDragging ? 100 : 'auto',
        opacity: isDragging ? 0.8 : 1,
        ...(pinnedStyle || {}),
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
                className={`${paddingClass} h-full w-full min-w-0 cursor-grab active:cursor-grabbing truncate`}
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
    stateScopeKey,
    resetViewStateToken,
    selectedYear,
    availableYears,
    onYearChange,
    serverModeActive = false,
    scrollToLastRowToken = 0,
    isLoading,
    exportViewRows,
    exportAllRows,
    onServerExportAll,
    onServerExportByPeriod,
    highlightRowId,
    highlightRowIds,
    focusColumnId,
    focusColumnToken,
    onAddClick,
    onTransactionsUpdated,
    onTransactionsDeleted,
    onTransactionsFieldsUpdated,
    onQueryChange,
    onPageChange,
    onPageSizeChange,
    operatorOptions = [],
    appOptions = [],
    telegramSourceOptions = [],
    syncState,
}) => {
    const [sorting, setSorting] = useState<SortingState>(() => buildDefaultSortingState());
    const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
    const [columnOrder, setColumnOrder] = useState<ColumnOrderState>(() => buildDefaultColumnOrder());
    const [columnVisibility, setColumnVisibility] = useState<Record<string, boolean>>(() => buildDefaultColumnVisibility());
    const [columnSizing, setColumnSizing] = useState<Record<string, number>>({});

    // Search State
    const [globalFilter, setGlobalFilter] = useState('');
    const [searchValue, setSearchValue] = useState('');
    const [searchHelpOpen, setSearchHelpOpen] = useState(false);
    const [density, setDensity] = useState<TableDensity>(DEFAULT_TABLE_DENSITY);
    const [pinnedCount, setPinnedCount] = useState<0 | 1 | 2 | 3>(DEFAULT_PINNED_COUNT);
    const [serverExportPending, setServerExportPending] = useState(false);
    const [viewMenuOpen, setViewMenuOpen] = useState(false);
    const [exportMenuOpen, setExportMenuOpen] = useState(false);
    const [exportPeriodOpen, setExportPeriodOpen] = useState(false);
    const [exportDateFrom, setExportDateFrom] = useState('');
    const [exportDateTo, setExportDateTo] = useState('');
    const [presetName, setPresetName] = useState('');
    const [highlightedColumnId, setHighlightedColumnId] = useState<string | null>(null);

    // Advanced Filters State
    const [filterDrawerOpen, setFilterDrawerOpen] = useState(false);
    const [confirmDeleteRows, setConfirmDeleteRows] = useState<number[] | null>(null);
    const [confirmDeletePresetName, setConfirmDeletePresetName] = useState<string | null>(null);
    const [renamePresetTarget, setRenamePresetTarget] = useState<string | null>(null);
    const [renamePresetValue, setRenamePresetValue] = useState('');
    const [activeFilters, setActiveFilters] = useState<ActiveFilters>(() => buildDefaultActiveFilters());
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
    const hydrationSettledRef = React.useRef(false);
    const lastResetTokenRef = React.useRef<number | undefined>(resetViewStateToken);
    const saveTimeoutRef = React.useRef<number | null>(null);
    const searchHelpRef = useRef<HTMLDivElement | null>(null);
    const exportMenuRef = useRef<HTMLDivElement | null>(null);
    const viewMenuRef = useRef<HTMLDivElement | null>(null);
    const normalizedHighlightRowIds = useMemo(
        () =>
            Array.from(
                new Set(
                    [highlightRowId, ...(highlightRowIds || [])]
                        .map((value) => Number(value))
                        .filter((value) => Number.isFinite(value) && value > 0),
                ),
            ),
        [highlightRowId, highlightRowIds],
    );
    const tableStateStorageKey = useMemo(
        () => `${TABLE_STATE_STORAGE_VERSION}:${stateScopeKey}`,
        [stateScopeKey],
    );

    const ensureLockedVisibility = useCallback((visibility: Record<string, boolean>) => {
        const next = { ...buildDefaultColumnVisibility(), ...visibility };
        return next;
    }, []);

    useEffect(() => {
        if (!focusColumnId || !focusColumnToken || !AVAILABLE_COLUMN_IDS.has(focusColumnId)) return;
        setColumnVisibility((prev) => ensureLockedVisibility({ ...prev, [focusColumnId]: true }));
        setHighlightedColumnId(focusColumnId);
        const timer = window.setTimeout(() => setHighlightedColumnId((current) => (current === focusColumnId ? null : current)), 3500);
        return () => window.clearTimeout(timer);
    }, [ensureLockedVisibility, focusColumnId, focusColumnToken]);

    // Debounce Search
    useEffect(() => {
        const timeout = setTimeout(() => {
            setGlobalFilter(searchValue);
        }, 300);
        return () => clearTimeout(timeout);
    }, [searchValue]);

    // Close popovers on outside click
    useEffect(() => {
        const handler = (e: MouseEvent) => {
            const target = e.target as Node;
            if (searchHelpOpen && searchHelpRef.current && !searchHelpRef.current.contains(target)) {
                setSearchHelpOpen(false);
            }
            if (exportMenuOpen && exportMenuRef.current && !exportMenuRef.current.contains(target)) {
                setExportMenuOpen(false);
                setExportPeriodOpen(false);
            }
            if (viewMenuOpen && viewMenuRef.current && !viewMenuRef.current.contains(target)) {
                setViewMenuOpen(false);
            }
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, [searchHelpOpen, exportMenuOpen, viewMenuOpen]);

    const sortFieldMap = useMemo<Record<string, string>>(() => ({
        operation_number: 'transaction_date',
        date_time: 'transaction_date',
        transaction_date: 'transaction_date',
        time: 'transaction_date',
        day: 'transaction_date',
        amount: 'amount',
        balance_after: 'balance_after',
        operator_raw: 'operator_raw',
        application_mapped: 'application_mapped',
        receiver_name: 'receiver_name',
        receiver_card: 'receiver_card',
        card_last_4: 'card_last_4',
        is_p2p: 'is_p2p',
        transaction_type: 'transaction_type',
        currency: 'currency',
        source_type: 'source_type',
        created_at: 'created_at',
        parsing_confidence: 'parsing_confidence',
        updated_at: 'updated_at',
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
    const [detailRawMessage, setDetailRawMessage] = useState<string | null>(null);
    const [detailRawLoading, setDetailRawLoading] = useState(false);

    // Context Menu State
    const [contextMenu, setContextMenu] = useState<{ x: number; y: number; targetIdx: string; type: 'header' | 'cell' } | null>(null);

    useEffect(() => {
        if (!detailRow) {
            setDetailRawMessage(null);
            setDetailRawLoading(false);
            return;
        }
        if (detailRow.raw_message) {
            setDetailRawMessage(detailRow.raw_message);
            setDetailRawLoading(false);
            return;
        }

        let cancelled = false;
        setDetailRawLoading(true);
        transactionsApi
            .getTransaction(detailRow.id)
            .then((fullRow) => {
                if (cancelled) return;
                setDetailRawMessage(fullRow.raw_message || null);
            })
            .catch(() => {
                if (cancelled) return;
                setDetailRawMessage(null);
            })
            .finally(() => {
                if (cancelled) return;
                setDetailRawLoading(false);
            });

        return () => {
            cancelled = true;
        };
    }, [detailRow]);

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
    const { presets, defaultPreset, isHydrated: presetsHydrated, savePreset, deletePreset, renamePreset, setDefaultPreset, getPreset } = useTableViewPresets(stateScopeKey);

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
    const temporaryExpandedColumnRef = useRef<{ columnId: string; previousSize: number } | null>(null);
    const textMeasureCanvasRef = useRef<HTMLCanvasElement | null>(null);
    const pendingScrollModeRef = useRef<'top' | 'bottom' | null>(null);
    const lastAppliedScrollTokenRef = useRef<number>(0);

    const scrollViewport = useCallback((mode: 'top' | 'bottom') => {
        if (!tableContainerRef.current) return;
        tableContainerRef.current.scrollTop = mode === 'bottom' ? tableContainerRef.current.scrollHeight : 0;
    }, []);

    // Wrap saveEdit to track history
    const saveEdit = useCallback(
        async (rowId: number, columnId: string, newValue: any) => {
            const row = data.find(r => r.id === rowId);
            if (!row) return;

            const fieldMap: Record<string, keyof Transaction> = {
                date_time: 'transaction_date',
                transaction_date: 'transaction_date',
                time: 'transaction_date',
                operator_raw: 'operator_raw',
                application_mapped: 'application_mapped',
                description: 'description',
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
                enableSorting: false,
                cell: (info) => {
                    const rowNumber = Math.max(0, (page - 1) * pageSize) + info.row.index + 1;
                    return <div className="font-mono text-table-xs">{rowNumber}</div>;
                },
            },
            {
                accessorFn: (row) => row.transaction_date ? new Date(row.transaction_date) : null,
                id: 'operation_number',
                header: '№ опер.',
                size: 78,
                minSize: 58,
                cell: (info) => {
                    const start = Math.max(0, (page - 1) * pageSize);
                    const sortId = sorting[0]?.id;
                    const isDateLinkedSort = ['operation_number', 'date_time', 'transaction_date', 'time', 'day'].includes(sortId || '');
                    const isDescending = Boolean(sorting[0]?.desc);
                    let operationNumber: number;
                    if (isDateLinkedSort) {
                        // Always chronological: oldest = 1, newest = total. Independent of sort direction.
                        operationNumber = isDescending
                            ? Math.max(total - start - info.row.index, 0)
                            : start + info.row.index + 1;
                    } else {
                        // Other column sorted — fall back to row position.
                        operationNumber = start + info.row.index + 1;
                    }
                    return <div className="font-mono text-table-xs">{operationNumber}</div>;
                },
            },
            {
                accessorFn: (row) => row.transaction_date ? new Date(row.transaction_date) : null,
                id: 'date_time',
                header: () => <div className="min-w-0 truncate">Дата и Время</div>,
                size: 115,
                minSize: 20,
                cell: (info) => {
                    const date = info.getValue();
                    return <div className="font-mono text-table-xs">{formatDateTime(date)}</div>;
                },
            },
            {
                accessorFn: (row) => row.transaction_date ? new Date(row.transaction_date) : null,
                id: 'transaction_date',
                header: 'Дата',
                size: 120,
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
                header: () => <div className="min-w-0 truncate">Оператор/Продавец</div>,
                size: 140,
                minSize: 20,
                cell: (info) => {
                    const operatorText = (info.getValue() as string | null)?.trim() || '';
                    if (!operatorText) {
                        return <div className="min-w-0 w-full truncate text-table-xs">—</div>;
                    }
                    return (
                        <OverflowTooltip text={operatorText} className="block min-w-0 w-full truncate text-table-xs">
                            {operatorText}
                        </OverflowTooltip>
                    );
                },
            },
            {
                accessorKey: 'application_mapped',
                id: 'application_mapped',
                header: () => <div className="min-w-0 truncate">Приложение</div>,
                size: 120,
                minSize: 20,
                cell: (info) => {
                    const value = (info.getValue() as string | null)?.trim() || '';
                    if (!value) return <div className="min-w-0 w-full truncate text-table-xs">—</div>;
                    return (
                        <OverflowTooltip text={value} className="block min-w-0 w-full truncate font-medium text-table-xs">
                            {value}
                        </OverflowTooltip>
                    );
                },
            },
            {
                accessorKey: 'description',
                id: 'description',
                header: 'Описание',
                size: 180,
                minSize: 20,
                cell: (info) => {
                    const value = (info.getValue() as string | null)?.trim() || '';
                    if (!value) return <div className="min-w-0 w-full truncate text-table-xs">—</div>;
                    return (
                        <OverflowTooltip text={value} className="block min-w-0 w-full truncate text-table-xs">
                            {value}
                        </OverflowTooltip>
                    );
                },
            },
            {
                accessorKey: 'receiver_name',
                id: 'receiver_name',
                header: () => <div className="min-w-0 truncate">Получатель</div>,
                size: 150,
                minSize: 20,
                cell: (info) => {
                    const value = (info.getValue() as string | null)?.trim() || '';
                    if (!value) return <div className="min-w-0 w-full truncate text-table-xs">—</div>;
                    return (
                        <OverflowTooltip text={value} className="block min-w-0 w-full truncate text-table-xs">
                            {value}
                        </OverflowTooltip>
                    );
                },
            },
            {
                accessorKey: 'receiver_card',
                id: 'receiver_card',
                header: () => <div className="min-w-0 truncate">Карта получателя</div>,
                size: 120,
                minSize: 20,
                cell: (info) => {
                    const value = (info.getValue() as string | null)?.trim() || '';
                    if (!value) return <div className="min-w-0 w-full truncate font-mono text-table-xs">—</div>;
                    return (
                        <OverflowTooltip text={value} className="block min-w-0 w-full truncate font-mono text-table-xs">
                            {value}
                        </OverflowTooltip>
                    );
                },
            },
            {
                accessorKey: 'amount',
                id: 'amount',
                header: 'Сумма',
                size: 100,
                minSize: 30,
                cell: (info) => {
                    const amount = parseFloat(info.getValue() as string);
                    if (isNaN(amount)) return <div className="font-mono font-medium">—</div>;
                    const formattedAmount = formatAmount(amount);

                    return (
                        <OverflowTooltip text={formattedAmount} className="block min-w-0 w-full truncate font-mono font-medium text-table-xs">
                            {formattedAmount}
                        </OverflowTooltip>
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
                    const formattedBalance = formatAmount(balanceNum);
                    return (
                        <OverflowTooltip text={formattedBalance} className="block min-w-0 w-full truncate font-mono text-table-xs">
                            {formattedBalance}
                        </OverflowTooltip>
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
                header: () => <div className="min-w-0 truncate">Тип</div>,
                size: 80,
                minSize: 20,
                cell: (info) => {
                    const value = resolveTransactionTypeDisplay(info.row.original) || '—';
                    if (value === '—') return <div className="min-w-0 w-full truncate text-table-xs">—</div>;
                    return (
                        <OverflowTooltip text={value} className="block min-w-0 w-full truncate text-table-xs">
                            {value}
                        </OverflowTooltip>
                    );
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
                header: () => <div className="min-w-0 truncate">Источник</div>,
                size: 80,
                minSize: 20,
                cell: (info) => {
                    const value = resolveSourceDisplay(info.row.original) || '—';
                    if (value === '—') return <div className="min-w-0 w-full truncate text-table-xs">—</div>;
                    return (
                        <OverflowTooltip text={value} className="block min-w-0 w-full truncate text-table-xs">
                            {value}
                        </OverflowTooltip>
                    );
                },
            },
        ],
        [page, pageSize, sorting, total]
    );

    // Column Type Mapping for Inline Editing
    const columnTypeMap: Record<string, CellType> = useMemo(() => ({
        date_time: 'datetime',
        transaction_date: 'date',
        time: 'time',
        operator_raw: 'text',
        application_mapped: 'text',
        description: 'text',
        receiver_name: 'text',
        receiver_card: 'text',
        amount: 'number',
        balance_after: 'number',
        card_last_4: 'text',
        is_p2p: 'checkbox',
        transaction_type: 'select',
        currency: 'select',
        source_type: 'select',
    }), []);

    const columnOptionsMap: Record<string, SelectOption[]> = useMemo(() => ({
        transaction_type: [
            { value: 'DEBIT', label: 'Списание' },
            { value: 'CREDIT', label: 'Пополнение' },
            { value: 'CONVERSION', label: 'Конверсия' },
            { value: 'REVERSAL', label: 'Отмена' },
        ],
        currency: ['UZS', 'USD'],
        source_type: [
            { value: 'AUTO', label: 'Авто' },
            { value: 'SMS', label: 'СМС' },
            { value: 'MANUAL', label: 'Ручной' },
        ],
    }), []);

    const ensureColumnOrderComplete = useCallback((order: string[]) => {
        const filtered = order.filter((id) => AVAILABLE_COLUMN_IDS.has(id));
        const normalized = [...filtered];
        if (!normalized.includes(OPERATION_NUMBER_COLUMN_ID)) {
            const anchorIndex = normalized.indexOf(OPERATION_NUMBER_ANCHOR_ID);
            if (anchorIndex >= 0) {
                normalized.splice(anchorIndex + 1, 0, OPERATION_NUMBER_COLUMN_ID);
            } else {
                normalized.unshift(OPERATION_NUMBER_COLUMN_ID);
            }
        }
        const missing = DEFAULT_COLUMN_ORDER.filter((id) => !normalized.includes(id));
        return [...normalized, ...missing];
    }, []);

    const normalizeDensity = useCallback((value: unknown): TableDensity => {
        return VALID_DENSITIES.includes(value as TableDensity)
            ? value as TableDensity
            : DEFAULT_TABLE_DENSITY;
    }, []);

    const normalizePinnedCount = useCallback((value: unknown): 0 | 1 | 2 | 3 => {
        const nextPinned = Number(value);
        if (Number.isFinite(nextPinned) && nextPinned >= 0 && nextPinned <= 3) {
            return nextPinned as 0 | 1 | 2 | 3;
        }
        return DEFAULT_PINNED_COUNT;
    }, []);

    const normalizeColumnSizing = useCallback((value: unknown): Record<string, number> => {
        if (!value || typeof value !== 'object') return {};
        return Object.fromEntries(
            Object.entries(value as Record<string, unknown>)
                .filter(([columnId, width]) => (
                    AVAILABLE_COLUMN_IDS.has(columnId) &&
                    Number.isFinite(width) &&
                    Number(width) >= MIN_PERSISTED_COLUMN_WIDTH &&
                    Number(width) <= MAX_PERSISTED_COLUMN_WIDTH
                ))
                .map(([columnId, width]) => [columnId, Math.round(Number(width))])
        );
    }, []);

    const normalizeColumnVisibility = useCallback((value: unknown): Record<string, boolean> => {
        if (!value || typeof value !== 'object') {
            return buildDefaultColumnVisibility();
        }
        const normalized = Object.fromEntries(
            Object.entries(value as Record<string, unknown>)
                .filter(([columnId, isVisible]) => AVAILABLE_COLUMN_IDS.has(columnId) && typeof isVisible === 'boolean')
                .map(([columnId, isVisible]) => [columnId, Boolean(isVisible)])
        );
        return ensureLockedVisibility(normalized);
    }, [ensureLockedVisibility]);

    const normalizeSortingState = useCallback((value: unknown): SortingState => {
        if (!Array.isArray(value)) {
            return buildDefaultSortingState();
        }
        const normalized = value
            .filter((item): item is { id: string; desc?: boolean } => Boolean(item && typeof item === 'object' && typeof (item as any).id === 'string'))
            .map((item) => ({ id: item.id, desc: Boolean(item.desc) }))
            .filter((item) => AVAILABLE_COLUMN_IDS.has(item.id));
        return normalized.length > 0 ? normalized : buildDefaultSortingState();
    }, []);

    const applySafeDefaults = useCallback(() => {
        setSorting(buildDefaultSortingState());
        setColumnFilters([]);
        setColumnOrder(buildDefaultColumnOrder());
        setColumnVisibility(buildDefaultColumnVisibility());
        setColumnSizing({});
        setDensity(DEFAULT_TABLE_DENSITY);
        setPinnedCount(DEFAULT_PINNED_COUNT);
        setGlobalFilter('');
        setSearchValue('');
        setActiveFilters(buildDefaultActiveFilters());
        setColumnStyles({});
        setCellStyles({});
    }, []);

    const captureCurrentViewState = useCallback((): TableViewState => ({
        columnOrder,
        columnSizing,
        columnVisibility: ensureLockedVisibility(columnVisibility),
        density,
        pinnedCount,
        activeFilters,
        globalFilter,
        columnStyles,
        cellStyles,
    }), [activeFilters, cellStyles, columnOrder, columnSizing, columnStyles, columnVisibility, density, ensureLockedVisibility, globalFilter, pinnedCount]);

    const applyPresetState = useCallback((state: TableViewState) => {
        const nextOrder = Array.isArray(state?.columnOrder) ? state.columnOrder.filter((id) => AVAILABLE_COLUMN_IDS.has(id)) : [];
        setColumnOrder(ensureColumnOrderComplete(nextOrder));
        setColumnVisibility(normalizeColumnVisibility(state?.columnVisibility));
        setColumnSizing(normalizeColumnSizing(state?.columnSizing));
        setDensity(normalizeDensity(state?.density));
        setPinnedCount(normalizePinnedCount(state?.pinnedCount));
        setActiveFilters({ ...buildDefaultActiveFilters(), ...((state?.activeFilters && typeof state.activeFilters === 'object') ? state.activeFilters : {}) });
        const nextGlobalFilter = typeof state?.globalFilter === 'string' ? state.globalFilter : '';
        setSearchValue(nextGlobalFilter);
        setGlobalFilter(nextGlobalFilter);
        setColumnStyles((state?.columnStyles && typeof state.columnStyles === 'object') ? state.columnStyles : {});
        setCellStyles((state?.cellStyles && typeof state.cellStyles === 'object') ? state.cellStyles : {});
    }, [
        ensureColumnOrderComplete,
        normalizeColumnSizing,
        normalizeColumnVisibility,
        normalizeDensity,
        normalizePinnedCount,
    ]);

    useEffect(() => {
        applySafeDefaults();
        appliedDefaultStateRef.current = false;
        restoredStateRef.current = false;
        hydrationSettledRef.current = false;
    }, [tableStateStorageKey, applySafeDefaults]);

    React.useEffect(() => {
        if (hydrationSettledRef.current) return;

        try {
            const raw = localStorage.getItem(tableStateStorageKey);
            if (raw) {
                const stored = JSON.parse(raw);
                setSorting(normalizeSortingState(stored?.sorting));
                setColumnOrder(
                    ensureColumnOrderComplete(
                        Array.isArray(stored?.columnOrder)
                            ? stored.columnOrder.filter((id: unknown): id is string => typeof id === 'string' && AVAILABLE_COLUMN_IDS.has(id))
                            : []
                    )
                );
                setColumnVisibility(normalizeColumnVisibility(stored?.columnVisibility));
                setColumnSizing(normalizeColumnSizing(stored?.columnSizing));
                setDensity(normalizeDensity(stored?.density));
                setPinnedCount(normalizePinnedCount(stored?.pinnedCount));
                const nextGlobalFilter = typeof stored?.globalFilter === 'string' ? stored.globalFilter : '';
                setGlobalFilter(nextGlobalFilter);
                setSearchValue(nextGlobalFilter);
                setActiveFilters({
                    ...buildDefaultActiveFilters(),
                    ...((stored?.activeFilters && typeof stored.activeFilters === 'object') ? stored.activeFilters : {}),
                });
                setColumnStyles((stored?.columnStyles && typeof stored.columnStyles === 'object') ? stored.columnStyles : {});
                setCellStyles((stored?.cellStyles && typeof stored.cellStyles === 'object') ? stored.cellStyles : {});
                if (Number.isFinite(stored?.pageSize) && stored.pageSize > 0 && stored.pageSize !== pageSize) {
                    onPageSizeChange(stored.pageSize);
                }
                restoredStateRef.current = true;
                appliedDefaultStateRef.current = true;
                hydrationSettledRef.current = true;
                return;
            }
        } catch (error) {
            try {
                localStorage.removeItem(tableStateStorageKey);
            } catch {
                // no-op
            }
            console.warn('Failed to restore table state', error);
        }
        if (!presetsHydrated) return;

        if (defaultPreset) {
            applyPresetState(defaultPreset.state);
            appliedDefaultStateRef.current = true;
        }
        hydrationSettledRef.current = true;
    }, [
        tableStateStorageKey,
        defaultPreset,
        presetsHydrated,
        pageSize,
        onPageSizeChange,
        applyPresetState,
        ensureColumnOrderComplete,
        normalizeColumnSizing,
        normalizeColumnVisibility,
        normalizeDensity,
        normalizePinnedCount,
        normalizeSortingState,
    ]);

    // Manual Global Filter & Advanced Filters
    const paginationState = useMemo(() => ({ pageIndex: Math.max(page - 1, 0), pageSize }), [page, pageSize]);
    const leftPinnedColumns = useMemo(() => {
        const orderedIds = ensureColumnOrderComplete(
            columnOrder.length > 0 ? columnOrder : columns.map((column) => column.id as string)
        );
        const visibleOrderedIds = orderedIds.filter((columnId) => columnVisibility[columnId] !== false);
        return visibleOrderedIds.slice(0, pinnedCount);
    }, [columnOrder, columns, columnVisibility, ensureColumnOrderComplete, pinnedCount]);
    const columnPinning = useMemo<ColumnPinningState>(() => ({ left: [...leftPinnedColumns], right: [] }), [leftPinnedColumns]);

    const table = useReactTable({
        data,
        columns,
        state: {
            sorting,
            columnFilters,
            columnOrder,
            columnVisibility,
            columnSizing,
            columnPinning,
            pagination: paginationState,
        },
        getRowId: (row) => String(row.id),
        manualPagination: true,
        manualSorting: true,
        manualFiltering: true,
        enableColumnPinning: true,
        columnResizeMode: 'onChange',
        onSortingChange: setSorting,
        onColumnFiltersChange: setColumnFilters,
        onColumnOrderChange: (updater) => {
            setColumnOrder((prev) => {
                const next = typeof updater === 'function'
                    ? (updater as (old: string[]) => string[])(prev)
                    : updater;
                return ensureColumnOrderComplete(next);
            });
        },
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
        setRenamePresetTarget(name);
        setRenamePresetValue(name);
    }, []);

    const handleDeletePreset = useCallback((name: string) => {
        setConfirmDeletePresetName(name);
    }, []);

    const handleSetDefaultPreset = useCallback((name: string) => {
        setDefaultPreset(name);
    }, [setDefaultPreset]);

    const rowHeight = useMemo(() => ROW_HEIGHT_BY_DENSITY[density] || ROW_HEIGHT_BY_DENSITY.standard, [density]);
    const cellPadding = useMemo(() => {
        return {
            'ultra-compact': 'px-1 py-0 text-[10px] leading-[1.15]',
            compact: 'px-1.5 py-0.5 text-[11px] leading-tight',
            standard: 'px-2 py-1 text-xs leading-4',
            comfortable: 'px-3 py-1.5 text-sm leading-5',
        }[density];
    }, [density]);
    const rows = table.getRowModel().rows;
    const rowCount = rows.length;

    const rowVirtualizer = useVirtualizer({
        count: rowCount,
        getScrollElement: () => tableContainerRef.current,
        estimateSize: () => rowHeight,
        overscan: 10,
        // Header row is sticky inside the same scroll container; offset measured
        // rows so the virtual window lines up under it.
        getItemKey: (index) => rows[index]?.id ?? index,
    });

    // Re-measure when row height (density) changes so virtual offsets stay correct.
    useEffect(() => {
        rowVirtualizer.measure();
    }, [rowHeight, rowVirtualizer]);

    const virtualRows = rowVirtualizer.getVirtualItems();
    const totalRowsHeight = rowVirtualizer.getTotalSize();
    const visibleLeafColumnsCount = table.getVisibleLeafColumns().length;
    const paddingTop = virtualRows.length > 0 ? virtualRows[0].start : 0;
    const paddingBottom =
        virtualRows.length > 0 ? totalRowsHeight - virtualRows[virtualRows.length - 1].end : 0;

    useEffect(() => {
        if (!normalizedHighlightRowIds.length || !tableContainerRef.current) return;
        const highlightSet = new Set(normalizedHighlightRowIds);
        // With row virtualization the target may not be mounted yet — scroll the
        // virtual window to its index first, then center it once it paints.
        const targetIndex = rows.findIndex((row) => highlightSet.has(Number(row.id)));
        if (targetIndex < 0) return;
        rowVirtualizer.scrollToIndex(targetIndex, { align: 'center' });
        window.requestAnimationFrame(() => {
            const viewport = tableContainerRef.current;
            if (!viewport) return;
            const selector = normalizedHighlightRowIds
                .map((value) => `tr[data-rowid="${value}"]`)
                .join(', ');
            const target = viewport.querySelector<HTMLTableRowElement>(selector);
            target?.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
        });
    }, [data.length, normalizedHighlightRowIds, rows, rowVirtualizer]);

    const visibleLeafColumns = table.getVisibleLeafColumns();
    const visibleColumnIndexMap = useMemo(() => {
        const map: Record<string, number> = {};
        visibleLeafColumns.forEach((column, index) => {
            map[column.id] = index;
        });
        return map;
    }, [visibleLeafColumns]);

    // Clamp/initialize pagination
    React.useEffect(() => {
        const maxPage = Math.max(1, Math.ceil(total / pageSize));
        if (page > maxPage) {
            onPageChange(maxPage);
        }
    }, [total, pageSize, page, onPageChange]);

    // Persist state
    React.useEffect(() => {
        if (saveTimeoutRef.current) {
            clearTimeout(saveTimeoutRef.current);
        }
        const stateToSave = {
            sorting,
            pageSize,
            columnOrder,
            columnSizing,
            columnVisibility,
            density,
            pinnedCount,
            globalFilter,
            activeFilters: { currency: activeFilters.currency || 'ALL', ...activeFilters },
            columnStyles,
            cellStyles,
        };
        saveTimeoutRef.current = window.setTimeout(() => {
            try {
                localStorage.setItem(tableStateStorageKey, JSON.stringify(stateToSave));
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
    }, [sorting, pageSize, columnOrder, columnSizing, columnVisibility, density, pinnedCount, globalFilter, activeFilters, columnStyles, cellStyles, tableStateStorageKey]);

    useEffect(() => {
        if (resetViewStateToken === undefined) return;
        if (lastResetTokenRef.current === resetViewStateToken) return;
        lastResetTokenRef.current = resetViewStateToken;
        try {
            localStorage.removeItem(tableStateStorageKey);
        } catch {
            // no-op
        }
        applySafeDefaults();
        onPageSizeChange(100);
        appliedDefaultStateRef.current = true;
        restoredStateRef.current = true;
        hydrationSettledRef.current = true;
    }, [
        resetViewStateToken,
        tableStateStorageKey,
        applySafeDefaults,
        onPageSizeChange,
    ]);

    useEffect(() => {
        if (!hydrationSettledRef.current || !scrollToLastRowToken || rowCount <= 0 || !tableContainerRef.current) return;
        if (lastAppliedScrollTokenRef.current === scrollToLastRowToken) return;
        lastAppliedScrollTokenRef.current = scrollToLastRowToken;
        requestAnimationFrame(() => {
            scrollViewport('bottom');
        });
    }, [scrollToLastRowToken, rowCount, scrollViewport]);

    useEffect(() => {
        if (!hydrationSettledRef.current || !pendingScrollModeRef.current || rowCount <= 0) return;
        const mode = pendingScrollModeRef.current;
        pendingScrollModeRef.current = null;
        requestAnimationFrame(() => {
            scrollViewport(mode);
        });
    }, [page, rowCount, scrollViewport]);

    const leftPinnedLeafColumns = table.getLeftLeafColumns();
    const lastPinnedLeftId = leftPinnedLeafColumns[leftPinnedLeafColumns.length - 1]?.id;

    const getPinnedStyles = useCallback(
        (columnId: string, isHeader = false): CSSProperties => {
            const column = table.getColumn(columnId);
            if (!column || column.getIsPinned() !== 'left') return {};
            const isLastPinned = lastPinnedLeftId === columnId;
            return {
                position: 'sticky',
                left: column.getStart('left'),
                zIndex: isHeader ? 50 : 20,
                backgroundColor: isHeader ? 'var(--table-header)' : undefined,
                borderRight: isLastPinned ? '1px solid var(--table-border, var(--border))' : undefined,
                boxShadow: isLastPinned ? '2px 0 0 rgba(148, 163, 184, 0.35)' : undefined,
            };
        },
        [table, lastPinnedLeftId]
    );

    const PaginationControls: React.FC<{ className?: string }> = ({ className }) => (
        <div className={`flex items-center gap-2 ${className || ''}`} style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 11 }}>
            <span className="text-foreground-secondary">{rowCount.toLocaleString('ru-RU')} стр.</span>
            <div className="tx-pagination">
                <button
                    onClick={() => table.previousPage()}
                    disabled={!table.getCanPreviousPage()}
                    className="tx-page-btn"
                    aria-label="Предыдущая"
                >
                    ‹
                </button>
                <span className="tx-pagination-page">
                    {table.getState().pagination.pageIndex + 1} / {table.getPageCount() || 1}
                </span>
                <button
                    onClick={() => table.nextPage()}
                    disabled={!table.getCanNextPage()}
                    className="tx-page-btn"
                    aria-label="Следующая"
                >
                    ›
                </button>
            </div>
        </div>
    );

    const handleNewestFirst = useCallback(() => {
        const isActive = sorting[0]?.id === 'transaction_date' && sorting[0]?.desc === true;
        setSorting(isActive ? [] : [{ id: 'transaction_date', desc: true }]);
        if (page === 1) {
            requestAnimationFrame(() => scrollViewport('top'));
            return;
        }
        pendingScrollModeRef.current = 'top';
        onPageChange(1);
    }, [onPageChange, page, scrollViewport, sorting]);

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
        void event;
    }

    const isInteractiveTarget = useCallback((target: EventTarget | null) => {
        return target instanceof HTMLElement && Boolean(
            target.closest('button, input, select, textarea, a, [role="button"], [contenteditable="true"], .resizer')
        );
    }, []);

    const handleDragOver = (event: DragOverEvent) => {
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
        if (isInteractiveTarget(e.target)) return;
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
        if (isInteractiveTarget(e.target)) return;
        const isMulti = e.ctrlKey || e.metaKey;
        if (isMulti) {
            toggleCellSelection(cellId, true);
        }
        // Single click logic is handled by MouseDown basically (clears and sets one),
        // but Click ensures we toggle if Ctrl is held.
        // For non-Ctrl click, mouse down already set exact cell.
    };

    const estimateExpandedWidth = useCallback((text: string, fallbackWidth: number) => {
        const normalized = text.replace(/\s+/g, ' ').trim();
        if (!normalized) return fallbackWidth;
        const fontSize =
            density === 'ultra-compact' ? 10 :
                density === 'compact' ? 11 :
                    density === 'standard' ? 12 : 14;
        const canvas = textMeasureCanvasRef.current || document.createElement('canvas');
        textMeasureCanvasRef.current = canvas;
        const context = canvas.getContext('2d');
        if (!context) {
            return Math.min(6000, Math.max(fallbackWidth, normalized.length * (fontSize * 0.72) + 44));
        }
        context.font = `${fontSize}px "Segoe UI", "Inter", sans-serif`;
        const measured = Math.ceil(context.measureText(normalized).width) + 44;
        return Math.min(6000, Math.max(fallbackWidth, measured));
    }, [density]);

    const restoreTemporaryExpandedColumn = useCallback(() => {
        const expanded = temporaryExpandedColumnRef.current;
        if (!expanded) return;
        setColumnSizing((prev) => {
            if (prev[expanded.columnId] === expanded.previousSize) {
                return prev;
            }
            return {
                ...prev,
                [expanded.columnId]: expanded.previousSize,
            };
        });
        temporaryExpandedColumnRef.current = null;
    }, []);

    const maybeExpandColumnForClippedCell = useCallback(
        (event: React.MouseEvent<HTMLTableCellElement>, columnId: string) => {
            const column = table.getColumn(columnId);
            if (!column || !column.getCanResize()) {
                restoreTemporaryExpandedColumn();
                return;
            }

            const targetElement = event.target as HTMLElement | null;
            const probe = targetElement?.closest('[data-overflow-probe="1"]') as HTMLElement | null;
            const fallbackElement = event.currentTarget as HTMLElement;
            const measuredElement = probe || fallbackElement;
            const isOverflowed = measuredElement.scrollWidth > measuredElement.clientWidth;
            const fullText = (probe?.dataset.fulltext || measuredElement.textContent || '').trim();

            if (!isOverflowed || !fullText) {
                restoreTemporaryExpandedColumn();
                return;
            }

            const currentWidth = column.getSize();
            const nextWidth = estimateExpandedWidth(fullText, currentWidth);
            const expanded = temporaryExpandedColumnRef.current;

            if (expanded && expanded.columnId !== columnId) {
                const previousSizeForCurrent = columnSizing[columnId] ?? currentWidth;
                setColumnSizing((prev) => ({
                    ...prev,
                    [expanded.columnId]: expanded.previousSize,
                    [columnId]: nextWidth,
                }));
                temporaryExpandedColumnRef.current = {
                    columnId,
                    previousSize: previousSizeForCurrent,
                };
                return;
            }

            if (!expanded) {
                temporaryExpandedColumnRef.current = {
                    columnId,
                    previousSize: columnSizing[columnId] ?? currentWidth,
                };
            }

            setColumnSizing((prev) => ({
                ...prev,
                [columnId]: nextWidth,
            }));
        },
        [table, restoreTemporaryExpandedColumn, estimateExpandedWidth, columnSizing]
    );

    useEffect(() => () => {
        restoreTemporaryExpandedColumn();
    }, [restoreTemporaryExpandedColumn]);

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
        description: 'description',
        receiver_name: 'receiver_name',
        receiver_card: 'receiver_card',
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

        const clip = (navigator as any)?.clipboard;
        if (!clip || typeof clip.writeText !== 'function') {
            showToast('error', 'Буфер обмена недоступен в этом окружении');
            return;
        }

        clip.writeText(tsv).then(
            () => showToast('success', 'Скопировано в буфер обмена'),
            () => showToast('error', 'Не удалось скопировать')
        );
    }, [selectedCells, data, table, showToast, fieldMap]);

    const handlePaste = useCallback(async () => {
        if (selectedCells.size === 0) return;

        try {
            const clip = (navigator as any)?.clipboard;
            if (!clip || typeof clip.readText !== 'function') {
                showToast('error', 'Чтение буфера обмена недоступно');
                return;
            }

            const text = await clip.readText();
            const rows = text.split('\n').map((row: string) => row.split('\t'));

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

            const localUpdates = payload.updates.map(update => {
                const newFields = { ...update.fields };
                if (newFields.transaction_type) {
                    newFields.transaction_type_display = TRANSACTION_TYPE_LABELS[String(newFields.transaction_type)] || newFields.transaction_type;
                }
                if (newFields.source_type) {
                    const targetRow = data.find(r => r.id === update.id);
                    const channel = newFields.source_type === 'MANUAL'
                        ? 'MANUAL'
                        : (targetRow?.source_channel && targetRow.source_channel !== 'MANUAL' ? targetRow.source_channel : 'SMS');
                    newFields.source_channel = channel;
                    newFields.source_display = SOURCE_CHANNEL_LABELS[channel] || channel;
                }
                return { id: update.id, fields: newFields };
            });

            await transactionsApi.bulkUpdateTransactions(payload);
            addAction({ type: 'PASTE', cells: [] });
            onTransactionsFieldsUpdated?.(localUpdates);
            showToast('success', `Вставлено ${payload.updates.length} строк`);
        } catch (error) {
            showToast('error', 'Не удалось вставить из буфера обмена');
        }
    }, [selectedCells, data, table, addAction, showToast, fieldMap, onTransactionsFieldsUpdated]);

    const handleDeleteSelected = useCallback(() => {
        if (selectedCells.size === 0) return;
        const rowIds = new Set<number>();
        selectedCells.forEach(cellKey => {
            const [rowId] = cellKey.split(':');
            rowIds.add(Number(rowId));
        });
        const idsArray = Array.from(rowIds);
        if (idsArray.length === 0) return;
        setConfirmDeleteRows(idsArray);
    }, [selectedCells]);

    const performDeleteSelected = useCallback(async () => {
        const idsArray = confirmDeleteRows;
        if (!idsArray || idsArray.length === 0) {
            setConfirmDeleteRows(null);
            return;
        }
        try {
            const res = await transactionsApi.bulkDeleteTransactions(idsArray);
            const failed = new Set(res?.failed_ids ?? []);
            const deletedIds = idsArray.filter(id => !failed.has(id));

            if (deletedIds.length) {
                const deletedRows = deletedIds.map(id => {
                    const row = data.find(r => r.id === id);
                    return { rowId: id, rowData: row };
                });
                addAction({ type: 'BULK_DELETE', rows: deletedRows });
                onTransactionsDeleted?.(deletedIds);
            }
            setSelectedCells(new Set());

            if (failed.size > 0) {
                console.warn('bulk-delete: часть записей не удалена', res?.failed_ids, res?.errors);
                const reason = describeDeleteError(res?.errors);
                if (deletedIds.length) {
                    showToast('warning', `Удалено ${deletedIds.length}, не удалось ${failed.size}${reason ? `: ${reason}` : ''}`);
                } else {
                    showToast('error', `Не удалось удалить${reason ? `: ${reason}` : ''}`);
                }
            } else {
                showToast('success', `Удалено ${deletedIds.length} записей`);
            }
        } catch (error) {
            console.error('bulk-delete: запрос завершился ошибкой', error);
            showToast('error', 'Ошибка при удалении');
        } finally {
            setConfirmDeleteRows(null);
        }
    }, [confirmDeleteRows, data, addAction, showToast, onTransactionsDeleted]);

    // Keyboard Shortcuts
    useKeyboardShortcuts({
        shortcuts: [
            { key: 'z', ctrl: true, handler: () => undo(), description: 'Отменить' },
            { key: 'y', ctrl: true, handler: () => redo(), description: 'Повторить' },
            { key: 'Delete', handler: () => handleDeleteSelected(), description: 'Удалить' },
            { key: 'Backspace', handler: () => handleDeleteSelected(), description: 'Удалить' },
            { key: 'c', ctrl: true, handler: () => handleCopy(), description: 'Копировать' },
            { key: 'v', ctrl: true, handler: () => handlePaste(), description: 'Вставить' },
            {
                key: 'Escape', handler: () => {
                    if (editingCell) cancelEdit();
                }, description: 'Отмена редактирования'
            },
        ],
        enabled: true,
    });

    const buildExportColumns = useCallback(() => {
        const columnsToExport = table.getVisibleLeafColumns();
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

    const isOperationNumberDescending = Boolean(sorting[0]?.desc)
        && ['operation_number', 'date_time', 'transaction_date', 'time', 'day'].includes(sorting[0]?.id || '');

    const exportCurrentView = useCallback(() => {
        const rowsToUse = exportViewRows || table.getPrePaginationRowModel().rows.map(r => r.original);
        if (!rowsToUse.length) {
            showToast('warning', 'Нет данных для экспорта.');
            return;
        }
        exportTransactionsToExcel({
            rows: rowsToUse,
            columns: buildExportColumns(),
            columnStyles: columnStyles as any,
            cellStyles: cellStyles as any,
            fileName: `transactions_view_${new Date().toISOString().slice(0, 10)}.xlsx`,
            includeAlternating: true,
            operationNumberDescending: isOperationNumberDescending,
            operationNumberTotal: rowsToUse.length,
        });
    }, [exportViewRows, table, columnStyles, cellStyles, buildExportColumns, isOperationNumberDescending, showToast]);

    const exportAll = useCallback(() => {
        const visibleColumnIds = table.getVisibleLeafColumns().map((column) => column.id);
        if (serverModeActive && onServerExportAll) {
            setServerExportPending(true);
            Promise.resolve(onServerExportAll(visibleColumnIds))
                .finally(() => setServerExportPending(false));
            return;
        }
        const rowsToUse = exportAllRows || exportViewRows || table.getPrePaginationRowModel().rows.map(r => r.original);
        if (!rowsToUse.length) {
            showToast('warning', 'Нет данных для экспорта.');
            return;
        }
        exportTransactionsToExcel({
            rows: rowsToUse,
            columns: buildExportColumns(),
            columnStyles: columnStyles as any,
            cellStyles: cellStyles as any,
            fileName: `transactions_all_${new Date().toISOString().slice(0, 10)}.xlsx`,
            includeAlternating: true,
            operationNumberDescending: isOperationNumberDescending,
            operationNumberTotal: rowsToUse.length,
        });
    }, [serverModeActive, onServerExportAll, exportAllRows, exportViewRows, table, columnStyles, cellStyles, buildExportColumns, isOperationNumberDescending, showToast]);

    const exportByPeriod = useCallback(() => {
        if (!exportDateFrom || !exportDateTo) {
            showToast('error', 'Укажите период (дата начала и дата конца).');
            return;
        }
        const from = new Date(exportDateFrom);
        const to = new Date(exportDateTo);
        to.setHours(23, 59, 59, 999);

        if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime()) || from > to) {
            showToast('error', 'Период указан некорректно.');
            return;
        }

        const visibleColumnIds = table.getVisibleLeafColumns().map((column) => column.id);
        if (serverModeActive && onServerExportByPeriod) {
            setServerExportPending(true);
            Promise.resolve(onServerExportByPeriod(exportDateFrom, exportDateTo, visibleColumnIds))
                .then(() => {
                    setExportPeriodOpen(false);
                    setExportMenuOpen(false);
                })
                .finally(() => setServerExportPending(false));
            return;
        }

        const allRows = exportAllRows || exportViewRows || table.getPrePaginationRowModel().rows.map((r) => r.original);
        const filtered = allRows.filter((tx) => {
            const txDate = tx.transaction_date ? new Date(tx.transaction_date) : null;
            if (!txDate || Number.isNaN(txDate.getTime())) return false;
            return txDate >= from && txDate <= to;
        });

        if (!filtered.length) {
            showToast('warning', 'Нет транзакций за выбранный период.');
            return;
        }

        exportTransactionsToExcel({
            rows: filtered,
            columns: buildExportColumns(),
            columnStyles: columnStyles as any,
            cellStyles: cellStyles as any,
            fileName: `transactions_${exportDateFrom}_${exportDateTo}.xlsx`,
            includeAlternating: true,
            operationNumberDescending: isOperationNumberDescending,
            operationNumberTotal: filtered.length,
        });
        setExportPeriodOpen(false);
        setExportMenuOpen(false);
    }, [
        exportDateFrom,
        exportDateTo,
        serverModeActive,
        onServerExportByPeriod,
        exportAllRows,
        exportViewRows,
        table,
        showToast,
        buildExportColumns,
        columnStyles,
        cellStyles,
        isOperationNumberDescending,
    ]);

    const selectedRowIds = useMemo(() => {
        const rows = new Set<number>();
        selectedCells.forEach((key) => {
            const rowId = Number(key.split(':')[0]);
            rows.add(rowId);
        });
        return Array.from(rows);
    }, [selectedCells]);

    // Applied filter chips intentionally removed per latest request

    return (
        <div className="tx-table-inner flex flex-col h-full min-h-0 overflow-hidden gap-2" style={{ padding: '10px 12px' }} onClick={() => {
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
                    onDelete={contextMenu.type === 'cell' ? handleDeleteSelected : undefined}
                />
            )}

            {/* Top controls */}
            <div className="mb-1 space-y-1 shrink-0">
                {/* Toolbar */}
                <div className="flex flex-wrap gap-1.5 items-center">
                    <div className="tx-search relative flex-1 min-w-[240px]" ref={searchHelpRef}>
                        <Search size={14} className="tx-search-icon" aria-hidden />
                        <input
                            type="text"
                            value={searchValue}
                            onChange={(e) => setSearchValue(e.target.value)}
                            className="tx-search-input"
                            placeholder='Поиск: 1250000, "Korzinka", date:2026-01-28, status:ошибка'
                        />
                        <button
                            type="button"
                            className="tx-search-help"
                            onClick={() => setSearchHelpOpen((v) => !v)}
                            title="Как искать"
                            aria-label="Помощь по поиску"
                        >
                            ?
                        </button>
                        <span className="tx-search-kbd" aria-hidden>⌘K</span>
                        {searchHelpOpen && (
                            <div className="absolute mt-2 right-0 w-72 p-3 bg-surface border border-border rounded shadow-lg text-sm z-50 tx-search-help-tip">
                                <div className="font-semibold mb-2" style={{ fontFamily: 'var(--font-display, serif)', fontSize: 14, fontWeight: 400 }}>Синтаксис поиска</div>
                                <div className="tx-search-help-tip-row"><code>amount:100000</code><span>точная сумма</span></div>
                                <div className="tx-search-help-tip-row"><code>date:2026-01-28</code><span>дата</span></div>
                                <div className="tx-search-help-tip-row"><code>status:ошибка</code><span>статус/метка</span></div>
                                <div className="tx-search-help-tip-row"><code>seller:korzinka</code><span>оператор</span></div>
                                <div className="tx-search-help-tip-row"><code>-status:дубликат</code><span>исключить</span></div>
                                <div className="tx-search-help-tip-row"><code>"фраза"</code><span>точное</span></div>
                            </div>
                        )}
                    </div>

                    <div className="flex items-center gap-1.5 ml-auto">
                        <button
                            onClick={onAddClick}
                            className="tx-btn tx-btn-primary"
                        >
                            + Добавить
                        </button>

                        <div className="relative" ref={exportMenuRef}>
                            <button
                                onClick={() => {
                                    setExportMenuOpen((prev) => {
                                        const next = !prev;
                                        if (!next) {
                                            setExportPeriodOpen(false);
                                        }
                                        return next;
                                    });
                                }}
                                className="tx-btn"
                                disabled={serverExportPending}
                            >
                                <FileText className="w-4 h-4" />
                                Экспорт
                            </button>
                            {exportMenuOpen && (
                                <div className="absolute top-full right-0 mt-1 w-56 bg-surface border border-border rounded-md shadow-lg z-50">
                                    <button
                                        onClick={() => {
                                            exportCurrentView();
                                            setExportPeriodOpen(false);
                                            setExportMenuOpen(false);
                                        }}
                                        className="w-full text-left px-3 py-2 text-sm hover:bg-surface-2 disabled:opacity-60"
                                        disabled={serverExportPending}
                                    >
                                        Экспорт текущего вида
                                    </button>
                                    <button
                                        onClick={() => {
                                            exportAll();
                                            setExportPeriodOpen(false);
                                            setExportMenuOpen(false);
                                        }}
                                        className="w-full text-left px-3 py-2 text-sm hover:bg-surface-2 disabled:opacity-60"
                                        disabled={serverExportPending}
                                    >
                                        Экспорт всех транзакций
                                    </button>
                                    <div className="border-t border-border my-1" />
                                    <button
                                        onClick={() => setExportPeriodOpen((prev) => !prev)}
                                        className="w-full text-left px-3 py-2 text-sm hover:bg-surface-2 disabled:opacity-60"
                                        disabled={serverExportPending}
                                    >
                                        Экспорт за период
                                    </button>
                                    {exportPeriodOpen && (
                                        <div className="px-3 py-2 space-y-2">
                                            <input
                                                type="date"
                                                value={exportDateFrom}
                                                onChange={(e) => setExportDateFrom(e.target.value)}
                                                className="w-full px-2 py-1 text-sm border border-border rounded bg-input-bg"
                                            />
                                            <input
                                                type="date"
                                                value={exportDateTo}
                                                onChange={(e) => setExportDateTo(e.target.value)}
                                                className="w-full px-2 py-1 text-sm border border-border rounded bg-input-bg"
                                            />
                                            <button
                                                onClick={exportByPeriod}
                                                disabled={!exportDateFrom || !exportDateTo || serverExportPending}
                                                className="w-full px-2 py-1.5 text-sm rounded bg-primary text-white hover:bg-primary/90 disabled:opacity-50"
                                            >
                                                {serverExportPending ? 'Экспорт...' : 'Скачать'}
                                            </button>
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>

                        <button
                            onClick={() => setFilterDrawerOpen(true)}
                            className={`tx-btn tx-filter-trigger${activeFilterCount > 0 ? ' is-active' : ''}`}
                        >
                            <Filter className="w-3.5 h-3.5" />
                            Фильтры
                            {activeFilterCount > 0 ? (
                                <span className="tx-filter-count">{activeFilterCount}</span>
                            ) : null}
                        </button>

                        <button
                            onClick={handleNewestFirst}
                            className={`tx-btn${
                                sorting[0]?.id === 'transaction_date' && sorting[0]?.desc
                                    ? ' is-active'
                                    : ''
                            }`}
                            title="Сначала новые — нажмите ещё раз, чтобы вернуть порядок по умолчанию"
                        >
                            Сначала новые
                        </button>

                        <div className="relative" ref={viewMenuRef}>
                            <button
                                onClick={() => setViewMenuOpen(!viewMenuOpen)}
                                className="tx-btn"
                            >
                                <Eye className="w-4 h-4" />
                                Вид
                            </button>
                            {viewMenuOpen && (
                                <div className="absolute top-full right-0 mt-1 w-[30rem] bg-surface border border-border rounded-md shadow-lg z-50">
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
                                            : col.id;
                                        const disabled = LOCKED_COLUMNS.has(col.id);
                                        return (
                                            <label key={col.id} className="flex items-center gap-2 text-sm text-foreground">
                                                <input
                                                    type="checkbox"
                                                    checked={col.getIsVisible()}
                                                    disabled={disabled}
                                                    onChange={(e) => toggleColumnVisibility(col.id, e.target.checked)}
                                                    aria-label={`Показать столбец ${label}`}
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
                                            onClick={() => { setDensity('ultra-compact'); setViewMenuOpen(false); }}
                                            className={`w-full text-left px-2 py-1 text-sm rounded focus:outline-none focus:ring-2 focus:ring-primary ${density === 'ultra-compact' ? 'bg-primary-light text-primary' : 'hover:bg-surface-2'}`}
                                        >
                                            Ультра-компактный
                                        </button>
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
                                        <div className="text-xs font-semibold text-foreground-muted mb-2 px-2">Закреплено слева</div>
                                        <div className="grid grid-cols-4 gap-1 px-2">
                                            {[0, 1, 2, 3].map((count) => (
                                                <button
                                                    key={count}
                                                    onClick={() => setPinnedCount(count as 0 | 1 | 2 | 3)}
                                                    className={`px-2 py-1 text-xs rounded border ${pinnedCount === count ? 'bg-primary-light text-primary border-primary/40' : 'border-border hover:bg-surface-2'}`}
                                                >
                                                    {count}
                                                </button>
                                            ))}
                                        </div>
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
                                                setSorting(buildDefaultSortingState());
                                                setActiveFilters(buildDefaultActiveFilters());
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
                        <button
                            onClick={() => undo()}
                            disabled={!canUndo}
                            className="tx-btn tx-btn-icon"
                            title="Отменить (Ctrl+Z)"
                        >
                            <Undo2 className="w-4 h-4" />
                        </button>
                        <button
                            onClick={() => redo()}
                            disabled={!canRedo}
                            className="tx-btn tx-btn-icon"
                            title="Повторить (Ctrl+Y)"
                        >
                            <Redo2 className="w-4 h-4" />
                        </button>
                    </div>

                </div>

                {/* Status + pagination + currency */}
                <div className="tx-status-row flex flex-wrap items-center gap-2 text-xs" style={{ padding: '6px 10px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--tx-radius-sm)' }}>
                    <div className="flex items-center gap-2 text-foreground">
                        <span
                            className={`tx-eyebrow-dot${syncState?.isSyncing ? ' is-warn' : ''}`}
                            style={{ width: 6, height: 6 }}
                        />
                        <span style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 11, letterSpacing: '0.04em' }}>
                            {syncState?.isSyncing
                                ? `SYNC ${syncState?.progress?.downloaded ?? 0}${syncState?.progress?.total ? `/${syncState.progress.total}` : ''}`
                                : syncState?.isOfflineReady
                                    ? 'READY'
                                    : isLoading
                                        ? 'LOADING…'
                                        : 'NO CACHE'}
                        </span>
                    </div>
                    <div className="text-foreground-secondary" style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 11 }}>
                        {syncState?.lastSyncAt ? new Date(syncState.lastSyncAt).toLocaleTimeString() : '—'}
                    </div>
                    {(syncState?.freshness?.serverLatestTransactionAt || syncState?.freshness?.localLatestTransactionAt) && (
                        <div className="flex flex-wrap items-center gap-2 text-foreground-secondary" style={{ fontSize: 11 }}>
                            <span className={syncState?.freshness?.desktopLagging ? 'text-warning' : 'text-success'}>
                                {syncState?.freshness?.desktopLagging ? '⚠ desktop отстаёт' : '✓ актуален'}
                            </span>
                        </div>
                    )}
                    <label className="tx-year-select" aria-label="Год / папка">
                        <span className="tx-year-select-label">Год</span>
                        <select
                            className="tx-year-select-control"
                            value={selectedYear ?? ''}
                            onChange={(e) => {
                                const next = e.target.value;
                                if (next === '') {
                                    onYearChange(null);
                                } else {
                                    const num = Number(next);
                                    if (Number.isFinite(num)) onYearChange(num);
                                }
                            }}
                        >
                            {availableYears.map((year) => (
                                <option key={year} value={year}>
                                    {year}
                                </option>
                            ))}
                        </select>
                    </label>
                    <div className="tx-seg" aria-label="Валюта">
                        {[
                            { key: 'ALL', label: 'Все' },
                            { key: 'UZS', label: 'UZS' },
                            { key: 'USD', label: 'USD' },
                        ].map((item) => (
                            <button
                                key={item.key}
                                type="button"
                                onClick={() => setActiveFilters({ ...activeFilters, currency: item.key as any })}
                                className={`tx-seg-btn${activeFilters.currency === item.key ? ' is-active' : ''}`}
                            >
                                {item.label}
                            </button>
                        ))}
                    </div>

                    <PaginationControls className="ml-auto" />

                    <button
                        onClick={syncState?.onSync}
                        disabled={syncState?.isSyncing}
                        className="tx-btn"
                    >
                        {syncState?.isSyncing && <div className="animate-spin h-3 w-3 border-2 border-primary border-t-transparent rounded-full" />}
                        {syncState?.isSyncing ? 'Синхронизация…' : 'Sync'}
                    </button>
                    {isSaving && (
                        <div className="flex items-center gap-1 text-foreground-secondary">
                            <div className="animate-spin h-3 w-3 border-2 border-primary border-t-transparent rounded-full"></div>
                            <span>Сохранение…</span>
                        </div>
                    )}
                    {selectedRowIds.length > 0 && (
                        <div className="flex items-center gap-1 border-l border-border pl-2 ml-1">
                            <div style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 11, color: 'var(--text)' }}>
                                <strong style={{ fontVariantNumeric: 'tabular-nums', marginRight: 4 }}>
                                    {selectedRowIds.length}
                                </strong>
                                выбрано
                            </div>
                            <button
                                onClick={() => setSelectedCells(new Set())}
                                className="tx-btn tx-btn-ghost"
                                style={{ height: 24, padding: '0 8px', fontSize: 11 }}
                            >
                                Снять
                            </button>
                        </div>
                    )}
                    {selectedRowIds.length > 0 && (
                        <>
                        <button
                            onClick={() => handleDeleteSelected()}
                            className="tx-btn"
                            style={{ color: 'var(--danger)', borderColor: 'color-mix(in srgb, var(--danger) 32%, transparent)' }}
                        >
                            <Trash2 className="w-3.5 h-3.5" />
                            Удалить
                        </button>
                        <button
                            onClick={() => {
                                const rowsToUse = data.filter((r) => selectedRowIds.includes(r.id));
                                if (!rowsToUse.length) return;
                                exportTransactionsToExcel({
                                    rows: rowsToUse,
                                    columns: buildExportColumns(),
                                    columnStyles: columnStyles as any,
                                    cellStyles: cellStyles as any,
                                    fileName: `transactions_selected_${new Date().toISOString().slice(0, 10)}.xlsx`,
                                    includeAlternating: true,
                                    operationNumberDescending: isOperationNumberDescending,
                                    operationNumberTotal: rowsToUse.length,
                                });
                            }}
                            className="tx-btn"
                        >
                            <FileText className="w-3.5 h-3.5" />
                            Экспорт
                        </button>
                        </>
                    )}
                </div>
            </div>

            <FilterDrawer
                isOpen={filterDrawerOpen}
                onClose={() => setFilterDrawerOpen(false)}
                onApply={(filters) => setActiveFilters(filters)}
                initialFilters={activeFilters}
                operatorOptions={operatorOptions}
                appOptions={appOptions}
                telegramSourceOptions={telegramSourceOptions}
            />

            <ConfirmDialog
                open={Boolean(confirmDeleteRows && confirmDeleteRows.length)}
                title={`Удалить ${confirmDeleteRows?.length ?? 0} ${confirmDeleteRows?.length === 1 ? 'запись' : 'записей'}?`}
                description="Действие нельзя отменить вручную, но можно вернуть через Undo."
                confirmLabel="Удалить"
                cancelLabel="Отмена"
                tone="danger"
                onConfirm={performDeleteSelected}
                onClose={() => setConfirmDeleteRows(null)}
            />

            <ConfirmDialog
                open={Boolean(confirmDeletePresetName)}
                title={`Удалить вид "${confirmDeletePresetName ?? ''}"?`}
                description="Сохранённый набор колонок и фильтров будет удалён без возможности восстановления."
                confirmLabel="Удалить"
                cancelLabel="Отмена"
                tone="danger"
                onConfirm={() => {
                    if (confirmDeletePresetName) {
                        deletePreset(confirmDeletePresetName);
                    }
                    setConfirmDeletePresetName(null);
                }}
                onClose={() => setConfirmDeletePresetName(null)}
            />

            <Dialog
                open={Boolean(renamePresetTarget)}
                onClose={() => {
                    setRenamePresetTarget(null);
                    setRenamePresetValue('');
                }}
                title="Переименовать вид"
                description="Дайте этому набору колонок и фильтров новое имя."
                width={420}
                footer={
                    <>
                        <span className="sp-spacer" />
                        <button
                            type="button"
                            className="sp-btn"
                            onClick={() => {
                                setRenamePresetTarget(null);
                                setRenamePresetValue('');
                            }}
                        >
                            Отмена
                        </button>
                        <button
                            type="button"
                            className="sp-btn sp-btn-primary"
                            disabled={!renamePresetValue.trim() || renamePresetValue.trim() === renamePresetTarget}
                            onClick={() => {
                                const next = renamePresetValue.trim();
                                if (renamePresetTarget && next && next !== renamePresetTarget) {
                                    renamePreset(renamePresetTarget, next);
                                }
                                setRenamePresetTarget(null);
                                setRenamePresetValue('');
                            }}
                        >
                            Сохранить
                        </button>
                    </>
                }
            >
                <div className="tx-field" style={{ marginTop: 4 }}>
                    <label className="tx-field-label" htmlFor="tx-rename-preset">Новое имя</label>
                    <input
                        id="tx-rename-preset"
                        autoFocus
                        type="text"
                        className="tx-field-input"
                        value={renamePresetValue}
                        onChange={(e) => setRenamePresetValue(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                                e.preventDefault();
                                const next = renamePresetValue.trim();
                                if (renamePresetTarget && next && next !== renamePresetTarget) {
                                    renamePreset(renamePresetTarget, next);
                                }
                                setRenamePresetTarget(null);
                                setRenamePresetValue('');
                            }
                        }}
                    />
                </div>
            </Dialog>

            {rowCount === 0 && !isLoading ? (
                <EmptyState
                    compact
                    icon={<FileText className="w-6 h-6 text-foreground-muted" />}
                    title="Транзакции не найдены"
                    description="Измените фильтры или добавьте новую транзакцию."
                />
            ) : (
                <div className="flex-1 min-h-0">
                    <DndContext
                        collisionDetection={closestCenter}
                        modifiers={[]}
                        onDragOver={handleDragOver}
                        onDragEnd={handleDragEnd}
                        sensors={sensors}
                    >
                        <div className="flex h-full min-h-0 flex-col">
                            <div
                                className="flex-1 min-h-0 overflow-x-scroll overflow-y-scroll overscroll-contain"
                                ref={tableContainerRef}
                                tabIndex={0}
                                role="region"
                                aria-label="Таблица транзакций"
                                onMouseLeave={restoreTemporaryExpandedColumn}
                                style={{
                                    scrollbarGutter: 'stable both-edges',
                                    WebkitOverflowScrolling: 'touch',
                                    touchAction: 'pan-x pan-y',
                                }}
                            >
                                <table
                                    className={`strict-table relative density-${density} w-max`}
                                    role="grid"
                                    aria-rowcount={total}
                                    style={{ width: table.getTotalSize(), minWidth: '100%' }}
                                >
                        <thead className="sticky top-0 z-30 bg-table-header shadow-sm">
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
                                                pinnedStyle={getPinnedStyles(header.column.id, true)}
                                                onContextMenu={(e) => handleHeaderContextMenu(e, header.column.id)}
                                                paddingClass={cellPadding}
                                            >
                                                <div
                                                    className={`flex min-w-0 items-center gap-1 ${header.column.getCanSort() ? 'cursor-pointer hover:text-foreground' : ''} ${highlightedColumnId === header.column.id ? 'rounded bg-primary/10 px-1 text-primary' : ''}`}
                                                    onClick={header.column.getToggleSortingHandler()}
                                                >
                                                    <div className="min-w-0 flex-1 truncate">
                                                        {flexRender(header.column.columnDef.header, header.getContext())}
                                                    </div>
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
                                <tr aria-hidden="true" style={{ height: `${paddingTop}px` }}>
                                    <td colSpan={visibleLeafColumnsCount} style={{ padding: 0, border: 'none' }} />
                                </tr>
                            )}
                            {virtualRows.map((virtualRow) => {
                                const rowIndex = virtualRow.index;
                                const row = rows[rowIndex];
                                if (!row) return null;
                                const rowData = row.original;
                                const lowConf = (rowData.parsing_confidence ?? 1) < LOW_CONFIDENCE_THRESHOLD;
                                const highlighted = normalizedHighlightRowIds.includes(Number(row.id));
                                const rowClass = `${lowConf ? 'row-low-conf' : ''} ${highlighted ? 'row-highlighted' : ''}`;

                                return (
                                    <tr
                                        key={row.id}
                                        data-rowid={Number(row.id)}
                                        data-index={rowIndex}
                                        style={{ height: `${rowHeight}px` }}
                                        className={rowClass}
                                    >
                                        {row.getVisibleCells().map((cell) => {
                                            const cellKey = `${row.id}:${cell.column.id}`;
                                            const isSelected = selectedCells.has(cellKey);

                                            // Use index from list of visible columns to ensure drag selection works with reorder
                                            const colIndex = visibleColumnIndexMap[cell.column.id] ?? -1;

                                            // Style Resolution: Cell Style > Column Style > Default
                                            const colStyle = columnStyles[cell.column.id] || {};
                                            const cStyle = cellStyles[cellKey] || {};
                                            const pinnedStyle = getPinnedStyles(cell.column.id, false);
                                            const isPinned = cell.column.getIsPinned() === 'left';
                                            const isDetailTriggerCell = ['row_number', 'operation_number', 'transaction_date', 'day'].includes(cell.column.id);
                                            const renderReadOnlyCell = ['row_number', 'operation_number', 'transaction_date', 'day'].includes(cell.column.id);
                                            const highlightedColumn = highlightedColumnId === cell.column.id;

                                            const finalStyle: CSSProperties = {
                                                ...pinnedStyle,
                                                textAlign: cStyle.textAlign || colStyle.textAlign || 'left',
                                                backgroundColor:
                                                    cStyle.backgroundColor ||
                                                    colStyle.backgroundColor,
                                            };

                                            return (
                                                <td
                                                    key={cell.id}
                                                    style={finalStyle}
                                                    className={`${isDetailTriggerCell ? 'cursor-pointer' : 'cursor-default'} ${isPinned ? 'pinned-cell' : ''} ${highlightedColumn ? 'bg-primary/10 text-primary' : ''} select-none border border-table-border text-table-text ${cellPadding} ${isSelected ? 'ring-2 ring-inset ring-primary z-10 bg-table-row-selected' : ''}`}
                                                    onClick={(e) => {
                                                        if (isDetailTriggerCell) {
                                                            e.stopPropagation();
                                                            setDetailRow(row.original);
                                                            return;
                                                        }
                                                        handleCellClick(e, cellKey);
                                                        maybeExpandColumnForClippedCell(e, cell.column.id);
                                                    }}
                                                    onMouseDown={(e) => handleCellMouseDown(e, row.id, cell.column.id, rowIndex, colIndex)}
                                                    onMouseEnter={() => handleCellMouseEnter(rowIndex, colIndex)}
                                                    onContextMenu={(e) => handleCellContextMenu(e, cellKey)}
                                                >
                                                    {renderReadOnlyCell ? (
                                                        flexRender(cell.column.columnDef.cell, cell.getContext())
                                                    ) : (
                                                        <EditableCell
                                                            value={cell.getValue()}
                                                            displayValue={
                                                                cell.column.id === 'transaction_type'
                                                                    ? resolveTransactionTypeDisplay(row.original)
                                                                    : cell.column.id === 'source_type'
                                                                        ? resolveSourceDisplay(row.original)
                                                                        : undefined
                                                            }
                                                            rowId={Number(row.id)}
                                                            columnId={cell.column.id}
                                                            cellType={columnTypeMap[cell.column.id] || 'text'}
                                                            options={columnOptionsMap[cell.column.id]}
                                                            onSave={saveEdit}
                                                            onCancel={cancelEdit}
                                                            isEditing={editingCell?.rowId === Number(row.id) && editingCell?.columnId === cell.column.id}
                                                            onStartEdit={() => {
                                                                restoreTemporaryExpandedColumn();
                                                                startEdit(Number(row.id), cell.column.id);
                                                            }}
                                                        />
                                                    )}
                                                </td>
                                            );
                                        })}
                                    </tr>
                                );
                            })}
                            {paddingBottom > 0 && (
                                <tr aria-hidden="true" style={{ height: `${paddingBottom}px` }}>
                                    <td colSpan={visibleLeafColumnsCount} style={{ padding: 0, border: 'none' }} />
                                </tr>
                            )}
                        </tbody>
                                </table>
                            </div>
                        </div>
                    </DndContext>
                </div>
            )}

            {/* Details Drawer */}
            <Sheet
                open={Boolean(detailRow)}
                onClose={() => setDetailRow(null)}
                width={520}
                ariaLabel="Детали транзакции"
                title={
                    <div style={{ minWidth: 0 }}>
                        <div className="tx-detail-eyebrow">
                            Транзакция · #{detailRow?.id ?? ''}
                        </div>
                        <h3
                            className="sp-sheet-title"
                            style={{
                                fontFamily: "var(--font-display, 'Instrument Serif', serif)",
                                fontSize: 22,
                                fontWeight: 400,
                                letterSpacing: '-0.01em',
                                marginTop: 4,
                            }}
                        >
                            Детали операции
                        </h3>
                    </div>
                }
                subtitle={
                    detailRow ? (
                        <>
                            {detailRow.parsing_method ? `Метод · ${detailRow.parsing_method}` : 'Метод · —'}
                            {' · '}
                            Уверенность ·{' '}
                            {detailRow.parsing_confidence !== null && detailRow.parsing_confidence !== undefined
                                ? `${Math.round((detailRow.parsing_confidence as number) * 100)}%`
                                : '—'}
                        </>
                    ) : null
                }
            >
                {detailRow ? (
                    <div className="tx-detail">
                        <div>
                            <div className="tx-detail-eyebrow">Сумма</div>
                            <div className="tx-detail-amount" style={{ marginTop: 6 }}>
                                {formatAmount(detailRow.amount)}
                                <span className="tx-detail-amount-currency">
                                    {detailRow.currency || ''}
                                </span>
                            </div>
                            {detailRow.application_mapped || detailRow.operator_raw ? (
                                <div className="tx-detail-receiver" style={{ marginTop: 8 }}>
                                    {detailRow.application_mapped || detailRow.operator_raw}
                                </div>
                            ) : null}
                        </div>

                        <div className="tx-detail-meta-grid">
                            <div className="tx-detail-meta-cell">
                                <span className="tx-detail-meta-label">Дата</span>
                                <span className="tx-detail-meta-value">
                                    {detailRow.transaction_date
                                        ? formatDateTime(new Date(detailRow.transaction_date))
                                        : '—'}
                                </span>
                            </div>
                            <div className="tx-detail-meta-cell">
                                <span className="tx-detail-meta-label">Тип</span>
                                <span className="tx-detail-meta-value">
                                    {resolveTransactionTypeDisplay(detailRow) || '—'}
                                </span>
                            </div>
                            <div className="tx-detail-meta-cell">
                                <span className="tx-detail-meta-label">Карта</span>
                                <span className="tx-detail-meta-value">
                                    {detailRow.card_last_4 ? `•••• ${detailRow.card_last_4}` : '—'}
                                </span>
                            </div>
                            <div className="tx-detail-meta-cell">
                                <span className="tx-detail-meta-label">Источник</span>
                                <span className="tx-detail-meta-value">
                                    {resolveSourceDisplay(detailRow) || '—'}
                                </span>
                            </div>
                        </div>

                        <div>
                            <h4 className="tx-detail-section-title">Исходный текст</h4>
                            <div className="tx-detail-raw" style={{ marginTop: 8 }}>
                                {detailRawLoading ? (
                                    <span style={{ color: 'var(--text-muted)' }}>Загрузка…</span>
                                ) : (
                                    detailRawMessage || '—'
                                )}
                            </div>
                        </div>

                        <div>
                            <h4 className="tx-detail-section-title" style={{ marginBottom: 8 }}>
                                Распарсенные поля
                            </h4>
                            <div className="tx-detail-fields">
                                {[
                                    { label: 'Оператор', value: detailRow.operator_raw || '—' },
                                    { label: 'Приложение', value: detailRow.application_mapped || '—' },
                                    { label: 'Валюта', value: detailRow.currency || '—' },
                                    {
                                        label: 'Остаток',
                                        value: detailRow.balance_after
                                            ? formatAmount(detailRow.balance_after)
                                            : '—',
                                    },
                                    { label: 'P2P', value: detailRow.is_p2p ? 'да' : 'нет' },
                                ].map((item) => (
                                    <div key={item.label} className="tx-detail-field">
                                        <span className="tx-detail-field-label">{item.label}</span>
                                        <span className="tx-detail-field-value">{item.value}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                ) : null}
            </Sheet>

        </div>
    );
};
