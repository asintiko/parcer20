import React from 'react';
import { prettyJson } from '../utils/aiAgentDisplay';

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
    details?: unknown;
    children?: React.ReactNode;
}

export const AiAgentToolCard: React.FC<AiAgentToolCardProps> = ({
    eyebrow,
    title,
    body,
    sections,
    details,
    children,
}) => {
    const hasSections = Array.isArray(sections) && sections.length > 0;
    return (
        <div className="agent-card">
            <div className="agent-card-head">
                {eyebrow ? <div className="agent-card-eyebrow">{eyebrow}</div> : null}
                <div className="agent-card-title">{title}</div>
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
            {details != null ? (
                <details className="agent-card-details">
                    <summary>Детали</summary>
                    <pre>{prettyJson(details)}</pre>
                </details>
            ) : null}
        </div>
    );
};
