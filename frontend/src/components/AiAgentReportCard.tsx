import React from 'react';
import type { AgentReport } from '../services/api';
import { AiAgentToolCard, type ToolCardSection } from './AiAgentToolCard';
import { humanizeSummaryKey } from '../utils/aiAgentDisplay';

interface AiAgentReportCardProps {
    report: AgentReport;
    onOpen: (reportId: string) => void;
}

const formatValue = (value: unknown): string => {
    if (value == null) return '—';
    if (typeof value === 'number') return value.toLocaleString('ru-RU');
    return String(value);
};

export const AiAgentReportCard: React.FC<AiAgentReportCardProps> = ({ report, onOpen }) => {
    const summaryEntries = Object.entries(report.summary || {}).slice(0, 6);
    const sections: ToolCardSection[] = summaryEntries.length
        ? [
              {
                  rows: summaryEntries.map(([key, value]) => ({
                      label: humanizeSummaryKey(key),
                      value: formatValue(value),
                  })),
              },
          ]
        : [];

    return (
        <AiAgentToolCard
            eyebrow={report.scope === 'team' ? 'КОМАНДНЫЙ ОТЧЁТ' : 'ЛИЧНЫЙ ОТЧЁТ'}
            title={report.title || 'Без названия'}
            sections={sections}
        >
            <div style={{ padding: '8px 14px 6px' }}>
                <button
                    type="button"
                    onClick={() => onOpen(report.id)}
                    className="agent-btn agent-btn-primary"
                    style={{ width: '100%' }}
                >
                    Открыть отчёт
                </button>
            </div>
        </AiAgentToolCard>
    );
};
