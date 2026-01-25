import React, { useState } from 'react';
import { X } from 'lucide-react';
import { CreateTransactionRequest } from '../services/api';

interface AddTransactionModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSubmit: (data: CreateTransactionRequest) => Promise<void>;
}

const defaultForm: CreateTransactionRequest & { balance?: string | null } = {
    datetime: '',
    operator: '',
    amount: '',
    card_last4: '',
    transaction_type: 'DEBIT',
    currency: 'UZS',
    app: '',
    balance: '',
    is_p2p: false,
    raw_text: '',
};

export const AddTransactionModal: React.FC<AddTransactionModalProps> = ({ isOpen, onClose, onSubmit }) => {
    const [form, setForm] = useState<typeof defaultForm>(defaultForm);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    if (!isOpen) return null;

    const handleChange = (key: keyof typeof defaultForm, value: any) => {
        setForm(prev => ({ ...prev, [key]: value }));
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError(null);
        setIsSubmitting(true);
        try {
            if (!form.datetime || !form.operator || !form.amount || !form.card_last4) {
                throw new Error('Заполните дату/время, оператора, сумму и 4 цифры карты');
            }
            const payload: CreateTransactionRequest = {
                datetime: new Date(form.datetime).toISOString(),
                operator: form.operator,
                amount: form.amount,
                card_last4: form.card_last4,
                transaction_type: form.transaction_type,
                currency: form.currency,
                app: form.app || undefined,
                balance: form.balance || undefined,
                is_p2p: form.is_p2p,
                raw_text: form.raw_text || undefined,
            };
            await onSubmit(payload);
            setForm(defaultForm);
        } catch (err: any) {
            setError(err?.message || 'Не удалось создать транзакцию');
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
            <div className="bg-surface rounded-lg shadow-xl border border-border w-full max-w-xl">
                <div className="flex items-center justify-between p-4 border-b border-border">
                    <h3 className="text-lg font-semibold text-foreground">Добавить транзакцию</h3>
                    <button onClick={onClose} className="p-2 rounded-full hover:bg-surface-2">
                        <X className="w-5 h-5" />
                    </button>
                </div>
                <form onSubmit={handleSubmit} className="p-4 space-y-4">
                    {error && <div className="text-sm text-danger">{error}</div>}
                    <div className="grid grid-cols-2 gap-4">
                        <label className="flex flex-col text-sm text-foreground">
                            Дата и время
                            <input
                                type="datetime-local"
                                className="input-base mt-1"
                                value={form.datetime}
                                onChange={(e) => handleChange('datetime', e.target.value)}
                                required
                            />
                        </label>
                        <label className="flex flex-col text-sm text-foreground">
                            Оператор
                            <input
                                type="text"
                                className="input-base mt-1"
                                value={form.operator}
                                onChange={(e) => handleChange('operator', e.target.value)}
                                required
                            />
                        </label>
                        <label className="flex flex-col text-sm text-foreground">
                            Приложение
                            <input
                                type="text"
                                className="input-base mt-1"
                                value={form.app || ''}
                                onChange={(e) => handleChange('app', e.target.value)}
                            />
                        </label>
                        <label className="flex flex-col text-sm text-foreground">
                            Сумма
                            <input
                                type="number"
                                min="0"
                                step="0.01"
                                className="input-base mt-1"
                                value={form.amount}
                                onChange={(e) => handleChange('amount', e.target.value)}
                                required
                            />
                        </label>
                        <label className="flex flex-col text-sm text-foreground">
                            Остаток
                            <input
                                type="number"
                                step="0.01"
                                className="input-base mt-1"
                                value={form.balance || ''}
                                onChange={(e) => handleChange('balance', e.target.value)}
                            />
                        </label>
                        <label className="flex flex-col text-sm text-foreground">
                            Последние 4 цифры
                            <input
                                type="text"
                                pattern="\\d{4}"
                                className="input-base mt-1"
                                value={form.card_last4}
                                onChange={(e) => handleChange('card_last4', e.target.value)}
                                required
                            />
                        </label>
                        <label className="flex flex-col text-sm text-foreground">
                            Тип
                            <select
                                className="input-base mt-1"
                                value={form.transaction_type}
                                onChange={(e) => handleChange('transaction_type', e.target.value)}
                            >
                                <option value="DEBIT">Списание</option>
                                <option value="CREDIT">Пополнение</option>
                                <option value="CONVERSION">Конверсия</option>
                                <option value="REVERSAL">Отмена</option>
                            </select>
                        </label>
                        <label className="flex flex-col text-sm text-foreground">
                            Валюта
                            <select
                                className="input-base mt-1"
                                value={form.currency}
                                onChange={(e) => handleChange('currency', e.target.value)}
                            >
                                <option value="UZS">UZS</option>
                                <option value="USD">USD</option>
                            </select>
                        </label>
                        <label className="flex items-center gap-2 text-sm text-foreground">
                            <input
                                type="checkbox"
                                checked={form.is_p2p}
                                onChange={(e) => handleChange('is_p2p', e.target.checked)}
                            />
                            P2P перевод
                        </label>
                        <label className="flex flex-col text-sm text-foreground col-span-2">
                            Исходный текст (опционально)
                            <textarea
                                className="input-base mt-1 min-h-[80px]"
                                value={form.raw_text || ''}
                                onChange={(e) => handleChange('raw_text', e.target.value)}
                            />
                        </label>
                    </div>
                    <div className="flex justify-end gap-2 pt-2">
                        <button type="button" onClick={onClose} className="px-3 py-2 border border-border rounded bg-surface hover:bg-surface-2">
                            Отмена
                        </button>
                        <button
                            type="submit"
                            disabled={isSubmitting}
                            className="px-3 py-2 rounded bg-primary text-white hover:bg-primary-dark disabled:opacity-60"
                        >
                            {isSubmitting ? 'Сохранение...' : 'Создать'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};
