import React from 'react';
import { motion } from 'motion/react';
import { Bot, Users, User as UserIcon, Megaphone, EyeOff, Lock, Radio } from 'lucide-react';
import { Avatar } from './Avatar';
import type { TelegramChat } from '../../services/api';

interface ChatListItemProps {
    chat: TelegramChat;
    active: boolean;
    onSelect: (chatId: number) => void;
    onContextMenu?: (e: React.MouseEvent, chat: TelegramChat) => void;
    /** Показывать badge `backlog_lag_messages`. По умолчанию — только для скрытых чатов. */
    showLagBadge?: boolean;
}

const formatTime = (iso?: string | null): string => {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    if (isToday) {
        return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    }
    const diffMs = now.getTime() - d.getTime();
    const days = diffMs / (1000 * 60 * 60 * 24);
    if (days < 7) {
        return d.toLocaleDateString('ru-RU', { weekday: 'short' });
    }
    return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' });
};

const previewOf = (chat: TelegramChat): string => {
    const m = chat.last_message;
    if (!m) return '';
    if (m.text) return m.text;
    if (m.photo) return '📷 Фото';
    if (m.document) return `📎 ${m.document.file_name || 'Документ'}`;
    return '';
};

const typeIconFor = (type: string) => {
    switch (type) {
        case 'bot':
            return Bot;
        case 'user':
            return UserIcon;
        case 'channel':
            return Megaphone;
        case 'group':
        case 'supergroup':
            return Users;
        default:
            return null;
    }
};

export const ChatListItem: React.FC<ChatListItemProps> = ({ chat, active, onSelect, onContextMenu, showLagBadge }) => {
    const TypeIcon = typeIconFor(chat.chat_type);
    const lag = chat.backlog_lag_messages || 0;
    const time = formatTime(chat.last_message?.date || chat.latest_message_date);
    const preview = previewOf(chat);
    const badgeVisible = lag > 0 && (showLagBadge ?? Boolean(chat.is_hidden));

    return (
        <button
            type="button"
            className={[
                'tg-chat-item',
                active ? 'is-active' : '',
                chat.is_hidden ? 'is-hidden' : '',
            ].filter(Boolean).join(' ')}
            onClick={() => onSelect(chat.chat_id)}
            onContextMenu={(e) => {
                if (onContextMenu) {
                    onContextMenu(e, chat);
                }
            }}
            aria-current={active ? 'true' : undefined}
        >
            {active ? (
                <motion.span
                    layoutId="tg-chat-active-bar"
                    className="tg-chat-item-bar"
                    transition={{ type: 'spring', stiffness: 420, damping: 36 }}
                />
            ) : null}
            <Avatar name={chat.title} seed={chat.chat_id} />
            <div className="tg-chat-meta">
                <div className="tg-chat-meta-row">
                    {TypeIcon ? <TypeIcon size={11} className="tg-chat-type-icon" /> : null}
                    <span className="tg-chat-title">{chat.title}</span>
                    {chat.is_hidden ? <EyeOff size={11} className="tg-chat-type-icon" aria-label="Скрытый чат" /> : null}
                    {chat.is_protected ? <Lock size={11} className="tg-chat-type-icon" aria-label="Защищён паролем" /> : null}
                    {chat.is_monitored ? (
                        <Radio
                            size={11}
                            className={`tg-chat-type-icon tg-chat-monitor-icon${chat.monitor_enabled ? ' is-active' : ' is-paused'}`}
                            aria-label={chat.monitor_enabled ? 'Чат в мониторинге' : 'Мониторинг приостановлен'}
                        />
                    ) : null}
                    {time ? <span className="tg-chat-time">{time}</span> : null}
                </div>
                <div className="tg-chat-preview-row">
                    <span className="tg-chat-preview">{preview || ' '}</span>
                    {badgeVisible ? (
                        <span className="tg-chat-badge">{lag > 99 ? '99+' : lag}</span>
                    ) : null}
                </div>
            </div>
        </button>
    );
};
