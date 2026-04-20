import React, { useMemo, useState } from 'react';
import { CreateTransactionRequest } from '../services/api';
import { DateTimePicker } from './DateTimePicker';
import { AutocompleteInput } from './AutocompleteInput';
import { Button, Input, Modal } from './ui';

interface AddTransactionModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSubmit: (data: CreateTransactionRequest) => Promise<void>;
    operatorOptions?: string[];
    appOptions?: string[];
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

type FormErrors = Partial<Record<'datetime' | 'operator' | 'amount' | 'card_last4', string>>;

export const AddTransactionModal: React.FC<AddTransactionModalProps> = ({
    isOpen,
    onClose,
    onSubmit,
    operatorOptions = [],
    appOptions = [],
}) => {
    const [form, setForm] = useState<typeof defaultForm>(defaultForm);
    const [errors, setErrors] = useState<FormErrors>({});
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const isValid = useMemo(() => {
        return Object.keys(errors).length === 0;
    }, [errors]);

    if (!isOpen) return null;

    const setField = (key: keyof typeof defaultForm, value: any) => {
        setForm((prev) => ({ ...prev, [key]: value }));
        setErrors((prev) => {
            const next = { ...prev };
            if (key in next) delete next[key as keyof FormErrors];
            return next;
        });
    };

    const validate = (): boolean => {
        const next: FormErrors = {};
        if (!form.datetime) next.datetime = 'Укажите дату и время';
        if (!form.operator.trim()) next.operator = 'Укажите оператора';
        const amountNum = Number(form.amount);
        if (!form.amount || !Number.isFinite(amountNum) || amountNum <= 0) {
            next.amount = 'Сумма должна быть больше нуля';
        }
        if (!/^\d{4}$/.test(form.card_last4 || '')) {
            next.card_last4 = 'Введите ровно 4 цифры карты';
        }
        setErrors(next);
        return Object.keys(next).length === 0;
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError(null);
        if (!validate()) return;

        setIsSubmitting(true);
        try {
            const payload: CreateTransactionRequest = {
                datetime: new Date(form.datetime).toISOString(),
                operator: form.operator.trim(),
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
            setErrors({});
            onClose();
        } catch (err: any) {
            setError(err?.message || 'Не удалось создать транзакцию');
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <Modal open={isOpen} onClose={onClose} title="Добавить транзакцию" widthClassName="max-w-2xl">
            <form onSubmit={handleSubmit} className="space-y-4">
                {error && <div className="text-sm text-danger">{error}</div>}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                        <label className="block text-sm font-medium text-foreground mb-1.5">Дата и время</label>
                        <DateTimePicker
                            value={form.datetime || null}
                            onChange={(val) => setField('datetime', val || '')}
                            zIndex={1500}
                        />
                        {errors.datetime ? <p className="mt-1 text-xs text-danger">{errors.datetime}</p> : null}
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-foreground mb-1.5">Оператор</label>
                        <AutocompleteInput
                            value={form.operator}
                            onChange={(val) => setField('operator', val)}
                            options={operatorOptions}
                            placeholder="Введите или выберите"
                            required
                            zIndex={1600}
                        />
                        {errors.operator ? <p className="mt-1 text-xs text-danger">{errors.operator}</p> : null}
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-foreground mb-1.5">Приложение</label>
                        <AutocompleteInput
                            value={form.app || ''}
                            onChange={(val) => setField('app', val)}
                            options={appOptions}
                            placeholder="Введите или выберите"
                            zIndex={1600}
                        />
                    </div>

                    <Input
                        type="number"
                        min="0"
                        step="0.01"
                        label="Сумма"
                        value={form.amount}
                        onChange={(e) => setField('amount', e.target.value)}
                        error={errors.amount}
                        required
                    />

                    <Input
                        type="number"
                        step="0.01"
                        label="Остаток"
                        value={form.balance || ''}
                        onChange={(e) => setField('balance', e.target.value)}
                    />

                    <Input
                        type="text"
                        pattern="\\d{4}"
                        label="Последние 4 цифры"
                        value={form.card_last4}
                        onChange={(e) => setField('card_last4', e.target.value)}
                        error={errors.card_last4}
                        required
                    />

                    <div>
                        <label className="block text-sm font-medium text-foreground mb-1.5">Тип</label>
                        <select
                            className="input-base"
                            value={form.transaction_type}
                            onChange={(e) => setField('transaction_type', e.target.value)}
                        >
                            <option value="DEBIT">Списание</option>
                            <option value="CREDIT">Пополнение</option>
                            <option value="CONVERSION">Конверсия</option>
                            <option value="REVERSAL">Отмена</option>
                        </select>
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-foreground mb-1.5">Валюта</label>
                        <select
                            className="input-base"
                            value={form.currency}
                            onChange={(e) => setField('currency', e.target.value)}
                        >
                            <option value="UZS">UZS</option>
                            <option value="USD">USD</option>
                        </select>
                    </div>

                    <label className="md:col-span-2 flex items-center gap-2 text-sm text-foreground">
                        <input
                            type="checkbox"
                            checked={form.is_p2p}
                            onChange={(e) => setField('is_p2p', e.target.checked)}
                            aria-label="P2P перевод"
                        />
                        P2P перевод
                    </label>

                    <label className="md:col-span-2 flex flex-col text-sm text-foreground">
                        Исходный текст (опционально)
                        <textarea
                            className="input-base mt-1 min-h-[80px]"
                            value={form.raw_text || ''}
                            onChange={(e) => setField('raw_text', e.target.value)}
                        />
                    </label>
                </div>

                <div className="flex justify-end gap-2 pt-2">
                    <Button type="button" variant="secondary" onClick={onClose}>
                        Отмена
                    </Button>
                    <Button type="submit" variant="primary" disabled={isSubmitting || !isValid}>
                        {isSubmitting ? 'Сохранение...' : 'Создать'}
                    </Button>
                </div>
            </form>
        </Modal>
    );
};
