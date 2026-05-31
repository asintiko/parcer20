import React, { useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Calendar, X, ArrowLeft, Eye, EyeOff, Bot, Users, User as UserIcon, Megaphone, CheckSquare, Lock } from 'lucide-react';
import { Avatar } from './Avatar';
import { PeriodPicker, formatRangeLabel } from './PeriodPicker';
import type { TelegramChat } from '../../services/api';

export interface DateRange {
    from?: string;
    to?: string;
}

interface ChatHeaderProps {
    chat: TelegramChat;
    onBack?: () => void;
    onToggleMonitor?: (chatId: number, on: boolean) => void;
    onToggleSelection?: () => void;
    selectionMode?: boolean;
    dateRange?: DateRange;
    onDateRangeChange?: (range: DateRange) => void;
}

const typeLabel = (type: string, memberCount?: number): string => {
    switch (type) {
        case 'bot':
            return 'бот';
        case 'user':
            return 'пользователь';
        case 'channel':
            return memberCount ? `канал · ${memberCount} подписчиков` : 'канал';
        case 'group':
        case 'supergroup':
            return memberCount ? `группа · ${memberCount} участников` : 'группа';
        default:
            return type;
    }
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

export const ChatHeader: React.FC<ChatHeaderProps> = ({
    chat,
    onBack,
    onToggleMonitor,
    onToggleSelection,
    selectionMode,
    dateRange,
    onDateRangeChange,
}) => {
    const TypeIcon = typeIconFor(chat.chat_type);
    const monitorOn = chat.monitor_enabled;
    const dateBtnRef = useRef<HTMLButtonElement>(null);
    const [dateOpen, setDateOpen] = useState(false);

    const range = dateRange || {};
    const hasFilter = Boolean(range.from || range.to);
    const rangeLabel = hasFilter ? formatRangeLabel(range) : '';

    return (
        <div className="tg-header">
            {onBack ? (
                <button
                    type="button"
                    className="tg-header-back"
                    onClick={onBack}
                    aria-label="Назад к списку чатов"
                >
                    <ArrowLeft size={18} />
                </button>
            ) : null}

            <AnimatePresence mode="wait" initial={false}>
                <motion.div
                    key={chat.chat_id}
                    style={{ display: 'contents' }}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1, transition: { duration: 0.2, ease: [0.16, 1, 0.3, 1] } }}
                    exit={{ opacity: 0, transition: { duration: 0.12 } }}
                >
                    <Avatar name={chat.title} seed={chat.chat_id} size={32} />

                    <div className="tg-header-meta">
                        <div className="tg-header-title">
                            {chat.title}
                            {chat.is_protected ? (
                                <Lock size={11} aria-label="Защищено паролем" style={{ marginLeft: 6, verticalAlign: '-1px', color: 'var(--text-muted)' }} />
                            ) : null}
                        </div>
                        <div className="tg-header-sub">
                            {TypeIcon ? <TypeIcon size={10} style={{ marginRight: 4, verticalAlign: '-1px' }} /> : null}
                            {typeLabel(chat.chat_type, chat.member_count)}
                            {chat.username ? ` · @${chat.username}` : ''}
                        </div>
                    </div>
                </motion.div>
            </AnimatePresence>

            <div className="tg-header-actions">
                {onDateRangeChange ? (
                    <>
                        <button
                            type="button"
                            ref={dateBtnRef}
                            className={`tg-header-period${hasFilter ? ' is-active' : ''}`}
                            onClick={() => setDateOpen((v) => !v)}
                            aria-label={hasFilter ? `Период: ${rangeLabel}` : 'Фильтр по дате'}
                            aria-expanded={dateOpen}
                            title={hasFilter ? `Период: ${rangeLabel}` : 'Фильтр по дате'}
                        >
                            <Calendar size={14} />
                            {hasFilter ? <span className="tg-header-period-label">{rangeLabel}</span> : null}
                        </button>
                        {hasFilter ? (
                            <button
                                type="button"
                                className="tg-header-btn"
                                onClick={() => onDateRangeChange({})}
                                aria-label="Сбросить период"
                                title="Сбросить период"
                            >
                                <X size={14} />
                            </button>
                        ) : null}
                        <PeriodPicker
                            open={dateOpen}
                            anchorRef={dateBtnRef}
                            range={range}
                            onChange={onDateRangeChange}
                            onClose={() => setDateOpen(false)}
                        />
                    </>
                ) : null}

                {onToggleSelection ? (
                    <button
                        type="button"
                        className={`tg-header-btn${selectionMode ? ' is-active' : ''}`}
                        onClick={onToggleSelection}
                        aria-label={selectionMode ? 'Выйти из режима выбора' : 'Выбрать сообщения'}
                        title={selectionMode ? 'Выйти из режима выбора' : 'Выбрать несколько'}
                    >
                        <AnimatePresence mode="wait" initial={false}>
                            <motion.span
                                key={selectionMode ? 'x' : 'sel'}
                                initial={{ opacity: 0, rotate: -20, scale: 0.8 }}
                                animate={{ opacity: 1, rotate: 0, scale: 1 }}
                                exit={{ opacity: 0, rotate: 20, scale: 0.8 }}
                                transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
                                style={{ display: 'inline-flex' }}
                            >
                                {selectionMode ? <X size={16} /> : <CheckSquare size={16} />}
                            </motion.span>
                        </AnimatePresence>
                    </button>
                ) : null}

                {onToggleMonitor ? (
                    <button
                        type="button"
                        className={`tg-header-btn${monitorOn ? ' is-active' : ''}`}
                        onClick={() => onToggleMonitor(chat.chat_id, !monitorOn)}
                        aria-label={monitorOn ? 'Выключить мониторинг' : 'Включить мониторинг'}
                        title={monitorOn ? 'Мониторинг включён' : 'Мониторинг выключен'}
                    >
                        <AnimatePresence mode="wait" initial={false}>
                            <motion.span
                                key={monitorOn ? 'on' : 'off'}
                                initial={{ opacity: 0, scale: 0.7 }}
                                animate={{ opacity: 1, scale: 1 }}
                                exit={{ opacity: 0, scale: 0.7 }}
                                transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
                                style={{ display: 'inline-flex' }}
                            >
                                {monitorOn ? <Eye size={16} /> : <EyeOff size={16} />}
                            </motion.span>
                        </AnimatePresence>
                    </button>
                ) : null}
            </div>
        </div>
    );
};
