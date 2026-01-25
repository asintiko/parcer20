import React, { useState, useEffect } from 'react';
import { X, Calendar, Search, DollarSign, Smartphone, Hash } from 'lucide-react';

interface FilterState {
    dateFrom: string;
    dateTo: string;
    daysOfWeek: number[];
    amountMin: string;
    amountMax: string;
    currency: 'UZS' | 'USD';
    transactionTypes: string[];
    operators: string[];
    apps: string[];
    sourceType: 'ALL' | 'TELEGRAM' | 'SMS' | 'MANUAL';
    cardId: string;
}

interface FilterDrawerProps {
    isOpen: boolean;
    onClose: () => void;
    onApply: (filters: FilterState) => void;
    initialFilters?: Partial<FilterState>;
}

const DEFAULT_FILTERS: FilterState = {
    dateFrom: '',
    dateTo: '',
    daysOfWeek: [],
    amountMin: '',
    amountMax: '',
    currency: 'UZS',
    transactionTypes: [],
    operators: [],
    apps: [],
    sourceType: 'ALL',
    cardId: '',
};

const OPERATORS_LIST = ['Beeline', 'Ucell', 'Mobiuz', 'Uztelecom', 'Korzinka', 'Makro', 'Click', 'Payme'];
const APPS_LIST = ['Click Evolution', 'Apelsin', 'Payme', 'Ipak Yuli'];
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

export const FilterDrawer: React.FC<FilterDrawerProps> = ({ isOpen, onClose, onApply, initialFilters }) => {
    const [filters, setFilters] = useState<FilterState>({ ...DEFAULT_FILTERS, ...initialFilters });
    const [isVisible, setIsVisible] = useState(false);
    const [isMounted, setIsMounted] = useState(false);

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

    const handleApply = () => {
        onApply(filters);
        onClose();
    };

    const handleReset = () => {
        setFilters(DEFAULT_FILTERS);
    };

    if (!isMounted) return null;

    return (
        <div className="fixed inset-0 z-[60] flex justify-end">
            {/* Backdrop */}
            <div
                className={`fixed inset-0 bg-black/20 backdrop-blur-sm transition-opacity duration-300 ease-in-out ${isVisible ? 'opacity-100' : 'opacity-0'
                    }`}
                onClick={onClose}
            />

            {/* Drawer */}
            <div
                className={`relative w-full max-w-md bg-surface h-full shadow-2xl flex flex-col transform transition-transform duration-300 ease-in-out border-l border-border ${isVisible ? 'translate-x-0' : 'translate-x-full'
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
                                <label className="text-xs text-foreground-muted mb-1 block">Дата C</label>
                                <input
                                    type="date"
                                    value={filters.dateFrom}
                                    onChange={e => setFilters({ ...filters, dateFrom: e.target.value })}
                                    className="input-base"
                                />
                            </div>
                            <div>
                                <label className="text-xs text-foreground-muted mb-1 block">Дата По</label>
                                <input
                                    type="date"
                                    value={filters.dateTo}
                                    onChange={e => setFilters({ ...filters, dateTo: e.target.value })}
                                    className="input-base"
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
                                {['UZS', 'USD'].map((curr) => (
                                    <button
                                        key={curr}
                                        onClick={() => setFilters({ ...filters, currency: curr as any })}
                                        className={`flex-1 px-4 py-2 text-sm font-medium border border-border first:rounded-l-lg last:rounded-r-lg focus:outline-none focus:ring-2 focus:ring-primary ${filters.currency === curr
                                                ? 'bg-primary-light text-primary border-primary/30 z-10'
                                                : 'bg-surface text-foreground border-border hover:bg-surface-2'
                                            } -ml-px first:ml-0`}
                                    >
                                        {curr}
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
                        <div className="mt-3">
                            <label className="text-xs text-foreground-muted mb-2 block">Операторы</label>
                            <div className="grid grid-cols-2 gap-2">
                                {OPERATORS_LIST.map(op => (
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
                            </div>
                        </div>
                        <div className="mt-4">
                            <label className="text-xs text-foreground-muted mb-2 block">Приложение</label>
                            <div className="grid grid-cols-2 gap-2">
                                {APPS_LIST.map(app => (
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
                            </div>
                        </div>
                        <div className="mt-4">
                            <label className="text-xs text-foreground-muted mb-2 block">Источник</label>
                            <div className="flex gap-4">
                                {['ALL', 'TELEGRAM', 'SMS', 'MANUAL'].map(src => (
                                    <label key={src} className="flex items-center gap-2 text-sm text-foreground">
                                        <input
                                            type="radio"
                                            name="sourceType"
                                            checked={filters.sourceType === src}
                                            onChange={() => setFilters({ ...filters, sourceType: src as any })}
                                            className="text-primary focus:ring-primary"
                                        />
                                        {getSourceLabel(src)}
                                    </label>
                                ))}
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

const getSourceLabel = (src: string) => {
    const map: Record<string, string> = {
        ALL: 'Все',
        TELEGRAM: 'Телеграм',
        SMS: 'СМС',
        MANUAL: 'Ручной',
    };
    return map[src] || src;
};

// CSS Utilities (injected for simplicity, ideally in index.css)
// .input-base: w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-1 focus:ring-blue-500 focus:border-blue-500 outline-none text-sm
// .section-title: text-sm font-bold text-gray-900 uppercase tracking-wide
