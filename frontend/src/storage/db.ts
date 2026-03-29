import Dexie, { Table } from 'dexie';
import { Transaction } from '../services/api';

const DB_ENCRYPTION_PREFIX = 'enc:v1:';
const DB_ENCRYPTION_KEY = String((import.meta as any)?.env?.VITE_DB_ENCRYPTION_KEY || 'tbsparcer-db-default-key');
const DB_ENCRYPTED_TABLES = [
    'transactions',
    'operatorMappings',
    'operatorReferences',
    'monitoredBotChats',
    'hiddenBotChats',
    'parsingLogs',
    'hourlyReports',
    'accessScopes',
    'receiptProcessingTasks',
    'lockedPeriods',
] as const;
const DB_PLAIN_FIELDS = new Set(['id', 'chat_id', 'table_name', 'key']);

const textEncoder = new TextEncoder();
const textDecoder = new TextDecoder();
const keyBytes = textEncoder.encode(DB_ENCRYPTION_KEY);

const toBase64 = (bytes: Uint8Array): string => {
    let binary = '';
    bytes.forEach((b) => {
        binary += String.fromCharCode(b);
    });
    return btoa(binary);
};

const fromBase64 = (encoded: string): Uint8Array => {
    const binary = atob(encoded);
    const out = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
        out[i] = binary.charCodeAt(i);
    }
    return out;
};

const xorBytes = (input: Uint8Array): Uint8Array => {
    if (!input.length || !keyBytes.length) return input;
    const out = new Uint8Array(input.length);
    for (let i = 0; i < input.length; i += 1) {
        out[i] = input[i] ^ keyBytes[i % keyBytes.length];
    }
    return out;
};

const encryptValue = (value: any): any => {
    if (value === undefined || value === null) return value;
    if (typeof value === 'string' && value.startsWith(DB_ENCRYPTION_PREFIX)) {
        return value;
    }
    try {
        const plain = JSON.stringify(value);
        const cipher = xorBytes(textEncoder.encode(plain));
        return `${DB_ENCRYPTION_PREFIX}${toBase64(cipher)}`;
    } catch {
        return value;
    }
};

const decryptValue = (value: any): any => {
    if (typeof value !== 'string' || !value.startsWith(DB_ENCRYPTION_PREFIX)) {
        return value;
    }
    try {
        const encoded = value.slice(DB_ENCRYPTION_PREFIX.length);
        const plainBytes = xorBytes(fromBase64(encoded));
        const plain = textDecoder.decode(plainBytes);
        return JSON.parse(plain);
    } catch {
        return value;
    }
};

const encryptObject = <T extends Record<string, any>>(row: T): T => {
    const next: Record<string, any> = { ...row };
    Object.keys(next).forEach((field) => {
        if (DB_PLAIN_FIELDS.has(field)) return;
        next[field] = encryptValue(next[field]);
    });
    return next as T;
};

const decryptObject = <T extends Record<string, any>>(row: T): T => {
    const next: Record<string, any> = { ...row };
    Object.keys(next).forEach((field) => {
        if (DB_PLAIN_FIELDS.has(field)) return;
        next[field] = decryptValue(next[field]);
    });
    return next as T;
};

export type MetaEntry = {
    key: string;
    value: string;
};

export type SyncMetaEntry = {
    table_name: string;
    last_sync_at?: string;
    last_server_id?: number;
    checksum?: string;
    row_count?: number;
};

export type GenericRow = {
    id?: number;
    chat_id?: number;
    [key: string]: any;
};

class TransactionsDB extends Dexie {
    transactions!: Table<Transaction, number>;
    operatorMappings!: Table<GenericRow, number>;
    operatorReferences!: Table<GenericRow, number>;
    monitoredBotChats!: Table<GenericRow, number>;
    hiddenBotChats!: Table<GenericRow, number>;
    parsingLogs!: Table<GenericRow, number>;
    hourlyReports!: Table<GenericRow, number>;
    accessScopes!: Table<GenericRow, number>;
    receiptProcessingTasks!: Table<GenericRow, number>;
    lockedPeriods!: Table<GenericRow, number>;
    syncMeta!: Table<SyncMetaEntry, string>;
    meta!: Table<MetaEntry, string>;

    constructor() {
        super('transactions-db');
        this.version(1).stores({
            transactions: '&id, transaction_date, currency, operator_raw, application_mapped',
            meta: '&key',
        });
        this.version(2).stores({
            transactions: '&id, transaction_date, currency, card_last_4, application_mapped',
            operatorMappings: '&id, pattern, priority',
            operatorReferences: '&id, operator_name, application_name',
            monitoredBotChats: '&chat_id, enabled',
            hiddenBotChats: '&chat_id',
            parsingLogs: '&id, created_at',
            hourlyReports: '&id, report_hour',
            accessScopes: '&id, name, is_active',
            receiptProcessingTasks: '&id, status',
            lockedPeriods: '&id, date_from, date_to, is_active',
            syncMeta: '&table_name, last_sync_at, last_server_id, checksum',
            meta: '&key',
        });
        this.version(3).stores({
            transactions: '&id, transaction_date, currency, card_last_4, application_mapped',
            operatorMappings: '&id, pattern, priority',
            operatorReferences: '&id, operator_name, application_name',
            monitoredBotChats: '&chat_id, enabled',
            hiddenBotChats: '&chat_id',
            parsingLogs: '&id, created_at',
            hourlyReports: '&id, report_hour',
            accessScopes: '&id, name, is_active',
            receiptProcessingTasks: '&id, status',
            lockedPeriods: '&id, date_from, date_to, is_active',
            syncMeta: '&table_name, last_sync_at, last_server_id, checksum',
            meta: '&key',
            accessAuditLog: null,
            chatPasswords: null,
        });
        this.version(4).stores({
            transactions: '&id, transaction_date, currency, card_last_4, application_mapped',
            operatorMappings: '&id, pattern, priority',
            operatorReferences: '&id, operator_name, application_name',
            monitoredBotChats: '&chat_id, enabled',
            hiddenBotChats: '&chat_id',
            parsingLogs: '&id, created_at',
            hourlyReports: '&id, report_hour',
            accessScopes: '&id, name, is_active',
            receiptProcessingTasks: '&id, status',
            lockedPeriods: '&id, date_from, date_to, is_active',
            syncMeta: '&table_name, last_sync_at, last_server_id, checksum',
            meta: '&key',
            accessAuditLog: null,
            chatPasswords: null,
        }).upgrade(async (tx) => {
            for (const tableName of DB_ENCRYPTED_TABLES) {
                const table = (tx as any).table(tableName);
                const rows = await table.toArray();
                for (const row of rows) {
                    await table.put(row);
                }
            }
        });
        this.installEncryptionHooks();
    }

    private installEncryptionHooks() {
        DB_ENCRYPTED_TABLES.forEach((tableName) => {
            const table = (this as any)[tableName] as Table<GenericRow, number>;
            if (!table) return;

            table.hook('creating', (_primKey, obj) => {
                const encrypted = encryptObject(obj as GenericRow);
                Object.assign(obj, encrypted);
            });

            table.hook('updating', (mods) => {
                const encryptedMods: Record<string, any> = {};
                Object.entries(mods).forEach(([field, value]) => {
                    const rootField = field.split('.')[0];
                    encryptedMods[field] = DB_PLAIN_FIELDS.has(rootField)
                        ? value
                        : encryptValue(value);
                });
                return encryptedMods;
            });

            table.hook('reading', (obj) => {
                return decryptObject(obj as GenericRow);
            });
        });
    }
}

export const db = new TransactionsDB();

export const clearLocalDatabase = async (): Promise<void> => {
    for (const table of db.tables) {
        await table.clear();
    }
};
