import { useMemo, useState, useEffect } from 'react';
import {
    ColumnDef,
    getCoreRowModel,
    getSortedRowModel,
    SortingState,
    useReactTable,
    flexRender,
} from '@tanstack/react-table';
import { Check, ChevronDown, ChevronUp, Loader2, Trash2 } from 'lucide-react';
import { OperatorReference } from '../services/api';

type EditableField = keyof Pick<OperatorReference, 'operator_name' | 'application_name' | 'is_p2p' | 'is_active'>;

interface ReferenceTableProps {
    data: OperatorReference[];
    isLoading?: boolean;
    total: number;
    page: number;
    pageSize: number | 'all';
    onPageChange: (page: number) => void;
    onPageSizeChange: (size: number | 'all') => void;
    onUpdate: (id: number, field: EditableField, value: any) => void;
    onDelete: (id: number) => void;
}

export function ReferenceTable({
    data,
    isLoading,
    total,
    page,
    pageSize,
    onPageChange,
    onPageSizeChange,
    onUpdate,
    onDelete,
}: ReferenceTableProps) {
    const [sorting, setSorting] = useState<SortingState>([{ id: 'operator_name', desc: false }]);
    const isAll = pageSize === 'all';
    const resolvedPageSize = isAll ? (total || data.length || 1) : pageSize;
    const pageCount = isAll ? 1 : Math.max(1, Math.ceil(total / resolvedPageSize));
    const pageStart = total === 0 ? 0 : isAll ? 1 : (page - 1) * resolvedPageSize + 1;
    const pageEnd = total === 0 ? 0 : isAll ? total : Math.min(page * resolvedPageSize, total);
    const disablePaging = isAll || total <= resolvedPageSize;
    const displayPage = isAll ? 1 : Math.min(page, pageCount);

    const columns = useMemo<ColumnDef<OperatorReference>[]>(
        () => [
            {
                accessorKey: 'operator_name',
                header: 'Operator / Продавец',
                cell: ({ row, getValue }) => (
                    <EditableTextCell
                        value={getValue<string>() || ''}
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
                        onCommit={(val) => onUpdate(row.original.id, 'application_name', val)}
                    />
                ),
            },
            {
                accessorKey: 'is_p2p',
                header: 'P2P',
                cell: ({ row, getValue }) => (
                    <ToggleCell
                        checked={!!getValue<boolean>()}
                        onChange={(val) => onUpdate(row.original.id, 'is_p2p', val)}
                    />
                ),
                meta: { align: 'center' } as any,
            },
            {
                accessorKey: 'is_active',
                header: 'Активен',
                cell: ({ row, getValue }) => (
                    <ToggleCell
                        checked={!!getValue<boolean>()}
                        onChange={(val) => onUpdate(row.original.id, 'is_active', val)}
                    />
                ),
                meta: { align: 'center' } as any,
            },
            {
                id: 'actions',
                header: '',
                cell: ({ row }) => (
                    <button
                        onClick={() => onDelete(row.original.id)}
                        className="text-danger hover:text-danger-hover p-2 rounded-md hover:bg-danger/10 transition-colors"
                        title="Удалить"
                    >
                        <Trash2 className="w-4 h-4" />
                    </button>
                ),
                size: 60,
            },
        ],
        [onUpdate, onDelete]
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
        <div className="border border-border rounded-lg overflow-hidden bg-surface shadow-sm h-full flex flex-col">
            <div className="overflow-auto flex-1">
                <table className="w-full min-w-[720px]">
                    <thead className="bg-table-header border-b border-table-border">
                        {table.getHeaderGroups().map((hg) => (
                            <tr key={hg.id}>
                                {hg.headers.map((header) => {
                                    const canSort = header.column.getCanSort();
                                    const sorted = header.column.getIsSorted();
                                    return (
                                        <th
                                            key={header.id}
                                            className={`px-4 py-3 text-left text-xs font-semibold text-foreground-secondary uppercase tracking-wide ${(header.column.columnDef.meta as any)?.align === 'center' ? 'text-center' : ''}`}
                                        >
                                            {canSort ? (
                                                <button
                                                    className="inline-flex items-center gap-1 hover:text-foreground"
                                                    onClick={header.column.getToggleSortingHandler()}
                                                >
                                                    {header.isPlaceholder
                                                        ? null
                                                        : header.column.columnDef.header?.toString() || ''}
                                                    {sorted === 'asc' && <ChevronUp className="w-4 h-4" />}
                                                    {sorted === 'desc' && <ChevronDown className="w-4 h-4" />}
                                                </button>
                                            ) : (
                                                header.isPlaceholder
                                                    ? null
                                                    : header.column.columnDef.header?.toString() || ''
                                            )}
                                        </th>
                                    );
                                })}
                            </tr>
                        ))}
                    </thead>
                    <tbody className="divide-y divide-border">
                        {isLoading ? (
                            <tr>
                                <td colSpan={columns.length} className="py-10 text-center text-foreground-secondary">
                                    <div className="flex items-center justify-center gap-2">
                                        <Loader2 className="w-4 h-4 animate-spin" /> Загрузка...
                                    </div>
                                </td>
                            </tr>
                        ) : data.length === 0 ? (
                            <tr>
                                <td colSpan={columns.length} className="py-10 text-center text-foreground-secondary">
                                    Нет данных
                                </td>
                            </tr>
                        ) : (
                            table.getRowModel().rows.map((row) => (
                                <tr key={row.id} className="hover:bg-table-row-hover">
                                    {row.getVisibleCells().map((cell) => {
                                        const centerCols = ['is_p2p', 'is_active', 'actions'];
                                        const isCenter = centerCols.includes(cell.column.id as string);
                                        return (
                                            <td
                                                key={cell.id}
                                                className={`px-4 py-3 text-sm text-foreground ${isCenter ? 'text-center' : ''}`}
                                            >
                                                {flexRender(cell.column.columnDef.cell, cell.getContext())}
                                            </td>
                                        );
                                    })}
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>

            <div className="flex items-center justify-between px-4 py-3 border-t border-border bg-surface-2 text-sm">
                <div className="text-foreground-secondary">
                    Показано {total === 0 ? 0 : pageStart}-{pageEnd} из {total}
                </div>
                <div className="flex items-center gap-3">
                    <select
                        value={isAll ? 'all' : String(pageSize)}
                        onChange={(e) => {
                            const val = e.target.value;
                            if (val === 'all') {
                                onPageSizeChange('all');
                            } else {
                                onPageSizeChange(Number(val));
                            }
                        }}
                        className="px-3 py-2 border border-border rounded-md bg-surface text-foreground text-sm"
                    >
                        <option value="all">Все</option>
                        {[20, 50, 100, 200, 500, 1000].map((size) => (
                            <option key={size} value={size.toString()}>
                                {`${size} / стр`}
                            </option>
                        ))}
                    </select>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => onPageChange(Math.max(1, page - 1))}
                            disabled={disablePaging || displayPage === 1}
                            className="px-3 py-2 border border-border rounded-md disabled:opacity-50 hover:bg-surface-2"
                        >
                            Назад
                        </button>
                        <div className="px-2">
                            {displayPage} / {pageCount}
                        </div>
                        <button
                            onClick={() => onPageChange(page + 1)}
                            disabled={disablePaging || page * resolvedPageSize >= total}
                            className="px-3 py-2 border border-border rounded-md disabled:opacity-50 hover:bg-surface-2"
                        >
                            Вперёд
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}

function EditableTextCell({ value, onCommit }: { value: string; onCommit: (v: string) => void }) {
    const [draft, setDraft] = useState(value);

    useEffect(() => {
        setDraft(value);
    }, [value]);

    const commit = () => {
        const trimmed = draft.trim();
        if (trimmed !== value.trim()) onCommit(trimmed);
    };

    return (
        <input
            className="w-full bg-transparent border border-border/60 rounded-md px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
                if (e.key === 'Enter') {
                    (e.target as HTMLInputElement).blur();
                }
                if (e.key === 'Escape') {
                    setDraft(value);
                    (e.target as HTMLInputElement).blur();
                }
            }}
        />
    );
}

function ToggleCell({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
    return (
        <label className="inline-flex items-center cursor-pointer select-none">
            <input
                type="checkbox"
                className="sr-only peer"
                checked={checked}
                onChange={(e) => onChange(e.target.checked)}
            />
            <div className="w-9 h-5 bg-border peer-checked:bg-primary rounded-full relative transition-colors">
                <span
                    className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-surface shadow-sm transition-all ${checked ? 'translate-x-4' : ''
                        }`}
                />
            </div>
            {checked && <Check className="w-4 h-4 text-primary ml-2" />}
        </label>
    );
}
