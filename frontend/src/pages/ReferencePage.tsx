import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { referenceApi, OperatorReferenceCreate } from '../services/api';
import { ReferenceTable } from '../components/ReferenceTable';
import { useToast } from '../components/Toast';
import { Search, Plus, Download, Upload, Filter, X, CheckCircle2 } from 'lucide-react';

const PAGE_SIZE_DEFAULT = 50;

export function ReferencePage() {
    const queryClient = useQueryClient();
    const { showToast } = useToast();

    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(PAGE_SIZE_DEFAULT);
    const [search, setSearch] = useState('');
    const [debouncedSearch, setDebouncedSearch] = useState('');
    const [applicationFilter, setApplicationFilter] = useState<string>('');
    const [activeOnly, setActiveOnly] = useState(true);
    const [p2pOnly, setP2pOnly] = useState(false);
    const [isAddOpen, setIsAddOpen] = useState(false);

    const fileInputRef = useRef<HTMLInputElement>(null);

    // Debounce search
    useEffect(() => {
        const t = setTimeout(() => setDebouncedSearch(search.trim()), 300);
        return () => clearTimeout(t);
    }, [search]);

    const appsQuery = useQuery({
        queryKey: ['reference-applications'],
        queryFn: referenceApi.getApplications,
    });

    const listQuery = useQuery(
        {
            queryKey: ['reference-list', page, pageSize, debouncedSearch, applicationFilter, activeOnly, p2pOnly],
            queryFn: () =>
                referenceApi.getOperators({
                    page,
                    page_size: pageSize,
                    search: debouncedSearch || undefined,
                    application: applicationFilter || undefined,
                    is_active: activeOnly ? true : undefined,
                    is_p2p: p2pOnly ? true : undefined,
                }),
        }
    );

    const createMutation = useMutation({
        mutationFn: referenceApi.createOperator,
        onSuccess: () => {
            showToast('success', 'Добавлено');
            queryClient.invalidateQueries({ queryKey: ['reference-list'] });
            setIsAddOpen(false);
        },
        onError: () => showToast('error', 'Не удалось добавить'),
    });

    const updateMutation = useMutation({
        mutationFn: ({ id, data }: { id: number; data: Partial<OperatorReferenceCreate> }) =>
            referenceApi.updateOperator(id, data),
        onSuccess: () => {
            showToast('success', 'Сохранено');
            queryClient.invalidateQueries({ queryKey: ['reference-list'] });
        },
        onError: () => showToast('error', 'Не удалось сохранить'),
    });

    const deleteMutation = useMutation({
        mutationFn: referenceApi.deleteOperator,
        onSuccess: () => {
            showToast('success', 'Удалено');
            queryClient.invalidateQueries({ queryKey: ['reference-list'] });
        },
        onError: () => showToast('error', 'Не удалось удалить'),
    });

    const importMutation = useMutation({
        mutationFn: referenceApi.importFromExcel,
        onSuccess: (res) => {
            showToast('success', `Импортировано: ${res.imported}, пропущено: ${res.skipped}`);
            if (res.errors?.length) console.error(res.errors);
            queryClient.invalidateQueries({ queryKey: ['reference-list'] });
        },
        onError: () => showToast('error', 'Ошибка импорта'),
    });

    const handleUpdate = (id: number, field: any, value: any) => {
        updateMutation.mutate({ id, data: { [field]: value } });
    };

    const handleDelete = (id: number) => {
        if (confirm('Удалить запись?')) {
            deleteMutation.mutate(id);
        }
    };

    const handleExport = async () => {
        try {
            const blob = await referenceApi.exportToExcel();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'operators.xlsx';
            a.click();
            window.URL.revokeObjectURL(url);
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

    const total = (listQuery.data as any)?.total || 0;
    const items = (listQuery.data as any)?.items || [];

    return (
        <div className="p-6 space-y-4 h-full flex flex-col bg-bg">
            <header className="flex flex-wrap gap-3 items-center justify-between">
                <div>
                    <h1 className="text-2xl font-semibold text-foreground">Справочник операторов</h1>
                    <p className="text-sm text-foreground-secondary">Единый источник маппинга оператор → приложение</p>
                </div>
                <div className="flex flex-wrap gap-2">
                    <button
                        onClick={() => fileInputRef.current?.click()}
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-surface border border-border text-sm hover:bg-surface-2"
                    >
                        <Upload className="w-4 h-4" /> Импорт Excel
                    </button>
                    <button
                        onClick={handleExport}
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-surface border border-border text-sm hover:bg-surface-2"
                    >
                        <Download className="w-4 h-4" /> Экспорт Excel
                    </button>
                    <button
                        onClick={() => setIsAddOpen(true)}
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-primary text-foreground-inverse text-sm hover:bg-primary-hover"
                    >
                        <Plus className="w-4 h-4" /> Добавить
                    </button>
                </div>
            </header>

            <div className="bg-surface border border-border rounded-lg p-4 shadow-sm">
                <div className="flex flex-wrap gap-3 items-center">
                    <div className="relative flex-1 min-w-[240px]">
                        <Search className="w-4 h-4 text-foreground-muted absolute left-3 top-1/2 -translate-y-1/2" />
                        <input
                            value={search}
                            onChange={(e) => {
                                setSearch(e.target.value);
                                setPage(1);
                            }}
                            placeholder="Поиск по оператору или приложению"
                            className="w-full pl-9 pr-3 py-2 border border-border rounded-md bg-input-bg text-input-text focus:ring-2 focus:ring-primary"
                        />
                    </div>

                    <div className="flex items-center gap-2">
                        <Filter className="w-4 h-4 text-foreground-muted" />
                        <select
                            value={applicationFilter}
                            onChange={(e) => {
                                setApplicationFilter(e.target.value);
                                setPage(1);
                            }}
                            className="px-3 py-2 border border-border rounded-md bg-input-bg text-sm text-input-text"
                        >
                            <option value="">Все приложения</option>
                            {appsQuery.data?.map((app) => (
                                <option key={app} value={app}>
                                    {app}
                                </option>
                            ))}
                        </select>
                    </div>

                    <label className="flex items-center gap-2 text-sm text-foreground">
                        <input
                            type="checkbox"
                            checked={activeOnly}
                            onChange={(e) => {
                                setActiveOnly(e.target.checked);
                                setPage(1);
                            }}
                            className="w-4 h-4 text-primary border-border rounded"
                        />
                        Только активные
                    </label>

                    <label className="flex items-center gap-2 text-sm text-foreground">
                        <input
                            type="checkbox"
                            checked={p2pOnly}
                            onChange={(e) => {
                                setP2pOnly(e.target.checked);
                                setPage(1);
                            }}
                            className="w-4 h-4 text-primary border-border rounded"
                        />
                        Только P2P
                    </label>
                </div>
            </div>

            <div className="flex-1 min-h-0">
                <ReferenceTable
                    data={items}
                    total={total}
                    page={page}
                    pageSize={pageSize}
                    isLoading={listQuery.isLoading || listQuery.isFetching}
                    onPageChange={setPage}
                    onPageSizeChange={(size) => {
                        setPageSize(size);
                        setPage(1);
                    }}
                    onUpdate={handleUpdate}
                    onDelete={handleDelete}
                />
            </div>

            <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx,.xls"
                onChange={handleImportFile}
                className="hidden"
            />

            {isAddOpen && (
                <AddModal
                    onClose={() => setIsAddOpen(false)}
                    onSubmit={(payload) => createMutation.mutate(payload)}
                    isSubmitting={createMutation.isPending}
                />
            )}
        </div>
    );
}

function AddModal({
    onClose,
    onSubmit,
    isSubmitting,
}: {
    onClose: () => void;
    onSubmit: (data: OperatorReferenceCreate) => void;
    isSubmitting: boolean;
}) {
    const [form, setForm] = useState<OperatorReferenceCreate>({
        operator_name: '',
        application_name: '',
        is_active: true,
        is_p2p: false,
    });

    return (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
            <div className="bg-surface w-full max-w-md rounded-lg border border-border shadow-xl">
                <div className="flex items-center justify-between px-4 py-3 border-b border-border">
                    <div className="flex items-center gap-2 text-foreground">
                        <CheckCircle2 className="w-4 h-4 text-primary" />
                        <h3 className="text-lg font-semibold">Новая запись</h3>
                    </div>
                    <button onClick={onClose} className="text-foreground-muted hover:text-foreground">
                        <X className="w-5 h-5" />
                    </button>
                </div>
                <div className="p-4 space-y-3">
                    <div>
                        <label className="block text-sm text-foreground mb-1">Оператор / продавец</label>
                        <input
                            className="w-full px-3 py-2 border border-border rounded-md bg-input-bg text-input-text focus:ring-2 focus:ring-primary"
                            value={form.operator_name}
                            onChange={(e) => setForm({ ...form, operator_name: e.target.value })}
                        />
                    </div>
                    <div>
                        <label className="block text-sm text-foreground mb-1">Приложение</label>
                        <input
                            className="w-full px-3 py-2 border border-border rounded-md bg-input-bg text-input-text focus:ring-2 focus:ring-primary"
                            value={form.application_name}
                            onChange={(e) => setForm({ ...form, application_name: e.target.value })}
                        />
                    </div>
                    <div className="flex items-center gap-4">
                        <label className="flex items-center gap-2 text-sm text-foreground">
                            <input
                                type="checkbox"
                                checked={form.is_p2p ?? false}
                                onChange={(e) => setForm({ ...form, is_p2p: e.target.checked })}
                                className="w-4 h-4 text-primary border-border rounded"
                            />
                            P2P
                        </label>
                        <label className="flex items-center gap-2 text-sm text-foreground">
                            <input
                                type="checkbox"
                                checked={form.is_active ?? true}
                                onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                                className="w-4 h-4 text-primary border-border rounded"
                            />
                            Активен
                        </label>
                    </div>
                </div>
                <div className="flex justify-end gap-2 px-4 py-3 border-t border-border bg-surface-2">
                    <button
                        onClick={onClose}
                        className="px-4 py-2 rounded-md border border-border text-foreground hover:bg-surface"
                    >
                        Отмена
                    </button>
                    <button
                        onClick={() => onSubmit(form)}
                        disabled={!form.operator_name.trim() || !form.application_name.trim() || isSubmitting}
                        className="px-4 py-2 rounded-md bg-primary text-foreground-inverse hover:bg-primary-hover disabled:opacity-50"
                    >
                        {isSubmitting ? 'Сохранение...' : 'Добавить'}
                    </button>
                </div>
            </div>
        </div>
    );
}
