import { useState, useCallback } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { transactionsApi, TransactionUpdateRequest, Transaction } from '../services/api';
import { useToast } from '../components/Toast';

export interface EditingCell {
    rowId: number;
    columnId: string;
}

export interface UseInlineEditOptions {
    onSuccess?: (rowId: number, columnId: string) => void;
    onError?: (error: Error, rowId: number, columnId: string) => void;
}

export const useInlineEdit = (options?: UseInlineEditOptions) => {
    const queryClient = useQueryClient();
    const [editingCell, setEditingCell] = useState<EditingCell | null>(null);
    const { showToast } = useToast();

    const updateMutation = useMutation({
        mutationFn: ({ id, data }: { id: number; data: TransactionUpdateRequest }) =>
            transactionsApi.updateTransaction(id, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['transactions'] });
            showToast('success', 'Изменения сохранены');
            options?.onSuccess?.(variables.id, Object.keys(variables.data)[0]);
        },
        onError: (error: Error, variables) => {
            showToast('error', `Ошибка сохранения: ${error.message}`);
            options?.onError?.(error, variables.id, Object.keys(variables.data)[0]);
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
                transaction_date: 'transaction_date',
                operator_raw: 'operator_raw',
                application_mapped: 'application_mapped',
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
                const current = row?.transaction_date ? new Date(row.transaction_date) : null;
                if (columnId === 'time' && current) {
                    const [hh, mm] = String(newValue).split(':');
                    current.setHours(Number(hh || 0), Number(mm || 0), 0, 0);
                    updateData.transaction_date = current.toISOString();
                } else if (columnId === 'transaction_date' && current) {
                    const [y, m, d] = String(newValue).split('-').map(Number);
                    current.setFullYear(y, (m || 1) - 1, d || 1);
                    updateData.transaction_date = current.toISOString();
                } else if (columnId === 'date_time') {
                    updateData.transaction_date = new Date(newValue).toISOString();
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
