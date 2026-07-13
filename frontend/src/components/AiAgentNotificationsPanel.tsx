import React from 'react';
import { motion } from 'motion/react';
import { ArrowLeft, CheckCheck, FileText } from 'lucide-react';
import type { AgentNotification, AgentReport } from '../services/api';
import { formatNotificationBody, formatNotificationTitle } from '../utils/aiAgentDisplay';

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

function stripHtml(raw: string): string {
    return raw
        .replace(/<br\s*\/?>/gi, '\n')
        .replace(/<\/(p|div|li)>/gi, '\n')
        .replace(/<[^>]+>/g, '')
        .replace(/&nbsp;/g, ' ')
        .replace(/&amp;/g, '&')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
}

function notificationTitle(n: AgentNotification): string {
    if (n.type === 'routine_report' && typeof n.payload?.name === 'string' && n.payload.name.trim()) {
        return n.payload.name.trim();
    }
    return formatNotificationTitle(n);
}

function notificationBody(n: AgentNotification): string {
    if (n.type === 'routine_report' && typeof n.payload?.text === 'string' && n.payload.text.trim()) {
        return stripHtml(n.payload.text);
    }
    return formatNotificationBody(n);
}

function formatWhen(raw?: string | null): string {
    if (!raw) return '';
    const d = new Date(raw);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' });
}

interface Props {
    notifications: AgentNotification[];
    reports: AgentReport[];
    onClose: () => void;
    onRead: (id: string) => void;
    onReadAll: () => void;
    onClaim: (itemId: string) => void;
    onRelease: (itemId: string) => void;
    onOpenReport: (reportId: string) => void;
}

export const AiAgentNotificationsPanel: React.FC<Props> = ({
    notifications,
    reports,
    onClose,
    onRead,
    onReadAll,
    onClaim,
    onRelease,
    onOpenReport,
}) => {
    const hasUnread = notifications.some((n) => !n.is_read);
    const isEmpty = notifications.length === 0 && reports.length === 0;

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
                    <div className="agent-eyebrow">Уведомления</div>
                </div>
                <button
                    type="button"
                    className="agent-icon-btn"
                    onClick={onReadAll}
                    disabled={!hasUnread}
                    aria-label="Прочитать все"
                    title="Прочитать все"
                >
                    <CheckCheck size={16} />
                </button>
            </div>

            <div className="agent-routines-list">
                {isEmpty ? (
                    <div className="agent-routines-empty">Новых уведомлений пока нет.</div>
                ) : (
                    <>
                        {notifications.map((n) => (
                            <div key={n.id} className={`agent-notif-row${!n.is_read ? ' is-unread' : ''}`}>
                                <div className="agent-notif-main">
                                    <div className="agent-notif-title">
                                        {!n.is_read ? <span className="agent-notif-dot" aria-hidden /> : null}
                                        {notificationTitle(n)}
                                    </div>
                                    <div className="agent-notif-body">{notificationBody(n)}</div>
                                    <div className="agent-notif-meta">
                                        <span>{formatWhen(n.created_at)}</span>
                                        {n.report_id ? (
                                            <button
                                                type="button"
                                                className="agent-notif-link"
                                                onClick={() => onOpenReport(n.report_id!)}
                                            >
                                                <FileText size={11} />
                                                Открыть отчёт
                                            </button>
                                        ) : null}
                                    </div>
                                </div>
                                {!n.is_read ? (
                                    <button
                                        type="button"
                                        className="agent-btn agent-notif-read-btn"
                                        onClick={() => onRead(n.id)}
                                    >
                                        Прочитано
                                    </button>
                                ) : null}
                            </div>
                        ))}

                        {reports.map((report) => (
                            <div key={report.id} className="agent-notif-report">
                                <div className="agent-notif-report-head">
                                    <div className="agent-notif-main">
                                        <div className="agent-notif-title">{report.title}</div>
                                        <div className="agent-notif-meta">
                                            <span>{report.scope === 'team' ? 'Командный' : 'Личный'}</span>
                                        </div>
                                    </div>
                                    <button
                                        type="button"
                                        className="agent-btn agent-notif-read-btn"
                                        onClick={() => onOpenReport(report.id)}
                                    >
                                        Открыть
                                    </button>
                                </div>
                                {report.items?.length ? (
                                    <div className="agent-notif-items">
                                        {report.items.slice(0, 5).map((item) => (
                                            <div key={item.id} className="agent-notif-item">
                                                <div className="agent-notif-item-title">{item.title}</div>
                                                {item.description ? (
                                                    <div className="agent-notif-item-desc">{item.description}</div>
                                                ) : null}
                                                <div className="agent-notif-item-actions">
                                                    <button type="button" className="agent-btn" onClick={() => onClaim(item.id)}>
                                                        Взять в работу
                                                    </button>
                                                    <button type="button" className="agent-btn" onClick={() => onRelease(item.id)}>
                                                        Освободить
                                                    </button>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                ) : null}
                            </div>
                        ))}
                    </>
                )}
            </div>
        </motion.div>
    );
};
