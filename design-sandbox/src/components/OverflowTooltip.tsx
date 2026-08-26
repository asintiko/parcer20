import { type ReactNode, useCallback, useRef, useState } from 'react';
import Tooltip from '@mui/material/Tooltip';

interface OverflowTooltipProps {
    text?: string | null;
    children: ReactNode;
    className?: string;
}

export function OverflowTooltip({ text, children, className }: OverflowTooltipProps) {
    const normalizedText = typeof text === 'string' ? text.trim() : '';
    const [isOverflowed, setIsOverflowed] = useState(false);
    const ref = useRef<HTMLSpanElement>(null);

    const handleMouseEnter = useCallback(() => {
        const element = ref.current;
        if (!element) return;
        setIsOverflowed(element.scrollWidth > element.clientWidth);
    }, []);

    if (!normalizedText) {
        return <span className={className}>{children}</span>;
    }

    return (
        <Tooltip
            arrow
            enterDelay={100}
            disableHoverListener={!isOverflowed}
            title={normalizedText}
            slotProps={{
                tooltip: {
                    sx: {
                        maxWidth: 520,
                        whiteSpace: 'normal',
                        wordBreak: 'break-word',
                        fontSize: '0.75rem',
                        lineHeight: 1.35,
                    },
                },
            }}
        >
            <span
                ref={ref}
                className={className}
                onMouseEnter={handleMouseEnter}
                data-overflow-probe="1"
                data-fulltext={normalizedText}
                style={{
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    display: 'block',
                }}
            >
                {children}
            </span>
        </Tooltip>
    );
}
