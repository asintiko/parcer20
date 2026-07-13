import React, { useEffect, useRef, useState } from 'react';
import { AlertCircle } from 'lucide-react';
import { Dialog } from './motion/Dialog';

type PromptModalProps = {
    open: boolean;
    title: string;
    description?: React.ReactNode;
    label?: string;
    placeholder?: string;
    initialValue?: string;
    confirmLabel?: string;
    cancelLabel?: string;
    inputType?: 'text' | 'password' | 'numeric';
    validate?: (value: string) => string | null;
    submitting?: boolean;
    serverError?: string | null;
    onSubmit: (value: string) => void;
    onClose: () => void;
};

export const PromptModal: React.FC<PromptModalProps> = ({
    open,
    title,
    description,
    label,
    placeholder,
    initialValue = '',
    confirmLabel = 'Подтвердить',
    cancelLabel = 'Отмена',
    inputType = 'text',
    validate,
    submitting = false,
    serverError,
    onSubmit,
    onClose,
}) => {
    const [value, setValue] = useState(initialValue);
    const [error, setError] = useState<string | null>(null);
    const inputRef = useRef<HTMLInputElement | null>(null);

    useEffect(() => {
        if (open) {
            setValue(initialValue);
            setError(null);
            const id = window.setTimeout(() => inputRef.current?.focus(), 80);
            return () => window.clearTimeout(id);
        }
        return;
    }, [open, initialValue]);

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        const v = value;
        const validationError = validate ? validate(v) : null;
        if (validationError) {
            setError(validationError);
            return;
        }
        setError(null);
        onSubmit(v);
    };

    const displayedError = error || serverError || null;
    const inputMode = inputType === 'numeric' ? 'numeric' : undefined;
    const htmlType = inputType === 'password' ? 'password' : 'text';

    return (
        <Dialog
            open={open}
            onClose={submitting ? () => {} : onClose}
            title={title}
            description={description}
            ariaLabel={title}
            footer={
                <>
                    <span className="sp-spacer" />
                    <button
                        type="button"
                        className="sp-btn"
                        onClick={onClose}
                        disabled={submitting}
                    >
                        {cancelLabel}
                    </button>
                    <button
                        type="button"
                        className="sp-btn sp-btn-primary"
                        onClick={(e) => handleSubmit(e as unknown as React.FormEvent)}
                        disabled={submitting}
                    >
                        {submitting ? (
                            <>
                                <span className="sp-btn-spinner" aria-hidden />
                                Отправка
                            </>
                        ) : (
                            confirmLabel
                        )}
                    </button>
                </>
            }
        >
            <form onSubmit={handleSubmit} className="sp-field-stack">
                {label ? (
                    <label className="sp-row-hint sp-form-label" htmlFor="sp-prompt-input">
                        {label}
                    </label>
                ) : null}
                <input
                    ref={inputRef}
                    id="sp-prompt-input"
                    type={htmlType}
                    inputMode={inputMode}
                    value={value}
                    onChange={(e) => {
                        setValue(e.target.value);
                        if (error) setError(null);
                    }}
                    placeholder={placeholder}
                    className={['sp-input', displayedError ? 'has-error' : ''].filter(Boolean).join(' ')}
                    autoComplete="off"
                    aria-invalid={Boolean(displayedError)}
                    aria-describedby={displayedError ? 'sp-prompt-error' : undefined}
                />
                {displayedError ? (
                    <div id="sp-prompt-error" className="sp-error sp-field-error">
                        <AlertCircle size={13} />
                        <span>{displayedError}</span>
                    </div>
                ) : null}
                {/* hidden submit so Enter works */}
                <button type="submit" style={{ display: 'none' }} />
            </form>
        </Dialog>
    );
};
