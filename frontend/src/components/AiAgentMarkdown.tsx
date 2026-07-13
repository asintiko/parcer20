import React, { useMemo, useState } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize';
import { Check, Copy } from 'lucide-react';

const SVG_TAGS = [
    'svg', 'path', 'g', 'rect', 'circle', 'line', 'polyline', 'polygon', 'ellipse',
    'text', 'tspan', 'defs', 'linearGradient', 'radialGradient', 'stop', 'title', 'desc',
];

const SVG_ATTRS = [
    'viewBox', 'xmlns', 'width', 'height', 'd', 'fill', 'stroke', 'strokeWidth',
    'stroke-width', 'strokeLinecap', 'stroke-linecap', 'strokeLinejoin', 'stroke-linejoin',
    'cx', 'cy', 'r', 'rx', 'ry', 'x', 'y', 'x1', 'y1', 'x2', 'y2', 'points', 'transform',
    'opacity', 'fillOpacity', 'fill-opacity', 'strokeOpacity', 'stroke-opacity', 'offset',
    'stopColor', 'stop-color', 'stopOpacity', 'stop-opacity', 'gradientUnits', 'textAnchor',
    'text-anchor', 'fontSize', 'font-size', 'fontFamily', 'font-family', 'dx', 'dy', 'class',
];

// Sanitize schema: GFM defaults + tightly-scoped inline SVG so the agent can draw
// small charts/diagrams. No script/iframe/foreignObject, no inline style, no event handlers.
const schema = {
    ...defaultSchema,
    tagNames: [...(defaultSchema.tagNames || []), ...SVG_TAGS],
    attributes: {
        ...(defaultSchema.attributes || {}),
        '*': [...((defaultSchema.attributes && defaultSchema.attributes['*']) || []), 'className'],
        ...SVG_TAGS.reduce<Record<string, string[]>>((acc, tag) => {
            acc[tag] = SVG_ATTRS;
            return acc;
        }, {}),
    },
};

function extractText(node: React.ReactNode): string {
    if (node == null || node === false || node === true) return '';
    if (typeof node === 'string' || typeof node === 'number') return String(node);
    if (Array.isArray(node)) return node.map(extractText).join('');
    if (React.isValidElement(node)) {
        return extractText((node.props as { children?: React.ReactNode }).children);
    }
    return '';
}

function CodeBlock({ className, children }: { className?: string; children?: React.ReactNode }) {
    const [copied, setCopied] = useState(false);
    const text = useMemo(() => extractText(children), [children]);
    const langMatch = (className || '').match(/language-([\w-]+)/);
    const lang = langMatch ? langMatch[1] : '';

    const onCopy = () => {
        const write = navigator?.clipboard?.writeText?.(text);
        Promise.resolve(write)
            .then(() => {
                setCopied(true);
                window.setTimeout(() => setCopied(false), 1500);
            })
            .catch(() => undefined);
    };

    return (
        <div className="agent-md-pre">
            {lang ? <span className="agent-md-pre-lang">{lang}</span> : null}
            <button
                type="button"
                className="agent-md-copy-btn"
                onClick={onCopy}
                aria-label={copied ? 'Скопировано' : 'Копировать'}
                title={copied ? 'Скопировано' : 'Копировать'}
            >
                {copied ? <Check size={12} /> : <Copy size={12} />}
            </button>
            <pre>
                <code className={className}>{children}</code>
            </pre>
        </div>
    );
}

const components: Components = {
    h1: ({ children }) => <h1 className="agent-md-h agent-md-h1">{children}</h1>,
    h2: ({ children }) => <h2 className="agent-md-h agent-md-h2">{children}</h2>,
    h3: ({ children }) => <h3 className="agent-md-h agent-md-h3">{children}</h3>,
    h4: ({ children }) => <h4 className="agent-md-h agent-md-h4">{children}</h4>,
    a: ({ children, href }) => (
        <a href={href} target="_blank" rel="noopener noreferrer" className="agent-md-link">
            {children}
        </a>
    ),
    hr: () => <hr className="agent-md-hr" />,
    table: ({ children }) => (
        <div className="agent-md-table-wrap">
            <table className="agent-md-table">{children}</table>
        </div>
    ),
    blockquote: ({ children }) => <blockquote className="agent-md-quote">{children}</blockquote>,
    pre: ({ children }) => {
        // The fenced block's <code> carries language + content; render via CodeBlock.
        const child = Array.isArray(children) ? children[0] : children;
        if (React.isValidElement(child)) {
            const props = child.props as { className?: string; children?: React.ReactNode };
            return <CodeBlock className={props.className} children={props.children} />;
        }
        return <CodeBlock>{children}</CodeBlock>;
    },
    code: ({ className, children }) => {
        const hasLang = /language-/.test(className || '');
        const isMultiline = String(extractText(children)).includes('\n');
        if (!hasLang && !isMultiline) {
            return <code className="agent-md-code-inline">{children}</code>;
        }
        return <code className={className}>{children}</code>;
    },
};

interface AiAgentMarkdownProps {
    content: string;
}

const AiAgentMarkdownBase: React.FC<AiAgentMarkdownProps> = ({ content }) => (
    <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, [rehypeSanitize, schema]]}
        components={components}
    >
        {content}
    </ReactMarkdown>
);

export const AiAgentMarkdown = React.memo(AiAgentMarkdownBase);
