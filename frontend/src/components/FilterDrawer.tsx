import React, { useState, useEffect, useMemo, useRef } from 'react';
import { X, Calendar, Search, DollarSign, Smartphone, Hash } from 'lucide-react';
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
    };
}

const TRANS_TYPES = ['DEBIT', 'CREDIT', 'CONVERSION', 'REVERSAL']; // Mapped values might differ, using keys for now
const DAYS_MAP = [
    { id: 1, label: 'Пн' },
    { id: 2, label: 'Вт' },
    { id: 3, label: 'Ср' },
    { id: 4, label: 'Чт' },
    { id: 5, label: 'Пт' },
    { id: 6, label: 'Сб' },
    { id: 0, label: 'Вс' },
];

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
    const [isVisible, setIsVisible] = useState(false);
    const [isMounted, setIsMounted] = useState(false);
    const [operatorSearch, setOperatorSearch] = useState('');
    const [appSearch, setAppSearch] = useState('');
    const [sourceSearch, setSourceSearch] = useState('');

    // Animation Logic
    useEffect(() => {
        if (isOpen) {
            setIsMounted(true);
            setTimeout(() => setIsVisible(true), 10);
        } else {
            setIsVisible(false);
            setTimeout(() => setIsMounted(false), 300);
        }
    }, [isOpen]);

    // Handlers
    const toggleDay = (day: number) => {
        setFilters(prev => ({
            ...prev,
            daysOfWeek: prev.daysOfWeek.includes(day)
                ? prev.daysOfWeek.filter(d => d !== day)
                : [...prev.daysOfWeek, day]
        }));
    };

    const toggleList = (key: 'operators' | 'apps' | 'transactionTypes', value: string) => {
        setFilters(prev => ({
            ...prev,
            [key]: prev[key].includes(value)
                ? prev[key].filter(v => v !== value)
                : [...prev[key], value]
        }));
    };

    const toggleTelegramSource = (chatId: number) => {
        setFilters((prev) => {
            const nextTelegramSourceIds = prev.telegramSourceIds.includes(chatId)
                ? prev.telegramSourceIds.filter((id) => id !== chatId)
                : [...prev.telegramSourceIds, chatId];
            return {
                ...prev,
                sourceType: nextTelegramSourceIds.length > 0 ? 'TELEGRAM' : 'ALL',
                telegramSourceIds: nextTelegramSourceIds,
            };
        });
    };

    const applyDirectSource = (sourceType: 'SMS' | 'MANUAL') => {
        setFilters((prev) => ({
            ...prev,
            sourceType: prev.sourceType === sourceType ? 'ALL' : sourceType,
            telegramSourceIds: [],
        }));
    };

    const handleApply = () => {
        onApply(filters);
        onClose();
    };

    const handleReset = () => {
        setFilters(normalizeFilterState());
        setOperatorSearch('');
        setAppSearch('');
        setSourceSearch('');
    };

    useEffect(() => {
        if (lastHydratedFiltersKeyRef.current === normalizedInitialFiltersKey) {
            return;
        }
        if (!isOpen || !isMounted) {
            setFilters(normalizedInitialFilters);
            lastHydratedFiltersKeyRef.current = normalizedInitialFiltersKey;
        }
    }, [isMounted, isOpen, normalizedInitialFilters, normalizedInitialFiltersKey]);

    useEffect(() => {
        if (!isOpen) {
            return;
        }
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

    if (!isMounted) return null;

    return (
        <div className={`fixed inset-0 z-[var(--z-modal)] flex justify-end ${isVisible ? 'pointer-events-auto' : 'pointer-events-none'}`}>
            {/* Backdrop */}
            <div
                className={`fixed inset-0 bg-black/20 backdrop-blur-sm transition-opacity duration-300 ease-in-out ${isVisible ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
                    }`}
                onClick={onClose}
            />

            {/* Drawer */}
            <div
                className={`relative w-full max-w-md bg-surface h-full shadow-2xl flex flex-col transform transition-transform duration-300 ease-in-out border-l border-border ${isVisible ? 'translate-x-0 pointer-events-auto' : 'translate-x-full pointer-events-none'
                    }`}
            >
                {/* Header */}
                <div className="flex items-center justify-between p-4 border-b border-border bg-surface">
                    <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
                        <Search className="w-5 h-5 text-primary" />
                        Фильтры
                    </h2>
                    <button onClick={onClose} className="p-1 hover:bg-surface-2 rounded-full text-foreground-secondary focus:outline-none focus:ring-2 focus:ring-primary">
                        <X className="w-6 h-6" />
                    </button>
                </div>

                {/* Content */}
                <div className="flex-1 overflow-y-auto p-5 space-y-8">

                    {/* Group A: Time */}
                    <section>
                        <h3 className="section-title flex items-center gap-2">
                            <Calendar className="w-4 h-4" /> Временные рамки
                        </h3>
                        <div className="grid grid-cols-2 gap-4 mt-3">
                            <div>
                                <label className="text-xs text-foreground-muted mb-1 block">Дата С</label>
                                <DatePicker
                                    value={filters.dateFrom || null}
                                    onChange={(val) => setFilters({ ...filters, dateFrom: val || '' })}
                                    zIndex={1500}
                                />
                            </div>
                            <div>
                                <label className="text-xs text-foreground-muted mb-1 block">Дата По</label>
                                <DatePicker
                                    value={filters.dateTo || null}
                                    onChange={(val) => setFilters({ ...filters, dateTo: val || '' })}
                                    zIndex={1500}
                                />
                            </div>
                        </div>
                        <div className="mt-4">
                            <label className="text-xs text-foreground-muted mb-2 block">Дни недели</label>
                            <div className="flex gap-1 flex-wrap">
                                {DAYS_MAP.map(day => (
                                    <button
                                        key={day.id}
                                        onClick={() => toggleDay(day.id)}
                                        className={`w-9 h-9 rounded-full text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-primary ${filters.daysOfWeek.includes(day.id)
                                                ? 'bg-primary text-foreground-inverse'
                                                : 'bg-surface-2 text-foreground-secondary hover:bg-surface-3'
                                            }`}
                                    >
                                        {day.label}
                                    </button>
                                ))}
                            </div>
                        </div>
                    </section>

                    {/* Group B: Finance */}
                    <section>
                        <h3 className="section-title flex items-center gap-2">
                            <DollarSign className="w-4 h-4" /> Финансы
                        </h3>
                        <div className="grid grid-cols-2 gap-4 mt-3">
                            <input
                                type="number"
                                placeholder="От (сум)"
                                value={filters.amountMin}
                                onChange={e => setFilters({ ...filters, amountMin: e.target.value })}
                                className="input-base"
                            />
                            <input
                                type="number"
                                placeholder="До (сум)"
                                value={filters.amountMax}
                                onChange={e => setFilters({ ...filters, amountMax: e.target.value })}
                                className="input-base"
                            />
                        </div>
                        <div className="mt-4">
                            <label className="text-xs text-foreground-muted mb-1 block">Валюта</label>
                            <div className="flex rounded-md shadow-sm" role="group">
                                {['ALL', 'UZS', 'USD'].map((curr) => (
                                    <button
                                        key={curr}
                                        onClick={() => setFilters({ ...filters, currency: curr as any })}
                                        className={`flex-1 px-4 py-2 text-sm font-medium border border-border first:rounded-l-lg last:rounded-r-lg focus:outline-none focus:ring-2 focus:ring-primary ${filters.currency === curr
                                                ? 'bg-primary-light text-primary border-primary/30 z-10'
                                                : 'bg-surface text-foreground border-border hover:bg-surface-2'
                                            } -ml-px first:ml-0`}
                                    >
                                        {curr === 'ALL' ? 'Все' : curr}
                                    </button>
                                ))}
                            </div>
                        </div>
                        <div className="mt-4">
                            <label className="text-xs text-foreground-muted mb-2 block">Тип операции</label>
                            <div className="flex flex-wrap gap-2">
                                {TRANS_TYPES.map(type => (
                                    <label key={type} className="flex items-center gap-2 p-2 border border-border rounded-md cursor-pointer hover:bg-surface-2">
                                        <input
                                            type="checkbox"
                                            checked={filters.transactionTypes.includes(type)}
                                            onChange={() => toggleList('transactionTypes', type)}
                                            className="custom-checkbox"
                                        />
                                        <span className="text-sm text-foreground">{getTypeLabel(type)}</span>
                                    </label>
                                ))}
                            </div>
                        </div>
                    </section>

                    {/* Group C: Entities */}
                    <section>
                        <h3 className="section-title flex items-center gap-2">
                            <Smartphone className="w-4 h-4" /> Сущности
                        </h3>
                        <div className="mt-3 space-y-2">
                            <div className="flex items-center justify-between">
                                <label className="text-xs text-foreground-muted">Операторы</label>
                                <div className="flex gap-2 text-[11px] text-primary">
                                    <button onClick={() => setFilters({ ...filters, operators: filteredOperators })}>Выбрать все</button>
                                    <button onClick={() => setFilters({ ...filters, operators: [] })}>Снять все</button>
                                </div>
                            </div>
                            <input
                                value={operatorSearch}
                                onChange={(e) => setOperatorSearch(e.target.value)}
                                placeholder="Поиск оператора"
                                className="input-base text-sm"
                            />
                            <div className="grid grid-cols-2 gap-2 max-h-40 overflow-auto border border-border rounded-md p-2">
                                {filteredOperators.map(op => (
                                    <label key={op} className="flex items-center gap-2 text-sm text-foreground">
                                        <input
                                            type="checkbox"
                                            checked={filters.operators.includes(op)}
                                            onChange={() => toggleList('operators', op)}
                                            className="rounded text-primary focus:ring-primary border-border"
                                        />
                                        {op}
                                    </label>
                                ))}
                                {filteredOperators.length === 0 && (
                                    <div className="text-xs text-foreground-secondary col-span-2">Ничего не найдено</div>
                                )}
                            </div>
                        </div>
                        <div className="mt-4 space-y-2">
                            <div className="flex items-center justify-between">
                                <label className="text-xs text-foreground-muted">Приложения</label>
                                <div className="flex gap-2 text-[11px] text-primary">
                                    <button onClick={() => setFilters({ ...filters, apps: filteredApps })}>Выбрать все</button>
                                    <button onClick={() => setFilters({ ...filters, apps: [] })}>Снять все</button>
                                </div>
                            </div>
                            <input
                                value={appSearch}
                                onChange={(e) => setAppSearch(e.target.value)}
                                placeholder="Поиск приложения"
                                className="input-base text-sm"
                            />
                            <div className="grid grid-cols-2 gap-2 max-h-40 overflow-auto border border-border rounded-md p-2">
                                {filteredApps.map(app => (
                                    <label key={app} className="flex items-center gap-2 text-sm text-foreground">
                                        <input
                                            type="checkbox"
                                            checked={filters.apps.includes(app)}
                                            onChange={() => toggleList('apps', app)}
                                            className="rounded text-primary focus:ring-primary border-border"
                                        />
                                        {app}
                                    </label>
                                ))}
                                {filteredApps.length === 0 && (
                                    <div className="text-xs text-foreground-secondary col-span-2">Ничего не найдено</div>
                                )}
                            </div>
                        </div>
                        <div className="mt-4">
                            <div className="flex items-center justify-between">
                                <label className="text-xs text-foreground-muted">Источник</label>
                                <button
                                    onClick={() => setFilters({ ...filters, sourceType: 'ALL', telegramSourceIds: [] })}
                                    className="text-[11px] text-primary"
                                >
                                    Сбросить источник
                                </button>
                            </div>
                            <div className="mt-3 flex flex-wrap gap-2">
                                <button
                                    type="button"
                                    onClick={() => applyDirectSource('SMS')}
                                    className={`rounded-md border px-3 py-1.5 text-sm transition-colors ${
                                        filters.sourceType === 'SMS'
                                            ? 'border-primary bg-primary text-foreground-inverse'
                                            : 'border-border bg-surface text-foreground hover:bg-surface-2'
                                    }`}
                                >
                                    СМС
                                </button>
                                <button
                                    type="button"
                                    onClick={() => applyDirectSource('MANUAL')}
                                    className={`rounded-md border px-3 py-1.5 text-sm transition-colors ${
                                        filters.sourceType === 'MANUAL'
                                            ? 'border-primary bg-primary text-foreground-inverse'
                                            : 'border-border bg-surface text-foreground hover:bg-surface-2'
                                    }`}
                                >
                                    Ручной
                                </button>
                            </div>
                            <div className="mt-4 space-y-2">
                                <div className="flex items-center justify-between">
                                    <label className="text-xs text-foreground-muted">Актуальные Telegram-источники</label>
                                    <div className="flex gap-2 text-[11px] text-primary">
                                        <button
                                            onClick={() =>
                                                setFilters({
                                                    ...filters,
                                                    sourceType: filteredTelegramSources.length > 0 ? 'TELEGRAM' : 'ALL',
                                                    telegramSourceIds: filteredTelegramSources.map((item) => item.chat_id),
                                                })
                                            }
                                        >
                                            Выбрать все
                                        </button>
                                        <button
                                            onClick={() =>
                                                setFilters({
                                                    ...filters,
                                                    sourceType: 'ALL',
                                                    telegramSourceIds: [],
                                                })
                                            }
                                        >
                                            Снять все
                                        </button>
                                    </div>
                                </div>
                                <input
                                    value={sourceSearch}
                                    onChange={(e) => setSourceSearch(e.target.value)}
                                    placeholder="Поиск бота, группы или канала"
                                    className="input-base text-sm"
                                />
                                <div className="grid grid-cols-1 gap-2 max-h-48 overflow-auto border border-border rounded-md p-2">
                                    {filteredTelegramSources.map((item) => (
                                        <label key={item.chat_id} className="flex items-start gap-2 text-sm text-foreground">
                                            <input
                                                type="checkbox"
                                                checked={filters.telegramSourceIds.includes(item.chat_id)}
                                                onChange={() => toggleTelegramSource(item.chat_id)}
                                                className="rounded text-primary focus:ring-primary border-border mt-0.5"
                                            />
                                            <div className="min-w-0">
                                                <div className="truncate">{item.title}</div>
                                                <div className="text-[11px] text-foreground-secondary">
                                                    {getChatTypeLabel(item.chat_type)} · {item.count}
                                                </div>
                                            </div>
                                        </label>
                                    ))}
                                    {filteredTelegramSources.length === 0 && (
                                        <div className="text-xs text-foreground-secondary">Нет актуальных источников</div>
                                    )}
                                </div>
                            </div>
                        </div>
                    </section>

                    {/* Group D: ID */}
                    <section>
                        <h3 className="section-title flex items-center gap-2">
                            <Hash className="w-4 h-4" /> Идентификаторы
                        </h3>
                        <div className="mt-3">
                            <input
                                type="text"
                                placeholder="Поиск по номеру ПК..."
                                value={filters.cardId}
                                onChange={e => setFilters({ ...filters, cardId: e.target.value })}
                                className="input-base"
                            />
                        </div>
                    </section>
                </div>

                {/* Footer */}
                <div className="p-4 border-t border-border bg-surface-2 flex gap-3">
                    <button
                        onClick={handleReset}
                        className="flex-1 px-4 py-2 bg-surface border border-border text-foreground font-medium rounded-lg hover:bg-surface-3 transition-colors focus:outline-none focus:ring-2 focus:ring-primary"
                    >
                        Сбросить
                    </button>
                    <button
                        onClick={handleApply}
                        className="flex-1 px-4 py-2 bg-primary text-foreground-inverse font-medium rounded-lg hover:bg-primary-hover transition-colors shadow-sm focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-surface"
                    >
                        Применить
                    </button>
                </div>
            </div>
        </div>
    );
};

// Helpers
const getTypeLabel = (type: string) => {
    const map: Record<string, string> = {
        DEBIT: 'Списание',
        CREDIT: 'Пополнение',
        CONVERSION: 'Конверсия',
        REVERSAL: 'Отмена'
    };
    return map[type] || type;
};

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

// CSS Utilities (injected for simplicity, ideally in index.css)
// .input-base: w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-1 focus:ring-blue-500 focus:border-blue-500 outline-none text-sm
// .section-title: text-sm font-bold text-gray-900 uppercase tracking-wide
