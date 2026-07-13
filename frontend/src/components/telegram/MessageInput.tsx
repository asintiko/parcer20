import React, { useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Send, Paperclip, Loader2 } from 'lucide-react';

interface MessageInputProps {
    onSend: (text: string) => void;
    onAttach?: (file: File) => void;
    disabled?: boolean;
    sending?: boolean;
    placeholder?: string;
}

export const MessageInput: React.FC<MessageInputProps> = ({
    onSend,
    onAttach,
    disabled,
    sending,
    placeholder = 'Сообщение...',
}) => {
    const [text, setText] = useState('');
    const fileRef = useRef<HTMLInputElement | null>(null);
    const taRef = useRef<HTMLTextAreaElement | null>(null);

    const trimmed = text.trim();
    const canSend = !disabled && !sending && trimmed.length > 0;

    const handleSend = () => {
        if (!canSend) return;
        onSend(trimmed);
        setText('');
        if (taRef.current) {
            taRef.current.style.height = 'auto';
        }
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
        setText(e.target.value);
        const ta = e.target;
        ta.style.height = 'auto';
        ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
    };

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const f = e.target.files?.[0];
        if (f && onAttach) onAttach(f);
        e.target.value = '';
    };

    return (
        <div className="tg-composer">
            {onAttach ? (
                <>
                    <input
                        ref={fileRef}
                        type="file"
                        hidden
                        onChange={handleFileChange}
                        accept=".pdf,application/pdf,image/*"
                    />
                    <button
                        type="button"
                        className="tg-composer-attach"
                        onClick={() => fileRef.current?.click()}
                        disabled={disabled || sending}
                        aria-label="Прикрепить файл"
                        title="Прикрепить файл"
                    >
                        <Paperclip size={18} />
                    </button>
                </>
            ) : null}

            <textarea
                ref={taRef}
                className="tg-composer-input"
                placeholder={placeholder}
                value={text}
                onChange={handleInput}
                onKeyDown={handleKeyDown}
                disabled={disabled}
                rows={1}
                aria-label="Сообщение"
            />

            <motion.button
                type="button"
                className="tg-composer-send"
                onClick={handleSend}
                disabled={!canSend}
                aria-label="Отправить сообщение"
                whileTap={canSend ? { scale: 0.92 } : undefined}
                animate={canSend ? { scale: 1, opacity: 1 } : { scale: 0.94, opacity: 0.5 }}
                transition={{ type: 'spring', stiffness: 420, damping: 28 }}
            >
                <AnimatePresence mode="wait" initial={false}>
                    <motion.span
                        key={sending ? 'sending' : 'idle'}
                        initial={{ opacity: 0, rotate: -25, scale: 0.7 }}
                        animate={{ opacity: 1, rotate: 0, scale: 1 }}
                        exit={{ opacity: 0, rotate: 25, scale: 0.7 }}
                        transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
                        style={{ display: 'inline-flex' }}
                    >
                        {sending ? (
                            <Loader2 size={14} className="tg-msg-process-spin" />
                        ) : (
                            <Send size={16} />
                        )}
                    </motion.span>
                </AnimatePresence>
            </motion.button>
        </div>
    );
};
