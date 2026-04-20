import React from 'react';

type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
    label?: string;
    error?: string | null;
    hint?: string;
    containerClassName?: string;
};

export function Input({
    label,
    error,
    hint,
    containerClassName = '',
    className = '',
    id,
    ...props
}: InputProps) {
    const inputId = id || props.name || undefined;
    return (
        <div className={containerClassName}>
            {label && (
                <label htmlFor={inputId} className="block text-sm font-medium text-foreground mb-1.5">
                    {label}
                </label>
            )}
            <input
                id={inputId}
                {...props}
                className={[
                    'input-base',
                    error ? 'border-danger focus:ring-danger/40' : '',
                    className,
                ]
                    .filter(Boolean)
                    .join(' ')}
                aria-invalid={Boolean(error)}
                aria-describedby={error ? `${inputId}-error` : undefined}
            />
            {error ? (
                <p id={`${inputId}-error`} className="mt-1 text-xs text-danger">
                    {error}
                </p>
            ) : hint ? (
                <p className="mt-1 text-xs text-foreground-muted">{hint}</p>
            ) : null}
        </div>
    );
}
