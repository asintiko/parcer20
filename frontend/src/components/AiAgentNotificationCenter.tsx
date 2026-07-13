import React from 'react';
import type { AgentNotification, AgentReport } from '../services/api';
import { formatNotificationBody, formatNotificationTitle, humanizeSummaryKey, prettyJson } from '../utils/aiAgentDisplay';

interface AiAgentNotificationCenterProps {
    notifications: AgentNotification[];
    reports: AgentReport[];
    onRead: (notificationId: string) => void;
    onReadAll: () => void;
    onClaim: (itemId: string) => void;
    onRelease: (itemId: string) => void;
    onOpenReport: (reportId: string) => void;
}

export const AiAgentNotificationCenter: React.FC<AiAgentNotificationCenterProps> = ({
    notifications,
    reports,
    onRead,
    onReadAll,
    onClaim,
    onRelease,
    onOpenReport,
}) => {
    return (
        <div className="flex h-full flex-col">
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
                <div className="text-sm font-semibold text-foreground">Уведомления</div>
                <button type="button" onClick={onReadAll} className="text-xs font-medium text-primary hover:underline">
                    Прочитать все
                </button>
            </div>
            <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
                {notifications.map((notification) => (
                    <div key={notification.id} className="rounded-lg border border-border bg-surface px-3 py-3">
                        <div className="flex items-start justify-between gap-3">
                            <div>
                                <div className="text-sm font-medium text-foreground">{formatNotificationTitle(notification)}</div>
                                <div className="mt-1 text-xs text-foreground-secondary whitespace-pre-wrap">
                                    {formatNotificationBody(notification)}
                                </div>
                            </div>
                            {!notification.is_read ? (
                                <button
                                    type="button"
                                    onClick={() => onRead(notification.id)}
                                    className="rounded-md border border-border px-2 py-1 text-xs hover:bg-surface-2"
                                >
                                    Прочитано
                                </button>
                            ) : null}
                        </div>
                        {notification.report_id ? (
                            <button
                                type="button"
                                onClick={() => onOpenReport(notification.report_id!)}
                                className="mt-2 text-xs font-medium text-primary hover:underline"
                            >
                                Открыть отчет
                            </button>
                        ) : null}
                        {notification.payload ? (
                            <details className="mt-3 rounded-md border border-border/60 bg-surface-2 px-2.5 py-2 text-xs text-foreground-secondary">
                                <summary className="cursor-pointer select-none font-medium text-foreground">Показать детали</summary>
                                <pre className="mt-2 whitespace-pre-wrap break-words">{prettyJson(notification.payload)}</pre>
                            </details>
                        ) : null}
                    </div>
                ))}
                {reports.map((report) => (
                    <div key={report.id} className="rounded-lg border border-border bg-surface-2 px-3 py-3">
                        <div className="flex items-center justify-between gap-3">
                            <div>
                                <div className="text-sm font-medium text-foreground">{report.title}</div>
                                <div className="text-xs text-foreground-secondary">{report.scope === 'team' ? 'Командный' : 'Личный'}</div>
                            </div>
                            <button
                                type="button"
                                onClick={() => onOpenReport(report.id)}
                                className="rounded-md border border-border px-2 py-1 text-xs hover:bg-surface"
                            >
                                Открыть
                            </button>
                        </div>
                        {report.items?.length ? (
                            <div className="mt-3 space-y-2">
                                {report.items.slice(0, 5).map((item) => (
                                    <div key={item.id} className="rounded-md border border-border/60 bg-surface px-2.5 py-2">
                                        <div className="text-sm font-medium text-foreground">{item.title}</div>
                                        {item.description ? (
                                            <div className="mt-1 text-xs text-foreground-secondary whitespace-pre-wrap">{item.description}</div>
                                        ) : null}
                                        <div className="mt-2 flex gap-2">
                                            <button
                                                type="button"
                                                onClick={() => onClaim(item.id)}
                                                className="rounded-md border border-border px-2 py-1 text-xs hover:bg-surface-2"
                                            >
                                                Взять в работу
                                            </button>
                                            <button
                                                type="button"
                                                onClick={() => onRelease(item.id)}
                                                className="rounded-md border border-border px-2 py-1 text-xs hover:bg-surface-2"
                                            >
                                                Освободить
                                            </button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        ) : null}
                        {report.summary && Object.keys(report.summary).length ? (
                            <details className="mt-3 rounded-md border border-border/60 bg-surface px-2.5 py-2 text-xs text-foreground-secondary">
                                <summary className="cursor-pointer select-none font-medium text-foreground">Показать детали</summary>
                                <div className="mt-2 space-y-1">
                                    {Object.entries(report.summary).slice(0, 8).map(([key, value]) => (
                                        <div key={key} className="flex items-center justify-between gap-3">
                                            <span>{humanizeSummaryKey(key)}</span>
                                            <span className="font-medium text-foreground">{String(value)}</span>
                                        </div>
                                    ))}
                                </div>
                            </details>
                        ) : null}
                    </div>
                ))}
                {!notifications.length && !reports.length ? (
                    <div className="rounded-lg border border-dashed border-border px-4 py-5 text-sm text-foreground-secondary">
                        Новых уведомлений пока нет.
                    </div>
                ) : null}
            </div>
        </div>
    );
};
