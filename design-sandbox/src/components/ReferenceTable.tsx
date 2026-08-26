import { useEffect, useMemo, useRef, useState } from 'react';
import {
    ColumnDef,
    flexRender,
    getCoreRowModel,
    getSortedRowModel,
    SortingState,
    useReactTable,
} from '@tanstack/react-table';
import { motion, AnimatePresence } from 'motion/react';
import { ArrowUp, ArrowDown, ChevronsUpDown, Loader2, Trash2, Pencil, FileX } from 'lucide-react';
import type { OperatorReference } from '../services/api';

type EditableField = keyof Pick<OperatorReference, 'operator_name' | 'application_name' | 'is_p2p' | 'is_active'>;
type Density = 'standard' | 'compact';

interface ReferenceTableProps {
    data: OperatorReference[];
    isLoading?: boolean;
    total: number;
    page: number;
    pageSize: number | 'all';
    density?: Density;
    selectedIds: Set<number>;
    onToggleRow: (id: number) => void;
    onToggleAll: (ids: number[], all: boolean) => void;
    onPageChange: (page: number) => void;
    onPageSizeChange: (size: number | 'all') => void;
    onUpdate: (id: number, field: EditableField, value: any) => void;
    onDelete: (id: number) => void;
    onEditFull?: (item: OperatorReference) => void;
}

export function ReferenceTable({
    data,
    isLoading,
    total,
    page,
    pageSize,
    density = 'standard',
    selectedIds,
    onToggleRow,
    onToggleAll,
    onPageChange,
    onPageSizeChange,
    onUpdate,
    onDelete,
    onEditFull,
}: ReferenceTableProps) {
    const [sorting, setSorting] = useState<SortingState>([{ id: 'operator_name', desc: false }]);
    const isAll = pageSize === 'all';
    const resolvedPageSize = isAll ? (total || data.length || 1) : pageSize;
    const pageCount = isAll ? 1 : Math.max(1, Math.ceil(total / resolvedPageSize));
    const pageStart = total === 0 ? 0 : isAll ? 1 : (page - 1) * resolvedPageSize + 1;
    const pageEnd = total === 0 ? 0 : isAll ? total : Math.min(page * resolvedPageSize, total);
    const disablePaging = isAll || total <= resolvedPageSize;
    const displayPage = isAll ? 1 : Math.min(page, pageCount);

    const visibleIds = useMemo(() => data.map((d) => d.id), [data]);
    const allChecked = data.length > 0 && data.every((d) => selectedIds.has(d.id));
    const someChecked = !allChecked && data.some((d) => selectedIds.has(d.id));

    const columns = useMemo<ColumnDef<OperatorReference>[]>(
        () => [
            {
                id: 'select',
                header: () => (
                    <input
                        type="checkbox"
                        className="rf-toggle"
                        aria-label="Выбрать все"
                        checked={allChecked}
                        ref={(el) => {
                            if (el) el.indeterminate = someChecked;
                        }}
                        onChange={(e) => onToggleAll(visibleIds, e.target.checked)}
                    />
                ),
                cell: ({ row }) => (
                    <input
                        type="checkbox"
                        className="rf-toggle"
                        aria-label={`Выбрать «${row.original.operator_name}»`}
                        checked={selectedIds.has(row.original.id)}
                        onChange={() => onToggleRow(row.original.id)}
                    />
                ),
                enableSorting: false,
                meta: { center: true, narrow: true } as any,
            },
            {
                accessorKey: 'operator_name',
                header: 'Оператор',
                cell: ({ row, getValue }) => (
                    <EditableTextCell
                        value={getValue<string>() || ''}
                        placeholder="—"
                        onCommit={(val) => onUpdate(row.original.id, 'operator_name', val)}
                    />
                ),
            },
            {
                accessorKey: 'application_name',
                header: 'Приложение',
                cell: ({ row, getValue }) => (
                    <EditableTextCell
                        value={getValue<string>() || ''}
                        placeholder="—"
                        onCommit={(val) => onUpdate(row.original.id, 'application_name', val)}
                    />
                ),
            },
            {
                accessorKey: 'is_p2p',
                header: 'P2P',
                cell: ({ row, getValue }) => {
                    const on = !!getValue<boolean>();
                    return (
                        <button
                            type="button"
                            aria-pressed={on}
                            aria-label={on ? 'P2P включён' : 'P2P выключен'}
                            onClick={() => onUpdate(row.original.id, 'is_p2p', !on)}
                            className="rf-row-action"
                            title={on ? 'P2P · нажмите чтобы выключить' : 'не P2P · нажмите чтобы включить'}
                        >
                            <span className={`rf-toggle-dot${on ? ' is-on' : ''}`} />
                        </button>
                    );
                },
                meta: { center: true, narrow: true } as any,
            },
            {
                accessorKey: 'is_active',
                header: 'Активен',
                cell: ({ row, getValue }) => (
                    <input
                        type="checkbox"
                        className="rf-toggle"
                        aria-label={`Активен: ${row.original.operator_name}`}
                        checked={!!getValue<boolean>()}
                        onChange={(e) => onUpdate(row.original.id, 'is_active', e.target.checked)}
                    />
                ),
                meta: { center: true, narrow: true } as any,
            },
            {
                id: 'actions',
                header: '',
                cell: ({ row }) => (
                    <div className="rf-row-actions">
                        {onEditFull ? (
                            <button
                                type="button"
                                onClick={() => onEditFull(row.original)}
                                className="rf-row-action"
                                title="Редактировать"
                                aria-label={`Редактировать ${row.original.operator_name}`}
                            >
                                <Pencil size={14} />
                            </button>
                        ) : null}
                        <button
                            type="button"
                            onClick={() => onDelete(row.original.id)}
                            className="rf-row-action is-danger"
                            title="Удалить"
                            aria-label={`Удалить ${row.original.operator_name}`}
                        >
                            <Trash2 size={14} />
                        </button>
                    </div>
                ),
                enableSorting: false,
                meta: { center: true, narrow: true } as any,
            },
        ],
        [allChecked, someChecked, visibleIds, selectedIds, onToggleAll, onToggleRow, onUpdate, onDelete, onEditFull]
    );

    const table = useReactTable({
        data,
        columns,
        state: { sorting },
        onSortingChange: setSorting,
        getCoreRowModel: getCoreRowModel(),
        getSortedRowModel: getSortedRowModel(),
        manualPagination: true,
        pageCount,
    });

    return (
        <div className="rf-table-wrap">
            <div className="rf-table-scroll">
                <table className={`rf-table density-${density}`}>
                    <thead>
                        {table.getHeaderGroups().map((hg) => (
                            <tr key={hg.id}>
                                {hg.headers.map((header) => {
                                    const meta = (header.column.columnDef.meta as any) || {};
                                    const canSort = header.column.getCanSort();
                                    const sortDir = header.column.getIsSorted();
                                    const cls = ['', meta.center ? 'is-center' : '', meta.narrow ? 'is-narrow' : '']
                                        .filter(Boolean)
                                        .join(' ');
                                    return (
                                        <th key={header.id} className={cls}>
                                            {header.isPlaceholder ? null : canSort ? (
                                                <button
                                                    type="button"
                                                    className={`rf-th-sort${sortDir ? ' is-sorted' : ''}`}
                                                    onClick={header.column.getToggleSortingHandler()}
                                                >
                                                    {flexRender(header.column.columnDef.header, header.getContext())}
                                                    <span className="rf-th-sort-icon">
                                                        {sortDir === 'asc' ? (
                                                            <ArrowUp size={11} />
                                                        ) : sortDir === 'desc' ? (
                                                            <ArrowDown size={11} />
                                                        ) : (
                                                            <ChevronsUpDown size={11} />
                                                        )}
                                                    </span>
                                                </button>
                                            ) : (
                                                flexRender(header.column.columnDef.header, header.getContext())
                                            )}
                                        </th>
                                    );
                                })}
                            </tr>
                        ))}
                    </thead>
                    <tbody>
                        {isLoading ? (
                            <tr>
                                <td colSpan={columns.length}>
                                    <div className="rf-empty">
                                        <Loader2 size={20} className="tg-msg-process-spin" />
                                        <div>Загружаем справочник…</div>
                                    </div>
                                </td>
                            </tr>
                        ) : data.length === 0 ? (
                            <tr>
                                <td colSpan={columns.length}>
                                    <div className="rf-empty">
                                        <div className="rf-empty-icon">
                                            <FileX size={22} />
                                        </div>
                                        <div className="rf-empty-title">Записей нет</div>
                                        <div className="rf-empty-sub">
                                            Очистите фильтры или добавьте первую запись через кнопку «+ Добавить».
                                        </div>
                                    </div>
                                </td>
                            </tr>
                        ) : (
                            <AnimatePresence initial={false}>
                                {table.getRowModel().rows.map((row, idx) => {
                                    const rowSelected = selectedIds.has(row.original.id);
                                    const inactive = !row.original.is_active;
                                    return (
                                        <motion.tr
                                            key={row.original.id}
                                            layout="position"
                                            initial={{ opacity: 0, y: 4 }}
                                            animate={{
                                                opacity: 1,
                                                y: 0,
                                                transition: {
                                                    duration: 0.18,
                                                    ease: [0.16, 1, 0.3, 1],
                                                    delay: idx < 12 ? idx * 0.012 : 0,
                                                },
                                            }}
                                            exit={{ opacity: 0, transition: { duration: 0.12 } }}
                                            className={[
                                                rowSelected ? 'is-selected' : '',
                                                inactive ? 'is-inactive' : '',
                                            ]
                                                .filter(Boolean)
                                                .join(' ')}
                                        >
                                            {row.getVisibleCells().map((cell) => {
                                                const meta = (cell.column.columnDef.meta as any) || {};
                                                const cls = [meta.center ? 'is-center' : '', meta.narrow ? 'is-narrow' : '']
                                                    .filter(Boolean)
                                                    .join(' ');
                                                return (
                                                    <td key={cell.id} className={cls}>
                                                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                                                    </td>
                                                );
                                            })}
                                        </motion.tr>
                                    );
                                })}
                            </AnimatePresence>
                        )}
                    </tbody>
                </table>
            </div>

            <div className="rf-footer">
                <div className="rf-footer-meta">
                    <strong>{total === 0 ? 0 : pageStart}</strong>–<strong>{pageEnd}</strong> из{' '}
                    <strong>{total}</strong>
                </div>
                <div className="rf-pagination">
                    <select
                        value={isAll ? 'all' : String(pageSize)}
                        onChange={(e) => {
                            const val = e.target.value;
                            if (val === 'all') onPageSizeChange('all');
                            else onPageSizeChange(Number(val));
                        }}
                        className="rf-app-select"
                        aria-label="Размер страницы"
                    >
                        <option value="all">Все</option>
                        {[20, 50, 100, 200, 500, 1000].map((s) => (
                            <option key={s} value={String(s)}>
                                {`${s} / стр`}
                            </option>
                        ))}
                    </select>
                    <button
                        type="button"
                        className="rf-page-btn"
                        onClick={() => onPageChange(Math.max(1, page - 1))}
                        disabled={disablePaging || displayPage === 1}
                        aria-label="Предыдущая страница"
                    >
                        ‹
                    </button>
                    <span className="rf-pagination-page">
                        {displayPage} / {pageCount}
                    </span>
                    <button
                        type="button"
                        className="rf-page-btn"
                        onClick={() => onPageChange(page + 1)}
                        disabled={disablePaging || page * resolvedPageSize >= total}
                        aria-label="Следующая страница"
                    >
                        ›
                    </button>
                </div>
            </div>
        </div>
    );
}

function EditableTextCell({
    value,
    placeholder,
    onCommit,
}: {
    value: string;
    placeholder?: string;
    onCommit: (v: string) => void;
}) {
    const [draft, setDraft] = useState(value);
    const ref = useRef<HTMLInputElement | null>(null);

    useEffect(() => {
        setDraft(value);
    }, [value]);

    const commit = () => {
        const trimmed = draft.trim();
        if (trimmed !== value.trim()) onCommit(trimmed);
    };

    return (
        <input
            ref={ref}
            className="rf-cell-input"
            value={draft}
            placeholder={placeholder}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    (e.currentTarget as HTMLInputElement).blur();
                }
                if (e.key === 'Escape') {
                    setDraft(value);
                    (e.currentTarget as HTMLInputElement).blur();
                }
            }}
        />
    );
}
