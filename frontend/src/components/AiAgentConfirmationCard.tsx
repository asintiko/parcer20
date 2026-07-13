import React from 'react';
import { motion } from 'motion/react';
import { AlertTriangle } from 'lucide-react';
import type { AgentConfirmationPayload, AgentRun } from '../services/api';

interface AiAgentConfirmationCardProps {
    run: AgentRun;
    onConfirm: (runId: string) => void;
    onReject?: (runId: string) => void;
    confirmPending?: boolean;
    rejectPending?: boolean;
}

interface DiffEntry {
    field: string;
    before: unknown;
    after: unknown;
}

function getPayload(run: AgentRun): AgentConfirmationPayload | null {
    const top = run.confirmation_payload;
    if (top && typeof top === 'object') return top;
    const fromResult = run.result?.confirmation_payload;
    if (fromResult && typeof fromResult === 'object') return fromResult as AgentConfirmationPayload;
    return null;
}

function fmtValue(value: unknown): string {
    if (value === null || value === undefined || value === '') return '—';
    if (typeof value === 'boolean') return value ? 'да' : 'нет';
    if (typeof value === 'number') return value.toLocaleString('ru-RU');
    if (typeof value === 'object') {
        try {
            return JSON.stringify(value);
        } catch {
            return String(value);
        }
    }
    return String(value);
}

const ACTION_LABELS: Record<string, { confirm: string; title: string; impact: (args: Record<string, any>) => string | null }> = {
    merge_duplicates: {
        confirm: 'Объединить',
        title: 'Объединение дублей',
        impact: (args) => {
            const pairs = Array.isArray(args.pairs) ? args.pairs.length : Array.isArray(args.duplicates) ? args.duplicates.length : 0;
            return pairs ? `Будут объединены ${pairs} пар(ы) транзакций.` : null;
        },
    },
    reparse_receipt: {
        confirm: 'Запустить разбор',
        title: 'Повторный разбор чека',
        impact: () => 'Старый разбор будет заменён результатом повторной обработки.',
    },
    publish_report: {
        confirm: 'Опубликовать',
        title: 'Публикация отчёта',
        impact: (args) => `Отчёт станет видимым: scope «${args.scope || 'team'}».`,
    },
    create_transaction: {
        confirm: 'Создать',
        title: 'Создание транзакции',
        impact: () => 'Новая запись попадёт в таблицу транзакций.',
    },
    update_transaction: {
        confirm: 'Применить',
        title: 'Редактирование транзакции',
        impact: (args) => (args.transaction_id ? `Изменения применятся к транзакции #${args.transaction_id}.` : null),
    },
    bulk_update_transactions: {
        confirm: 'Применить ко всем',
        title: 'Массовое редактирование',
        impact: (args) => {
            const count = Array.isArray(args.transaction_ids) ? args.transaction_ids.length : 0;
            return count ? `Изменения применятся к ${count} записям.` : null;
        },
    },
    apply_app_mapping: { confirm: 'Применить mapping', title: 'Применение app mapping', impact: () => null },
    apply_data_verification: { confirm: 'Применить', title: 'Применение проверки данных', impact: () => null },
    apply_bot_reconciliation: { confirm: 'Применить', title: 'Применение сверки', impact: () => null },
};

const Row: React.FC<{ label: string; value: unknown }> = ({ label, value }) => (
    <div className="agent-card-row">
        <span className="agent-card-row-label">{label}</span>
        <span className="agent-card-row-value">{fmtValue(value)}</span>
    </div>
);

const PreviewBlock: React.FC<{ children: React.ReactNode }> = ({ children }) => (
    <div
        style={{
            border: '1px solid var(--border)',
            borderRadius: 'var(--agent-radius)',
            background: 'var(--surface)',
            padding: '4px 0',
        }}
    >
        {children}
    </div>
);

const CreateTxPreview: React.FC<{ args: Record<string, any> }> = ({ args }) => (
    <PreviewBlock>
        <Row label="Дата" value={args.transaction_datetime} />
        <Row label="Тип" value={args.transaction_type} />
        <Row label="Сумма" value={`${fmtValue(args.amount)} ${fmtValue(args.currency)}`} />
        <Row label="Оператор" value={args.operator} />
        <Row label="Карта" value={args.card_last4 ? `••••${args.card_last4}` : null} />
        {args.app ? <Row label="Приложение" value={args.app} /> : null}
        {args.is_p2p ? <Row label="P2P" value /> : null}
        {args.is_p2p ? <Row label="Получатель" value={args.receiver_name} /> : null}
    </PreviewBlock>
);

const UpdateTxPreview: React.FC<{ args: Record<string, any> }> = ({ args }) => {
    const patch = (args.patch || {}) as Record<string, unknown>;
    const entries = Object.entries(patch);
    return (
        <PreviewBlock>
            <Row label="Транзакция" value={args.transaction_id ? `#${args.transaction_id}` : null} />
            {entries.length === 0 ? (
                <div style={{ padding: '6px 14px', fontSize: 12.5, color: 'var(--text-muted)' }}>
                    Изменений в patch нет
                </div>
            ) : (
                entries.map(([field, value]) => <Row key={field} label={field} value={value} />)
            )}
        </PreviewBlock>
    );
};

const BulkUpdatePreview: React.FC<{ args: Record<string, any>; sample?: DiffEntry[] | unknown }> = ({ args, sample }) => {
    const ids = Array.isArray(args.transaction_ids) ? args.transaction_ids : [];
    const patch = (args.patch || {}) as Record<string, unknown>;
    const patchEntries = Object.entries(patch);
    const sampleArr = Array.isArray(sample) ? sample : [];
    return (
        <PreviewBlock>
            <Row label="Транзакций" value={ids.length} />
            {ids.length > 0 ? (
                <div
                    style={{
                        padding: '4px 14px',
                        fontSize: 11,
                        fontFamily: 'var(--font-mono, monospace)',
                        color: 'var(--text-muted)',
                        letterSpacing: '0.02em',
                    }}
                >
                    IDs: {ids.slice(0, 12).join(', ')}{ids.length > 12 ? '…' : ''}
                </div>
            ) : null}
            <div style={{ borderTop: '1px solid var(--border)', marginTop: 4, paddingTop: 4 }}>
                <div className="agent-card-section-title">Изменения</div>
                {patchEntries.length === 0 ? (
                    <div style={{ padding: '4px 14px 8px', fontSize: 12.5, color: 'var(--text-muted)' }}>
                        Patch пуст
                    </div>
                ) : (
                    patchEntries.map(([field, value]) => <Row key={field} label={field} value={value} />)
                )}
            </div>
            {sampleArr.length > 0 ? (
                <div style={{ padding: '6px 14px', fontSize: 11.5, color: 'var(--text-muted)' }}>
                    Пример diff на {sampleArr.length} записей.
                </div>
            ) : null}
        </PreviewBlock>
    );
};

const MergeDuplicatesPreview: React.FC<{ args: Record<string, any> }> = ({ args }) => {
    const pairs = Array.isArray(args.pairs) ? args.pairs : Array.isArray(args.duplicates) ? args.duplicates : [];
    if (pairs.length === 0) {
        return (
            <PreviewBlock>
                <Row label="Пар к объединению" value={0} />
            </PreviewBlock>
        );
    }
    return (
        <PreviewBlock>
            <Row label="Пар к объединению" value={pairs.length} />
            {pairs.slice(0, 5).map((p: any, idx: number) => (
                <div
                    key={idx}
                    style={{
                        padding: '4px 14px',
                        fontFamily: 'var(--font-mono, monospace)',
                        fontSize: 11.5,
                        color: 'var(--text)',
                    }}
                >
                    #{p.primary_id ?? p.primary} ↔ #{p.duplicate_id ?? p.duplicate}
                </div>
            ))}
            {pairs.length > 5 ? (
                <div style={{ padding: '4px 14px 8px', fontSize: 11.5, color: 'var(--text-muted)' }}>
                    …ещё {pairs.length - 5}
                </div>
            ) : null}
        </PreviewBlock>
    );
};

const ReparseReceiptPreview: React.FC<{ args: Record<string, any> }> = ({ args }) => (
    <PreviewBlock>
        <Row label="Chat" value={args.chat_id} />
        <Row label="Message" value={args.message_id} />
        {args.raw_text ? (
            <div
                style={{
                    margin: '4px 14px 8px',
                    paddingTop: 6,
                    borderTop: '1px solid var(--border)',
                    fontFamily: 'var(--font-mono, monospace)',
                    fontSize: 11.5,
                    color: 'var(--text-secondary)',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-all',
                }}
            >
                {String(args.raw_text).slice(0, 400)}
            </div>
        ) : null}
    </PreviewBlock>
);

const PublishReportPreview: React.FC<{ args: Record<string, any> }> = ({ args }) => (
    <PreviewBlock>
        <Row label="Отчёт" value={args.title} />
        <Row label="Scope" value={args.scope} />
        <Row label="Items" value={args.items_count ?? args.item_count} />
    </PreviewBlock>
);

const GenericPreview: React.FC<{ args: Record<string, any> }> = ({ args }) => {
    const entries = Object.entries(args || {});
    if (entries.length === 0) return null;
    return (
        <PreviewBlock>
            {entries.map(([key, value]) => (
                <Row key={key} label={key} value={value} />
            ))}
        </PreviewBlock>
    );
};

function renderPreview(action: string, payload: AgentConfirmationPayload, run: AgentRun) {
    const args = (payload.args || {}) as Record<string, any>;
    switch (action) {
        case 'create_transaction':
            return <CreateTxPreview args={args} />;
        case 'update_transaction':
            return <UpdateTxPreview args={args} />;
        case 'bulk_update_transactions': {
            const sample = (run.result as any)?.cards?.find?.((c: any) => c?.type === 'preview_bulk_update_tx')?.payload?.sample;
            return <BulkUpdatePreview args={args} sample={sample} />;
        }
        case 'merge_duplicates':
            return <MergeDuplicatesPreview args={args} />;
        case 'reparse_receipt':
            return <ReparseReceiptPreview args={args} />;
        case 'publish_report':
            return <PublishReportPreview args={args} />;
        default:
            return <GenericPreview args={args} />;
    }
}

export const AiAgentConfirmationCard: React.FC<AiAgentConfirmationCardProps> = ({
    run,
    onConfirm,
    onReject,
    confirmPending,
    rejectPending,
}) => {
    if (!run.requires_confirmation) return null;

    const payload = getPayload(run);
    const action = String(payload?.action || '');
    const meta = ACTION_LABELS[action] || {
        confirm: 'Подтвердить',
        title: 'Требуется подтверждение',
        impact: () => null,
    };
    const args = (payload?.args || {}) as Record<string, any>;
    const message =
        (run.result as any)?.assistant_message ||
        (run.result as any)?.message ||
        'Для продолжения агент ждёт подтверждение действия.';
    const impactText = meta.impact(args);
    const busy = Boolean(confirmPending || rejectPending);

    return (
        <motion.div
            className="agent-confirm"
            initial={{ opacity: 0, y: 8, scale: 0.985 }}
            animate={{
                opacity: 1,
                y: 0,
                scale: 1,
                transition: { duration: 0.32, ease: [0.34, 1.3, 0.64, 1] },
            }}
        >
            <div className="agent-confirm-head">
                <AlertTriangle size={14} className="agent-confirm-icon" aria-hidden />
                <span className="agent-confirm-eyebrow">Подтверждение</span>
            </div>
            <div className="agent-confirm-body">
                <h4 className="agent-confirm-title">{meta.title}</h4>
                {message ? <div className="agent-confirm-desc">{message}</div> : null}
                {impactText ? (
                    <div className="agent-confirm-impact">
                        <strong>Последствие.</strong> {impactText}
                    </div>
                ) : null}
                {payload ? <div style={{ marginTop: 10 }}>{renderPreview(action, payload, run)}</div> : null}
            </div>
            <div className="agent-confirm-actions">
                <button
                    type="button"
                    className="agent-btn agent-btn-primary"
                    onClick={() => onConfirm(run.id)}
                    disabled={busy}
                >
                    {confirmPending ? 'Подтверждение…' : meta.confirm}
                </button>
                {onReject ? (
                    <button
                        type="button"
                        className="agent-btn"
                        onClick={() => onReject(run.id)}
                        disabled={busy}
                    >
                        {rejectPending ? 'Отклоняю…' : 'Отклонить'}
                    </button>
                ) : null}
            </div>
        </motion.div>
    );
};
