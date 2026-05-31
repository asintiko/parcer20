// Mock data for Telegram-client (design sandbox).

import type { TelegramChat, TelegramChatMessage } from './api';

const hoursAgo = (h: number) => new Date(Date.now() - h * 3600 * 1000).toISOString();
const daysAgo = (d: number) => new Date(Date.now() - d * 24 * 3600 * 1000).toISOString();

export const TG_MOCK_CHATS: TelegramChat[] = [
    {
        chat_id: -1001234567890,
        title: 'Сбербанк уведомления',
        chat_type: 'bot',
        is_hidden: false,
        is_protected: false,
        is_monitored: true,
        monitor_enabled: true,
        last_message: { id: 1024, date: hoursAgo(0.2), text: 'Покупка на 1 540 ₽ — Магнит', is_outgoing: false },
        latest_message_id: 1024,
        latest_message_date: hoursAgo(0.2),
        backlog_lag_messages: 3,
        backlog_state: 'lagging',
    },
    {
        chat_id: -1009876543210,
        title: 'Тинькофф · алерты',
        chat_type: 'channel',
        is_hidden: false,
        is_protected: false,
        is_monitored: false,
        monitor_enabled: false,
        last_message: { id: 712, date: hoursAgo(2), text: 'Поступление 50 000 ₽ от Иван И.', is_outgoing: false },
        latest_message_id: 712,
        latest_message_date: hoursAgo(2),
        backlog_lag_messages: 0,
        backlog_state: 'healthy',
    },
    {
        chat_id: -200110011001,
        title: 'Бухгалтерия',
        chat_type: 'group',
        member_count: 6,
        is_hidden: false,
        is_protected: false,
        is_monitored: true,
        monitor_enabled: true,
        last_message: { id: 412, date: hoursAgo(5), text: 'Отправил отчёт за месяц.', is_outgoing: false },
        latest_message_id: 412,
        latest_message_date: hoursAgo(5),
        backlog_lag_messages: 0,
        backlog_state: 'healthy',
    },
    {
        chat_id: 880088,
        title: 'Андрей Бачинин',
        chat_type: 'user',
        username: 'andrey_b',
        is_hidden: false,
        is_protected: false,
        is_monitored: false,
        monitor_enabled: false,
        last_message: { id: 88, date: daysAgo(1), text: '👌', is_outgoing: true },
        latest_message_id: 88,
        latest_message_date: daysAgo(1),
        backlog_lag_messages: 0,
        backlog_state: 'healthy',
    },
    {
        chat_id: -200120012001,
        title: 'Маркетплейс · отгрузки',
        chat_type: 'supergroup',
        member_count: 124,
        is_hidden: false,
        is_protected: true,
        is_monitored: true,
        monitor_enabled: true,
        last_message: { id: 9001, date: daysAgo(2), text: 'Отгрузка по заказу #4521 готова.', is_outgoing: false },
        latest_message_id: 9001,
        latest_message_date: daysAgo(2),
        backlog_lag_messages: 12,
        backlog_state: 'lagging',
    },
    {
        chat_id: -200130013001,
        title: 'Поставщики · накладные',
        chat_type: 'group',
        member_count: 4,
        is_hidden: true,
        is_protected: false,
        is_monitored: false,
        monitor_enabled: false,
        last_message: { id: 3, date: daysAgo(3), text: 'Скан накладной во вложении.', is_outgoing: false },
        latest_message_id: 3,
        latest_message_date: daysAgo(3),
        backlog_lag_messages: 0,
        backlog_state: 'healthy',
    },
    {
        chat_id: 770077,
        title: 'Личное · Заметки',
        chat_type: 'user',
        username: 'me_notes',
        is_hidden: true,
        is_protected: false,
        is_monitored: false,
        monitor_enabled: false,
        last_message: { id: 5, date: daysAgo(7), text: 'Не забыть оплатить аренду', is_outgoing: true },
        latest_message_id: 5,
        latest_message_date: daysAgo(7),
        backlog_lag_messages: 0,
        backlog_state: 'healthy',
    },
    {
        chat_id: -200140014001,
        title: 'Devops · prod-alerts',
        chat_type: 'channel',
        member_count: 12,
        is_hidden: false,
        is_protected: false,
        is_monitored: true,
        monitor_enabled: true,
        last_message: { id: 1500, date: daysAgo(0.5), text: '🟢 prod-api · 200 OK · uptime 99.98%', is_outgoing: false },
        latest_message_id: 1500,
        latest_message_date: daysAgo(0.5),
        backlog_lag_messages: 0,
        backlog_state: 'healthy',
    },
];

const sampleReceiptUrl = 'https://images.unsplash.com/photo-1554224155-8d04cb21cd6c?w=600&q=80';
const sampleReceiptUrl2 = 'https://images.unsplash.com/photo-1567427018369-58fe9eee3ea3?w=600&q=80';

export const TG_MOCK_MESSAGES: Record<number, TelegramChatMessage[]> = {
    [-1001234567890]: [
        { id: 1001, date: daysAgo(2), is_outgoing: false, text: 'Здравствуйте! Это бот «Сбербанк уведомления». Я буду отправлять вам сводки по транзакциям.' },
        { id: 1002, date: daysAgo(2), is_outgoing: true, text: 'Привет, давай настроим' },
        { id: 1003, date: daysAgo(1), is_outgoing: false, text: '💳 Покупка\nКарта *4567\nСумма: 2 350,00 ₽\nМесто: Пятёрочка' },
        { id: 1004, date: daysAgo(1), is_outgoing: false, text: '💸 Перевод\nКарта *4567\nСумма: 5 000,00 ₽\nКому: Иван И.' },
        { id: 1005, date: hoursAgo(8), is_outgoing: false, text: '💳 Покупка\nКарта *4567\nСумма: 18 900,00 ₽\nМесто: M.Видео', photo: { file_id: 1, file_name: 'receipt-1.png', mime_type: 'image/png', size: 245000, download_url: sampleReceiptUrl, width: 600, height: 800 } },
        { id: 1006, date: hoursAgo(7), is_outgoing: true, text: 'Получил, обрабатываю' },
        { id: 1007, date: hoursAgo(3), is_outgoing: false, text: '💳 Покупка\nКарта *4567\nСумма: 540,00 ₽\nМесто: Кофейня Smile' },
        { id: 1008, date: hoursAgo(2), is_outgoing: false, text: 'Месячная выписка во вложении.', document: { file_id: 100, file_name: 'statement-march.pdf', mime_type: 'application/pdf', size: 152340, download_url: '#' } },
        { id: 1009, date: hoursAgo(0.5), is_outgoing: false, text: '💳 Покупка\nКарта *4567\nСумма: 1 540,00 ₽\nМесто: Магнит' },
        { id: 1024, date: hoursAgo(0.2), is_outgoing: false, text: 'Покупка на 1 540 ₽ — Магнит' },
    ],
    [-1009876543210]: [
        { id: 700, date: daysAgo(1), is_outgoing: false, text: '📊 Дневной отчёт\nТранзакций: 12\nОборот: 124 500 ₽' },
        { id: 701, date: daysAgo(0.5), is_outgoing: false, text: '⚠️ Подозрительная операция\nКарта *9821, 8 200 ₽, г. Стамбул', photo: { file_id: 2, file_name: 'alert.png', mime_type: 'image/png', size: 180000, download_url: sampleReceiptUrl2 } },
        { id: 712, date: hoursAgo(2), is_outgoing: false, text: 'Поступление 50 000 ₽ от Иван И.' },
    ],
    [-200110011001]: [
        { id: 400, date: daysAgo(3), is_outgoing: false, text: 'Готовлю отчёт за прошлый месяц.' },
        { id: 401, date: daysAgo(3), is_outgoing: true, text: 'Окей, жду' },
        { id: 402, date: daysAgo(1), is_outgoing: false, text: 'Согласовали с финдиректором, можем закрывать?' },
        { id: 403, date: hoursAgo(8), is_outgoing: true, text: 'Да, закрывайте' },
        { id: 404, date: hoursAgo(6), is_outgoing: false, text: 'Загрузил все накладные.', document: { file_id: 11, file_name: 'invoices-2024-03.zip', mime_type: 'application/zip', size: 8900000, download_url: '#' } },
        { id: 412, date: hoursAgo(5), is_outgoing: false, text: 'Отправил отчёт за месяц.' },
    ],
    [880088]: [
        { id: 80, date: daysAgo(2), is_outgoing: false, text: 'Привет!' },
        { id: 81, date: daysAgo(2), is_outgoing: true, text: 'Привет, как дела?' },
        { id: 82, date: daysAgo(1.9), is_outgoing: false, text: 'Норм. Скинь, плиз, отчёт по бухгалтерии.' },
        { id: 83, date: daysAgo(1.5), is_outgoing: true, text: 'Сейчас, минутку', document: { file_id: 22, file_name: 'отчёт.pdf', mime_type: 'application/pdf', size: 320000, download_url: '#' } },
        { id: 84, date: daysAgo(1.4), is_outgoing: false, text: 'Получил, спасибо!' },
        { id: 85, date: daysAgo(1.3), is_outgoing: false, text: 'А ещё за прошлый период есть?' },
        { id: 86, date: daysAgo(1.2), is_outgoing: true, text: 'Завтра скину' },
        { id: 87, date: daysAgo(1.1), is_outgoing: false, text: 'Окей' },
        { id: 88, date: daysAgo(1), is_outgoing: true, text: '👌' },
    ],
    [-200120012001]: [
        { id: 8990, date: daysAgo(3), is_outgoing: false, text: 'Заказ #4521 принят в работу. Ожидаем оплату.' },
        { id: 8991, date: daysAgo(3), is_outgoing: false, text: 'Поступила оплата 145 000 ₽. Отгружаем.' },
        { id: 9001, date: daysAgo(2), is_outgoing: false, text: 'Отгрузка по заказу #4521 готова.' },
    ],
    [-200130013001]: [
        { id: 1, date: daysAgo(5), is_outgoing: false, text: 'Поставщик ИП Иванов — счёт за март.', document: { file_id: 50, file_name: 'invoice-march-2024.pdf', mime_type: 'application/pdf', size: 80000, download_url: '#' } },
        { id: 2, date: daysAgo(4), is_outgoing: true, text: 'Принято' },
        { id: 3, date: daysAgo(3), is_outgoing: false, text: 'Скан накладной во вложении.', photo: { file_id: 60, file_name: 'nakladnaya.jpg', mime_type: 'image/jpeg', size: 220000, download_url: sampleReceiptUrl } },
    ],
    [770077]: [
        { id: 1, date: daysAgo(15), is_outgoing: true, text: 'Список дел на неделю:\n1) Договор\n2) Аренда\n3) Налоги' },
        { id: 2, date: daysAgo(10), is_outgoing: true, text: 'Договор подписан' },
        { id: 5, date: daysAgo(7), is_outgoing: true, text: 'Не забыть оплатить аренду' },
    ],
    [-200140014001]: [
        { id: 1490, date: daysAgo(2), is_outgoing: false, text: '🔴 prod-api · 503 · 5 minutes' },
        { id: 1491, date: daysAgo(2), is_outgoing: false, text: '🟡 prod-api · degraded · investigating' },
        { id: 1492, date: daysAgo(1), is_outgoing: false, text: '🟢 prod-api · 200 OK · resolved' },
        { id: 1500, date: daysAgo(0.5), is_outgoing: false, text: '🟢 prod-api · 200 OK · uptime 99.98%' },
    ],
};

// ─── Push emulation ───────────────────────────────────────────────────────────

let pushSequence = 100_000;

const PUSH_TEMPLATES_BY_TYPE: Record<string, Array<() => Partial<TelegramChatMessage>>> = {
    bot: [
        () => ({ text: `💳 Покупка\nКарта *4567\nСумма: ${(Math.random() * 9000 + 100).toFixed(0)} ₽\nМесто: ${pickOne(['Магнит', 'Пятёрочка', 'Лента', 'Кофейня Smile', 'Wildberries'])}` }),
        () => ({ text: `💸 Перевод\nКарта *4567\nСумма: ${(Math.random() * 50000 + 500).toFixed(0)} ₽\nКому: ${pickOne(['Иван И.', 'Мария Л.', 'Артур К.'])}` }),
        () => ({ text: '📊 Дневная сводка готова', document: { file_id: pushSequence, file_name: 'daily.pdf', mime_type: 'application/pdf', size: 92340 } }),
    ],
    channel: [
        () => ({ text: `📈 ${pickOne(['Курс USD', 'Курс EUR', 'Сводка по картам'])}: ${(Math.random() * 100 + 80).toFixed(2)}` }),
        () => ({ text: `🟢 prod-api · 200 OK · uptime ${(99.8 + Math.random() * 0.2).toFixed(2)}%` }),
    ],
    group: [
        () => ({ text: pickOne(['Подписали договор.', 'Закрыли месяц.', 'Согласовали бюджет.', 'Отправил счета на проверку.']) }),
        () => ({ text: 'Скан во вложении.', photo: { file_id: pushSequence, file_name: 'scan.jpg', mime_type: 'image/jpeg', size: 180000 } }),
    ],
    supergroup: [
        () => ({ text: `Заказ #${Math.floor(Math.random() * 9000 + 1000)} принят в работу.` }),
        () => ({ text: `Поступила оплата ${(Math.random() * 200000 + 10000).toFixed(0)} ₽.` }),
    ],
    user: [
        () => ({ text: pickOne(['Привет!', 'Готов?', 'Скинь, пожалуйста, отчёт.', 'Спасибо!', 'Окей, договорились.']) }),
    ],
};

function pickOne<T>(values: T[]): T {
    return values[Math.floor(Math.random() * values.length)];
}

export function pushMessageToChat(chatId: number, partial: Partial<TelegramChatMessage> = {}): TelegramChatMessage {
    pushSequence += 1;
    const id = pushSequence;
    const date = new Date().toISOString();
    const message: TelegramChatMessage = {
        date,
        is_outgoing: false,
        text: partial.text ?? '',
        photo: partial.photo ?? null,
        document: partial.document ?? null,
        ...partial,
        id,
    };

    if (!TG_MOCK_MESSAGES[chatId]) {
        TG_MOCK_MESSAGES[chatId] = [];
    }
    TG_MOCK_MESSAGES[chatId].push(message);

    const chatIdx = TG_MOCK_CHATS.findIndex((c) => c.chat_id === chatId);
    if (chatIdx >= 0) {
        const chat = TG_MOCK_CHATS[chatIdx];
        chat.last_message = {
            id,
            date,
            is_outgoing: Boolean(message.is_outgoing),
            text: message.text || (message.photo ? '📷 Фото' : message.document ? `📎 ${message.document.file_name || 'Документ'}` : ''),
        };
        chat.latest_message_id = id;
        chat.latest_message_date = date;
        if (chat.monitor_enabled) {
            chat.backlog_lag_messages = (chat.backlog_lag_messages || 0) + 1;
            chat.backlog_state = 'lagging';
        }
    }

    return message;
}

export function synthesizeIncomingMessage(chat: TelegramChat): Partial<TelegramChatMessage> {
    const templates = PUSH_TEMPLATES_BY_TYPE[chat.chat_type] || PUSH_TEMPLATES_BY_TYPE.user;
    const factory = templates[Math.floor(Math.random() * templates.length)];
    const partial = factory();
    return {
        date: new Date().toISOString(),
        is_outgoing: false,
        ...partial,
    };
}

export interface PushLoopOptions {
    intervalMs?: number;
    jitterMs?: number;
    onPush?: (chatId: number, message: TelegramChatMessage) => void;
}

let activePushTimer: ReturnType<typeof setTimeout> | null = null;

export function startMockPushLoop(options: PushLoopOptions = {}): () => void {
    if (activePushTimer) {
        return stopMockPushLoop;
    }
    const { intervalMs = 9000, jitterMs = 6000, onPush } = options;

    const tick = () => {
        const eligible = TG_MOCK_CHATS.filter((c) => Boolean(c.latest_message_id));
        if (eligible.length > 0) {
            // Bias towards bot/channel for receipt-like demos.
            const weighted: TelegramChat[] = [];
            eligible.forEach((c) => {
                const weight = c.chat_type === 'bot' ? 4 : c.chat_type === 'channel' ? 2 : 1;
                for (let i = 0; i < weight; i += 1) weighted.push(c);
            });
            const target = pickOne(weighted);
            const partial = synthesizeIncomingMessage(target);
            const message = pushMessageToChat(target.chat_id, partial);
            onPush?.(target.chat_id, message);
        }
        const next = intervalMs + Math.floor(Math.random() * jitterMs);
        activePushTimer = setTimeout(tick, next);
    };

    activePushTimer = setTimeout(tick, intervalMs);
    return stopMockPushLoop;
}

export function stopMockPushLoop(): void {
    if (activePushTimer) {
        clearTimeout(activePushTimer);
        activePushTimer = null;
    }
}
