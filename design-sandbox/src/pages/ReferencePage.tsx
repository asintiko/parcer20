import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Search, Plus, Download, Upload, Rows3, Rows2, X } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { referenceApi, type OperatorReference, type OperatorReferenceCreate } from '../services/api';
import { ReferenceTable } from '../components/ReferenceTable';
import { useToast } from '../components/Toast';
import { Sheet } from '../components/motion/Sheet';
import { ConfirmDialog } from '../components/motion/ConfirmDialog';
import '../styles/reference.css';

type PageSizeOption = number | 'all';
const PAGE_SIZE_DEFAULT: PageSizeOption = 100;
type StatusFilter = 'all' | 'active' | 'inactive' | 'p2p';
type Density = 'standard' | 'compact';

const STATUS_FILTERS: { key: StatusFilter; label: string }[] = [
    { key: 'all', label: 'Все' },
    { key: 'active', label: 'Активные' },
    { key: 'inactive', label: 'Неактивные' },
    { key: 'p2p', label: 'P2P' },
];

export function ReferencePage() {
    const queryClient = useQueryClient();
    const { showToast } = useToast();

    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState<PageSizeOption>(PAGE_SIZE_DEFAULT);
    const [search, setSearch] = useState('');
    const [debouncedSearch, setDebouncedSearch] = useState('');
    const [applicationFilter, setApplicationFilter] = useState<string>('');
    const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
    const [density, setDensity] = useState<Density>('standard');
    const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

    const [editTarget, setEditTarget] = useState<OperatorReference | null>(null);
    const [isAddOpen, setIsAddOpen] = useState(false);
    const [confirmDelete, setConfirmDelete] = useState<{ ids: number[]; label: string } | null>(null);

    const fileInputRef = useRef<HTMLInputElement>(null);
    const searchRef = useRef<HTMLInputElement>(null);

    // Debounce search
    useEffect(() => {
        const t = setTimeout(() => setDebouncedSearch(search.trim()), 240);
        return () => clearTimeout(t);
    }, [search]);

    const appsQuery = useQuery({
        queryKey: ['reference-applications'],
        queryFn: referenceApi.getApplications,
    });

    // Stats use a separate, unfiltered query so chips always show absolute counts.
    const statsQuery = useQuery({
        queryKey: ['reference-stats'],
        queryFn: () => referenceApi.getOperators({ all: true }),
    });

    const listQuery = useQuery({
        queryKey: [
            'reference-list',
            pageSize === 'all' ? 'all' : page,
            pageSize,
            debouncedSearch,
            applicationFilter,
            statusFilter,
        ],
        queryFn: () =>
            referenceApi.getOperators({
                page: pageSize === 'all' ? 1 : page,
                page_size: pageSize === 'all' ? undefined : pageSize,
                all: pageSize === 'all' ? true : undefined,
                search: debouncedSearch || undefined,
                application: applicationFilter || undefined,
                is_active:
                    statusFilter === 'active' ? true : statusFilter === 'inactive' ? false : undefined,
                is_p2p: statusFilter === 'p2p' ? true : undefined,
            }),
    });

    const stats = useMemo(() => {
        const items: OperatorReference[] = (statsQuery.data as any)?.items || [];
        const total = items.length;
        const active = items.filter((i) => i.is_active).length;
        const p2p = items.filter((i) => i.is_p2p).length;
        const apps = new Set(items.map((i) => i.application_name).filter(Boolean)).size;
        const inactive = total - active;
        return { total, active, inactive, p2p, apps };
    }, [statsQuery.data]);

    const createMutation = useMutation({
        mutationFn: referenceApi.createOperator,
        onSuccess: () => {
            showToast('success', 'Запись добавлена');
            queryClient.invalidateQueries({ queryKey: ['reference-list'] });
            queryClient.invalidateQueries({ queryKey: ['reference-stats'] });
            queryClient.invalidateQueries({ queryKey: ['reference-applications'] });
            setIsAddOpen(false);
        },
        onError: () => showToast('error', 'Не удалось добавить'),
    });

    const updateMutation = useMutation({
        mutationFn: ({ id, data }: { id: number; data: Partial<OperatorReferenceCreate> }) =>
            referenceApi.updateOperator(id, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['reference-list'] });
            queryClient.invalidateQueries({ queryKey: ['reference-stats'] });
        },
        onError: () => showToast('error', 'Не удалось сохранить'),
    });

    const deleteMutation = useMutation({
        mutationFn: referenceApi.deleteOperator,
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['reference-list'] });
            queryClient.invalidateQueries({ queryKey: ['reference-stats'] });
        },
        onError: () => showToast('error', 'Не удалось удалить'),
    });

    const importMutation = useMutation({
        mutationFn: referenceApi.importFromExcel,
        onSuccess: (res) => {
            showToast('success', `Импортировано: ${res.imported} · пропущено: ${res.skipped}`);
            if (res.errors?.length) {
                showToast('warning', `Импорт с ошибками: ${res.errors.length}`, {
                    duration: 8000,
                    details: res.errors.join('\n'),
                });
            }
            queryClient.invalidateQueries({ queryKey: ['reference-list'] });
            queryClient.invalidateQueries({ queryKey: ['reference-stats'] });
            queryClient.invalidateQueries({ queryKey: ['reference-applications'] });
        },
        onError: () => showToast('error', 'Ошибка импорта'),
    });

    const handleUpdate = (id: number, field: any, value: any) => {
        updateMutation.mutate({ id, data: { [field]: value } });
    };

    const handleDelete = (id: number) => {
        const item = ((listQuery.data as any)?.items || []).find((i: OperatorReference) => i.id === id);
        setConfirmDelete({ ids: [id], label: item?.operator_name || '' });
    };

    const handleBulkDelete = () => {
        const ids = Array.from(selectedIds);
        setConfirmDelete({ ids, label: `${ids.length} записей` });
    };

    const handleBulkActive = (active: boolean) => {
        Array.from(selectedIds).forEach((id) =>
            updateMutation.mutate({ id, data: { is_active: active } }),
        );
        setSelectedIds(new Set());
        showToast('success', active ? 'Записи активированы' : 'Записи деактивированы');
    };

    const handleConfirmDelete = async () => {
        if (!confirmDelete) return;
        await Promise.all(confirmDelete.ids.map((id) => deleteMutation.mutateAsync(id)));
        showToast('success', confirmDelete.ids.length > 1 ? 'Удалено' : 'Запись удалена');
        setSelectedIds((s) => {
            const n = new Set(s);
            confirmDelete.ids.forEach((id) => n.delete(id));
            return n;
        });
        setConfirmDelete(null);
    };

    const handleExport = async () => {
        try {
            const blob = await referenceApi.exportToExcel();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `operators-${new Date().toISOString().slice(0, 10)}.xlsx`;
            a.click();
            window.URL.revokeObjectURL(url);
            showToast('success', 'Файл сохранён');
        } catch {
            showToast('error', 'Экспорт не удался');
        }
    };

    const handleImportFile = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        importMutation.mutate(file);
        if (fileInputRef.current) fileInputRef.current.value = '';
    };

    // ⌘K / Ctrl+K → focus search; ⌘N / Ctrl+N → add new
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            const mod = e.metaKey || e.ctrlKey;
            if (mod && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                searchRef.current?.focus();
            }
            if (mod && e.key.toLowerCase() === 'n') {
                e.preventDefault();
                setIsAddOpen(true);
            }
            if (e.key === 'Escape' && document.activeElement === searchRef.current) {
                setSearch('');
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, []);

    const total = (listQuery.data as any)?.total || 0;
    const items: OperatorReference[] = (listQuery.data as any)?.items || [];

    const onToggleRow = (id: number) =>
        setSelectedIds((s) => {
            const n = new Set(s);
            if (n.has(id)) n.delete(id);
            else n.add(id);
            return n;
        });

    const onToggleAll = (ids: number[], all: boolean) =>
        setSelectedIds((s) => {
            const n = new Set(s);
            if (all) ids.forEach((id) => n.add(id));
            else ids.forEach((id) => n.delete(id));
            return n;
        });

    return (
        <div className="rf-shell">
            <header className="rf-head">
                <div className="rf-eyebrow">
                    <span className="rf-eyebrow-dot" />
                    Справочник · operator → application
                </div>
                <div className="rf-head-row">
                    <div className="rf-head-text">
                        <h1 className="rf-title">
                            Справочник <em>операторов</em>
                        </h1>
                        <p className="rf-subtitle">
                            Единый источник маппинга: имя продавца на чеке → нормализованное приложение.
                            Используется в каскаде распознавания.
                        </p>
                    </div>
                    <div className="rf-head-actions">
                        <button
                            type="button"
                            className="rf-btn"
                            onClick={() => fileInputRef.current?.click()}
                            disabled={importMutation.isPending}
                        >
                            <Upload size={14} />
                            {importMutation.isPending ? 'Импорт…' : 'Импорт'}
                        </button>
                        <button type="button" className="rf-btn" onClick={handleExport}>
                            <Download size={14} />
                            Экспорт
                        </button>
                        <button
                            type="button"
                            className="rf-btn rf-btn-primary"
                            onClick={() => setIsAddOpen(true)}
                            title="⌘N · добавить запись"
                        >
                            <Plus size={14} />
                            Добавить
                        </button>
                    </div>
                </div>
            </header>

            <div className="rf-stats" role="region" aria-label="Сводка справочника">
                <div className="rf-stat">
                    <div className="rf-stat-label">Всего</div>
                    <div className="rf-stat-value">{stats.total}</div>
                    <div className="rf-stat-meta">записей в справочнике</div>
                </div>
                <div className="rf-stat is-accent">
                    <div className="rf-stat-label">Активных</div>
                    <div className="rf-stat-value">{stats.active}</div>
                    <div className="rf-stat-meta">
                        {stats.total ? Math.round((stats.active / stats.total) * 100) : 0}% от общего
                    </div>
                </div>
                <div className="rf-stat">
                    <div className="rf-stat-label">P2P</div>
                    <div className="rf-stat-value">{stats.p2p}</div>
                    <div className="rf-stat-meta">помечено как P2P</div>
                </div>
                <div className="rf-stat">
                    <div className="rf-stat-label">Приложений</div>
                    <div className="rf-stat-value">{stats.apps}</div>
                    <div className="rf-stat-meta">уникальных целей</div>
                </div>
            </div>

            <div className="rf-toolbar">
                <div className="rf-search">
                    <Search size={14} className="rf-search-icon" aria-hidden />
                    <input
                        ref={searchRef}
                        type="search"
                        className="rf-search-input"
                        value={search}
                        onChange={(e) => {
                            setSearch(e.target.value);
                            setPage(1);
                        }}
                        placeholder="Поиск по оператору или приложению"
                        aria-label="Поиск по справочнику"
                    />
                    {search ? (
                        <button
                            type="button"
                            onClick={() => {
                                setSearch('');
                                searchRef.current?.focus();
                            }}
                            className="rf-search-kbd"
                            style={{ cursor: 'pointer' }}
                            aria-label="Очистить поиск"
                        >
                            ESC
                        </button>
                    ) : (
                        <span className="rf-search-kbd" aria-hidden>
                            ⌘K
                        </span>
                    )}
                </div>

                <div className="rf-chips" role="tablist" aria-label="Фильтр по статусу">
                    {STATUS_FILTERS.map(({ key, label }) => {
                        const count =
                            key === 'all'
                                ? stats.total
                                : key === 'active'
                                ? stats.active
                                : key === 'inactive'
                                ? stats.inactive
                                : stats.p2p;
                        const active = statusFilter === key;
                        return (
                            <button
                                key={key}
                                type="button"
                                role="tab"
                                aria-selected={active}
                                className={`rf-chip${active ? ' is-active' : ''}`}
                                onClick={() => {
                                    setStatusFilter(key);
                                    setPage(1);
                                }}
                            >
                                {label}
                                <span className="rf-chip-count">{count}</span>
                            </button>
                        );
                    })}
                </div>

                <select
                    className="rf-app-select"
                    value={applicationFilter}
                    onChange={(e) => {
                        setApplicationFilter(e.target.value);
                        setPage(1);
                    }}
                    aria-label="Фильтр по приложению"
                >
                    <option value="">Все приложения</option>
                    {appsQuery.data?.map((app) => (
                        <option key={app} value={app}>
                            {app}
                        </option>
                    ))}
                </select>

                <span className="rf-toolbar-spacer" />

                <button
                    type="button"
                    className="rf-btn rf-btn-icon"
                    onClick={() => setDensity((d) => (d === 'standard' ? 'compact' : 'standard'))}
                    aria-label={density === 'standard' ? 'Компактный режим' : 'Обычный режим'}
                    title={density === 'standard' ? 'Компактный режим' : 'Обычный режим'}
                >
                    {density === 'standard' ? <Rows2 size={14} /> : <Rows3 size={14} />}
                </button>
            </div>

            <AnimatePresence>
                {selectedIds.size > 0 ? (
                    <motion.div
                        className="rf-bulk"
                        role="region"
                        aria-label="Массовые действия"
                        initial={{ y: -6, opacity: 0 }}
                        animate={{ y: 0, opacity: 1 }}
                        exit={{ y: -6, opacity: 0 }}
                        transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
                    >
                        <span className="rf-bulk-count">
                            <strong>{selectedIds.size}</strong> выбрано
                        </span>
                        <button
                            type="button"
                            className="rf-bulk-action"
                            onClick={() => handleBulkActive(true)}
                        >
                            Активировать
                        </button>
                        <button
                            type="button"
                            className="rf-bulk-action"
                            onClick={() => handleBulkActive(false)}
                        >
                            Деактивировать
                        </button>
                        <span className="rf-bulk-spacer" />
                        <button
                            type="button"
                            className="rf-bulk-action is-danger"
                            onClick={handleBulkDelete}
                        >
                            Удалить · {selectedIds.size}
                        </button>
                        <button
                            type="button"
                            className="rf-bulk-action"
                            onClick={() => setSelectedIds(new Set())}
                            aria-label="Снять выбор"
                            title="Снять выбор"
                            style={{ width: 26, padding: 0, justifyContent: 'center' }}
                        >
                            <X size={13} />
                        </button>
                    </motion.div>
                ) : null}
            </AnimatePresence>

            <ReferenceTable
                data={items}
                total={total}
                page={page}
                pageSize={pageSize}
                density={density}
                isLoading={listQuery.isLoading || listQuery.isFetching}
                selectedIds={selectedIds}
                onToggleRow={onToggleRow}
                onToggleAll={onToggleAll}
                onPageChange={setPage}
                onPageSizeChange={(size) => {
                    setPageSize(size);
                    setPage(1);
                }}
                onUpdate={handleUpdate}
                onDelete={handleDelete}
                onEditFull={(item) => setEditTarget(item)}
            />

            <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx,.xls"
                onChange={handleImportFile}
                className="hidden"
                style={{ display: 'none' }}
            />

            <Sheet
                open={isAddOpen}
                onClose={() => setIsAddOpen(false)}
                title="Новая запись"
                subtitle="оператор → приложение"
                ariaLabel="Добавить запись в справочник"
                width={420}
                footer={
                    <>
                        <span className="sp-spacer" />
                        <button
                            type="button"
                            className="sp-btn"
                            onClick={() => setIsAddOpen(false)}
                            disabled={createMutation.isPending}
                        >
                            Отмена
                        </button>
                    </>
                }
            >
                <ReferenceForm
                    suggestedApps={appsQuery.data || []}
                    busy={createMutation.isPending}
                    onSubmit={(payload) => createMutation.mutate(payload)}
                    submitLabel="Добавить"
                />
            </Sheet>

            <Sheet
                open={editTarget !== null}
                onClose={() => setEditTarget(null)}
                title="Редактирование"
                subtitle={editTarget?.operator_name || ''}
                ariaLabel="Редактировать запись"
                width={420}
                footer={
                    <>
                        <span className="sp-spacer" />
                        <button
                            type="button"
                            className="sp-btn"
                            onClick={() => setEditTarget(null)}
                        >
                            Закрыть
                        </button>
                    </>
                }
            >
                {editTarget ? (
                    <ReferenceForm
                        suggestedApps={appsQuery.data || []}
                        initial={editTarget}
                        busy={updateMutation.isPending}
                        onSubmit={(payload) => {
                            updateMutation.mutate({ id: editTarget.id, data: payload });
                            setEditTarget(null);
                            showToast('success', 'Сохранено');
                        }}
                        submitLabel="Сохранить"
                    />
                ) : null}
            </Sheet>

            <ConfirmDialog
                open={confirmDelete !== null}
                title={
                    confirmDelete && confirmDelete.ids.length > 1
                        ? `Удалить ${confirmDelete.ids.length} записей?`
                        : 'Удалить запись?'
                }
                description={
                    confirmDelete?.label
                        ? `Будет удалено: ${confirmDelete.label}.`
                        : 'Это действие необратимо.'
                }
                confirmLabel={confirmDelete && confirmDelete.ids.length > 1 ? 'Удалить все' : 'Удалить'}
                tone="danger"
                onConfirm={handleConfirmDelete}
                onClose={() => setConfirmDelete(null)}
            />
        </div>
    );
}

interface ReferenceFormProps {
    initial?: Partial<OperatorReferenceCreate>;
    suggestedApps: string[];
    busy?: boolean;
    onSubmit: (data: OperatorReferenceCreate) => void;
    submitLabel?: string;
}

function ReferenceForm({
    initial,
    suggestedApps,
    busy,
    onSubmit,
    submitLabel = 'Сохранить',
}: ReferenceFormProps) {
    const [form, setForm] = useState<OperatorReferenceCreate>({
        operator_name: initial?.operator_name || '',
        application_name: initial?.application_name || '',
        is_p2p: initial?.is_p2p ?? false,
        is_active: initial?.is_active ?? true,
    });
    const [error, setError] = useState<string | null>(null);

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        if (!form.operator_name.trim() || !form.application_name.trim()) {
            setError('Оператор и приложение обязательны');
            return;
        }
        setError(null);
        onSubmit({
            operator_name: form.operator_name.trim(),
            application_name: form.application_name.trim(),
            is_p2p: form.is_p2p,
            is_active: form.is_active,
        });
    };

    const listId = useMemo(() => `rf-apps-${Math.random().toString(36).slice(2, 8)}`, []);

    return (
        <form className="rf-form" onSubmit={handleSubmit}>
            <div className="rf-field">
                <label className="rf-field-label" htmlFor="rf-op">
                    Оператор · продавец
                </label>
                <input
                    id="rf-op"
                    className="rf-field-input"
                    value={form.operator_name}
                    onChange={(e) => setForm({ ...form, operator_name: e.target.value })}
                    placeholder="Например: Магнит"
                    autoFocus
                />
            </div>
            <div className="rf-field">
                <label className="rf-field-label" htmlFor="rf-app">
                    Приложение
                </label>
                <input
                    id="rf-app"
                    className="rf-field-input"
                    value={form.application_name}
                    onChange={(e) => setForm({ ...form, application_name: e.target.value })}
                    placeholder="uzcard / humo / ofd / ..."
                    list={listId}
                />
                <datalist id={listId}>
                    {suggestedApps.map((app) => (
                        <option key={app} value={app} />
                    ))}
                </datalist>
            </div>
            <div className="rf-field-row">
                <label className="rf-field-toggle">
                    <input
                        type="checkbox"
                        className="rf-toggle"
                        checked={form.is_p2p ?? false}
                        onChange={(e) => setForm({ ...form, is_p2p: e.target.checked })}
                    />
                    P2P
                </label>
                <label className="rf-field-toggle">
                    <input
                        type="checkbox"
                        className="rf-toggle"
                        checked={form.is_active ?? true}
                        onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                    />
                    Активен
                </label>
            </div>
            {error ? <div className="rf-field-error">{error}</div> : null}
            <button
                type="submit"
                className="rf-btn rf-btn-primary"
                disabled={busy || !form.operator_name.trim() || !form.application_name.trim()}
                style={{ alignSelf: 'flex-start' }}
            >
                {busy ? 'Сохраняем…' : submitLabel}
            </button>
        </form>
    );
}
