/**
 * Transactions Page Component
 * Uses server-side pagination/filtering/sorting to reduce frontend workload
 */
import { useCallback, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { transactionsApi, TransactionsQueryParams, TransactionListResponse } from '../services/api';
import { TransactionTable } from '../components/TransactionTable';

type SortState = { sort_by: string; sort_dir: 'asc' | 'desc' };

type FiltersState = {
    search?: string;
    dateFrom?: string;
    dateTo?: string;
    operators?: string[];
    apps?: string[];
    amountMin?: string;
    amountMax?: string;
    parsing_method?: string;
    confidence_min?: number;
    confidence_max?: number;
    parsingMethod?: 'REGEX' | 'GPT' | 'MANUAL';
    lowConfidence?: boolean;
    source_type?: 'AUTO' | 'MANUAL';
    transaction_type?: 'DEBIT' | 'CREDIT' | 'CONVERSION' | 'REVERSAL';
    transaction_types?: string[];
    currency?: 'UZS' | 'USD';
    card?: string;
    days_of_week?: number[];
};

export function TransactionsPage() {
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(100);
    const [sort, setSort] = useState<SortState>({ sort_by: 'transaction_date', sort_dir: 'desc' });
    const [filters, setFilters] = useState<FiltersState>({ currency: 'UZS' });

    const queryKey = useMemo(() => ['transactions', page, pageSize, sort, filters], [page, pageSize, sort, filters]);

    const { data, isLoading } = useQuery<TransactionListResponse>({
        queryKey,
        queryFn: () => {
            const params: TransactionsQueryParams = {
                page,
                page_size: pageSize,
                sort_by: sort.sort_by,
                sort_dir: sort.sort_dir,
                search: filters.search,
                date_from: filters.dateFrom,
                date_to: filters.dateTo,
                operators: filters.operators,
                apps: filters.apps,
                amount_min: filters.amountMin,
                amount_max: filters.amountMax,
                parsing_method: filters.parsing_method,
                confidence_min: filters.confidence_min,
                confidence_max: filters.confidence_max,
                source_type: filters.source_type,
                transaction_type: filters.transaction_type,
                transaction_types: filters.transaction_types,
                currency: filters.currency,
                card: filters.card,
                days_of_week: filters.days_of_week,
            };
            return transactionsApi.getTransactions(params);
        },
        refetchInterval: 30000,
    });

    const handleQueryChange = useCallback((next: Partial<FiltersState> & { sort_by?: string; sort_dir?: 'asc' | 'desc'; search?: string; filters?: any }) => {
        if (next.sort_by || next.sort_dir) {
            setSort({
                sort_by: next.sort_by || sort.sort_by,
                sort_dir: next.sort_dir || sort.sort_dir,
            });
        }

        const { sort_by, sort_dir, filters: incomingFilters, ...rest } = next;
        const updatedFilters: FiltersState = { ...rest };

        if (incomingFilters) {
            updatedFilters.dateFrom = incomingFilters.dateFrom || undefined;
            updatedFilters.dateTo = incomingFilters.dateTo || undefined;
            updatedFilters.amountMin = incomingFilters.amountMin || undefined;
            updatedFilters.amountMax = incomingFilters.amountMax || undefined;
            updatedFilters.currency = incomingFilters.currency || undefined;
            updatedFilters.operators = incomingFilters.operators && incomingFilters.operators.length ? incomingFilters.operators : undefined;
            updatedFilters.apps = incomingFilters.apps && incomingFilters.apps.length ? incomingFilters.apps : undefined;
            updatedFilters.source_type = incomingFilters.sourceType && incomingFilters.sourceType !== 'ALL' ? incomingFilters.sourceType : undefined;
            updatedFilters.transaction_type = incomingFilters.transactionTypes?.length === 1 ? incomingFilters.transactionTypes[0] : undefined;
            updatedFilters.transaction_types = incomingFilters.transactionTypes && incomingFilters.transactionTypes.length > 1 ? incomingFilters.transactionTypes : undefined;
            updatedFilters.card = incomingFilters.cardId || undefined;
            updatedFilters.days_of_week = incomingFilters.daysOfWeek && incomingFilters.daysOfWeek.length ? incomingFilters.daysOfWeek : undefined;
            updatedFilters.parsing_method = incomingFilters.parsingMethod || undefined;
            updatedFilters.lowConfidence = incomingFilters.lowConfidence || false;
            updatedFilters.confidence_max = incomingFilters.confidenceMax !== undefined
                ? incomingFilters.confidenceMax
                : (incomingFilters.lowConfidence ? 0.6 : undefined);
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

    return (
        <div className="h-full flex flex-col bg-bg">
            <div className="flex-1 overflow-hidden p-4">
                <div className="h-full flex flex-col bg-surface border border-table-border rounded-lg shadow-sm">
                    <div className="flex-1 overflow-hidden p-0">
                        <TransactionTable
                            data={data?.items || []}
                            total={data?.total || 0}
                            page={page}
                            pageSize={pageSize}
                            isLoading={isLoading}
                            onQueryChange={handleQueryChange}
                            onPageChange={handlePageChange}
                            onPageSizeChange={handlePageSizeChange}
                        />
                    </div>
                    {data && (
                        <div className="px-4 py-2 border-t border-table-border text-xs text-foreground-secondary bg-surface-2">
                            Всего записей: {data.total}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
