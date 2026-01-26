import React, { memo } from 'react';
import {
    Loader2,
    AlertCircle,
    CheckCircle2,
    XCircle,
} from 'lucide-react';
import { TelegramChatMessage, TelegramProcessResult, API_BASE_URL } from '../services/api';

interface MessageItemProps {
    message: TelegramChatMessage;
    isSelected: boolean;
    status?: TelegramProcessResult;
    processingId: number | null;
    currentChatId: number | null;
    onToggleSelect: (id: number) => void;
    onProcess: (chatId: number, messageId: number) => void;
    onReprocess: (chatId: number, messageId: number) => void;
    onPreview: (url: string) => void;
    formatDateTime: (date?: string | null) => string;
}

export const MessageItem = memo<MessageItemProps>(({
    message,
    isSelected,
    status,
    processingId,
    currentChatId,
    onToggleSelect,
    onProcess,
    onReprocess,
    onPreview,
    formatDateTime,
}) => {
    const msgId = message.id as number;
    const doc = message.document;
    const isPdf = doc?.mime_type?.toLowerCase().includes('pdf');
    const downloadUrl = doc?.download_url
        ? `${API_BASE_URL}${doc.download_url}`
        : doc?.file_id
            ? `${API_BASE_URL}/api/tg/files/${doc.file_id}`
            : null;
    const sizeLabel = (() => {
        if (doc?.size === undefined) return '';
        const kb = doc.size / 1024;
        return kb > 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${kb.toFixed(0)} KB`;
    })();

    const handleMessageClick = (e: React.MouseEvent) => {
        // Don't toggle if clicking buttons or links
        const target = e.target as HTMLElement;
        if (target.closest('button') || target.closest('a') || target.closest('input')) {
            return;
        }
        onToggleSelect(msgId);
    };

    const statusText = status?.status || 'not_processed';
    const err = status?.error;

    return (
        <div
            className={`flex items-start gap-3 p-2 rounded-lg transition-colors cursor-pointer ${isSelected ? 'bg-primary/10 ring-2 ring-primary/30' : 'hover:bg-surface-2/50'
                }`}
            onClick={handleMessageClick}
        >
            <input
                type="checkbox"
                className="mt-2 w-6 h-6 text-primary border-border rounded focus:ring-primary cursor-pointer flex-shrink-0"
                checked={isSelected}
                onChange={() => onToggleSelect(msgId)}
            />
            <div className={`flex-1 flex ${message.is_outgoing ? 'justify-end' : 'justify-start'}`}>
                <div
                    className={`max-w-[75%] rounded-lg px-4 py-3 border shadow-sm ${message.is_outgoing
                            ? 'bg-primary text-foreground-inverse border-primary/40'
                            : 'bg-surface-2 text-foreground border-border'
                        }`}
                >
                    <div className="text-sm whitespace-pre-wrap">
                        {message.text || 'Сообщение без текста'}
                    </div>
                    {doc && (
                        <div className="mt-2 rounded-md border border-border/60 bg-surface px-3 py-2 text-xs">
                            <div className="font-semibold">Документ</div>
                            <div className="flex flex-wrap gap-2 items-center mt-1">
                                <span className="truncate max-w-[200px]">{doc.file_name || 'файл'}</span>
                                {sizeLabel && <span className="text-foreground-muted">{sizeLabel}</span>}
                                {downloadUrl && (
                                    <button
                                        type="button"
                                        className="underline text-primary hover:text-primary-hover"
                                        onClick={() => window.open(downloadUrl, '_blank')}
                                    >
                                        {isPdf ? 'Открыть PDF' : 'Открыть'}
                                    </button>
                                )}
                                {downloadUrl && isPdf && (
                                    <button
                                        type="button"
                                        className="underline text-primary hover:text-primary-hover"
                                        onClick={() => onPreview(downloadUrl)}
                                    >
                                        Просмотр
                                    </button>
                                )}
                            </div>
                        </div>
                    )}
                    <div className="flex items-center gap-2 text-xs mt-2">
                        {(() => {
                            if (statusText === 'done') {
                                return (
                                    <span className="flex items-center gap-1 text-success">
                                        <CheckCircle2 className="w-4 h-4" /> Обработан
                                        {status?.check_id ? ` #${status.check_id}` : ''}
                                    </span>
                                );
                            }
                            if (statusText === 'queued') {
                                return (
                                    <span className="flex items-center gap-1 text-warning">
                                        <Loader2 className="w-4 h-4 animate-spin" /> В очереди
                                    </span>
                                );
                            }
                            if (statusText === 'processing') {
                                return (
                                    <span className="flex items-center gap-1 text-info">
                                        <Loader2 className="w-4 h-4 animate-spin" /> Обработка
                                    </span>
                                );
                            }
                            if (statusText === 'failed') {
                                return (
                                    <span className="flex items-center gap-1 text-danger" title={err || 'Ошибка'}>
                                        <XCircle className="w-4 h-4" /> Ошибка {err ? `: ${err}` : ''}
                                    </span>
                                );
                            }
                            return (
                                <span className="flex items-center gap-1 text-foreground-secondary">
                                    <AlertCircle className="w-4 h-4" /> Не обработан
                                </span>
                            );
                        })()}
                    </div>
                    <div className="text-[11px] mt-1 text-right opacity-80">
                        {formatDateTime(message.date)}
                    </div>
                    <div className="flex justify-end mt-3 gap-2">
                        {status?.status === 'done' ? (
                            <>
                                <button
                                    type="button"
                                    className="text-sm px-4 py-2 min-h-[40px] rounded-md border border-success text-success bg-success/10 cursor-default font-medium"
                                    disabled
                                >
                                    ✓ Обработано
                                </button>
                                <button
                                    type="button"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        if (!currentChatId) return;
                                        onReprocess(currentChatId, msgId);
                                    }}
                                    className="text-sm px-4 py-2 min-h-[40px] rounded-md border border-border text-foreground-secondary hover:bg-surface-2 disabled:opacity-50 font-medium transition-colors"
                                    disabled={processingId === msgId}
                                >
                                    {processingId === msgId ? (
                                        <Loader2 className="w-4 h-4 animate-spin" />
                                    ) : (
                                        '↻ Повторить'
                                    )}
                                </button>
                            </>
                        ) : (
                            <button
                                type="button"
                                onClick={(e) => {
                                    e.stopPropagation();
                                    if (!currentChatId) return;
                                    onProcess(currentChatId, msgId);
                                }}
                                className={`text-sm px-4 py-2 min-h-[40px] rounded-md border font-medium ${message.is_outgoing
                                        ? 'border-primary/60 text-foreground-inverse/90 hover:bg-primary/90'
                                        : 'border-primary text-primary hover:bg-primary/10'
                                    } transition-colors`}
                                disabled={
                                    processingId === msgId ||
                                    ['queued', 'processing'].includes(status?.status || '')
                                }
                            >
                                {processingId === msgId ? (
                                    <span className="flex items-center gap-2">
                                        <Loader2 className="w-4 h-4 animate-spin" /> Обработка...
                                    </span>
                                ) : (
                                    '▶ Обработать'
                                )}
                            </button>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
});

MessageItem.displayName = 'MessageItem';
