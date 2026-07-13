import React, { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Plus, Play, Trash2, CheckCircle2, XCircle, Clock } from 'lucide-react';
import { routinesApi, type Routine, type RoutineKind, type RoutineCreate } from '../services/api';
import { useToast } from './Toast';
import { ConfirmDialog } from './motion/ConfirmDialog';

const KINDS: { value: RoutineKind; label: string }[] = [
    { value: 'reconcile', label: 'Сверка' },
    { value: 'summary', label: 'Сводка' },
    { value: 'receipt_audit', label: 'Аудит чеков' },
    { value: 'custom', label: 'Другое' },
];

// вс=0, пн=1 … сб=6 (matches backend _WEEKDAY map)
const WEEKDAYS: { value: number; label: string }[] = [
    { value: 1, label: 'Пн' },
    { value: 2, label: 'Вт' },
    { value: 3, label: 'Ср' },
    { value: 4, label: 'Чт' },
    { value: 5, label: 'Пт' },
    { value: 6, label: 'Сб' },
    { value: 0, label: 'Вс' },
];

const WEEKDAY_FULL: Record<number, string> = {
    0: 'Вс', 1: 'Пн', 2: 'Вт', 3: 'Ср', 4: 'Чт', 5: 'Пт', 6: 'Сб',
};

type ScheduleType = 'once' | 'weekly' | 'daily';

function pad2(n: number): string {
    return n.toString().padStart(2, '0');
}

function buildWeeklyCron(days: number[], time: string): string {
    const [h, m] = time.split(':');
    const order = [1, 2, 3, 4, 5, 6, 0];
    const sorted = days.length
        ? order.filter((d) => days.includes(d))
        : [1];
    return `${Number(m)} ${Number(h)} * * ${sorted.join(',')}`;
}

function buildDailyCron(time: string): string {
    const [h, m] = time.split(':');
    return `${Number(m)} ${Number(h)} * * *`;
}

function buildOncePlaceholderCron(date: string, time: string): string {
    const [h, m] = time.split(':');
    const day = Number(date.split('-')[2] || 1);
    return `${Number(m)} ${Number(h)} ${day} * *`;
}

function formatOnceLabel(iso?: string | null): string {
    if (!iso) return 'Однократно';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return 'Однократно';
    return `Однократно ${d.toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })}`;
}

function cronHuman(routine: Routine): string {
    if (routine.schedule_kind === 'once') {
        return formatOnceLabel(routine.run_at);
    }
    return cronToHuman(routine.cron);
}

function cronToHuman(cron: string): string {
    const parts = cron.trim().split(/\s+/);
    if (parts.length !== 5) return cron;
    const [m, h, , , dow] = parts;
    const time = `${pad2(Number(h) || 0)}:${pad2(Number(m) || 0)}`;
    if (dow === '*') return `Каждый день в ${time}`;
    const days = dow.split(',').map((d) => Number(d)).filter((d) => !Number.isNaN(d));
    if (!days.length) return cron;
    const order = [1, 2, 3, 4, 5, 6, 0];
    const labels = order.filter((d) => days.includes(d)).map((d) => WEEKDAY_FULL[d]);
    return `Каждый ${labels.join(', ')} в ${time}`;
}

const panelVariants = {
    hidden: { x: '100%' },
    visible: {
        x: 0,
        transition: { duration: 0.36, ease: [0.05, 0.7, 0.1, 1] as [number, number, number, number] },
    },
    exit: {
        x: '100%',
        transition: { duration: 0.24, ease: [0.3, 0, 0.8, 0.15] as [number, number, number, number] },
    },
};

interface Props {
    onClose: () => void;
    onModalOpenChange?: (open: boolean) => void;
}

export const AiAgentRoutinesPanel: React.FC<Props> = ({ onClose, onModalOpenChange }) => {
    const qc = useQueryClient();
    const { showToast } = useToast();
    const [creating, setCreating] = useState(false);
    const [confirmDelete, setConfirmDelete] = useState<Routine | null>(null);

    useEffect(() => {
        onModalOpenChange?.(confirmDelete !== null);
    }, [confirmDelete, onModalOpenChange]);

    const listQuery = useQuery({ queryKey: ['routines-list'], queryFn: routinesApi.list });
    const items: Routine[] = listQuery.data || [];
    const invalidate = () => qc.invalidateQueries({ queryKey: ['routines-list'] });

    const createMut = useMutation({
        mutationFn: routinesApi.create,
        onSuccess: () => { showToast('success', 'Рутина создана'); invalidate(); setCreating(false); },
        onError: () => showToast('error', 'Не удалось создать рутину'),
    });
    const updateMut = useMutation({
        mutationFn: ({ id, data }: { id: string; data: Partial<RoutineCreate> }) => routinesApi.update(id, data),
        onMutate: async ({ id, data }) => {
            await qc.cancelQueries({ queryKey: ['routines-list'] });
            const prev = qc.getQueryData<Routine[]>(['routines-list']);
            if (prev && typeof data.enabled === 'boolean') {
                qc.setQueryData<Routine[]>(['routines-list'], prev.map((r) => r.id === id ? { ...r, enabled: data.enabled as boolean } : r));
            }
            return { prev };
        },
        onError: (_e, _v, ctx) => {
            if (ctx?.prev) qc.setQueryData(['routines-list'], ctx.prev);
            showToast('error', 'Не удалось сохранить');
        },
        onSettled: invalidate,
    });
    const runMut = useMutation({
        mutationFn: routinesApi.run,
        onSuccess: () => showToast('success', 'Запущено — отчёт придёт в канал и чат агента'),
        onError: () => showToast('error', 'Не удалось запустить'),
    });
    const deleteMut = useMutation({
        mutationFn: routinesApi.remove,
        onSuccess: () => { showToast('success', 'Рутина удалена'); invalidate(); },
        onError: () => showToast('error', 'Не удалось удалить'),
    });

    return (
        <motion.div
            className="agent-routines"
            variants={panelVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
        >
            <div className="agent-routines-head">
                <button type="button" className="agent-icon-btn" onClick={onClose} aria-label="Назад к чату" title="Назад">
                    <ArrowLeft size={16} />
                </button>
                <div className="agent-routines-head-text">
                    <div className="agent-eyebrow">Рутины агента</div>
                </div>
                <button type="button" className="agent-icon-btn" onClick={() => setCreating((v) => !v)}
                    aria-label="Создать рутину" title="Создать рутину" data-active={creating || undefined}>
                    <Plus size={16} />
                </button>
            </div>

            {creating ? (
                <RoutineMiniForm
                    busy={createMut.isPending}
                    onCancel={() => setCreating(false)}
                    onSubmit={(p) => createMut.mutate(p)}
                />
            ) : null}

            <div className="agent-routines-list">
                {listQuery.isLoading ? (
                    <div className="agent-routines-empty">Загружаем…</div>
                ) : items.length === 0 ? (
                    <div className="agent-routines-empty">
                        Рутин пока нет. Нажмите «+» или попросите агента в чате: «каждый понедельник в 12 делай сверку».
                    </div>
                ) : items.map((r) => (
                    <div key={r.id} className={`agent-routines-row${!r.enabled ? ' is-off' : ''}`}>
                        <div className="agent-routines-row-main">
                            <div className="agent-routines-row-title">{r.name}</div>
                            <div className="agent-routines-row-meta">
                                <code>{cronHuman(r)}</code>
                                <RoutineStatus status={r.last_status} at={r.last_run_at} />
                            </div>
                        </div>
                        <div className="agent-routines-row-actions">
                            <input type="checkbox" className="agent-routines-toggle" checked={r.enabled}
                                title={r.enabled ? 'Выключить' : 'Включить'}
                                onChange={(e) => updateMut.mutate({ id: r.id, data: { enabled: e.target.checked } })} />
                            <button type="button" className="agent-icon-btn" title="Запустить сейчас"
                                onClick={() => runMut.mutate(r.id)}><Play size={13} /></button>
                            <button type="button" className="agent-icon-btn" title="Удалить"
                                onClick={() => setConfirmDelete(r)}><Trash2 size={13} /></button>
                        </div>
                    </div>
                ))}
            </div>

            <ConfirmDialog
                open={confirmDelete !== null}
                title="Удалить рутину?"
                description={confirmDelete ? `Будет удалена рутина «${confirmDelete.name}». Это действие необратимо.` : ''}
                confirmLabel="Удалить"
                cancelLabel="Отмена"
                tone="danger"
                onConfirm={async () => { if (confirmDelete) { await deleteMut.mutateAsync(confirmDelete.id); setConfirmDelete(null); } }}
                onClose={() => setConfirmDelete(null)}
            />
        </motion.div>
    );
};

function RoutineStatus({ status, at }: { status?: string | null; at?: string | null }) {
    if (!status) return <span className="agent-routines-status">—</span>;
    const when = at ? new Date(at).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '';
    const icon = status === 'ok' ? <CheckCircle2 size={12} /> : status === 'error' ? <XCircle size={12} /> : <Clock size={12} />;
    const color = status === 'ok' ? 'var(--success)' : status === 'error' ? 'var(--danger)' : 'var(--text-muted)';
    return <span className="agent-routines-status" style={{ color }}>{icon}<span>{when}</span></span>;
}

interface FormProps {
    busy?: boolean;
    onCancel: () => void;
    onSubmit: (data: RoutineCreate) => void;
}

function RoutineMiniForm({ busy, onCancel, onSubmit }: FormProps) {
    const [name, setName] = useState('');
    const [scheduleType, setScheduleType] = useState<ScheduleType>('weekly');
    const [days, setDays] = useState<number[]>([1]);
    const [weeklyTime, setWeeklyTime] = useState('12:00');
    const [dailyTime, setDailyTime] = useState('09:00');
    const [onceDate, setOnceDate] = useState('');
    const [onceTime, setOnceTime] = useState('09:00');
    const [kind, setKind] = useState<RoutineKind>('reconcile');
    const [task, setTask] = useState('');
    const [error, setError] = useState<string | null>(null);

    const toggleDay = (value: number) => {
        setDays((prev) => (prev.includes(value) ? prev.filter((d) => d !== value) : [...prev, value]));
    };

    const preview = (() => {
        if (scheduleType === 'once') {
            if (!onceDate) return 'Выберите дату и время';
            const iso = new Date(`${onceDate}T${onceTime}`);
            if (Number.isNaN(iso.getTime())) return 'Выберите дату и время';
            return formatOnceLabel(iso.toISOString());
        }
        if (scheduleType === 'daily') {
            return `Каждый день в ${dailyTime}`;
        }
        return cronToHuman(buildWeeklyCron(days, weeklyTime));
    })();

    const submit = (e: React.FormEvent) => {
        e.preventDefault();
        if (!name.trim() || !task.trim()) {
            setError('Название и задача обязательны');
            return;
        }

        let cron: string;
        let schedule_kind: 'recurring' | 'once';
        let run_at: string | null = null;

        if (scheduleType === 'once') {
            if (!onceDate) {
                setError('Укажите дату и время');
                return;
            }
            const dt = new Date(`${onceDate}T${onceTime}`);
            if (Number.isNaN(dt.getTime())) {
                setError('Некорректная дата или время');
                return;
            }
            if (dt.getTime() <= Date.now()) {
                setError('Дата и время должны быть в будущем');
                return;
            }
            schedule_kind = 'once';
            run_at = dt.toISOString();
            cron = buildOncePlaceholderCron(onceDate, onceTime);
        } else if (scheduleType === 'daily') {
            schedule_kind = 'recurring';
            cron = buildDailyCron(dailyTime);
        } else {
            if (!days.length) {
                setError('Выберите хотя бы один день недели');
                return;
            }
            schedule_kind = 'recurring';
            cron = buildWeeklyCron(days, weeklyTime);
        }

        setError(null);
        onSubmit({
            name: name.trim(),
            kind,
            task_prompt: task.trim(),
            cron,
            schedule_kind,
            run_at,
        });
    };

    return (
        <form className="agent-routines-form" onSubmit={submit}>
            <input className="agent-routines-input" value={name} autoFocus placeholder="Название (Еженедельная сверка)"
                onChange={(e) => setName(e.target.value)} />

            <div className="agent-seg" role="group" aria-label="Тип расписания">
                {([
                    { value: 'once', label: 'Разово' },
                    { value: 'weekly', label: 'Еженедельно' },
                    { value: 'daily', label: 'Ежедневно' },
                ] as { value: ScheduleType; label: string }[]).map((opt) => (
                    <button
                        type="button"
                        key={opt.value}
                        className="agent-seg-btn"
                        data-active={scheduleType === opt.value || undefined}
                        onClick={() => setScheduleType(opt.value)}
                    >
                        {opt.label}
                    </button>
                ))}
            </div>

            {scheduleType === 'weekly' ? (
                <>
                    <div className="agent-routines-days" role="group" aria-label="Дни недели">
                        {WEEKDAYS.map((d) => (
                            <button
                                type="button"
                                key={d.value}
                                className="agent-routines-day"
                                data-active={days.includes(d.value) || undefined}
                                onClick={() => toggleDay(d.value)}
                            >
                                {d.label}
                            </button>
                        ))}
                    </div>
                    <input type="time" className="agent-routines-input agent-routines-time" value={weeklyTime}
                        onChange={(e) => setWeeklyTime(e.target.value)} aria-label="Время запуска" />
                </>
            ) : null}

            {scheduleType === 'daily' ? (
                <input type="time" className="agent-routines-input agent-routines-time" value={dailyTime}
                    onChange={(e) => setDailyTime(e.target.value)} aria-label="Время запуска" />
            ) : null}

            {scheduleType === 'once' ? (
                <div className="agent-routines-once">
                    <input type="date" className="agent-routines-input agent-routines-time" value={onceDate}
                        onChange={(e) => setOnceDate(e.target.value)} aria-label="Дата запуска" />
                    <input type="time" className="agent-routines-input agent-routines-time" value={onceTime}
                        onChange={(e) => setOnceTime(e.target.value)} aria-label="Время запуска" />
                </div>
            ) : null}

            <div className="agent-routines-preview">{preview}</div>

            <select className="agent-routines-input" value={kind} onChange={(e) => setKind(e.target.value as RoutineKind)}>
                {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
            </select>
            <textarea className="agent-routines-input" rows={2} value={task} placeholder="Что делать (текстом)"
                onChange={(e) => setTask(e.target.value)} />
            {error ? <div className="agent-routines-error">{error}</div> : null}
            <div className="agent-routines-form-actions">
                <button type="button" className="agent-btn" onClick={onCancel}>Отмена</button>
                <button type="submit" className="agent-btn agent-btn-primary" disabled={busy}>
                    {busy ? 'Создаю…' : 'Создать'}
                </button>
            </div>
        </form>
    );
}
