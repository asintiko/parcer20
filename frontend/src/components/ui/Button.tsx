import React from 'react';

type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';
type ButtonSize = 'sm' | 'md';

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: ButtonVariant;
    size?: ButtonSize;
    fullWidth?: boolean;
};

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
    primary:
        'bg-primary text-foreground-inverse border border-primary hover:bg-primary-hover focus:ring-primary/50',
    secondary:
        'bg-surface border border-border text-foreground hover:bg-surface-2 focus:ring-primary/40',
    danger:
        'bg-danger text-foreground-inverse border border-danger hover:bg-danger-hover focus:ring-danger/40',
    ghost:
        'bg-transparent border border-transparent text-foreground-secondary hover:bg-surface-2 hover:text-foreground focus:ring-primary/30',
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
    sm: 'px-3 py-1.5 text-sm rounded-md',
    md: 'px-4 py-2 text-sm rounded-lg',
};

export function Button({
    className = '',
    variant = 'secondary',
    size = 'md',
    fullWidth = false,
    disabled,
    ...props
}: ButtonProps) {
    const widthClass = fullWidth ? 'w-full' : '';
    return (
        <button
            {...props}
            disabled={disabled}
            className={[
                'inline-flex items-center justify-center gap-2 transition-colors',
                'focus:outline-none focus:ring-2',
                'disabled:opacity-50 disabled:cursor-not-allowed',
                VARIANT_CLASSES[variant],
                SIZE_CLASSES[size],
                widthClass,
                className,
            ]
                .filter(Boolean)
                .join(' ')}
        />
    );
}
