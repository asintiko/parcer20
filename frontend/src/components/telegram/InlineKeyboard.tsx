import React, { useState } from 'react';
import { ExternalLink, AppWindow, Copy, Check } from 'lucide-react';
import type { TgKeyboardButton, TgReplyMarkup } from '../../services/api';

interface InlineKeyboardProps {
    markup: TgReplyMarkup;
    onOpenWebApp: (btn: TgKeyboardButton) => void;
    onOpenLink: (url: string) => void;
}

const CopyButton: React.FC<{ btn: TgKeyboardButton }> = ({ btn }) => {
    const [copied, setCopied] = useState(false);

    const handleCopy = async () => {
        const text = btn.url || btn.text;
        try {
            await navigator.clipboard.writeText(text);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1400);
        } catch {
            /* clipboard unavailable — ignore silently */
        }
    };

    return (
        <button
            type="button"
            className="tg-ikb-btn is-copy"
            onClick={handleCopy}
            title={`Скопировать: ${btn.text}`}
        >
            <span className="tg-ikb-btn-label">{btn.text}</span>
            <span className="tg-ikb-btn-icon" aria-hidden>
                {copied ? <Check size={12} /> : <Copy size={12} />}
            </span>
        </button>
    );
};

const KeyboardButton: React.FC<{
    btn: TgKeyboardButton;
    onOpenWebApp: (btn: TgKeyboardButton) => void;
    onOpenLink: (url: string) => void;
}> = ({ btn, onOpenWebApp, onOpenLink }) => {
    if (btn.type === 'web_app') {
        return (
            <button
                type="button"
                className="tg-ikb-btn is-webapp"
                onClick={() => btn.url && onOpenWebApp(btn)}
                disabled={!btn.url}
                title={`Открыть мини-приложение: ${btn.text}`}
            >
                <span className="tg-ikb-btn-icon" aria-hidden>
                    <AppWindow size={12} />
                </span>
                <span className="tg-ikb-btn-label">{btn.text}</span>
                <span className="tg-ikb-badge" aria-label="Мини-приложение">
                    app
                </span>
            </button>
        );
    }

    if (btn.type === 'url' || btn.type === 'login_url') {
        return (
            <button
                type="button"
                className="tg-ikb-btn is-link"
                onClick={() => btn.url && onOpenLink(btn.url)}
                disabled={!btn.url}
                title={btn.url ? `Открыть ссылку: ${btn.url}` : btn.text}
            >
                <span className="tg-ikb-btn-label">{btn.text}</span>
                <span className="tg-ikb-btn-icon" aria-hidden>
                    <ExternalLink size={12} />
                </span>
            </button>
        );
    }

    if (btn.type === 'copy_text') {
        return <CopyButton btn={btn} />;
    }

    // callback / buy / switch_inline / other → inert (no server round-trip yet).
    return (
        <button
            type="button"
            className="tg-ikb-btn is-inert"
            disabled
            tabIndex={-1}
            aria-disabled
            title="Эта кнопка требует ответа от бота и пока не поддерживается"
        >
            <span className="tg-ikb-btn-label">{btn.text}</span>
        </button>
    );
};

export const InlineKeyboard: React.FC<InlineKeyboardProps> = ({ markup, onOpenWebApp, onOpenLink }) => {
    if (!markup.rows?.length) return null;

    return (
        <div
            className={`tg-ikb${markup.kind === 'keyboard' ? ' is-reply-keyboard' : ''}`}
            role="group"
            aria-label="Кнопки сообщения"
        >
            {markup.rows.map((row, rIdx) => (
                <div className="tg-ikb-row" key={`r-${rIdx}`}>
                    {row.map((btn, bIdx) => (
                        <KeyboardButton
                            key={`b-${rIdx}-${bIdx}`}
                            btn={btn}
                            onOpenWebApp={onOpenWebApp}
                            onOpenLink={onOpenLink}
                        />
                    ))}
                </div>
            ))}
        </div>
    );
};
