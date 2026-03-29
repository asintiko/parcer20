import React from 'react';
import type { AgentReport } from '../services/api';
import { AiAgentToolCard } from './AiAgentToolCard';
import { humanizeSummaryKey } from '../utils/aiAgentDisplay';

interface AiAgentReportCardProps {
    report: AgentReport;
    onOpen: (reportId: string) => void;
}

export const AiAgentReportCard: React.FC<AiAgentReportCardProps> = ({ report, onOpen }) => {
    const summaryEntries = Object.entries(report.summary || {}).slice(0, 5);
    return (
        <AiAgentToolCard title={report.scope === 'team' ? 'Командный отчет' : 'Личный отчет'} body={report.title}>
            <div className="space-y-1 text-xs text-foreground-secondary">
                {summaryEntries.map(([key, value]) => (
                    <div key={key} className="flex items-center justify-between gap-3">
                        <span>{humanizeSummaryKey(key)}</span>
                        <span className="font-medium text-foreground">{String(value)}</span>
                    </div>
                ))}
            </div>
            <button
                type="button"
                onClick={() => onOpen(report.id)}
                className="mt-3 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium hover:bg-surface"
            >
                Открыть отчет
            </button>
        </AiAgentToolCard>
    );
};
