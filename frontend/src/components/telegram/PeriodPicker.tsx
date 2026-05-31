import React, { useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Calendar, ChevronDown, Check } from 'lucide-react';
import { Popover } from '../motion/Popover';
import type { DateRange } from './ChatHeader';

export interface PeriodPickerProps {
    open: boolean;
    anchorRef: React.RefObject<HTMLElement>;
    range: DateRange;
    onChange: (range: DateRange) => void;
    onClose: () => void;
}

type PresetKey = 'today' | 'yesterday' | 'last7' | 'last30' | 'thisMonth' | 'prevMonth';

interface Preset {
    key: PresetKey;
    label: string;
}

const PRESETS: Preset[] = [
    { key: 'today', label: 'Сегодня' },
    { key: 'yesterday', label: 'Вчера' },
    { key: 'last7', label: 'Последние 7 дней' },
    { key: 'last30', label: 'Последние 30 дней' },
    { key: 'thisMonth', label: 'Этот месяц' },
    { key: 'prevMonth', label: 'Прошлый месяц' },
];

const toIsoDay = (d: Date): string => {
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
};

export function presetToRange(key: PresetKey, today: Date = new Date()): DateRange {
    const d = (offsetDays = 0) => {
        const x = new Date(today.getFullYear(), today.getMonth(), today.getDate());
        x.setDate(x.getDate() + offsetDays);
        return x;
    };
    switch (key) {
        case 'today': {
            const t = d(0);
            return { from: toIsoDay(t), to: toIsoDay(t) };
        }
        case 'yesterday': {
            const t = d(-1);
            return { from: toIsoDay(t), to: toIsoDay(t) };
        }
        case 'last7':
            return { from: toIsoDay(d(-6)), to: toIsoDay(d(0)) };
        case 'last30':
            return { from: toIsoDay(d(-29)), to: toIsoDay(d(0)) };
        case 'thisMonth': {
            const start = new Date(today.getFullYear(), today.getMonth(), 1);
            return { from: toIsoDay(start), to: toIsoDay(d(0)) };
        }
        case 'prevMonth': {
            const start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
            const end = new Date(today.getFullYear(), today.getMonth(), 0);
            return { from: toIsoDay(start), to: toIsoDay(end) };
        }
    }
}

export function matchesPreset(range: DateRange, key: PresetKey, today: Date = new Date()): boolean {
    const p = presetToRange(key, today);
    return p.from === range.from && p.to === range.to;
}

export function formatRangeLabel(range: DateRange, today: Date = new Date()): string {
    if (!range.from && !range.to) return '';
    for (const preset of PRESETS) {
        if (matchesPreset(range, preset.key, today)) {
            return preset.label;
        }
    }
    const fmt = (iso?: string) => {
        if (!iso) return '…';
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return iso;
        return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' });
    };
    return `${fmt(range.from)} — ${fmt(range.to)}`;
}

const customVariants = {
    hidden: { height: 0, opacity: 0 },
    visible: { height: 'auto', opacity: 1, transition: { duration: 0.22, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] } },
    exit: { height: 0, opacity: 0, transition: { duration: 0.16, ease: [0.4, 0, 1, 1] as [number, number, number, number] } },
};

export const PeriodPicker: React.FC<PeriodPickerProps> = ({ open, anchorRef, range, onChange, onClose }) => {
    const today = useMemo(() => new Date(), []);
    const [customOpen, setCustomOpen] = useState<boolean>(() => Boolean(range.from || range.to) && !PRESETS.some((p) => matchesPreset(range, p.key, today)));
    const [from, setFrom] = useState<string>(range.from || '');
    const [to, setTo] = useState<string>(range.to || '');

    const apply = (next: DateRange) => {
        onChange(next);
        onClose();
    };

    const applyCustom = () => {
        apply({ from: from || undefined, to: to || undefined });
    };

    const reset = () => {
        setFrom('');
        setTo('');
        onChange({});
        onClose();
    };

    return (
        <Popover open={open} anchorRef={anchorRef} onClose={onClose} placement="bottom-end" minWidth={260} ariaLabel="Выбор периода">
            <div className="tg-period-popover" role="dialog" aria-label="Выбор периода">
                <div className="tg-period-presets" role="menu">
                    {PRESETS.map((p) => {
                        const active = matchesPreset(range, p.key, today);
                        return (
                            <button
                                key={p.key}
                                type="button"
                                role="menuitemradio"
                                aria-checked={active}
                                aria-current={active ? 'true' : undefined}
                                className={`tg-period-preset${active ? ' is-active' : ''}`}
                                onClick={() => apply(presetToRange(p.key, today))}
                            >
                                <span>{p.label}</span>
                                {active ? <Check size={13} aria-hidden /> : null}
                            </button>
                        );
                    })}
                </div>

                <div className="tg-period-sep" aria-hidden />

                <button
                    type="button"
                    className={`tg-period-preset is-toggle${customOpen ? ' is-open' : ''}`}
                    aria-expanded={customOpen}
                    onClick={() => setCustomOpen((v) => !v)}
                >
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                        <Calendar size={13} />
                        Свой диапазон
                    </span>
                    <motion.span
                        animate={{ rotate: customOpen ? 180 : 0 }}
                        transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
                        style={{ display: 'inline-flex' }}
                    >
                        <ChevronDown size={13} />
                    </motion.span>
                </button>

                <AnimatePresence initial={false}>
                    {customOpen ? (
                        <motion.div
                            key="custom-block"
                            className="tg-period-custom"
                            variants={customVariants}
                            initial="hidden"
                            animate="visible"
                            exit="exit"
                        >
                            <div className="tg-period-custom-row">
                                <label>
                                    <span className="tg-period-label">От</span>
                                    <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} max={to || undefined} />
                                </label>
                                <label>
                                    <span className="tg-period-label">До</span>
                                    <input type="date" value={to} onChange={(e) => setTo(e.target.value)} min={from || undefined} />
                                </label>
                            </div>
                            <div className="tg-period-custom-actions">
                                <button type="button" className="tg-popover-btn" onClick={reset}>
                                    Сброс
                                </button>
                                <span style={{ flex: 1 }} />
                                <button
                                    type="button"
                                    className="tg-popover-btn is-primary"
                                    onClick={applyCustom}
                                    disabled={!from && !to}
                                >
                                    Применить
                                </button>
                            </div>
                        </motion.div>
                    ) : null}
                </AnimatePresence>
            </div>
        </Popover>
    );
};
