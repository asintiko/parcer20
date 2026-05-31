import React from 'react';
import { motion } from 'motion/react';
import type { AgentLocateResult, AgentMessage, AgentReport, AgentRun } from '../services/api';
import { AiAgentToolCard, type ToolCardSection } from './AiAgentToolCard';
import { AiAgentReportCard } from './AiAgentReportCard';
import { AiAgentConfirmationCard } from './AiAgentConfirmationCard';
import { formatNavigationLabel, humanizeSummaryKey, prettyJson } from '../utils/aiAgentDisplay';

const formatTime = (raw?: string | null) => {
    if (!raw) return '';
    const d = new Date(raw);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
};

const renderInline = (text: string) => {
    const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
    return parts.map((part, i) => {
        if (!part) return null;
        if (part.startsWith('`') && part.endsWith('`')) {
            return <code key={i}>{part.slice(1, -1)}</code>;
        }
        if (part.startsWith('**') && part.endsWith('**')) {
            return <strong key={i}>{part.slice(2, -2)}</strong>;
        }
        return <React.Fragment key={i}>{part}</React.Fragment>;
    });
};

const renderMarkdown = (text: string) => {
    const lines = text.split('\n');
    const blocks: React.ReactNode[] = [];
    let listBuffer: { items: string[]; type: 'ul' | 'ol' } | null = null;
    let codeBuffer: string[] | null = null;
    let codeKey = 0;

    const flushList = () => {
        if (!listBuffer) return;
        const Tag = listBuffer.type === 'ul' ? 'ul' : 'ol';
        blocks.push(
            <Tag key={`list-${blocks.length}`}>
                {listBuffer.items.map((item, i) => (
                    <li key={i}>{renderInline(item)}</li>
                ))}
            </Tag>,
        );
        listBuffer = null;
    };

    const flushCode = () => {
        if (!codeBuffer) return;
        blocks.push(<pre key={`code-${codeKey++}`}>{codeBuffer.join('\n')}</pre>);
        codeBuffer = null;
    };

    for (const raw of lines) {
        const line = raw.trimEnd();
        if (codeBuffer) {
            if (line.startsWith('```')) {
                flushCode();
            } else {
                codeBuffer.push(line);
            }
            continue;
        }
        if (line.startsWith('```')) {
            flushList();
            codeBuffer = [];
            continue;
        }
        const ulMatch = line.match(/^[-*•]\s+(.*)$/);
        const olMatch = line.match(/^\d+[.)]\s+(.*)$/);
        if (ulMatch) {
            if (listBuffer && listBuffer.type !== 'ul') flushList();
            if (!listBuffer) listBuffer = { items: [], type: 'ul' };
            listBuffer.items.push(ulMatch[1]);
            continue;
        }
        if (olMatch) {
            if (listBuffer && listBuffer.type !== 'ol') flushList();
            if (!listBuffer) listBuffer = { items: [], type: 'ol' };
            listBuffer.items.push(olMatch[1]);
            continue;
        }
        flushList();
        if (!line.trim()) continue;
        blocks.push(<p key={`p-${blocks.length}`}>{renderInline(line)}</p>);
    }
    flushCode();
    flushList();
    return blocks;
};

const formatValue = (value: unknown): string => {
    if (value == null) return '—';
    if (typeof value === 'number') return value.toLocaleString('ru-RU');
    if (typeof value === 'boolean') return value ? 'да' : 'нет';
    return String(value);
};

interface AiAgentMessageProps {
    message: AgentMessage;
    latestRun: AgentRun | null;
    onNavigate: (target: AgentLocateResult) => void;
    onOpenReport: (reportId: string) => void;
    onConfirmRun: (runId: string) => void;
    onRejectRun?: (runId: string) => void;
    confirmPending?: boolean;
    rejectPending?: boolean;
}

export const AiAgentMessage: React.FC<AiAgentMessageProps> = ({
    message,
    latestRun,
    onNavigate,
    onOpenReport,
    onConfirmRun,
    onRejectRun,
    confirmPending,
    rejectPending,
}) => {
    const isUser = message.role === 'user';
    const content = message.content || {};
    const cards = Array.isArray(content.cards) ? content.cards : [];
    const navigationTargets = Array.isArray(content.navigation_targets) ? content.navigation_targets : [];

    const buildAnalyticsSections = (card: any): { eyebrow?: string; sections: ToolCardSection[]; details?: unknown } => {
        const payload = card?.payload && typeof card.payload === 'object' ? card.payload : {};
        const totals = Array.isArray(payload.totals) ? payload.totals : [];
        const topApplications = Array.isArray(payload.top_applications) ? payload.top_applications : [];
        const topSources = Array.isArray(payload.top_sources) ? payload.top_sources : [];
        const sections: ToolCardSection[] = [];

        const overview: ToolCardSection = { rows: [] };
        if (payload.period_label) overview.rows.push({ label: 'Период', value: String(payload.period_label) });
        if (payload.total_operations != null)
            overview.rows.push({ label: 'Операций', value: formatValue(payload.total_operations) });
        if (overview.rows.length) sections.push(overview);

        if (totals.length) {
            sections.push({
                title: 'Объёмы по валютам',
                rows: totals.map((t: any) => ({
                    label: String(t.currency || 'UNKNOWN'),
                    value: formatValue(t.total),
                })),
            });
        }

        if (topApplications.length) {
            sections.push({
                title: 'Крупнейшие приложения',
                rows: topApplications.slice(0, 6).map((a: any) => ({
                    label: String(a.name || '—'),
                    value: formatValue(a.total),
                })),
            });
        }

        if (topSources.length) {
            sections.push({
                title: 'Крупнейшие источники',
                rows: topSources.slice(0, 6).map((s: any) => ({
                    label: String(s.title || s.chat_id || '—'),
                    value: formatValue(s.total),
                })),
            });
        }

        return { eyebrow: 'АНАЛИТИКА', sections, details: card?.details };
    };

    const buildAuditSections = (card: any): { eyebrow?: string; sections: ToolCardSection[]; details?: unknown } => {
        const payload = card?.payload && typeof card.payload === 'object' ? card.payload : {};
        const sections: ToolCardSection[] = [];

        const overview: ToolCardSection = { rows: [] };
        if (payload.period_label) overview.rows.push({ label: 'Период', value: String(payload.period_label) });
        if (payload.checked_chats != null)
            overview.rows.push({ label: 'Проверено чатов', value: formatValue(payload.checked_chats) });
        if (payload.total_issues != null)
            overview.rows.push({ label: 'Проблем', value: formatValue(payload.total_issues) });
        if (payload.estimated_candidates != null)
            overview.rows.push({ label: 'Кандидатов', value: formatValue(payload.estimated_candidates) });
        if (overview.rows.length) sections.push(overview);

        const categories = payload.categories && typeof payload.categories === 'object' ? payload.categories : null;
        if (categories) {
            const rows = Object.entries(categories).map(([key, value]) => ({
                label: humanizeSummaryKey(key),
                value: formatValue(value),
            }));
            if (rows.length) sections.push({ title: 'Категории', rows });
        }

        const byChat = Array.isArray(payload.by_chat) ? payload.by_chat.slice(0, 5) : [];
        if (byChat.length) {
            sections.push({
                title: 'По чатам',
                rows: byChat.map((c: any) => ({
                    label: String(c.title || c.chat_id || 'Источник'),
                    value: `${formatValue(c.total_candidates || 0)} канд.`,
                })),
            });
        }

        const issuesPreview = Array.isArray(payload.issues_preview) ? payload.issues_preview.slice(0, 4) : [];
        if (issuesPreview.length) {
            sections.push({
                title: 'Ключевые кейсы',
                rows: issuesPreview.map((it: any) => ({
                    label: String(it.title || humanizeSummaryKey(it.category || 'problem')),
                    value: String(it.summary || '').slice(0, 80) || '—',
                })),
            });
        }

        return { eyebrow: 'АУДИТ', sections, details: card?.details };
    };

    const buildGenericSections = (card: any): { eyebrow?: string; sections: ToolCardSection[]; details?: unknown } => {
        const payload = card?.payload;
        const sections: ToolCardSection[] = [];

        if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
            const entries = Object.entries(payload as Record<string, unknown>).filter(
                ([, value]) => value != null && value !== '',
            );
            if (entries.length) {
                sections.push({
                    rows: entries.slice(0, 8).map(([key, value]) => ({
                        label: humanizeSummaryKey(key),
                        value: formatValue(value),
                    })),
                });
            }
        }

        if (Array.isArray(payload)) {
            sections.push({
                rows: [{ label: 'Найдено записей', value: String(payload.length) }],
            });
        }

        return {
            eyebrow: String(card?.type || 'РЕЗУЛЬТАТ').toUpperCase(),
            sections,
            details: card?.details ?? card?.payload,
        };
    };

    return (
        <motion.div
            className={`agent-msg${isUser ? ' is-user' : ' is-agent'}`}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.32, ease: [0.2, 0, 0, 1] }}
        >
            <div className="agent-msg-head">
                <span className="agent-msg-role">{isUser ? 'Вы' : 'Агент'}</span>
                <span className="agent-msg-time">{formatTime(message.created_at)}</span>
            </div>

            {content.message ? (
                <div className="agent-msg-body">{renderMarkdown(String(content.message))}</div>
            ) : null}

            {cards.length ? (
                <div className="agent-msg-cards">
                    {cards.map((card: any, index: number) => {
                        const baseKey = `${message.id}-card-${index}`;
                        if (card?.type === 'report' && card?.report) {
                            return (
                                <AiAgentReportCard
                                    key={baseKey}
                                    report={card.report as AgentReport}
                                    onOpen={onOpenReport}
                                />
                            );
                        }
                        if (card?.type === 'report' && card?.payload?.id) {
                            return (
                                <AiAgentReportCard
                                    key={baseKey}
                                    report={card.payload as AgentReport}
                                    onOpen={onOpenReport}
                                />
                            );
                        }
                        if (card?.type === 'analytics') {
                            const built = buildAnalyticsSections(card);
                            return (
                                <AiAgentToolCard
                                    key={baseKey}
                                    eyebrow={built.eyebrow}
                                    title={String(card?.title || 'Итоги')}
                                    body={String(card?.body || '')}
                                    sections={built.sections}
                                    details={built.details}
                                />
                            );
                        }
                        if (card?.type === 'audit' || String(card?.title || '').toLowerCase().includes('аудит')) {
                            const built = buildAuditSections(card);
                            return (
                                <AiAgentToolCard
                                    key={baseKey}
                                    eyebrow={built.eyebrow}
                                    title={String(card?.title || 'Аудит мониторинга чеков')}
                                    body={String(card?.body || '')}
                                    sections={built.sections}
                                    details={built.details}
                                />
                            );
                        }
                        const built = buildGenericSections(card);
                        return (
                            <AiAgentToolCard
                                key={baseKey}
                                eyebrow={built.eyebrow}
                                title={String(card?.title || card?.type || 'Результат')}
                                body={typeof card?.body === 'string' ? card.body : ''}
                                sections={built.sections}
                                details={built.details}
                            />
                        );
                    })}
                </div>
            ) : null}

            {navigationTargets.length ? (
                <div className="agent-msg-nav">
                    {navigationTargets.map((target: AgentLocateResult, index: number) => (
                        <button
                            key={`${message.id}-nav-${index}`}
                            type="button"
                            className="agent-nav-pill"
                            onClick={() => onNavigate(target)}
                        >
                            {formatNavigationLabel(target)}
                        </button>
                    ))}
                </div>
            ) : null}

            {!isUser && latestRun?.requires_confirmation ? (
                <div style={{ marginTop: 12 }}>
                    <AiAgentConfirmationCard
                        run={latestRun}
                        onConfirm={onConfirmRun}
                        onReject={onRejectRun}
                        confirmPending={confirmPending}
                        rejectPending={rejectPending}
                    />
                </div>
            ) : null}
        </motion.div>
    );
};

// utility re-export to keep imports tidy
export { prettyJson };
