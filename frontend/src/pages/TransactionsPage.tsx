/**
 * Transactions Page Component
 * Offline-first: loads from IndexedDB, manual sync to server, local filtering/sorting/pagination
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Transaction } from '../services/api';
import { TransactionTable } from '../components/TransactionTable';
import { useOfflineTransactions } from '../hooks/useOfflineTransactions';
import { AddTransactionModal } from '../components/AddTransactionModal';
import { transactionsApi, CreateTransactionRequest, referenceApi } from '../services/api';

type SortState = { sort_by: string; sort_dir: 'asc' | 'desc' };

type FiltersState = {
    search?: string;
    dateFrom?: string;
    dateTo?: string;
    operators?: string[];
    apps?: string[];
    amountMin?: string;
    amountMax?: string;
    source_channel?: 'TELEGRAM' | 'SMS' | 'MANUAL';
    transaction_type?: 'DEBIT' | 'CREDIT' | 'CONVERSION' | 'REVERSAL';
    transaction_types?: string[];
    currency?: 'ALL' | 'UZS' | 'USD';
    card?: string;
    days_of_week?: number[];
};

export function TransactionsPage() {
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(100);
    const [sort, setSort] = useState<SortState>({ sort_by: 'transaction_date', sort_dir: 'asc' });
    const [filters, setFilters] = useState<FiltersState>({ currency: 'ALL' });
    const [addModalOpen, setAddModalOpen] = useState(false);
    const [highlightRowId, setHighlightRowId] = useState<number | null>(null);

    const {
        data,
        isLoading: offlineLoading,
        isOfflineReady,
        syncProgress,
        syncFromServer,
        upsertTransactions,
        removeTransactions,
        updateTransactionFields,
        lastSyncAt,
    } = useOfflineTransactions();

    const filteredData = useMemo(() => {
        const search = (filters.search || '').trim().toLowerCase();

        const dateToEnd = filters.dateTo ? new Date(filters.dateTo) : null;
        if (dateToEnd) {
            dateToEnd.setHours(23, 59, 59, 999);
        }

        return data.filter((tx: Transaction) => {
            const txDate = tx.transaction_date ? new Date(tx.transaction_date) : null;

            if (filters.currency && filters.currency !== 'ALL' && tx.currency !== filters.currency) return false;
            if (filters.dateFrom && txDate && txDate < new Date(filters.dateFrom)) return false;
            if (dateToEnd && txDate && txDate > dateToEnd) return false;

            if (filters.days_of_week?.length && txDate) {
                const dayIdx = txDate.getDay();
                if (!filters.days_of_week.includes(dayIdx)) return false;
            }

            const amount = tx.amount ? Math.abs(parseFloat(tx.amount)) : undefined;
            if (filters.amountMin && amount !== undefined && !Number.isNaN(amount) && amount < parseFloat(filters.amountMin)) return false;
            if (filters.amountMax && amount !== undefined && !Number.isNaN(amount) && amount > parseFloat(filters.amountMax)) return false;

            if (filters.operators?.length) {
                const op = (tx.operator_raw || '').toLowerCase();
                if (!filters.operators.some((o) => op.includes(o.toLowerCase()))) return false;
            }

            if (filters.apps?.length) {
                const app = (tx.application_mapped || '').toLowerCase();
                if (!filters.apps.some((a) => app.includes(a.toLowerCase()))) return false;
            }

            if (filters.transaction_type && tx.transaction_type !== filters.transaction_type) return false;
            if (filters.transaction_types?.length && !filters.transaction_types.includes(tx.transaction_type)) return false;
            if (filters.source_channel && tx.source_channel !== filters.source_channel) return false;
            if (filters.card) {
                if (tx.card_last_4 !== filters.card) return false;
            }

            if (search) {
                const blob = `${tx.operator_raw || ''} ${tx.application_mapped || ''} ${tx.raw_message || ''} ${tx.amount || ''} ${tx.currency || ''}`.toLowerCase();
                if (!blob.includes(search)) return false;
            }

            return true;
        });
    }, [data, filters]);

    const sortComparator = useCallback((key: string | undefined, dir: 'asc' | 'desc') => {
        const sortKey = key || 'transaction_date';
        const dirMultiplier = dir === 'asc' ? 1 : -1;
        const getValue = (tx: Transaction) => {
            const value = (tx as any)[sortKey];
            if (sortKey.includes('date')) {
                return value ? new Date(value).getTime() : 0;
            }
            if (sortKey === 'amount' || sortKey === 'balance_after') {
                const num = parseFloat(value ?? '0');
                return Number.isNaN(num) ? 0 : num;
            }
            if (typeof value === 'string') return value.toLowerCase();
            return value ?? '';
        };
        return (a: Transaction, b: Transaction) => {
            const av = getValue(a);
            const bv = getValue(b);
            if (av < bv) return -1 * dirMultiplier;
            if (av > bv) return 1 * dirMultiplier;
            return 0;
        };
    }, [sort.sort_by, sort.sort_dir]);

    const sortedData = useMemo(() => {
        return [...filteredData].sort(sortComparator(sort.sort_by, sort.sort_dir));
    }, [filteredData, sort.sort_by, sort.sort_dir, sortComparator]);

    const allSortedData = useMemo(() => {
        return [...data].sort(sortComparator(sort.sort_by, sort.sort_dir));
    }, [data, sort.sort_by, sort.sort_dir, sortComparator]);

    // Load operators from reference dictionary
    const { data: referenceData } = useQuery({
        queryKey: ['reference-operators-for-autocomplete'],
        queryFn: () => referenceApi.getOperators({ page_size: 500 }),
        staleTime: 5 * 60 * 1000, // 5 minutes
    });

    // Combine operators from transactions and reference
    const operatorOptions = useMemo(() => {
        const set = new Set<string>();
        // From transactions
        data.forEach((tx) => {
            if (tx.operator_raw) set.add(tx.operator_raw);
        });
        // From reference dictionary
        referenceData?.items?.forEach((op) => {
            if (op.operator_name) set.add(op.operator_name);
        });
        return Array.from(set).sort((a, b) => a.localeCompare(b));
    }, [data, referenceData]);

    // Combine apps from transactions and reference
    const appOptions = useMemo(() => {
        const set = new Set<string>();
        // From transactions
        data.forEach((tx) => {
            if (tx.application_mapped) set.add(tx.application_mapped);
        });
        // From reference dictionary
        referenceData?.items?.forEach((op) => {
            if (op.application_name) set.add(op.application_name);
        });
        return Array.from(set).sort((a, b) => a.localeCompare(b));
    }, [data, referenceData]);

    const total = sortedData.length;

    useEffect(() => {
        const maxPage = Math.max(1, Math.ceil(total / pageSize));
        if (page > maxPage) {
            setPage(maxPage);
        }
    }, [page, pageSize, total]);

    const paginatedItems = useMemo(() => {
        const start = (page - 1) * pageSize;
        const end = start + pageSize;
        return sortedData.slice(start, end);
    }, [sortedData, page, pageSize]);

    const handleQueryChange = useCallback((next: Partial<FiltersState> & { sort_by?: string; sort_dir?: 'asc' | 'desc'; search?: string; filters?: any }) => {
        if (next.sort_by || next.sort_dir) {
            setSort({
                sort_by: next.sort_by || sort.sort_by,
                sort_dir: next.sort_dir || sort.sort_dir,
            });
        }

        const { filters: incomingFilters, ...rest } = next;
        const updatedFilters: FiltersState = { ...rest };
        if (next.search !== undefined) {
            updatedFilters.search = next.search;
        }

        if (incomingFilters) {
            updatedFilters.dateFrom = incomingFilters.dateFrom || undefined;
            updatedFilters.dateTo = incomingFilters.dateTo || undefined;
            updatedFilters.amountMin = incomingFilters.amountMin || undefined;
            updatedFilters.amountMax = incomingFilters.amountMax || undefined;
            updatedFilters.currency = incomingFilters.currency || undefined;
            updatedFilters.operators = incomingFilters.operators && incomingFilters.operators.length ? incomingFilters.operators : undefined;
            updatedFilters.apps = incomingFilters.apps && incomingFilters.apps.length ? incomingFilters.apps : undefined;
            updatedFilters.source_channel = incomingFilters.sourceType && incomingFilters.sourceType !== 'ALL' ? incomingFilters.sourceType : undefined;
            updatedFilters.transaction_type = incomingFilters.transactionTypes?.length === 1 ? incomingFilters.transactionTypes[0] : undefined;
            updatedFilters.transaction_types = incomingFilters.transactionTypes && incomingFilters.transactionTypes.length > 1 ? incomingFilters.transactionTypes : undefined;
            updatedFilters.card = incomingFilters.cardId || undefined;
            updatedFilters.days_of_week = incomingFilters.daysOfWeek && incomingFilters.daysOfWeek.length ? incomingFilters.daysOfWeek : undefined;
        }

        if (Object.keys(updatedFilters).length > 0) {
            setFilters(prev => ({ ...prev, ...updatedFilters }));
        }
        setPage(1);
    }, [sort.sort_by, sort.sort_dir]);

    const handlePageChange = useCallback((nextPage: number) => {
        setPage(Math.max(1, nextPage));
    }, []);

    const handlePageSizeChange = useCallback((nextSize: number) => {
        setPageSize(nextSize);
        setPage(1);
    }, []);

    const handleTransactionsUpdated = useCallback((txs: Transaction[]) => {
        upsertTransactions(txs);
    }, [upsertTransactions]);

    const handleTransactionsDeleted = useCallback((ids: number[]) => {
        removeTransactions(ids);
    }, [removeTransactions]);

    const handleTransactionsFieldsUpdated = useCallback((updates: Array<{ id: number; fields: Record<string, any> }>) => {
        updateTransactionFields(updates);
    }, [updateTransactionFields]);

    const handleCreateTransaction = useCallback(async (payload: CreateTransactionRequest) => {
        const created = await transactionsApi.createTransaction(payload);
        upsertTransactions([created]);
        const nextTotal = total + 1;
        const nextMaxPage = Math.max(1, Math.ceil(nextTotal / pageSize));
        setPage(nextMaxPage);
        setHighlightRowId(created.id);
        setAddModalOpen(false);
    }, [pageSize, total, upsertTransactions]);

    useEffect(() => {
        if (!highlightRowId) return;
        const t = setTimeout(() => setHighlightRowId(null), 2000);
        return () => clearTimeout(t);
    }, [highlightRowId]);

    return (
        <div className="h-full flex flex-col bg-bg">
            <div className="flex-1 overflow-hidden p-4">
                <div className="h-full flex flex-col bg-surface border border-table-border rounded-lg shadow-sm">
                    <div className="flex-1 overflow-hidden p-0 pb-6">
                        <div className="flex flex-col gap-3 px-4 py-2 border-b border-table-border bg-surface-2">
                            <div className="flex items-center justify-between">
                                <div className="text-sm text-foreground-secondary">
                                    {isOfflineReady ? 'Локальный кеш загружен' : 'Кеш отсутствует, выполняется синхронизация'}
                                    {lastSyncAt ? ` · Последняя синхронизация: ${new Date(lastSyncAt).toLocaleString()}` : ''}
                                </div>
                                <button
                                    onClick={() => syncFromServer()}
                                    disabled={offlineLoading || syncProgress.status === 'running'}
                                    className="px-3 py-1.5 text-sm font-medium text-foreground bg-surface border border-border rounded hover:bg-surface-2 disabled:opacity-60"
                                >
                                    {syncProgress.status === 'running'
                                        ? `Синхронизация... (${syncProgress.downloaded} записей)`
                                        : 'Синхронизировать'}
                                </button>
                            </div>
                            <div className="px-3 py-2 text-sm font-medium text-foreground bg-surface shadow-sm rounded-md border border-table-border">
                                Всего записей: {total}
                            </div>
                        </div>
                        <TransactionTable
                            data={paginatedItems}
                            total={total}
                            page={page}
                            pageSize={pageSize}
                            isLoading={offlineLoading && !isOfflineReady}
                            exportViewRows={sortedData}
                            exportAllRows={allSortedData}
                            highlightRowId={highlightRowId}
                            onAddClick={() => setAddModalOpen(true)}
                            onTransactionsUpdated={handleTransactionsUpdated}
                            onTransactionsDeleted={handleTransactionsDeleted}
                            onTransactionsFieldsUpdated={handleTransactionsFieldsUpdated}
                            onQueryChange={handleQueryChange}
                            onPageChange={handlePageChange}
                            onPageSizeChange={handlePageSizeChange}
                            operatorOptions={operatorOptions}
                            appOptions={appOptions}
                        />
                    </div>
                </div>
            </div>
            <AddTransactionModal
                isOpen={addModalOpen}
                onClose={() => setAddModalOpen(false)}
                onSubmit={handleCreateTransaction}
                operatorOptions={operatorOptions}
                appOptions={appOptions}
            />
        </div>
    );
}
