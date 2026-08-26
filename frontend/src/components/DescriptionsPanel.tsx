import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AnimatePresence, motion } from 'motion/react';
import { Search, Plus, Loader2, Trash2, X, Check, FileX } from 'lucide-react';
import {
    descriptionsApi,
    transactionsApi,
    type DescriptionReference,
    type DescriptionCreate,
} from '../services/api';
import { useToast } from './Toast';
import { Sheet } from './motion/Sheet';
import { ConfirmDialog } from './motion/ConfirmDialog';
import { OverflowTooltip } from './OverflowTooltip';
import { MultiOperatorSelect } from './MultiOperatorSelect';

const PAGE_SIZE = 100;

export function DescriptionsPanel() {
    const queryClient = useQueryClient();
    const { showToast } = useToast();

    const [page, setPage] = useState(1);
    const [search, setSearch] = useState('');
    const [debouncedSearch, setDebouncedSearch] = useState('');
    const [isAddOpen, setIsAddOpen] = useState(false);
    const [confirmDelete, setConfirmDelete] = useState<DescriptionReference | null>(null);

    const searchRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        const t = setTimeout(() => setDebouncedSearch(search.trim()), 240);
        return () => clearTimeout(t);
    }, [search]);

    const listQuery = useQuery({
        queryKey: ['descriptions', page, PAGE_SIZE, debouncedSearch],
        queryFn: () =>
            descriptionsApi.list({
                page,
                page_size: PAGE_SIZE,
                search: debouncedSearch || undefined,
            }),
    });

    const initQuery = useQuery({
        queryKey: ['transactions-init'],
        queryFn: transactionsApi.getInit,
        staleTime: 5 * 60 * 1000,
    });

    const operatorOptions = initQuery.data?.operators ?? [];

    const invalidate = () => queryClient.invalidateQueries({ queryKey: ['descriptions'] });

    const createMutation = useMutation({
        mutationFn: (payload: DescriptionCreate) => descriptionsApi.create(payload),
        onSuccess: () => {
            showToast('success', 'Описание добавлено');
            invalidate();
            setIsAddOpen(false);
        },
        onError: () => showToast('error', 'Не удалось добавить'),
    });

    const updateMutation = useMutation({
        mutationFn: ({ id, text }: { id: number; text: string }) =>
            descriptionsApi.update(id, text),
        onSuccess: () => invalidate(),
        onError: () => showToast('error', 'Не удалось сохранить'),
    });

    const deleteMutation = useMutation({
        mutationFn: (id: number) => descriptionsApi.remove(id),
        onSuccess: () => {
            showToast('success', 'Описание удалено');
            invalidate();
        },
        onError: () => showToast('error', 'Не удалось удалить'),
    });

    const linkMutation = useMutation({
        mutationFn: ({ id, raws }: { id: number; raws: string[] }) =>
            descriptionsApi.linkOperators(id, raws),
        onSuccess: () => {
            showToast('success', 'Оператор привязан');
            invalidate();
        },
        onError: () => showToast('error', 'Не удалось привязать'),
    });

    const unlinkMutation = useMutation({
        mutationFn: ({ id, raws }: { id: number; raws: string[] }) =>
            descriptionsApi.unlinkOperators(id, raws),
        onSuccess: () => invalidate(),
        onError: () => showToast('error', 'Не удалось отвязать'),
    });

    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            const mod = e.metaKey || e.ctrlKey;
            if (mod && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                searchRef.current?.focus();
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, []);

    const items = (listQuery.data?.items as DescriptionReference[] | undefined) || [];
    const total = listQuery.data?.total || 0;
    const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
    const pageStart = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
    const pageEnd = Math.min(page * PAGE_SIZE, total);

    return (
        <>
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
                        placeholder="Поиск по описанию или оператору"
                        aria-label="Поиск по описаниям"
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

                <span className="rf-toolbar-spacer" />

                <button
                    type="button"
                    className="rf-btn rf-btn-primary"
                    onClick={() => setIsAddOpen(true)}
                >
                    <Plus size={14} />
                    Добавить описание
                </button>
            </div>

            <div className="rf-table-wrap">
                <div className="rf-table-scroll">
                    <table className="rf-table density-standard">
                        <thead>
                            <tr>
                                <th>Описание</th>
                                <th>Операторы</th>
                                <th className="is-center is-narrow">Источник</th>
                                <th className="is-center is-narrow" />
                            </tr>
                        </thead>
                        <tbody>
                            {listQuery.isError ? (
                                <tr>
                                    <td colSpan={4}>
                                        <div className="rf-empty">
                                            <div className="rf-empty-icon">
                                                <FileX size={22} />
                                            </div>
                                            <div className="rf-empty-title">Ошибка загрузки</div>
                                            <div className="rf-empty-sub">
                                                Не удалось получить список описаний. Повторите попытку позже.
                                            </div>
                                        </div>
                                    </td>
                                </tr>
                            ) : listQuery.isLoading ? (
                                <tr>
                                    <td colSpan={4}>
                                        <div className="rf-empty">
                                            <Loader2 size={20} className="tg-msg-process-spin" />
                                            <div>Загружаем описания…</div>
                                        </div>
                                    </td>
                                </tr>
                            ) : items.length === 0 ? (
                                <tr>
                                    <td colSpan={4}>
                                        <div className="rf-empty">
                                            <div className="rf-empty-icon">
                                                <FileX size={22} />
                                            </div>
                                            <div className="rf-empty-title">Описаний нет</div>
                                            <div className="rf-empty-sub">
                                                {debouncedSearch
                                                    ? 'Ничего не найдено. Измените запрос.'
                                                    : 'Добавьте первое описание через кнопку «Добавить описание».'}
                                            </div>
                                        </div>
                                    </td>
                                </tr>
                            ) : (
                                <AnimatePresence initial={false}>
                                    {items.map((item, idx) => (
                                        <motion.tr
                                            key={item.id}
                                            layout="position"
                                            initial={{ opacity: 0, y: 4 }}
                                            animate={{
                                                opacity: 1,
                                                y: 0,
                                                transition: {
                                                    duration: 0.18,
                                                    ease: [0.16, 1, 0.3, 1],
                                                    delay: idx < 12 ? idx * 0.012 : 0,
                                                },
                                            }}
                                            exit={{ opacity: 0, transition: { duration: 0.12 } }}
                                        >
                                            <td>
                                                <EditableTextCell
                                                    value={item.text}
                                                    placeholder="—"
                                                    onCommit={(val) => {
                                                        if (val && val !== item.text) {
                                                            updateMutation.mutate({ id: item.id, text: val });
                                                        }
                                                    }}
                                                />
                                            </td>
                                            <td>
                                                <OperatorChips
                                                    item={item}
                                                    options={operatorOptions}
                                                    onUnlink={(raw) =>
                                                        unlinkMutation.mutate({ id: item.id, raws: [raw] })
                                                    }
                                                    onLink={(raws) =>
                                                        linkMutation.mutate({ id: item.id, raws })
                                                    }
                                                />
                                            </td>
                                            <td className="is-center is-narrow">
                                                <div className="rf-source-badges">
                                                    {(item.sources.length ? item.sources : ['—']).map((s) => (
                                                        <span
                                                            key={s}
                                                            className={`rf-source-badge${s === 'agent' ? ' is-agent' : ''}`}
                                                        >
                                                            {s}
                                                        </span>
                                                    ))}
                                                </div>
                                            </td>
                                            <td className="is-center is-narrow">
                                                <div className="rf-row-actions">
                                                    <button
                                                        type="button"
                                                        onClick={() => setConfirmDelete(item)}
                                                        className="rf-row-action is-danger"
                                                        title="Удалить"
                                                        aria-label={`Удалить описание «${item.text}»`}
                                                    >
                                                        <Trash2 size={14} />
                                                    </button>
                                                </div>
                                            </td>
                                        </motion.tr>
                                    ))}
                                </AnimatePresence>
                            )}
                        </tbody>
                    </table>
                </div>

                <div className="rf-footer">
                    <div className="rf-footer-meta">
                        <strong>{pageStart}</strong>–<strong>{pageEnd}</strong> из <strong>{total}</strong>
                    </div>
                    <div className="rf-pagination">
                        <button
                            type="button"
                            className="rf-page-btn"
                            onClick={() => setPage((p) => Math.max(1, p - 1))}
                            disabled={page <= 1}
                            aria-label="Предыдущая страница"
                        >
                            ‹
                        </button>
                        <span className="rf-pagination-page">
                            {Math.min(page, pageCount)} / {pageCount}
                        </span>
                        <button
                            type="button"
                            className="rf-page-btn"
                            onClick={() => setPage((p) => p + 1)}
                            disabled={page * PAGE_SIZE >= total}
                            aria-label="Следующая страница"
                        >
                            ›
                        </button>
                    </div>
                </div>
            </div>

            <Sheet
                open={isAddOpen}
                onClose={() => setIsAddOpen(false)}
                title="Новое описание"
                subtitle="описание → operator"
                ariaLabel="Добавить описание"
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
                <DescriptionForm
                    busy={createMutation.isPending}
                    operatorOptions={operatorOptions}
                    onSubmit={(payload) => createMutation.mutate(payload)}
                />
            </Sheet>

            <ConfirmDialog
                open={confirmDelete !== null}
                title="Удалить описание?"
                description={
                    confirmDelete
                        ? `Будет удалено: «${confirmDelete.text}». Привязки операторов также снимутся.`
                        : 'Это действие необратимо.'
                }
                confirmLabel="Удалить"
                tone="danger"
                onConfirm={async () => {
                    if (confirmDelete) await deleteMutation.mutateAsync(confirmDelete.id);
                    setConfirmDelete(null);
                }}
                onClose={() => setConfirmDelete(null)}
            />
        </>
    );
}

function OperatorChips({
    item,
    options,
    onUnlink,
    onLink,
}: {
    item: DescriptionReference;
    options: string[];
    onUnlink: (raw: string) => void;
    onLink: (raws: string[]) => void;
}) {
    const [adding, setAdding] = useState(false);
    const [draft, setDraft] = useState<string[]>([]);

    const linkedSet = useMemo(
        () => new Set(item.operator_keys.map((k) => k.toLowerCase())),
        [item.operator_keys],
    );

    const availableOptions = useMemo(
        () => options.filter((o) => !linkedSet.has(o.toLowerCase())),
        [options, linkedSet],
    );

    const commit = () => {
        const raws = draft
            .map((s) => s.trim())
            .filter((s) => s && !linkedSet.has(s.toLowerCase()));
        if (raws.length) onLink(Array.from(new Set(raws)));
        setDraft([]);
        setAdding(false);
    };

    return (
        <div className="rf-desc-ops">
            {item.operator_keys.length === 0 ? (
                <span className="rf-desc-op-empty">нет привязок</span>
            ) : (
                item.operator_keys.map((key) => (
                    <span key={key} className="rf-desc-op">
                        <OverflowTooltip text={key} className="rf-desc-op-text">
                            {key}
                        </OverflowTooltip>
                        <button
                            type="button"
                            className="rf-desc-op-x"
                            onClick={() => onUnlink(key)}
                            aria-label={`Отвязать оператор ${key}`}
                            title="Отвязать"
                        >
                            <X size={11} />
                        </button>
                    </span>
                ))
            )}
            {adding ? (
                <span className="rf-desc-link-form">
                    <div className="rf-desc-link-select">
                        <MultiOperatorSelect
                            value={draft}
                            onChange={setDraft}
                            options={availableOptions}
                            placeholder="operator_raw"
                        />
                    </div>
                    <button
                        type="button"
                        className="rf-desc-op-x"
                        onClick={commit}
                        disabled={draft.length === 0}
                        aria-label="Подтвердить привязку"
                        title="Привязать"
                    >
                        <Check size={12} />
                    </button>
                    <button
                        type="button"
                        className="rf-desc-op-x"
                        onClick={() => {
                            setDraft([]);
                            setAdding(false);
                        }}
                        aria-label="Отменить привязку"
                        title="Отмена"
                    >
                        <X size={12} />
                    </button>
                </span>
            ) : (
                <button
                    type="button"
                    className="rf-desc-link"
                    onClick={() => setAdding(true)}
                    aria-label="Привязать оператора"
                >
                    <Plus size={11} />
                    оператор
                </button>
            )}
        </div>
    );
}

interface DescriptionFormProps {
    busy?: boolean;
    operatorOptions: string[];
    onSubmit: (data: DescriptionCreate) => void;
}

function DescriptionForm({ busy, operatorOptions, onSubmit }: DescriptionFormProps) {
    const [text, setText] = useState('');
    const [operators, setOperators] = useState<string[]>([]);
    const [error, setError] = useState<string | null>(null);

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        if (!text.trim()) {
            setError('Текст описания обязателен');
            return;
        }
        setError(null);
        const raws = Array.from(
            new Set(operators.map((s) => s.trim()).filter(Boolean)),
        );
        onSubmit({
            text: text.trim(),
            operator_raws: raws.length ? raws : undefined,
            source: 'manual',
        });
    };

    const listId = useMemo(() => `rf-desc-${Math.random().toString(36).slice(2, 8)}`, []);

    return (
        <form className="rf-form" onSubmit={handleSubmit}>
            <div className="rf-field">
                <label className="rf-field-label" htmlFor={`${listId}-text`}>
                    Описание
                </label>
                <input
                    id={`${listId}-text`}
                    className="rf-field-input"
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    placeholder="Например: Продукты · Korzinka"
                    autoFocus
                />
            </div>
            <div className="rf-field">
                <label className="rf-field-label" htmlFor={`${listId}-ops`}>
                    Операторы (необязательно)
                </label>
                <MultiOperatorSelect
                    value={operators}
                    onChange={setOperators}
                    options={operatorOptions}
                    placeholder="Выберите операторов…"
                />
            </div>
            {error ? <div className="rf-field-error">{error}</div> : null}
            <button
                type="submit"
                className="rf-btn rf-btn-primary"
                disabled={busy || !text.trim()}
                style={{ alignSelf: 'flex-start' }}
            >
                {busy ? 'Сохраняем…' : 'Добавить'}
            </button>
        </form>
    );
}

function EditableTextCell({
    value,
    placeholder,
    onCommit,
}: {
    value: string;
    placeholder?: string;
    onCommit: (v: string) => void;
}) {
    const [draft, setDraft] = useState(value);

    useEffect(() => {
        setDraft(value);
    }, [value]);

    const commit = () => {
        const trimmed = draft.trim();
        if (trimmed !== value.trim()) onCommit(trimmed);
    };

    return (
        <input
            className="rf-cell-input"
            value={draft}
            placeholder={placeholder}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    (e.currentTarget as HTMLInputElement).blur();
                }
                if (e.key === 'Escape') {
                    setDraft(value);
                    (e.currentTarget as HTMLInputElement).blur();
                }
            }}
        />
    );
}
