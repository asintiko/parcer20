import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Sheet } from './motion/Sheet';
import { DatePicker } from './DateTimePicker';

interface FilterState {
    dateFrom: string;
    dateTo: string;
    daysOfWeek: number[];
    amountMin: string;
    amountMax: string;
    currency: 'ALL' | 'UZS' | 'USD';
    transactionTypes: string[];
    operators: string[];
    apps: string[];
    sourceType: 'ALL' | 'TELEGRAM' | 'SMS' | 'MANUAL';
    telegramSourceIds: number[];
    cardId: string;
    parsingMethod?: string;
    confidenceMin?: number;
    confidenceMax?: number;
}

interface FilterDrawerProps {
    isOpen: boolean;
    onClose: () => void;
    onApply: (filters: FilterState) => void;
    initialFilters?: Partial<FilterState>;
    operatorOptions?: string[];
    appOptions?: string[];
    telegramSourceOptions?: Array<{ chat_id: number; title: string; chat_type?: 'bot' | 'group' | 'supergroup' | 'channel' | 'private' | null; count: number }>;
}

const DEFAULT_FILTERS: FilterState = {
    dateFrom: '',
    dateTo: '',
    daysOfWeek: [],
    amountMin: '',
    amountMax: '',
    currency: 'ALL',
    transactionTypes: [],
    operators: [],
    apps: [],
    sourceType: 'ALL',
    telegramSourceIds: [],
    cardId: '',
    parsingMethod: undefined,
    confidenceMin: undefined,
    confidenceMax: undefined,
};

function normalizeFilterState(input?: Partial<FilterState>): FilterState {
    const nextSourceType = input?.sourceType;
    const nextTelegramSourceIds = Array.isArray(input?.telegramSourceIds) ? [...input.telegramSourceIds] : [];
    const normalizedSourceType =
        nextSourceType === 'SMS' || nextSourceType === 'MANUAL'
            ? nextSourceType
            : nextTelegramSourceIds.length > 0
                ? 'TELEGRAM'
                : 'ALL';
    return {
        ...DEFAULT_FILTERS,
        ...input,
        daysOfWeek: Array.isArray(input?.daysOfWeek) ? [...input.daysOfWeek] : [],
        transactionTypes: Array.isArray(input?.transactionTypes) ? [...input.transactionTypes] : [],
        operators: Array.isArray(input?.operators) ? [...input.operators] : [],
        apps: Array.isArray(input?.apps) ? [...input.apps] : [],
        sourceType: normalizedSourceType,
        telegramSourceIds: nextTelegramSourceIds,
        parsingMethod: input?.parsingMethod || undefined,
        confidenceMin:
            typeof input?.confidenceMin === 'number' && Number.isFinite(input.confidenceMin)
                ? input.confidenceMin
                : undefined,
        confidenceMax:
            typeof input?.confidenceMax === 'number' && Number.isFinite(input.confidenceMax)
                ? input.confidenceMax
                : undefined,
    };
}

const TRANS_TYPES: Array<{ value: string; label: string }> = [
    { value: 'DEBIT', label: 'Списание' },
    { value: 'CREDIT', label: 'Пополнение' },
    { value: 'CONVERSION', label: 'Конверсия' },
    { value: 'REVERSAL', label: 'Отмена' },
];

const DAYS_MAP: Array<{ id: number; label: string }> = [
    { id: 1, label: 'Пн' },
    { id: 2, label: 'Вт' },
    { id: 3, label: 'Ср' },
    { id: 4, label: 'Чт' },
    { id: 5, label: 'Пт' },
    { id: 6, label: 'Сб' },
    { id: 0, label: 'Вс' },
];

const PARSING_METHODS: Array<{ value: string; label: string }> = [
    { value: 'regex', label: 'Regex' },
    { value: 'gpt', label: 'GPT' },
    { value: 'manual', label: 'Ручной' },
    { value: 'operator_mapper', label: 'Mapper' },
];

const SOURCE_PILLS: Array<{ value: 'ALL' | 'TELEGRAM' | 'SMS' | 'MANUAL'; label: string }> = [
    { value: 'ALL', label: 'Все' },
    { value: 'TELEGRAM', label: 'Telegram' },
    { value: 'SMS', label: 'СМС' },
    { value: 'MANUAL', label: 'Ручной' },
];

const CURRENCY_PILLS: Array<{ value: 'ALL' | 'UZS' | 'USD'; label: string }> = [
    { value: 'ALL', label: 'Все' },
    { value: 'UZS', label: 'UZS' },
    { value: 'USD', label: 'USD' },
];

const getChatTypeLabel = (type?: string | null) => {
    const map: Record<string, string> = {
        bot: 'Бот',
        group: 'Группа',
        supergroup: 'Супергруппа',
        channel: 'Канал',
        private: 'Личка',
    };
    if (!type) return 'Telegram';
    return map[type] || type;
};

export const FilterDrawer: React.FC<FilterDrawerProps> = ({
    isOpen,
    onClose,
    onApply,
    initialFilters,
    operatorOptions = [],
    appOptions = [],
    telegramSourceOptions = [],
}) => {
    const normalizedInitialFilters = useMemo(() => normalizeFilterState(initialFilters), [initialFilters]);
    const normalizedInitialFiltersKey = useMemo(
        () => JSON.stringify(normalizedInitialFilters),
        [normalizedInitialFilters],
    );
    const lastHydratedFiltersKeyRef = useRef(normalizedInitialFiltersKey);
    const [filters, setFilters] = useState<FilterState>(() => normalizedInitialFilters);
    const [operatorSearch, setOperatorSearch] = useState('');
    const [appSearch, setAppSearch] = useState('');
    const [sourceSearch, setSourceSearch] = useState('');

    const toggleDay = (day: number) => {
        setFilters((prev) => ({
            ...prev,
            daysOfWeek: prev.daysOfWeek.includes(day)
                ? prev.daysOfWeek.filter((d) => d !== day)
                : [...prev.daysOfWeek, day],
        }));
    };

    const toggleList = (key: 'operators' | 'apps' | 'transactionTypes', value: string) => {
        setFilters((prev) => ({
            ...prev,
            [key]: prev[key].includes(value)
                ? prev[key].filter((v) => v !== value)
                : [...prev[key], value],
        }));
    };

    const toggleTelegramSource = (chatId: number) => {
        setFilters((prev) => {
            const nextTelegramSourceIds = prev.telegramSourceIds.includes(chatId)
                ? prev.telegramSourceIds.filter((id) => id !== chatId)
                : [...prev.telegramSourceIds, chatId];
            return {
                ...prev,
                sourceType: nextTelegramSourceIds.length > 0 ? 'TELEGRAM' : prev.sourceType === 'TELEGRAM' ? 'ALL' : prev.sourceType,
                telegramSourceIds: nextTelegramSourceIds,
            };
        });
    };

    const setSourceType = (sourceType: FilterState['sourceType']) => {
        setFilters((prev) => ({
            ...prev,
            sourceType,
            telegramSourceIds: sourceType === 'TELEGRAM' ? prev.telegramSourceIds : [],
        }));
    };

    const setParsingMethod = (value?: string) => {
        setFilters((prev) => ({ ...prev, parsingMethod: value }));
    };

    const handleApply = () => {
        onApply(filters);
        onClose();
    };

    const handleReset = () => {
        const resetFilters = normalizeFilterState();
        setFilters(resetFilters);
        setOperatorSearch('');
        setAppSearch('');
        setSourceSearch('');
        onApply(resetFilters);
    };

    useEffect(() => {
        if (lastHydratedFiltersKeyRef.current === normalizedInitialFiltersKey) {
            return;
        }
        if (!isOpen) {
            setFilters(normalizedInitialFilters);
            lastHydratedFiltersKeyRef.current = normalizedInitialFiltersKey;
        }
    }, [isOpen, normalizedInitialFilters, normalizedInitialFiltersKey]);

    useEffect(() => {
        if (!isOpen) return;
        if (lastHydratedFiltersKeyRef.current !== normalizedInitialFiltersKey) {
            setFilters(normalizedInitialFilters);
            lastHydratedFiltersKeyRef.current = normalizedInitialFiltersKey;
        }
    }, [isOpen, normalizedInitialFilters, normalizedInitialFiltersKey]);

    const filteredOperators = operatorOptions
        .filter((op) => op.toLowerCase().includes(operatorSearch.toLowerCase()))
        .sort((a, b) => a.localeCompare(b));

    const filteredApps = appOptions
        .filter((app) => app.toLowerCase().includes(appSearch.toLowerCase()))
        .sort((a, b) => a.localeCompare(b));

    const filteredTelegramSources = telegramSourceOptions
        .filter((item) => item.title.toLowerCase().includes(sourceSearch.toLowerCase()))
        .sort((a, b) => a.title.localeCompare(b.title));

    const confidenceMinPercent =
        typeof filters.confidenceMin === 'number' && Number.isFinite(filters.confidenceMin)
            ? Math.round(filters.confidenceMin * 100)
            : '';
    const confidenceMaxPercent =
        typeof filters.confidenceMax === 'number' && Number.isFinite(filters.confidenceMax)
            ? Math.round(filters.confidenceMax * 100)
            : '';

    return (
        <Sheet
            open={isOpen}
            onClose={onClose}
            width={520}
            ariaLabel="Фильтры транзакций"
            title={
                <div style={{ minWidth: 0 }}>
                    <div className="tx-detail-eyebrow">Уточнение</div>
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
                        Фильтры
                    </h3>
                </div>
            }
            subtitle="Точная настройка выборки. Применяется ко всем колонкам."
            footer={
                <>
                    <button type="button" className="sp-btn" onClick={handleReset}>
                        Сбросить всё
                    </button>
                    <span className="sp-spacer" />
                    <button type="button" className="sp-btn" onClick={onClose}>
                        Отмена
                    </button>
                    <button type="button" className="sp-btn sp-btn-primary" onClick={handleApply}>
                        Применить
                    </button>
                </>
            }
        >
            <div className="tx-filters">
                <section className="tx-filter-group">
                    <h4 className="tx-filter-group-title">Период</h4>
                    <div className="tx-filter-row">
                        <div className="tx-field">
                            <label className="tx-field-label">с</label>
                            <DatePicker
                                value={filters.dateFrom || null}
                                onChange={(val) => setFilters({ ...filters, dateFrom: val || '' })}
                                zIndex={1500}
                            />
                        </div>
                        <div className="tx-field">
                            <label className="tx-field-label">по</label>
                            <DatePicker
                                value={filters.dateTo || null}
                                onChange={(val) => setFilters({ ...filters, dateTo: val || '' })}
                                zIndex={1500}
                            />
                        </div>
                    </div>
                    <div className="tx-filter-pills" style={{ marginTop: 4 }}>
                        {DAYS_MAP.map((day) => (
                            <button
                                key={day.id}
                                type="button"
                                className={`tx-filter-pill${filters.daysOfWeek.includes(day.id) ? ' is-active' : ''}`}
                                onClick={() => toggleDay(day.id)}
                            >
                                {day.label}
                            </button>
                        ))}
                    </div>
                </section>

                <section className="tx-filter-group">
                    <h4 className="tx-filter-group-title">Финансы</h4>
                    <div className="tx-filter-row">
                        <div className="tx-field">
                            <label className="tx-field-label">Сумма от</label>
                            <input
                                type="number"
                                className="tx-field-input"
                                value={filters.amountMin}
                                onChange={(e) => setFilters({ ...filters, amountMin: e.target.value })}
                                placeholder="0"
                            />
                        </div>
                        <div className="tx-field">
                            <label className="tx-field-label">Сумма до</label>
                            <input
                                type="number"
                                className="tx-field-input"
                                value={filters.amountMax}
                                onChange={(e) => setFilters({ ...filters, amountMax: e.target.value })}
                                placeholder="∞"
                            />
                        </div>
                    </div>
                    <div className="tx-filter-pills">
                        {CURRENCY_PILLS.map((c) => (
                            <button
                                key={c.value}
                                type="button"
                                className={`tx-filter-pill${filters.currency === c.value ? ' is-active' : ''}`}
                                onClick={() => setFilters({ ...filters, currency: c.value })}
                            >
                                {c.label}
                            </button>
                        ))}
                    </div>
                    <div className="tx-filter-pills">
                        {TRANS_TYPES.map((type) => (
                            <button
                                key={type.value}
                                type="button"
                                className={`tx-filter-pill${filters.transactionTypes.includes(type.value) ? ' is-active' : ''}`}
                                onClick={() => toggleList('transactionTypes', type.value)}
                            >
                                {type.label}
                            </button>
                        ))}
                    </div>
                </section>

                <section className="tx-filter-group">
                    <h4 className="tx-filter-group-title">Источник</h4>
                    <div className="tx-filter-pills">
                        {SOURCE_PILLS.map((s) => (
                            <button
                                key={s.value}
                                type="button"
                                className={`tx-filter-pill${filters.sourceType === s.value ? ' is-active' : ''}`}
                                onClick={() => setSourceType(s.value)}
                            >
                                {s.label}
                            </button>
                        ))}
                    </div>
                    <div className="tx-field" style={{ marginTop: 4 }}>
                        <label className="tx-field-label">Поиск Telegram-источника</label>
                        <input
                            type="text"
                            className="tx-field-input"
                            value={sourceSearch}
                            onChange={(e) => setSourceSearch(e.target.value)}
                            placeholder="Бот, группа, канал"
                        />
                    </div>
                    <div className="tx-filter-checkboxes" style={{ gridTemplateColumns: '1fr', maxHeight: 180 }}>
                        {filteredTelegramSources.length === 0 ? (
                            <div className="tx-filter-empty">Нет актуальных источников</div>
                        ) : (
                            filteredTelegramSources.map((item) => (
                                <label key={item.chat_id} className="tx-filter-check">
                                    <input
                                        type="checkbox"
                                        checked={filters.telegramSourceIds.includes(item.chat_id)}
                                        onChange={() => toggleTelegramSource(item.chat_id)}
                                    />
                                    <span style={{ minWidth: 0 }}>
                                        <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {item.title}
                                        </div>
                                        <div
                                            style={{
                                                fontFamily: "var(--font-mono, monospace)",
                                                fontSize: 10.5,
                                                color: 'var(--text-muted)',
                                                letterSpacing: '0.04em',
                                                marginTop: 2,
                                            }}
                                        >
                                            {getChatTypeLabel(item.chat_type)} · {item.count}
                                        </div>
                                    </span>
                                </label>
                            ))
                        )}
                    </div>
                </section>

                <section className="tx-filter-group">
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <h4 className="tx-filter-group-title">Операторы</h4>
                        <div style={{ display: 'flex', gap: 12 }}>
                            <button
                                type="button"
                                onClick={() => setFilters({ ...filters, operators: filteredOperators })}
                                style={{
                                    fontFamily: 'var(--font-mono, monospace)',
                                    fontSize: 10.5,
                                    color: 'var(--text-muted)',
                                    background: 'transparent',
                                    border: 0,
                                    cursor: 'pointer',
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.1em',
                                }}
                            >
                                Все
                            </button>
                            <button
                                type="button"
                                onClick={() => setFilters({ ...filters, operators: [] })}
                                style={{
                                    fontFamily: 'var(--font-mono, monospace)',
                                    fontSize: 10.5,
                                    color: 'var(--text-muted)',
                                    background: 'transparent',
                                    border: 0,
                                    cursor: 'pointer',
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.1em',
                                }}
                            >
                                Снять
                            </button>
                        </div>
                    </div>
                    <div className="tx-field">
                        <input
                            type="text"
                            className="tx-field-input"
                            value={operatorSearch}
                            onChange={(e) => setOperatorSearch(e.target.value)}
                            placeholder="Поиск оператора"
                        />
                    </div>
                    <div className="tx-filter-checkboxes">
                        {filteredOperators.length === 0 ? (
                            <div className="tx-filter-empty">Ничего не найдено</div>
                        ) : (
                            filteredOperators.map((op) => (
                                <label key={op} className="tx-filter-check">
                                    <input
                                        type="checkbox"
                                        checked={filters.operators.includes(op)}
                                        onChange={() => toggleList('operators', op)}
                                    />
                                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {op}
                                    </span>
                                </label>
                            ))
                        )}
                    </div>
                </section>

                <section className="tx-filter-group">
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <h4 className="tx-filter-group-title">Приложения</h4>
                        <div style={{ display: 'flex', gap: 12 }}>
                            <button
                                type="button"
                                onClick={() => setFilters({ ...filters, apps: filteredApps })}
                                style={{
                                    fontFamily: 'var(--font-mono, monospace)',
                                    fontSize: 10.5,
                                    color: 'var(--text-muted)',
                                    background: 'transparent',
                                    border: 0,
                                    cursor: 'pointer',
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.1em',
                                }}
                            >
                                Все
                            </button>
                            <button
                                type="button"
                                onClick={() => setFilters({ ...filters, apps: [] })}
                                style={{
                                    fontFamily: 'var(--font-mono, monospace)',
                                    fontSize: 10.5,
                                    color: 'var(--text-muted)',
                                    background: 'transparent',
                                    border: 0,
                                    cursor: 'pointer',
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.1em',
                                }}
                            >
                                Снять
                            </button>
                        </div>
                    </div>
                    <div className="tx-field">
                        <input
                            type="text"
                            className="tx-field-input"
                            value={appSearch}
                            onChange={(e) => setAppSearch(e.target.value)}
                            placeholder="Поиск приложения"
                        />
                    </div>
                    <div className="tx-filter-checkboxes">
                        {filteredApps.length === 0 ? (
                            <div className="tx-filter-empty">Ничего не найдено</div>
                        ) : (
                            filteredApps.map((app) => (
                                <label key={app} className="tx-filter-check">
                                    <input
                                        type="checkbox"
                                        checked={filters.apps.includes(app)}
                                        onChange={() => toggleList('apps', app)}
                                    />
                                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {app}
                                    </span>
                                </label>
                            ))
                        )}
                    </div>
                </section>

                <section className="tx-filter-group">
                    <h4 className="tx-filter-group-title">Парсер · уверенность</h4>
                    <div className="tx-filter-pills">
                        <button
                            type="button"
                            className={`tx-filter-pill${!filters.parsingMethod ? ' is-active' : ''}`}
                            onClick={() => setParsingMethod(undefined)}
                        >
                            Все
                        </button>
                        {PARSING_METHODS.map((m) => (
                            <button
                                key={m.value}
                                type="button"
                                className={`tx-filter-pill${filters.parsingMethod === m.value ? ' is-active' : ''}`}
                                onClick={() => setParsingMethod(filters.parsingMethod === m.value ? undefined : m.value)}
                            >
                                {m.label}
                            </button>
                        ))}
                    </div>
                    <div className="tx-filter-row">
                        <div className="tx-field">
                            <label className="tx-field-label">Уверенность от %</label>
                            <input
                                type="number"
                                min="0"
                                max="100"
                                step="1"
                                className="tx-field-input"
                                value={confidenceMinPercent}
                                onChange={(e) => {
                                    const raw = e.target.value;
                                    if (raw === '') {
                                        setFilters({ ...filters, confidenceMin: undefined });
                                        return;
                                    }
                                    const parsed = Number(raw);
                                    if (!Number.isFinite(parsed)) return;
                                    setFilters({
                                        ...filters,
                                        confidenceMin: Math.max(0, Math.min(100, parsed)) / 100,
                                    });
                                }}
                                placeholder="0"
                            />
                        </div>
                        <div className="tx-field">
                            <label className="tx-field-label">Уверенность до %</label>
                            <input
                                type="number"
                                min="0"
                                max="100"
                                step="1"
                                className="tx-field-input"
                                value={confidenceMaxPercent}
                                onChange={(e) => {
                                    const raw = e.target.value;
                                    if (raw === '') {
                                        setFilters({ ...filters, confidenceMax: undefined });
                                        return;
                                    }
                                    const parsed = Number(raw);
                                    if (!Number.isFinite(parsed)) return;
                                    setFilters({
                                        ...filters,
                                        confidenceMax: Math.max(0, Math.min(100, parsed)) / 100,
                                    });
                                }}
                                placeholder="100"
                            />
                        </div>
                    </div>
                </section>

                <section className="tx-filter-group">
                    <h4 className="tx-filter-group-title">Идентификаторы</h4>
                    <div className="tx-field">
                        <label className="tx-field-label">Последние 4 цифры карты</label>
                        <input
                            type="text"
                            className="tx-field-input"
                            value={filters.cardId}
                            onChange={(e) => setFilters({ ...filters, cardId: e.target.value })}
                            placeholder="1234"
                            maxLength={4}
                            inputMode="numeric"
                        />
                    </div>
                </section>
            </div>
        </Sheet>
    );
};
