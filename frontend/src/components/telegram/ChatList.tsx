import React, { useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Search, MessageSquare } from 'lucide-react';
import { ChatListItem } from './ChatListItem';
import type { TelegramChat } from '../../services/api';

export type ChatFilter = 'all' | 'active' | 'hidden';

interface ChatListProps {
    chats: TelegramChat[];
    activeChatId: number | null;
    onSelect: (chatId: number) => void;
    onContextMenu?: (e: React.MouseEvent, chat: TelegramChat) => void;
    isLoading?: boolean;
    statusLabel?: string;
    statusTone?: 'ready' | 'warning' | 'error' | 'idle';
    filter: ChatFilter;
    onFilterChange: (f: ChatFilter) => void;
}

const STATUS_CLASS: Record<string, string> = {
    ready: 'is-ready',
    warning: 'is-warning',
    error: 'is-error',
    idle: '',
};

const TABS: { key: ChatFilter; label: string }[] = [
    { key: 'active', label: 'Активные' },
    { key: 'all', label: 'Все' },
    { key: 'hidden', label: 'Скрытые' },
];

const STAGGER_LIMIT = 12;

export const ChatList: React.FC<ChatListProps> = ({
    chats,
    activeChatId,
    onSelect,
    onContextMenu,
    isLoading,
    statusLabel,
    statusTone = 'idle',
    filter,
    onFilterChange,
}) => {
    const [query, setQuery] = useState('');

    const counts = useMemo(() => ({
        all: chats.length,
        active: chats.filter((c) => !c.is_hidden).length,
        hidden: chats.filter((c) => c.is_hidden).length,
    }), [chats]);

    const filtered = useMemo(() => {
        let list = chats;
        if (filter === 'active') list = list.filter((c) => !c.is_hidden);
        else if (filter === 'hidden') list = list.filter((c) => c.is_hidden);

        const q = query.trim().toLowerCase();
        if (q) {
            list = list.filter((c) =>
                c.title.toLowerCase().includes(q) ||
                (c.username || '').toLowerCase().includes(q)
            );
        }
        return list;
    }, [chats, query, filter]);

    return (
        <aside className="tg-list-pane" aria-label="Список чатов">
            <div className="tg-list-head">
                <div className="tg-list-head-row">
                    <h2 className="tg-list-title">Чаты</h2>
                    {statusLabel ? (
                        <span className={`tg-status-pill ${STATUS_CLASS[statusTone] || ''}`}>
                            <span className="tg-status-dot" />
                            {statusLabel}
                        </span>
                    ) : null}
                </div>

                <div className="tg-search">
                    <Search size={14} className="tg-search-icon" aria-hidden />
                    <input
                        type="search"
                        className="tg-search-input"
                        placeholder="Поиск по чатам..."
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        aria-label="Поиск чатов"
                    />
                </div>

                <div className="tg-tabs" role="tablist" aria-label="Фильтр чатов">
                    {TABS.map(({ key, label }) => {
                        const count = counts[key];
                        const active = filter === key;
                        return (
                            <button
                                key={key}
                                type="button"
                                role="tab"
                                aria-selected={active}
                                className={`tg-tab${active ? ' is-active' : ''}`}
                                onClick={() => onFilterChange(key)}
                            >
                                {active ? (
                                    <motion.span
                                        layoutId="tg-tab-pill"
                                        className="tg-tab-pill"
                                        transition={{ type: 'spring', stiffness: 380, damping: 32 }}
                                    />
                                ) : null}
                                <span style={{ position: 'relative', zIndex: 1 }}>{label}</span>
                                {count > 0 ? (
                                    <span className="tg-tab-count" style={{ position: 'relative', zIndex: 1 }}>
                                        {count}
                                    </span>
                                ) : null}
                            </button>
                        );
                    })}
                </div>
            </div>

            <div className="tg-list">
                {isLoading ? (
                    <div className="tg-list-empty">
                        <div className="tg-list-empty-title">Загружаем чаты…</div>
                    </div>
                ) : filtered.length === 0 ? (
                    <div className="tg-list-empty">
                        {query ? (
                            <>
                                <div className="tg-list-empty-title">Ничего не найдено</div>
                                <div>Попробуйте другой запрос.</div>
                            </>
                        ) : filter === 'hidden' ? (
                            <>
                                <div className="tg-list-empty-title">Скрытых чатов нет</div>
                                <div>Используйте контекстное меню, чтобы скрыть чат.</div>
                            </>
                        ) : (
                            <>
                                <MessageSquare size={28} style={{ opacity: 0.4, marginBottom: 8 }} />
                                <div className="tg-list-empty-title">Чатов нет</div>
                                <div>Подождите, идёт загрузка из Telegram.</div>
                            </>
                        )}
                    </div>
                ) : (
                    <AnimatePresence initial={false}>
                        {filtered.map((c, idx) => (
                            <motion.div
                                key={c.chat_id}
                                layout="position"
                                initial={{ opacity: 0, y: 6 }}
                                animate={{
                                    opacity: 1,
                                    y: 0,
                                    transition: {
                                        duration: 0.28,
                                        ease: [0.16, 1, 0.3, 1],
                                        delay: idx < STAGGER_LIMIT ? idx * 0.024 : 0,
                                    },
                                }}
                                exit={{ opacity: 0, transition: { duration: 0.12 } }}
                            >
                                <ChatListItem
                                    chat={c}
                                    active={c.chat_id === activeChatId}
                                    onSelect={onSelect}
                                    onContextMenu={onContextMenu}
                                    showLagBadge={filter === 'hidden' || filter === 'all' ? Boolean(c.is_hidden) : false}
                                />
                            </motion.div>
                        ))}
                    </AnimatePresence>
                )}
            </div>
        </aside>
    );
};
