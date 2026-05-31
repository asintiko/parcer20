// Seed data for the design sandbox. No real backend.
import type {
    Transaction,
    UserInfo,
    OperatorReference,
} from './api';

export const MOCK_USER: UserInfo = {
    id: 1,
    username: 'admin',
    display_name: 'Дизайнер',
    role: 'admin',
    allowed_tabs: ['dashboard', 'reference', 'userbot', 'logs', 'admin'],
    allowed_folders: [],
    forbidden_periods: [],
    allowed_sources: [],
    can_toggle_sources: true,
    permissions_version: 1,
    totp_enabled: false,
    totp_confirmed_at: null,
    force_2fa: false,
    session_ttl_days: 30,
    exp: null,
};

const operators = [
    { raw: 'CLICK*PAY UZ', app: 'Click', is_p2p: false },
    { raw: 'PAYME UZ', app: 'Payme', is_p2p: false },
    { raw: 'UZUM PAY', app: 'Uzum Pay', is_p2p: false },
    { raw: 'HUMO TRANSFER', app: 'Humo', is_p2p: true },
    { raw: 'VISA RETAIL', app: 'Visa Retail', is_p2p: false },
    { raw: 'KOROBKA TASHKENT', app: 'Korzinka', is_p2p: false },
    { raw: 'HAVAS UZ', app: 'Havas', is_p2p: false },
    { raw: 'YANDEX GO', app: 'Yandex Go', is_p2p: false },
    { raw: 'WOLT MARKET', app: 'Wolt', is_p2p: false },
    { raw: 'EVOS DELIVERY', app: 'Evos', is_p2p: false },
    { raw: 'MAKRO MARKET', app: 'Makro', is_p2p: false },
    { raw: 'BEELINE TOPUP', app: 'Beeline', is_p2p: false },
];

const cards = ['4242', '8801', '1149', '5677'];
const types: Array<Transaction['transaction_type']> = ['DEBIT', 'CREDIT', 'CONVERSION', 'REVERSAL'];

const seededRandom = (seed: number) => {
    let value = seed;
    return () => {
        value = (value * 1664525 + 1013904223) % 0xffffffff;
        return value / 0xffffffff;
    };
};

const rand = seededRandom(42);

const buildTransactions = (count: number): Transaction[] => {
    const items: Transaction[] = [];
    const now = Date.now();
    for (let i = 0; i < count; i += 1) {
        const op = operators[Math.floor(rand() * operators.length)];
        const card = cards[Math.floor(rand() * cards.length)];
        const type = types[Math.floor(rand() * 2)]; // Bias towards DEBIT/CREDIT
        const isUsd = rand() < 0.07;
        const baseAmount = isUsd
            ? Math.round(rand() * 50000) / 100
            : Math.round(rand() * 1500000);
        const amount = String(baseAmount);
        const balance = String(Math.max(0, Math.round(rand() * 8000000)));
        const date = new Date(now - i * 1000 * 60 * 47 - Math.floor(rand() * 86400000));
        items.push({
            id: 1000 + i,
            transaction_date: date.toISOString().slice(0, 19),
            amount,
            currency: isUsd ? 'USD' : 'UZS',
            card_last_4: card,
            operator_raw: op.raw,
            application_mapped: op.app,
            transaction_type: type,
            transaction_type_display: type === 'DEBIT' ? 'Списание' : type === 'CREDIT' ? 'Зачисление' : type,
            balance_after: balance,
            receiver_name: op.is_p2p ? 'Иван П.' : null,
            receiver_card: op.is_p2p ? '8600****1149' : null,
            source_type: rand() < 0.7 ? 'AUTO' : 'MANUAL',
            source_channel: rand() < 0.8 ? 'TELEGRAM' : 'MANUAL',
            source_display: rand() < 0.8 ? 'Telegram bot' : 'Ручной ввод',
            source_chat_id: rand() < 0.8 ? -1001234567890 : null,
            source_chat_title: rand() < 0.8 ? 'Bank Notifications' : null,
            source_origin_type: 'bot',
            parsing_method: rand() < 0.6 ? 'regex' : 'gpt',
            parsing_confidence: Math.round(rand() * 100) / 100,
            is_p2p: op.is_p2p,
            created_at: date.toISOString(),
            raw_message: `Покупка ${amount} ${isUsd ? 'USD' : 'UZS'} в ${op.raw}, карта *${card}`,
        });
    }
    return items.sort((a, b) => b.transaction_date.localeCompare(a.transaction_date));
};

export const MOCK_TRANSACTIONS: Transaction[] = buildTransactions(120);

export const MOCK_OPERATORS: OperatorReference[] = operators.map((op, idx) => ({
    id: idx + 1,
    operator_name: op.raw,
    application_name: op.app,
    is_p2p: op.is_p2p,
    is_active: true,
}));

export const MOCK_APPLICATIONS = Array.from(new Set(operators.map((o) => o.app))).sort();

export const MOCK_CHAT_TITLES = Array.from(
    new Set(MOCK_TRANSACTIONS.map((t) => t.source_chat_title).filter(Boolean) as string[])
);
