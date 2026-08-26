import React, { useMemo, useState } from 'react';
import { CreateTransactionRequest } from '../services/api';
import { DateTimePicker } from './DateTimePicker';
import { AutocompleteInput } from './AutocompleteInput';
import { Sheet } from './motion/Sheet';

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

    const isValid = useMemo(() => Object.keys(errors).length === 0, [errors]);

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

    const handleSubmit = async (e?: React.FormEvent) => {
        e?.preventDefault();
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

    const handleClose = () => {
        if (isSubmitting) return;
        onClose();
    };

    return (
        <Sheet
            open={isOpen}
            onClose={handleClose}
            width={520}
            ariaLabel="Добавить транзакцию"
            title={
                <div style={{ minWidth: 0 }}>
                    <div className="tx-detail-eyebrow">Новая запись</div>
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
                        Добавить транзакцию
                    </h3>
                </div>
            }
            subtitle="Запись будет помечена как ручной источник."
            footer={
                <>
                    <span className="sp-spacer" />
                    <button
                        type="button"
                        className="sp-btn"
                        onClick={handleClose}
                        disabled={isSubmitting}
                    >
                        Отмена
                    </button>
                    <button
                        type="button"
                        className="sp-btn sp-btn-primary"
                        onClick={() => handleSubmit()}
                        disabled={isSubmitting || !isValid}
                    >
                        {isSubmitting ? (
                            <>
                                <span className="sp-btn-spinner" aria-hidden />
                                Сохраняем
                            </>
                        ) : (
                            'Создать'
                        )}
                    </button>
                </>
            }
        >
            <form onSubmit={handleSubmit} className="tx-form">
                {error ? <div className="tx-field-error">{error}</div> : null}

                <div className="tx-field">
                    <label className="tx-field-label">Дата и время</label>
                    <DateTimePicker
                        value={form.datetime || null}
                        onChange={(val) => setField('datetime', val || '')}
                        zIndex={1500}
                    />
                    {errors.datetime ? <div className="tx-field-error">{errors.datetime}</div> : null}
                </div>

                <div className="tx-field">
                    <label className="tx-field-label">Оператор</label>
                    <AutocompleteInput
                        value={form.operator}
                        onChange={(val) => setField('operator', val)}
                        options={operatorOptions}
                        placeholder="Введите или выберите"
                        required
                        zIndex={1600}
                    />
                    {errors.operator ? <div className="tx-field-error">{errors.operator}</div> : null}
                </div>

                <div className="tx-field">
                    <label className="tx-field-label">Приложение</label>
                    <AutocompleteInput
                        value={form.app || ''}
                        onChange={(val) => setField('app', val)}
                        options={appOptions}
                        placeholder="Введите или выберите"
                        zIndex={1600}
                    />
                </div>

                <div className="tx-field-row">
                    <div className="tx-field">
                        <label className="tx-field-label">Сумма</label>
                        <input
                            type="number"
                            min="0"
                            step="0.01"
                            className="tx-field-input"
                            value={form.amount}
                            onChange={(e) => setField('amount', e.target.value)}
                            placeholder="0.00"
                            required
                        />
                        {errors.amount ? <div className="tx-field-error">{errors.amount}</div> : null}
                    </div>
                    <div className="tx-field">
                        <label className="tx-field-label">Остаток</label>
                        <input
                            type="number"
                            step="0.01"
                            className="tx-field-input"
                            value={form.balance || ''}
                            onChange={(e) => setField('balance', e.target.value)}
                            placeholder="—"
                        />
                    </div>
                </div>

                <div className="tx-field-row">
                    <div className="tx-field">
                        <label className="tx-field-label">Последние 4 цифры</label>
                        <input
                            type="text"
                            inputMode="numeric"
                            pattern="\d{4}"
                            maxLength={4}
                            className="tx-field-input"
                            value={form.card_last4}
                            onChange={(e) => setField('card_last4', e.target.value.replace(/\D/g, '').slice(0, 4))}
                            placeholder="1234"
                            required
                        />
                        {errors.card_last4 ? <div className="tx-field-error">{errors.card_last4}</div> : null}
                    </div>
                    <div className="tx-field">
                        <label className="tx-field-label">Валюта</label>
                        <select
                            className="tx-field-select"
                            value={form.currency}
                            onChange={(e) => setField('currency', e.target.value)}
                        >
                            <option value="UZS">UZS</option>
                            <option value="USD">USD</option>
                        </select>
                    </div>
                </div>

                <div className="tx-field">
                    <label className="tx-field-label">Тип</label>
                    <select
                        className="tx-field-select"
                        value={form.transaction_type}
                        onChange={(e) => setField('transaction_type', e.target.value)}
                    >
                        <option value="DEBIT">Списание</option>
                        <option value="CREDIT">Пополнение</option>
                        <option value="CONVERSION">Конверсия</option>
                        <option value="REVERSAL">Отмена</option>
                    </select>
                </div>

                <label
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 10,
                        fontSize: 13,
                        color: 'var(--text)',
                        cursor: 'pointer',
                    }}
                >
                    <input
                        type="checkbox"
                        checked={form.is_p2p}
                        onChange={(e) => setField('is_p2p', e.target.checked)}
                    />
                    P2P-перевод
                </label>

                <div className="tx-field">
                    <label className="tx-field-label">Исходный текст · опционально</label>
                    <textarea
                        className="tx-field-input"
                        style={{ minHeight: 88, resize: 'vertical', paddingTop: 8 }}
                        value={form.raw_text || ''}
                        onChange={(e) => setField('raw_text', e.target.value)}
                        placeholder="SMS / Telegram сообщение, если есть"
                    />
                </div>
            </form>
        </Sheet>
    );
};
