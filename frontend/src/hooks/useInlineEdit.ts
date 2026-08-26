import { useState, useCallback } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { transactionsApi, TransactionUpdateRequest, Transaction } from '../services/api';
import { useToast } from '../components/Toast';

export interface EditingCell {
    rowId: number;
    columnId: string;
}

export interface UseInlineEditOptions {
    onSuccess?: (params: { rowId: number; columnId: string; updated?: Transaction }) => void;
    onError?: (params: { error: Error; rowId: number; columnId: string }) => void;
}

export const useInlineEdit = (options?: UseInlineEditOptions) => {
    const queryClient = useQueryClient();
    const [editingCell, setEditingCell] = useState<EditingCell | null>(null);
    const { showToast } = useToast();

    const updateMutation = useMutation({
        mutationFn: ({ id, data }: { id: number; data: TransactionUpdateRequest }) =>
            transactionsApi.updateTransaction(id, data),
        onMutate: async ({ id, data }) => {
            await queryClient.cancelQueries({ queryKey: ['transactions-server'], exact: false });
            const snapshot = queryClient.getQueriesData({ queryKey: ['transactions-server'], exact: false });
            queryClient.setQueriesData(
                { queryKey: ['transactions-server'], exact: false },
                (old: any) => {
                    if (!old?.items) return old;
                    return {
                        ...old,
                        items: old.items.map((t: Transaction) =>
                            t.id === id ? { ...t, ...data } : t,
                        ),
                    };
                },
            );
            return { snapshot };
        },
        onSuccess: (response, variables) => {
            queryClient.setQueriesData(
                { queryKey: ['transactions-server'], exact: false },
                (old: any) => {
                    if (!old?.items) return old;
                    return {
                        ...old,
                        items: old.items.map((t: Transaction) =>
                            t.id === variables.id ? response.transaction : t,
                        ),
                    };
                },
            );
            queryClient.invalidateQueries({ queryKey: ['transactions-init'] });
            // Description is resolved at the operator level: a single edit changes the
            // description for every receipt of the same merchant, so refetch the full list.
            if ('description' in variables.data) {
                queryClient.invalidateQueries({ queryKey: ['transactions-server'], exact: false });
            }
            showToast('success', 'Изменения сохранены');
            options?.onSuccess?.({
                rowId: variables.id,
                columnId: Object.keys(variables.data)[0],
                updated: response.transaction,
            });
        },
        onError: (error: any, variables, context: any) => {
            if (context?.snapshot) {
                for (const [key, value] of context.snapshot) {
                    queryClient.setQueryData(key, value);
                }
            }
            const detail =
                error?.response?.data?.detail ||
                error?.response?.data?.message ||
                error?.message ||
                'неизвестная ошибка';
            showToast('error', `Ошибка сохранения: ${detail}`);
            options?.onError?.({
                error,
                rowId: variables.id,
                columnId: Object.keys(variables.data)[0],
            });
        },
    });

    const startEdit = useCallback((rowId: number, columnId: string) => {
        setEditingCell({ rowId, columnId });
    }, []);

    const cancelEdit = useCallback(() => {
        setEditingCell(null);
    }, []);

    const saveEdit = useCallback(
        async (rowId: number, columnId: string, newValue: any, row?: Transaction) => {
            const fieldMap: Record<string, string> = {
                date_time: 'transaction_date',
                transaction_date: 'transaction_date',
                time: 'transaction_date',
                operator_raw: 'operator_raw',
                application_mapped: 'application_mapped',
                description: 'description',
                amount: 'amount',
                balance_after: 'balance_after',
                card_last_4: 'card_last_4',
                transaction_type: 'transaction_type',
                currency: 'currency',
                source_type: 'source_type',
                parsing_method: 'parsing_method',
                parsing_confidence: 'parsing_confidence',
            };

            const apiField = fieldMap[columnId] || columnId;
            const updateData: TransactionUpdateRequest = {};

            if (apiField === 'transaction_date') {
                const formatLocalIso = (d: Date) => {
                    const pad = (n: number) => String(n).padStart(2, '0');
                    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
                };
                const current = row?.transaction_date ? new Date(row.transaction_date) : null;
                if (columnId === 'time' && current) {
                    const [hh, mm] = String(newValue).split(':');
                    current.setHours(Number(hh || 0), Number(mm || 0), 0, 0);
                    updateData.transaction_date = formatLocalIso(current);
                } else if (columnId === 'transaction_date' && current) {
                    const [y, m, d] = String(newValue).split('-').map(Number);
                    current.setFullYear(y, (m || 1) - 1, d || 1);
                    updateData.transaction_date = formatLocalIso(current);
                } else if (columnId === 'date_time') {
                    const d = new Date(newValue);
                    updateData.transaction_date = isNaN(d.getTime())
                        ? String(newValue)
                        : formatLocalIso(d);
                } else {
                    updateData.transaction_date = newValue;
                }
            } else if (apiField === 'source_type') {
                updateData.source_type = newValue === 'AUTO' || newValue === 'MANUAL' ? newValue : String(newValue || '').toUpperCase() as any;
            } else {
                (updateData as any)[apiField] = newValue;
            }

            await updateMutation.mutateAsync({ id: rowId, data: updateData });
        },
        [updateMutation]
    );

    return {
        editingCell,
        startEdit,
        cancelEdit,
        saveEdit,
        isSaving: updateMutation.isPending,
    };
};
