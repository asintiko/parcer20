import React from 'react';
import {
    Activity,
    BarChart3,
    CheckCircle2,
    ClipboardCheck,
    FileText,
    Globe,
    Layers,
    Loader2,
    type LucideIcon,
    Search,
    ShieldAlert,
    Tags,
    XCircle,
} from 'lucide-react';

export type ToolCardStatus = 'running' | 'completed' | 'failed';

export interface ToolCardRow {
    label: string;
    value: React.ReactNode;
}

export interface ToolCardSection {
    title?: string;
    rows: ToolCardRow[];
}

interface AiAgentToolCardProps {
    eyebrow?: string;
    title: string;
    body?: string;
    sections?: ToolCardSection[];
    tool?: string | null;
    type?: string | null;
    status?: ToolCardStatus;
    children?: React.ReactNode;
}

const TOOL_ICONS: Record<string, LucideIcon> = {
    transaction_analytics: BarChart3,
    monitored_chat_sync_audit: ClipboardCheck,
    duplicate_detector: Layers,
    duplicate_merge_preview: Layers,
    processing_errors_analyzer: ShieldAlert,
    failed_receipt_investigator: ShieldAlert,
    source_health_check: Activity,
    db_inspector: Activity,
    table_search_and_navigate: Search,
    telegram_cache_search: Search,
    message_to_transaction_trace: Search,
    report_builder: FileText,
    report_publish_tool: FileText,
    verify_receipt_parse: ClipboardCheck,
    receipt_reparse_preview: ClipboardCheck,
    auto_describe_operators: Globe,
    set_operator_description: Tags,
    list_operator_descriptions: Tags,
    rollback_operator_descriptions: Tags,
};

const TYPE_ICONS: Record<string, LucideIcon> = {
    analytics: BarChart3,
    audit: ClipboardCheck,
    report: FileText,
};

const STATUS_LABELS: Record<ToolCardStatus, string> = {
    running: 'Выполняется',
    completed: 'Готово',
    failed: 'Ошибка',
};

const StatusIcon: Record<ToolCardStatus, LucideIcon> = {
    running: Loader2,
    completed: CheckCircle2,
    failed: XCircle,
};

const resolveIcon = (tool?: string | null, type?: string | null): LucideIcon => {
    if (tool && TOOL_ICONS[tool]) return TOOL_ICONS[tool];
    const key = String(type || '').toLowerCase();
    if (TYPE_ICONS[key]) return TYPE_ICONS[key];
    return Layers;
};

export const AiAgentToolCard: React.FC<AiAgentToolCardProps> = ({
    eyebrow,
    title,
    body,
    sections,
    tool,
    type,
    status,
    children,
}) => {
    const hasSections = Array.isArray(sections) && sections.length > 0;
    const Icon = resolveIcon(tool, type);
    const StatusGlyph = status ? StatusIcon[status] : null;
    return (
        <div className="agent-card" data-status={status || undefined}>
            <div className="agent-card-head">
                <span className="agent-card-icon" aria-hidden>
                    <Icon size={15} />
                </span>
                <div className="agent-card-head-text">
                    {eyebrow ? <div className="agent-card-eyebrow">{eyebrow}</div> : null}
                    <div className="agent-card-title">{title}</div>
                </div>
                {status && StatusGlyph ? (
                    <span
                        className={`agent-card-status is-${status}`}
                        aria-label={STATUS_LABELS[status]}
                    >
                        <StatusGlyph size={12} aria-hidden />
                        {STATUS_LABELS[status]}
                    </span>
                ) : null}
            </div>
            {body || hasSections || children ? (
                <div className="agent-card-body">
                    {body ? <p>{body}</p> : null}
                    {hasSections
                        ? sections!.map((section, index) => (
                              <div key={index} className="agent-card-section">
                                  {section.title ? (
                                      <div className="agent-card-section-title">{section.title}</div>
                                  ) : null}
                                  {section.rows.map((row, rowIndex) => (
                                      <div key={rowIndex} className="agent-card-row">
                                          <span className="agent-card-row-label">{row.label}</span>
                                          <span className="agent-card-row-value">{row.value}</span>
                                      </div>
                                  ))}
                              </div>
                          ))
                        : null}
                    {children}
                </div>
            ) : null}
        </div>
    );
};
