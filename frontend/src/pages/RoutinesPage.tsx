import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Play, History as HistoryIcon, Trash2, CheckCircle2, XCircle, Clock } from 'lucide-react';
import { routinesApi, type Routine, type RoutineCreate, type RoutineKind, type RoutineRun } from '../services/api';
import { useToast } from '../components/Toast';
import { Sheet } from '../components/motion/Sheet';
import { ConfirmDialog } from '../components/motion/ConfirmDialog';
import '../styles/reference.css';

const KINDS: { value: RoutineKind; label: string }[] = [
    { value: 'reconcile', label: 'Сверка' },
    { value: 'summary', label: 'Сводка' },
    { value: 'custom', label: 'Другое' },
];

const KIND_LABEL: Record<string, string> = {
    reconcile: 'Сверка',
    summary: 'Сводка',
    custom: 'Другое',
};

const CRON_PRESETS: { label: string; cron: string }[] = [
    { label: 'Каждый пн в 12:00', cron: '0 12 * * 1' },
    { label: 'Ежедневно в 9:00', cron: '0 9 * * *' },
    { label: 'Каждый час', cron: '0 * * * *' },
    { label: '1-го числа в 10:00', cron: '0 10 1 * *' },
];

function cronHuman(cron: string): string {
    const found = CRON_PRESETS.find((p) => p.cron === cron.trim());
    return found ? found.label : cron;
}

export function RoutinesPage() {
    const queryClient = useQueryClient();
    const { showToast } = useToast();

    const [isAddOpen, setIsAddOpen] = useState(false);
    const [editTarget, setEditTarget] = useState<Routine | null>(null);
    const [confirmDelete, setConfirmDelete] = useState<Routine | null>(null);
    const [historyTarget, setHistoryTarget] = useState<Routine | null>(null);

    const listQuery = useQuery({ queryKey: ['routines-list'], queryFn: routinesApi.list });
    const items: Routine[] = listQuery.data || [];

    const invalidate = () => queryClient.invalidateQueries({ queryKey: ['routines-list'] });

    const createMutation = useMutation({
        mutationFn: routinesApi.create,
        onSuccess: () => { showToast('success', 'Рутина создана'); invalidate(); setIsAddOpen(false); },
        onError: () => showToast('error', 'Не удалось создать рутину'),
    });
    const updateMutation = useMutation({
        mutationFn: ({ id, data }: { id: string; data: Partial<RoutineCreate> }) => routinesApi.update(id, data),
        onSuccess: () => invalidate(),
        onError: () => showToast('error', 'Не удалось сохранить'),
    });
    const deleteMutation = useMutation({
        mutationFn: routinesApi.remove,
        onSuccess: () => { showToast('success', 'Рутина удалена'); invalidate(); },
        onError: () => showToast('error', 'Не удалось удалить'),
    });
    const runMutation = useMutation({
        mutationFn: routinesApi.run,
        onSuccess: () => showToast('success', 'Запущено — отчёт придёт в канал и в чат агента'),
        onError: () => showToast('error', 'Не удалось запустить'),
    });

    const enabledCount = items.filter((r) => r.enabled).length;

    return (
        <div className="rf-shell">
            <header className="rf-head">
                <div className="rf-eyebrow"><span className="rf-eyebrow-dot" />Рутины · плановые задачи агента</div>
                <div className="rf-head-row">
                    <div className="rf-head-text">
                        <h1 className="rf-title">Рутины <em>агента</em></h1>
                        <p className="rf-subtitle">Запланированные задачи: агент по расписанию делает сверку, сводки и присылает отчёт.</p>
                    </div>
                    <div className="rf-head-actions">
                        <button type="button" className="rf-btn rf-btn-primary" onClick={() => setIsAddOpen(true)}>
                            <Plus size={14} /> Добавить рутину
                        </button>
                    </div>
                </div>
            </header>

            <div className="rf-stats">
                <div className="rf-stat"><span className="rf-stat-value">{items.length}</span><span className="rf-stat-label">всего</span></div>
                <div className="rf-stat"><span className="rf-stat-value">{enabledCount}</span><span className="rf-stat-label">активных</span></div>
            </div>

            <div className="rf-table-wrap">
                <table className="rf-table">
                    <thead>
                        <tr>
                            <th>Название</th>
                            <th>Расписание</th>
                            <th>Тип</th>
                            <th>Последний запуск</th>
                            <th className="is-center">Активна</th>
                            <th className="is-narrow">Действия</th>
                        </tr>
                    </thead>
                    <tbody>
                        {listQuery.isLoading ? (
                            <tr><td colSpan={6} className="rf-field-label" style={{ padding: 24 }}>Загружаем…</td></tr>
                        ) : items.length === 0 ? (
                            <tr><td colSpan={6} style={{ padding: 24, color: 'var(--text-muted)' }}>
                                Рутин пока нет. Нажмите «Добавить рутину» или попросите агента в чате: «каждый понедельник в 12 делай сверку».
                            </td></tr>
                        ) : items.map((r) => (
                            <tr key={r.id} className={!r.enabled ? 'is-inactive' : undefined}>
                                <td><button type="button" onClick={() => setEditTarget(r)}
                                    style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: 'var(--text)', font: 'inherit', fontWeight: 500, textAlign: 'left' }}>{r.name}</button></td>
                                <td><code style={{ fontFamily: 'var(--font-mono)' }}>{cronHuman(r.cron)}</code></td>
                                <td>{KIND_LABEL[r.kind] || r.kind}</td>
                                <td><StatusBadge status={r.last_status} at={r.last_run_at} /></td>
                                <td className="is-center">
                                    <input type="checkbox" className="rf-toggle" checked={r.enabled}
                                        onChange={(e) => updateMutation.mutate({ id: r.id, data: { enabled: e.target.checked } })} />
                                </td>
                                <td className="is-narrow">
                                    <div style={{ display: 'flex', gap: 4 }}>
                                        <button className="rf-btn rf-btn-icon" title="Запустить сейчас" onClick={() => runMutation.mutate(r.id)}><Play size={14} /></button>
                                        <button className="rf-btn rf-btn-icon" title="История запусков" onClick={() => setHistoryTarget(r)}><HistoryIcon size={14} /></button>
                                        <button className="rf-btn rf-btn-icon" title="Удалить" onClick={() => setConfirmDelete(r)}><Trash2 size={14} /></button>
                                    </div>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            <Sheet open={isAddOpen} onClose={() => setIsAddOpen(false)} title="Новая рутина" ariaLabel="Добавить рутину" width={480}
                footer={<><span className="sp-spacer" /><button className="sp-btn" onClick={() => setIsAddOpen(false)}>Отмена</button></>}>
                <RoutineForm busy={createMutation.isPending} submitLabel="Создать"
                    onSubmit={(p) => createMutation.mutate(p)} />
            </Sheet>

            <Sheet open={editTarget !== null} onClose={() => setEditTarget(null)} title="Рутина" subtitle={editTarget?.name} ariaLabel="Редактировать рутину" width={480}
                footer={<><span className="sp-spacer" /><button className="sp-btn" onClick={() => setEditTarget(null)}>Закрыть</button></>}>
                {editTarget ? (
                    <RoutineForm initial={editTarget} busy={updateMutation.isPending} submitLabel="Сохранить"
                        onSubmit={(p) => { updateMutation.mutate({ id: editTarget.id, data: p }); setEditTarget(null); showToast('success', 'Сохранено'); }} />
                ) : null}
            </Sheet>

            <Sheet open={historyTarget !== null} onClose={() => setHistoryTarget(null)} title="История запусков" subtitle={historyTarget?.name} ariaLabel="История запусков" width={560}
                footer={<><span className="sp-spacer" /><button className="sp-btn" onClick={() => setHistoryTarget(null)}>Закрыть</button></>}>
                {historyTarget ? <RunHistory routineId={historyTarget.id} /> : null}
            </Sheet>

            <ConfirmDialog open={confirmDelete !== null}
                title="Удалить рутину?" description={confirmDelete ? `Будет удалена рутина «${confirmDelete.name}». Это действие необратимо.` : ''}
                confirmLabel="Удалить" tone="danger"
                onConfirm={async () => { if (confirmDelete) { await deleteMutation.mutateAsync(confirmDelete.id); setConfirmDelete(null); } }}
                onClose={() => setConfirmDelete(null)} />
        </div>
    );
}

function StatusBadge({ status, at }: { status?: string | null; at?: string | null }) {
    if (!status) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
    const when = at ? new Date(at).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '';
    const icon = status === 'ok' ? <CheckCircle2 size={13} /> : status === 'error' ? <XCircle size={13} /> : <Clock size={13} />;
    const color = status === 'ok' ? 'var(--success)' : status === 'error' ? 'var(--danger)' : 'var(--text-muted)';
    return <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color }}>{icon}<span style={{ color: 'var(--text-muted)', fontSize: 'var(--text-xs)' }}>{when}</span></span>;
}

interface RoutineFormProps {
    initial?: Partial<Routine>;
    busy?: boolean;
    submitLabel?: string;
    onSubmit: (data: RoutineCreate) => void;
}

function RoutineForm({ initial, busy, submitLabel = 'Сохранить', onSubmit }: RoutineFormProps) {
    const [name, setName] = useState(initial?.name || '');
    const [cron, setCron] = useState(initial?.cron || '0 12 * * 1');
    const [kind, setKind] = useState<RoutineKind>((initial?.kind as RoutineKind) || 'reconcile');
    const [task, setTask] = useState(initial?.task_prompt || '');
    const [deliverChannel, setDeliverChannel] = useState(initial?.deliver_to_channel ?? true);
    const [deliverChat, setDeliverChat] = useState(initial?.deliver_to_chat ?? true);
    const [error, setError] = useState<string | null>(null);

    const submit = (e: React.FormEvent) => {
        e.preventDefault();
        if (!name.trim() || !cron.trim() || !task.trim()) {
            setError('Название, расписание и задача обязательны');
            return;
        }
        setError(null);
        onSubmit({
            name: name.trim(), cron: cron.trim(), kind, task_prompt: task.trim(),
            deliver_to_channel: deliverChannel, deliver_to_chat: deliverChat,
        });
    };

    return (
        <form className="rf-form" onSubmit={submit}>
            <div className="rf-field">
                <label className="rf-field-label" htmlFor="rt-name">Название</label>
                <input id="rt-name" className="rf-field-input" value={name} autoFocus
                    onChange={(e) => setName(e.target.value)} placeholder="Еженедельная сверка" />
            </div>

            <div className="rf-field">
                <label className="rf-field-label">Расписание</label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
                    {CRON_PRESETS.map((p) => (
                        <button type="button" key={p.cron} className="rf-chip"
                            data-active={cron.trim() === p.cron || undefined}
                            onClick={() => setCron(p.cron)}>{p.label}</button>
                    ))}
                </div>
                <input className="rf-field-input" value={cron} onChange={(e) => setCron(e.target.value)}
                    placeholder="0 12 * * 1" style={{ fontFamily: 'var(--font-mono)' }} />
                <span style={{ color: 'var(--text-muted)', fontSize: 'var(--text-2xs)', marginTop: 4 }}>
                    cron: мин час день месяц день_недели (Asia/Tashkent, пн=1)
                </span>
            </div>

            <div className="rf-field">
                <label className="rf-field-label" htmlFor="rt-kind">Тип</label>
                <select id="rt-kind" className="rf-app-select" value={kind} onChange={(e) => setKind(e.target.value as RoutineKind)}>
                    {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
                </select>
            </div>

            <div className="rf-field">
                <label className="rf-field-label" htmlFor="rt-task">Задача (текстом)</label>
                <textarea id="rt-task" className="rf-field-input" rows={3} value={task}
                    onChange={(e) => setTask(e.target.value)}
                    placeholder="Сверить все транзакции с локальными сообщениями Telegram и сообщить об ошибках." />
            </div>

            <div className="rf-field-row">
                <label className="rf-field-toggle">
                    <input type="checkbox" className="rf-toggle" checked={deliverChannel} onChange={(e) => setDeliverChannel(e.target.checked)} />
                    Отчёт в Telegram-канал
                </label>
                <label className="rf-field-toggle">
                    <input type="checkbox" className="rf-toggle" checked={deliverChat} onChange={(e) => setDeliverChat(e.target.checked)} />
                    Отчёт в чат агента
                </label>
            </div>

            {error ? <div className="rf-field-error">{error}</div> : null}
            <button type="submit" className="rf-btn rf-btn-primary" disabled={busy} style={{ alignSelf: 'flex-start' }}>
                {busy ? 'Сохраняем…' : submitLabel}
            </button>
        </form>
    );
}

function RunHistory({ routineId }: { routineId: string }) {
    const runsQuery = useQuery({ queryKey: ['routine-runs', routineId], queryFn: () => routinesApi.runs(routineId) });
    const runs: RoutineRun[] = runsQuery.data || [];
    if (runsQuery.isLoading) return <div className="rf-field-label" style={{ padding: 12 }}>Загружаем…</div>;
    if (runs.length === 0) return <div style={{ padding: 12, color: 'var(--text-muted)' }}>Запусков пока не было.</div>;
    return (
        <table className="rf-table">
            <thead><tr><th>Время</th><th>Триггер</th><th>Статус</th><th>Итог</th></tr></thead>
            <tbody>
                {runs.map((run) => (
                    <tr key={run.id}>
                        <td style={{ whiteSpace: 'nowrap' }}>{run.started_at ? new Date(run.started_at).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '—'}</td>
                        <td>{run.trigger === 'manual' ? 'вручную' : 'по расписанию'}</td>
                        <td style={{ color: run.status === 'ok' ? 'var(--success)' : run.status === 'error' ? 'var(--danger)' : 'var(--text-muted)' }}>
                            {run.status === 'ok' ? 'успех' : run.status === 'error' ? 'ошибка' : 'выполняется'}
                        </td>
                        <td style={{ color: 'var(--text-secondary)', fontSize: 'var(--text-xs)' }}>{run.summary || run.error_text || '—'}</td>
                    </tr>
                ))}
            </tbody>
        </table>
    );
}
