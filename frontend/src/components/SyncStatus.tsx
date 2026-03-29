import { RefreshCcw } from 'lucide-react';

type TableSyncInfo = {
    table: string;
    rows: number;
    serverRows?: number;
    lagRows?: number;
    lastSyncAt?: string;
    error?: string;
};

type SyncStatusProps = {
    state: 'idle' | 'syncing' | 'lagging' | 'error';
    lagRows?: number;
    lastSyncAt?: string | null;
    tableStatuses?: TableSyncInfo[];
    onSync?: () => void;
};

const stateLabel = (state: SyncStatusProps['state']) => {
    if (state === 'syncing') return 'Синхронизация...';
    if (state === 'lagging') return 'Отстаёт';
    if (state === 'error') return 'Ошибка синхронизации';
    return 'Синхронизировано';
};

const stateDotClass = (state: SyncStatusProps['state']) => {
    if (state === 'syncing') return 'bg-info';
    if (state === 'lagging') return 'bg-warning';
    if (state === 'error') return 'bg-danger';
    return 'bg-success';
};

export function SyncStatus({ state, lagRows = 0, lastSyncAt, tableStatuses, onSync }: SyncStatusProps) {
    const title = `${stateLabel(state)}${state === 'lagging' ? ` на ${lagRows} записей` : ''}${lastSyncAt ? ` • ${new Date(lastSyncAt).toLocaleString()}` : ''}`;
    return (
        <details className="relative">
            <summary
                className="list-none flex items-center gap-2 px-3 py-1.5 rounded-md border border-border bg-surface-2 text-xs cursor-pointer select-none"
                title={title}
            >
                <span className={`h-2 w-2 rounded-full ${stateDotClass(state)} ${state === 'syncing' ? 'animate-pulse' : ''}`} />
                <span>{state === 'lagging' ? `Отстаёт на ${lagRows}` : stateLabel(state)}</span>
            </summary>
            <div className="absolute right-0 mt-2 min-w-[320px] max-h-72 overflow-auto rounded-md border border-border bg-surface shadow-lg p-3 z-50">
                <div className="flex items-center justify-between mb-2">
                    <h4 className="text-sm font-semibold text-foreground">Детали синхронизации</h4>
                    {onSync && (
                        <button
                            onClick={onSync}
                            className="flex items-center gap-1 text-xs px-2 py-1 rounded border border-border hover:bg-surface-2"
                        >
                            <RefreshCcw className="w-3 h-3" />
                            Обновить
                        </button>
                    )}
                </div>
                <div className="text-xs text-foreground-secondary mb-2">
                    Последняя синхронизация: {lastSyncAt ? new Date(lastSyncAt).toLocaleString() : '—'}
                </div>
                <div className="space-y-2">
                    {(tableStatuses || []).map((item) => (
                        <div key={item.table} className="p-2 rounded border border-border bg-surface-2">
                            <div className="flex items-center justify-between">
                                <span className="font-medium text-foreground">{item.table}</span>
                                <span className="text-foreground-secondary">
                                    {typeof item.serverRows === 'number' ? `${item.rows}/${item.serverRows}` : item.rows}
                                </span>
                            </div>
                            {item.lastSyncAt && <div className="text-[11px] text-foreground-secondary">{new Date(item.lastSyncAt).toLocaleString()}</div>}
                            {!!item.lagRows && item.lagRows > 0 && <div className="text-[11px] text-warning">Отставание: {item.lagRows}</div>}
                            {item.error && <div className="text-[11px] text-danger">{item.error}</div>}
                        </div>
                    ))}
                </div>
            </div>
        </details>
    );
}
