import { FormEvent, useState } from 'react';

type ChatPasswordModalProps = {
    open: boolean;
    chatTitle?: string;
    onClose: () => void;
    onSubmit: (password: string) => Promise<{ ok: boolean; error?: string }>;
};

export function ChatPasswordModal({ open, chatTitle, onClose, onSubmit }: ChatPasswordModalProps) {
    const [password, setPassword] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [submitting, setSubmitting] = useState(false);

    if (!open) return null;

    const submit = async (e: FormEvent) => {
        e.preventDefault();
        if (!password.trim() || submitting) return;
        setSubmitting(true);
        setError(null);
        const result = await onSubmit(password.trim());
        if (!result.ok) {
            setError(result.error || 'Неверный пароль');
            setSubmitting(false);
            return;
        }
        setPassword('');
        setSubmitting(false);
        onClose();
    };

    return (
        <div className="fixed inset-0 z-[var(--z-overlay)] bg-black/50 flex items-center justify-center p-4">
            <form onSubmit={submit} className="w-full max-w-sm rounded-lg border border-border bg-surface p-5 shadow-lg">
                <h3 className="text-base font-semibold text-foreground mb-1">Защищенный чат</h3>
                <p className="text-sm text-foreground-secondary mb-4">
                    {chatTitle ? `Введите пароль для "${chatTitle}"` : 'Введите пароль для доступа к чату'}
                </p>
                <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full px-3 py-2 border border-border rounded-md bg-input-bg text-input-text"
                    autoFocus
                />
                {error && <div className="mt-2 text-sm text-danger">{error}</div>}
                <div className="mt-4 flex justify-end gap-2">
                    <button type="button" onClick={onClose} className="px-3 py-2 text-sm border border-border rounded-md">
                        Отмена
                    </button>
                    <button type="submit" disabled={submitting} className="px-3 py-2 text-sm bg-primary text-foreground-inverse rounded-md">
                        {submitting ? 'Проверка...' : 'Войти'}
                    </button>
                </div>
            </form>
        </div>
    );
}
