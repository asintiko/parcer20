import React, { useEffect, useState } from 'react';
import { Lock } from 'lucide-react';
import { Dialog } from '../motion/Dialog';

interface PasswordDialogProps {
    open: boolean;
    chatTitle: string;
    mode: 'set' | 'verify' | 'remove';
    busy?: boolean;
    error?: string | null;
    onClose: () => void;
    onSubmit: (password: string) => void;
}

const META: Record<PasswordDialogProps['mode'], { title: string; desc: string; cta: string; placeholder: string; needConfirm?: boolean }> = {
    set: {
        title: 'Установить пароль',
        desc: 'Чат будет защищён паролем. Без него содержимое не будет показываться.',
        cta: 'Установить',
        placeholder: 'Минимум 4 символа',
        needConfirm: true,
    },
    verify: {
        title: 'Введите пароль',
        desc: 'Этот чат защищён. Введите пароль, чтобы открыть его содержимое.',
        cta: 'Открыть',
        placeholder: 'Пароль',
    },
    remove: {
        title: 'Снять защиту',
        desc: 'Введите текущий пароль, чтобы убрать защиту с этого чата.',
        cta: 'Снять защиту',
        placeholder: 'Текущий пароль',
    },
};

export const PasswordDialog: React.FC<PasswordDialogProps> = ({
    open, chatTitle, mode, busy, error, onClose, onSubmit,
}) => {
    const meta = META[mode];
    const [password, setPassword] = useState('');
    const [confirm, setConfirm] = useState('');
    const [localError, setLocalError] = useState<string | null>(null);

    useEffect(() => {
        if (open) {
            setPassword('');
            setConfirm('');
            setLocalError(null);
        }
    }, [open, mode]);

    const handleSubmit = () => {
        const p = password.trim();
        if (!p) {
            setLocalError('Введите пароль');
            return;
        }
        if (mode === 'set') {
            if (p.length < 4) {
                setLocalError('Минимум 4 символа');
                return;
            }
            if (p !== confirm.trim()) {
                setLocalError('Пароли не совпадают');
                return;
            }
        }
        setLocalError(null);
        onSubmit(p);
    };

    const showError = error || localError;

    return (
        <Dialog
            open={open}
            onClose={busy ? () => {} : onClose}
            ariaLabel={meta.title}
            title={
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span aria-hidden style={{
                        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                        width: 28, height: 28, borderRadius: 4,
                        background: 'var(--surface-2)', color: 'var(--text)',
                    }}>
                        <Lock size={15} />
                    </span>
                    <h3 className="sp-sheet-title">{meta.title}</h3>
                </div>
            }
            description={
                <>
                    {meta.desc}
                    <div style={{ marginTop: 4, fontSize: 12, color: 'var(--text-muted)' }}>
                        Чат: <b>{chatTitle}</b>
                    </div>
                </>
            }
            width={420}
            footer={
                <>
                    <span className="sp-spacer" />
                    <button
                        type="button"
                        className="sp-btn"
                        onClick={onClose}
                        disabled={busy}
                    >
                        Отмена
                    </button>
                    <button
                        type="button"
                        className={`sp-btn ${mode === 'remove' ? 'sp-btn-danger sp-btn-solid' : 'sp-btn-primary'}`}
                        onClick={handleSubmit}
                        disabled={busy}
                        autoFocus
                    >
                        {busy ? 'Сохраняем…' : meta.cta}
                    </button>
                </>
            }
        >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 4 }}>
                <input
                    type="password"
                    className="tg-input-box"
                    placeholder={meta.placeholder}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoFocus
                    autoComplete="new-password"
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && !meta.needConfirm) {
                            e.preventDefault();
                            handleSubmit();
                        }
                    }}
                />
                {meta.needConfirm ? (
                    <input
                        type="password"
                        className="tg-input-box"
                        placeholder="Повторите пароль"
                        value={confirm}
                        onChange={(e) => setConfirm(e.target.value)}
                        autoComplete="new-password"
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                                e.preventDefault();
                                handleSubmit();
                            }
                        }}
                    />
                ) : null}
                {showError ? (
                    <div style={{ color: 'var(--danger)', fontSize: 12.5 }}>{showError}</div>
                ) : null}
            </div>
        </Dialog>
    );
};
