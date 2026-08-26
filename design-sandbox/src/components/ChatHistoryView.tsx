import React, { useCallback, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Search, ChevronLeft, ChevronRight, Loader2, FileText, Calendar, Zap, CheckCircle, AlertTriangle } from 'lucide-react';
import {
    telegramClientApi,
    type TelegramChatMessage,
    type TelegramMessagesResponse,
} from '../services/api';
import { MessageItem } from './MessageItem';

interface ChatHistoryViewProps {
    chatId: number;
    onProcessReceipt?: (messageId: number) => void;
}

const PAGE_SIZE = 100;

export const ChatHistoryView: React.FC<ChatHistoryViewProps> = ({ chatId, onProcessReceipt }) => {
    const [page, setPage] = useState(0);
    const [search, setSearch] = useState('');
    const [searchInput, setSearchInput] = useState('');
    const [dateFrom, setDateFrom] = useState('');
    const [dateTo, setDateTo] = useState('');
    const containerRef = useRef<HTMLDivElement>(null);
    const queryClient = useQueryClient();

    const offset = page * PAGE_SIZE;

    const historyQuery = useQuery<TelegramMessagesResponse>({
        queryKey: ['history-messages', chatId, offset, search, dateFrom, dateTo],
        queryFn: () =>
            telegramClientApi.getHistoryMessages(chatId, {
                limit: PAGE_SIZE,
                offset,
                search: search || undefined,
                date_from: dateFrom || undefined,
                date_to: dateTo || undefined,
            }),
        enabled: chatId > 0,
        placeholderData: (previousData) => previousData,
    });

    const receiptStatsQuery = useQuery({
        queryKey: ['history-receipt-status', chatId],
        queryFn: () => telegramClientApi.getHistoryReceiptStatus(chatId),
        enabled: chatId > 0,
        refetchInterval: 15000,
    });

    const processAllMutation = useMutation({
        mutationFn: () => telegramClientApi.processHistoryReceipts(chatId, { max_messages: 1000 }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['history-receipt-status', chatId] });
        },
    });

    const total = historyQuery.data?.total ?? 0;
    const messages = historyQuery.data?.items ?? [];
    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

    const stats = receiptStatsQuery.data;
    const hasStats = stats && stats.total_messages > 0;

    const handleSearch = useCallback((e: React.FormEvent) => {
        e.preventDefault();
        setSearch(searchInput.trim());
        setPage(0);
    }, [searchInput]);

    const handleClearFilters = useCallback(() => {
        setSearch('');
        setSearchInput('');
        setDateFrom('');
        setDateTo('');
        setPage(0);
    }, []);

    const goToPage = useCallback((p: number) => {
        setPage(Math.max(0, Math.min(p, totalPages - 1)));
        containerRef.current?.scrollTo({ top: 0 });
    }, [totalPages]);

    const hasFilters = search || dateFrom || dateTo;

    return (
        <div className="flex flex-col h-full min-h-0">
            {/* Filters bar */}
            <div className="flex-shrink-0 p-3 border-b border-border space-y-2 bg-surface">
                <form onSubmit={handleSearch} className="flex items-center gap-2">
                    <div className="relative flex-1">
                        <Search className="w-3.5 h-3.5 text-foreground-muted absolute left-2.5 top-2.5" />
                        <input
                            type="text"
                            value={searchInput}
                            onChange={(e) => setSearchInput(e.target.value)}
                            placeholder="Поиск по тексту..."
                            className="w-full pl-8 pr-3 py-2 text-xs border border-border rounded-md bg-input-bg text-input-text"
                        />
                    </div>
                    <button
                        type="submit"
                        className="px-3 py-2 text-xs rounded-md border border-primary/30 text-primary hover:bg-primary/5"
                    >
                        Найти
                    </button>
                </form>

                <div className="flex items-center gap-2 flex-wrap">
                    <div className="flex items-center gap-1 text-xs text-foreground-secondary">
                        <Calendar className="w-3 h-3" />
                        С:
                    </div>
                    <input
                        type="date"
                        value={dateFrom}
                        onChange={(e) => {
                            setDateFrom(e.target.value);
                            setPage(0);
                        }}
                        className="px-2 py-1 text-xs border border-border rounded-md bg-input-bg text-input-text"
                    />
                    <div className="text-xs text-foreground-secondary">По:</div>
                    <input
                        type="date"
                        value={dateTo}
                        onChange={(e) => {
                            setDateTo(e.target.value);
                            setPage(0);
                        }}
                        className="px-2 py-1 text-xs border border-border rounded-md bg-input-bg text-input-text"
                    />
                    {hasFilters && (
                        <button
                            type="button"
                            onClick={handleClearFilters}
                            className="px-2 py-1 text-xs rounded-md border border-border text-foreground-secondary hover:bg-surface-2"
                        >
                            Сбросить
                        </button>
                    )}
                    <div className="ml-auto text-xs text-foreground-muted">
                        Всего: {total.toLocaleString()}
                    </div>
                </div>

                {/* Receipt processing bar */}
                {hasStats && (
                    <div className="flex items-center gap-2 pt-1">
                        <div className="flex items-center gap-1.5 text-xs text-foreground-secondary">
                            <FileText className="w-3 h-3" />
                            <span>
                                Чеков: {stats.total_transactions_from_chat}
                                {stats.processed_messages > 0 && (
                                    <span className="text-foreground-muted"> / обработано: {stats.processed_messages}</span>
                                )}
                            </span>
                        </div>
                        <button
                            type="button"
                            onClick={() => processAllMutation.mutate()}
                            disabled={processAllMutation.isPending}
                            className="ml-auto inline-flex items-center gap-1 px-2 py-1 text-xs rounded-md bg-primary/10 text-primary hover:bg-primary/20 disabled:opacity-50"
                        >
                            {processAllMutation.isPending ? (
                                <Loader2 className="w-3 h-3 animate-spin" />
                            ) : (
                                <Zap className="w-3 h-3" />
                            )}
                            Обработать чеки
                        </button>
                    </div>
                )}

                {/* Processing result notification */}
                {processAllMutation.isSuccess && processAllMutation.data && (
                    <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-success/10 text-success text-xs">
                        <CheckCircle className="w-3 h-3 flex-shrink-0" />
                        <span>
                            Отсканировано: {processAllMutation.data.total_scanned},
                            в очередь: {processAllMutation.data.queued},
                            пропущено: {processAllMutation.data.skipped}
                            {processAllMutation.data.errors > 0 && (
                                <span className="text-danger">, ошибок: {processAllMutation.data.errors}</span>
                            )}
                        </span>
                    </div>
                )}
                {processAllMutation.isError && (
                    <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-danger/10 text-danger text-xs">
                        <AlertTriangle className="w-3 h-3 flex-shrink-0" />
                        <span>Ошибка обработки чеков</span>
                    </div>
                )}
            </div>

            {/* Messages list */}
            <div ref={containerRef} className="flex-1 overflow-y-auto min-h-0 p-3">
                {historyQuery.isLoading && (
                    <div className="flex items-center justify-center py-10 gap-2 text-foreground-secondary">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span className="text-sm">Загрузка истории...</span>
                    </div>
                )}

                {!historyQuery.isLoading && messages.length === 0 && (
                    <div className="flex flex-col items-center justify-center py-10 text-foreground-secondary gap-2">
                        <FileText className="w-6 h-6" />
                        <span className="text-sm">
                            {hasFilters ? 'Ничего не найдено' : 'Нет сообщений в истории'}
                        </span>
                        {!hasFilters && (
                            <span className="text-xs">Запустите синхронизацию для загрузки истории чата</span>
                        )}
                    </div>
                )}

                <div className="space-y-1">
                    {messages.map((msg: TelegramChatMessage) => (
                        <MessageItem
                            key={msg.id}
                            message={msg}
                            onProcess={
                                onProcessReceipt
                                    ? () => onProcessReceipt(msg.id!)
                                    : undefined
                            }
                        />
                    ))}
                </div>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
                <div className="flex-shrink-0 flex items-center justify-between px-3 py-2 border-t border-border bg-surface text-xs">
                    <button
                        type="button"
                        onClick={() => goToPage(page - 1)}
                        disabled={page === 0}
                        className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-border hover:bg-surface-2 disabled:opacity-40"
                    >
                        <ChevronLeft className="w-3 h-3" />
                        Назад
                    </button>
                    <div className="flex items-center gap-1 text-foreground-secondary">
                        <span>Стр. {page + 1} / {totalPages}</span>
                        <span className="text-foreground-muted">
                            ({offset + 1}–{Math.min(offset + PAGE_SIZE, total)} из {total.toLocaleString()})
                        </span>
                    </div>
                    <button
                        type="button"
                        onClick={() => goToPage(page + 1)}
                        disabled={page >= totalPages - 1}
                        className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-border hover:bg-surface-2 disabled:opacity-40"
                    >
                        Вперёд
                        <ChevronRight className="w-3 h-3" />
                    </button>
                </div>
            )}
        </div>
    );
};
