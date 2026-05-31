import React from 'react';
import { MessageSquare, EyeOff, CalendarOff, Search } from 'lucide-react';

export type EmptyMode = 'no-chat' | 'no-messages' | 'no-results' | 'period-empty' | 'hidden-empty';

interface EmptyStateProps {
    mode?: EmptyMode;
    query?: string;
}

const COPY: Record<EmptyMode, { title: string; sub: string; Icon: React.ComponentType<any> }> = {
    'no-chat': {
        title: 'Выберите чат',
        sub: 'Нажмите на чат в списке слева, чтобы посмотреть сообщения.',
        Icon: MessageSquare,
    },
    'no-messages': {
        title: 'Сообщений ещё нет',
        sub: 'Напишите первое сообщение в этом чате.',
        Icon: MessageSquare,
    },
    'no-results': {
        title: 'Ничего не найдено',
        sub: 'Попробуйте изменить запрос.',
        Icon: Search,
    },
    'period-empty': {
        title: 'В выбранном периоде сообщений нет',
        sub: 'Расширьте диапазон дат или сбросьте фильтр.',
        Icon: CalendarOff,
    },
    'hidden-empty': {
        title: 'Скрытых чатов нет',
        sub: 'Используйте контекстное меню, чтобы скрыть чат.',
        Icon: EyeOff,
    },
};

export const EmptyState: React.FC<EmptyStateProps> = ({ mode = 'no-chat', query }) => {
    const meta = COPY[mode];
    const Icon = meta.Icon;
    return (
        <div className="tg-stream">
            <div className="tg-stream-empty">
                <div className="tg-stream-empty-icon">
                    <Icon size={24} />
                </div>
                <div className="tg-stream-empty-title">{meta.title}</div>
                <div>{query ? `${meta.sub} «${query}»` : meta.sub}</div>
            </div>
        </div>
    );
};
