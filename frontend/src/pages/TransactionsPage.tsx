/**
 * Transactions Page Component
 * Offline-first: loads from IndexedDB, manual sync to server, local filtering/sorting/pagination
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useLocation, useNavigate } from 'react-router-dom';
import { AlertCircle, Lock, ShieldAlert, Plug } from 'lucide-react';
import { AgentLocateResult, Transaction } from '../services/api';
import { TransactionTable } from '../components/TransactionTable';
import { useOfflineTransactions } from '../hooks/useOfflineTransactions';
import { AddTransactionModal } from '../components/AddTransactionModal';
import { LockedPeriodBanner } from '../components/LockedPeriodBanner';
import { transactionsApi, CreateTransactionRequest, referenceApi, securityApi } from '../services/api';
import { useToast } from '../components/Toast';
import { useAuth } from '../contexts/AuthContext';
import { useAiAgent } from '../contexts/AiAgentContext';
import { buildClientStateScope, buildScopedStorageKey } from '../utils/clientStateScope';
import '../styles/transactions.css';

type SortState = { sort_by: string; sort_dir: 'asc' | 'desc' };

type FiltersState = {
    search?: string;
    dateFrom?: string;
    dateTo?: string;
    operators?: string[];
    apps?: string[];
    amountMin?: string;
    amountMax?: string;
    source_channel?: 'TELEGRAM' | 'SMS' | 'MANUAL';
    source_chat_ids?: number[];
    transaction_type?: 'DEBIT' | 'CREDIT' | 'CONVERSION' | 'REVERSAL';
    transaction_types?: string[];
    currency?: 'ALL' | 'UZS' | 'USD';
    card?: string;
    days_of_week?: number[];
    parsing_method?: string;
    confidence_min?: number;
    confidence_max?: number;
};

const TRANSACTIONS_PAGE_KEY_PREFIX = 'transactionsPageState:v2';
const TRANSACTIONS_TABLE_STATE_KEY_PREFIX = 'transactionsTableState:v6';

function buildYearRange(startYear: number | null, endYear: number | null): number[] {
    if (startYear === null && endYear === null) return [];
    const start = startYear ?? endYear;
    const end = endYear ?? startYear;
    if (start === null || end === null) return [];
    const low = Math.min(start, end);
    const high = Math.max(start, end);
    if (high - low > 50) return [];
    const years: number[] = [];
    for (let y = low; y <= high; y += 1) {
        years.push(y);
    }
    return years;
}

function isoStartOfYear(year: number): string {
    return `${year}-01-01T00:00:00`;
}

function isoEndOfYear(year: number): string {
    return `${year}-12-31T23:59:59`;
}

function sourceChannelToSourceType(channel?: 'TELEGRAM' | 'SMS' | 'MANUAL') {
    if (!channel) return undefined;
    if (channel === 'TELEGRAM') return 'AUTO' as const;
    return channel;
}

function normalizeStringArray(values?: string[]): string[] | undefined {
    if (!values?.length) return undefined;
    return [...values].sort((a, b) => a.localeCompare(b));
}

function normalizeNumberArray(values?: number[]): number[] | undefined {
    if (!values?.length) return undefined;
    return [...values].sort((a, b) => a - b);
}

function normalizeFiltersStateForComparison(value: FiltersState): FiltersState {
    return {
        search: value.search?.trim() || undefined,
        dateFrom: value.dateFrom || undefined,
        dateTo: value.dateTo || undefined,
        operators: normalizeStringArray(value.operators),
        apps: normalizeStringArray(value.apps),
        amountMin: value.amountMin || undefined,
        amountMax: value.amountMax || undefined,
        source_channel: value.source_channel || undefined,
        source_chat_ids: normalizeNumberArray(value.source_chat_ids),
        transaction_type: value.transaction_type || undefined,
        transaction_types: normalizeStringArray(value.transaction_types),
        currency: value.currency === 'ALL' ? 'ALL' : value.currency || 'ALL',
        card: value.card || undefined,
        days_of_week: normalizeNumberArray(value.days_of_week),
        parsing_method: value.parsing_method || undefined,
        confidence_min: typeof value.confidence_min === 'number' && Number.isFinite(value.confidence_min) ? value.confidence_min : undefined,
        confidence_max: typeof value.confidence_max === 'number' && Number.isFinite(value.confidence_max) ? value.confidence_max : undefined,
    };
}

function buildNextFiltersState(
    next: Partial<FiltersState> & { search?: string; filters?: any },
): FiltersState {
    const incomingFilters = next.filters;
    const incomingConfidenceMin = incomingFilters?.confidenceMin;
    const incomingConfidenceMax = incomingFilters?.confidenceMax;
    return normalizeFiltersStateForComparison({
        search: next.search,
        dateFrom: incomingFilters?.dateFrom || undefined,
        dateTo: incomingFilters?.dateTo || undefined,
        operators: incomingFilters?.operators,
        apps: incomingFilters?.apps,
        amountMin: incomingFilters?.amountMin || undefined,
        amountMax: incomingFilters?.amountMax || undefined,
        source_channel: incomingFilters?.sourceType && incomingFilters.sourceType !== 'ALL' ? incomingFilters.sourceType : undefined,
        source_chat_ids: incomingFilters?.telegramSourceIds,
        transaction_type: incomingFilters?.transactionTypes?.length === 1 ? incomingFilters.transactionTypes[0] : undefined,
        transaction_types: incomingFilters?.transactionTypes?.length > 1 ? incomingFilters.transactionTypes : undefined,
        currency: incomingFilters?.currency === 'ALL' ? 'ALL' : incomingFilters?.currency || 'ALL',
        card: incomingFilters?.cardId || undefined,
        days_of_week: incomingFilters?.daysOfWeek,
        parsing_method: incomingFilters?.parsingMethod || undefined,
        confidence_min:
            typeof incomingConfidenceMin === 'number' && Number.isFinite(incomingConfidenceMin)
                ? incomingConfidenceMin
                : undefined,
        confidence_max:
            typeof incomingConfidenceMax === 'number' && Number.isFinite(incomingConfidenceMax)
                ? incomingConfidenceMax
                : undefined,
    });
}

function areSortStatesEqual(a: SortState, b: SortState): boolean {
    return a.sort_by === b.sort_by && a.sort_dir === b.sort_dir;
}

function areFiltersStatesEqual(a: FiltersState, b: FiltersState): boolean {
    return JSON.stringify(normalizeFiltersStateForComparison(a)) === JSON.stringify(normalizeFiltersStateForComparison(b));
}

export function TransactionsPage() {
    const { showToast } = useToast();
    const { user } = useAuth();
    const location = useLocation();
    const navigate = useNavigate();
    const isAdmin = user?.role === 'admin';
    const stateScopeKey = useMemo(() => buildClientStateScope(user?.username), [user?.username]);
    const pageStateStorageKey = useMemo(
        () => buildScopedStorageKey(TRANSACTIONS_PAGE_KEY_PREFIX, stateScopeKey),
        [stateScopeKey],
    );
    const tableStateStorageKey = useMemo(
        () => buildScopedStorageKey(TRANSACTIONS_TABLE_STATE_KEY_PREFIX, stateScopeKey),
        [stateScopeKey],
    );
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(100);
    const [sort, setSort] = useState<SortState>({ sort_by: 'transaction_date', sort_dir: 'asc' });
    const [filters, setFilters] = useState<FiltersState>({ currency: 'ALL' });
    const [debouncedSearch, setDebouncedSearch] = useState('');
    const [addModalOpen, setAddModalOpen] = useState(false);
    const [highlightRowId, setHighlightRowId] = useState<number | null>(null);
    const [highlightRowIds, setHighlightRowIds] = useState<number[]>([]);
    const [highlightDurationMs, setHighlightDurationMs] = useState<number>(3000);
    const [focusColumnId, setFocusColumnId] = useState<string | null>(null);
    const [focusColumnToken, setFocusColumnToken] = useState(0);
    const [selectedYear, setSelectedYear] = useState<number | null>(null);
    const [otpCode, setOtpCode] = useState('');
    const [otpScopeId, setOtpScopeId] = useState<number | null>(null);
    const [otpExpiresAt, setOtpExpiresAt] = useState<number | null>(null);
    const [otpSecondsLeft, setOtpSecondsLeft] = useState<number>(0);
    const [tableResetViewToken, setTableResetViewToken] = useState(0);
    const lastCachedRestoreYearRef = useRef<number | null>(null);
    const prevYearRef = useRef<number | null>(selectedYear);
    const autoOtpRequestKeyRef = useRef<string | null>(null);
    const yearMissingCountRef = useRef<Record<number, number>>({});
    const hasScopedPageRestoreRef = useRef(false);
    const currentSortRef = useRef(sort);
    const currentFiltersRef = useRef(filters);
    const currentPageRef = useRef(page);
    const consumedAgentNavigationTokenRef = useRef<number | null>(null);
    const consumedUiActionTokenRef = useRef<number | null>(null);
    const exportAllRef = useRef<(columns?: string[]) => Promise<void> | void>(() => {});
    const { pendingUiAction, consumeUiAction } = useAiAgent();

    useEffect(() => {
        currentSortRef.current = sort;
    }, [sort]);

    useEffect(() => {
        currentFiltersRef.current = filters;
    }, [filters]);

    useEffect(() => {
        currentPageRef.current = page;
    }, [page]);

    useEffect(() => {
        const state = (location.state || {}) as { agentNavigation?: AgentLocateResult; ts?: number };
        const target = state.agentNavigation;
        const token = Number(state.ts || 0);
        if (!target || !token || consumedAgentNavigationTokenRef.current === token) {
            return;
        }
        consumedAgentNavigationTokenRef.current = token;

        if (
            target.sort_hint &&
            typeof target.sort_hint.sort_by === 'string' &&
            (target.sort_hint.sort_dir === 'asc' || target.sort_hint.sort_dir === 'desc')
        ) {
            setSort({
                sort_by: target.sort_hint.sort_by,
                sort_dir: target.sort_hint.sort_dir,
            });
        }

        if (target.suggested_filters && typeof target.suggested_filters === 'object') {
            const sf: any = target.suggested_filters;
            const isReset = sf.reset === true;
            setFilters((prev) => {
                const base: FiltersState = isReset ? { currency: 'ALL' } : prev;
                const next: FiltersState = { ...base };

                if (typeof sf.search === 'string') next.search = sf.search;
                if (typeof sf.dateFrom === 'string') next.dateFrom = sf.dateFrom;
                if (typeof sf.dateTo === 'string') next.dateTo = sf.dateTo;
                if (Array.isArray(sf.apps)) next.apps = sf.apps.map((v: any) => String(v));
                if (Array.isArray(sf.operators)) next.operators = sf.operators.map((v: any) => String(v));
                if (sf.amount_min !== undefined && sf.amount_min !== null) {
                    next.amountMin = String(sf.amount_min);
                }
                if (sf.amount_max !== undefined && sf.amount_max !== null) {
                    next.amountMax = String(sf.amount_max);
                }
                if (typeof sf.currency === 'string') {
                    const upper = sf.currency.toUpperCase();
                    next.currency = upper === 'UZS' || upper === 'USD' ? upper : 'ALL';
                }
                if (Array.isArray(sf.transaction_types)) {
                    const upper = sf.transaction_types.map((v: any) => String(v).toUpperCase());
                    next.transaction_types = upper;
                    next.transaction_type = upper.length === 1
                        ? (upper[0] as FiltersState['transaction_type'])
                        : undefined;
                }
                if (typeof sf.source_channel === 'string') {
                    const ch = sf.source_channel.toUpperCase();
                    next.source_channel = (ch === 'TELEGRAM' || ch === 'SMS' || ch === 'MANUAL')
                        ? (ch as FiltersState['source_channel'])
                        : undefined;
                }
                if (Array.isArray(sf.source_chat_ids)) {
                    next.source_chat_ids = sf.source_chat_ids
                        .map((v: any) => Number(v))
                        .filter((v: number) => Number.isFinite(v));
                }
                if (typeof sf.card_id === 'string') {
                    next.card = sf.card_id;
                }
                if (Array.isArray(sf.days_of_week)) {
                    next.days_of_week = sf.days_of_week
                        .map((v: any) => Number(v))
                        .filter((v: number) => Number.isFinite(v) && v >= 0 && v <= 6);
                }
                if (typeof sf.parsing_method === 'string') {
                    next.parsing_method = sf.parsing_method;
                }
                if (sf.confidence_min !== undefined && sf.confidence_min !== null) {
                    const num = Number(sf.confidence_min);
                    if (Number.isFinite(num)) next.confidence_min = num;
                }
                if (sf.confidence_max !== undefined && sf.confidence_max !== null) {
                    const num = Number(sf.confidence_max);
                    if (Number.isFinite(num)) next.confidence_max = num;
                }
                return normalizeFiltersStateForComparison(next);
            });
        }

        if (target.page_hint) {
            setPage(Math.max(1, Number(target.page_hint)));
        }
        const nextHighlightSeconds = Math.max(2, Number(target.highlight_seconds || 3));
        setHighlightDurationMs(nextHighlightSeconds * 1000);
        if (target.row_id) {
            setHighlightRowId(Number(target.row_id));
        }
        if (Array.isArray(target.row_ids)) {
            setHighlightRowIds(
                target.row_ids
                    .map((value: any) => Number(value))
                    .filter((value: number) => Number.isFinite(value)),
            );
        } else if (target.row_id) {
            setHighlightRowIds([Number(target.row_id)]);
        } else {
            setHighlightRowIds([]);
        }
        if (target.column_id) {
            setFocusColumnId(String(target.column_id));
            setFocusColumnToken(Date.now());
        }

        navigate(location.pathname, { replace: true, state: null });
    }, [location.pathname, location.state, navigate]);

    /**
     * Consume `pendingUiAction` from AiAgentContext. Each ui_action emitted by
     * the agent (apply_filters / clear_filters / mark_rows / scroll_to_row /
     * open_details / export) is mapped to existing setters / handlers. Routing
     * (`navigate_view`) is handled at App level.
     */
    useEffect(() => {
        if (!pendingUiAction) return;
        if (consumedUiActionTokenRef.current === pendingUiAction.token) return;
        const kind = String(pendingUiAction.kind || '').toLowerCase();
        if (!kind || kind === 'noop' || kind === 'nop' || kind === 'navigate_view') return;
        const target = pendingUiAction.target || {};
        if (kind !== 'export' && target.area && target.area !== 'transactions_table') return;

        consumedUiActionTokenRef.current = pendingUiAction.token;
        const params = (pendingUiAction.params || {}) as Record<string, any>;

        const applyFiltersPayload = (raw: Record<string, any>, reset: boolean) => {
            setFilters((prev) => {
                const base: FiltersState = reset ? { currency: 'ALL' } : prev;
                const next: FiltersState = { ...base };
                if (typeof raw.search === 'string') next.search = raw.search;
                if (typeof raw.dateFrom === 'string') next.dateFrom = raw.dateFrom;
                if (typeof raw.dateTo === 'string') next.dateTo = raw.dateTo;
                if (typeof raw.date_from === 'string') next.dateFrom = raw.date_from;
                if (typeof raw.date_to === 'string') next.dateTo = raw.date_to;
                if (Array.isArray(raw.apps)) {
                    next.apps = raw.apps.map((v: any) => String(v));
                } else if (typeof raw.application === 'string' && raw.application) {
                    next.apps = [raw.application];
                }
                if (Array.isArray(raw.operators)) {
                    next.operators = raw.operators.map((v: any) => String(v));
                } else if (typeof raw.operator === 'string' && raw.operator) {
                    next.operators = [raw.operator];
                }
                if (raw.amount_min !== undefined && raw.amount_min !== null && raw.amount_min !== '') {
                    next.amountMin = String(raw.amount_min);
                } else if (raw.min_amount !== undefined && raw.min_amount !== null && raw.min_amount !== '') {
                    next.amountMin = String(raw.min_amount);
                }
                if (raw.amount_max !== undefined && raw.amount_max !== null && raw.amount_max !== '') {
                    next.amountMax = String(raw.amount_max);
                } else if (raw.max_amount !== undefined && raw.max_amount !== null && raw.max_amount !== '') {
                    next.amountMax = String(raw.max_amount);
                }
                if (typeof raw.currency === 'string') {
                    const upper = raw.currency.toUpperCase();
                    next.currency = upper === 'UZS' || upper === 'USD' ? upper : 'ALL';
                }
                if (Array.isArray(raw.transaction_types)) {
                    const upper = raw.transaction_types.map((v: any) => String(v).toUpperCase());
                    next.transaction_types = upper;
                    next.transaction_type = upper.length === 1
                        ? (upper[0] as FiltersState['transaction_type'])
                        : undefined;
                } else if (typeof raw.transaction_type === 'string') {
                    const upper = raw.transaction_type.toUpperCase() as FiltersState['transaction_type'];
                    next.transaction_type = upper;
                    next.transaction_types = undefined;
                }
                if (typeof raw.source_channel === 'string' || typeof raw.source_type === 'string') {
                    const ch = String(raw.source_channel || raw.source_type).toUpperCase();
                    next.source_channel = (ch === 'TELEGRAM' || ch === 'SMS' || ch === 'MANUAL')
                        ? (ch as FiltersState['source_channel'])
                        : undefined;
                }
                if (Array.isArray(raw.source_chat_ids)) {
                    next.source_chat_ids = raw.source_chat_ids
                        .map((v: any) => Number(v))
                        .filter((v: number) => Number.isFinite(v));
                } else if (raw.source_chat_id !== undefined && raw.source_chat_id !== null) {
                    const num = Number(raw.source_chat_id);
                    if (Number.isFinite(num)) next.source_chat_ids = [num];
                }
                if (typeof raw.card_id === 'string') {
                    next.card = raw.card_id;
                } else if (typeof raw.card_last_4 === 'string') {
                    next.card = raw.card_last_4;
                }
                if (Array.isArray(raw.days_of_week)) {
                    next.days_of_week = raw.days_of_week
                        .map((v: any) => Number(v))
                        .filter((v: number) => Number.isFinite(v) && v >= 0 && v <= 6);
                }
                if (typeof raw.parsing_method === 'string') {
                    next.parsing_method = raw.parsing_method;
                }
                if (raw.confidence_min !== undefined && raw.confidence_min !== null) {
                    const num = Number(raw.confidence_min);
                    if (Number.isFinite(num)) next.confidence_min = num;
                }
                if (raw.confidence_max !== undefined && raw.confidence_max !== null) {
                    const num = Number(raw.confidence_max);
                    if (Number.isFinite(num)) next.confidence_max = num;
                }
                return normalizeFiltersStateForComparison(next);
            });
            setPage(1);
        };

        if (kind === 'apply_filters') {
            const rawFilters = (params.filters && typeof params.filters === 'object')
                ? params.filters as Record<string, any>
                : params;
            applyFiltersPayload(rawFilters, Boolean(params.reset));
        } else if (kind === 'clear_filters') {
            setFilters({ currency: 'ALL' });
            setDebouncedSearch('');
            setHighlightRowId(null);
            setHighlightRowIds([]);
            setPage(1);
        } else if (kind === 'mark_rows') {
            const rawIds: any[] = Array.isArray(params.transaction_ids)
                ? params.transaction_ids
                : Array.isArray(params.ids)
                    ? params.ids
                    : Array.isArray(target.ids) ? target.ids : [];
            const ids = rawIds.map((v) => Number(v)).filter((v) => Number.isFinite(v) && v > 0);
            if (ids.length) {
                const scope = String(params.scope || params.mode || 'replace').toLowerCase();
                setHighlightRowIds((prev) => {
                    if (scope === 'add') {
                        const set = new Set([...prev, ...ids]);
                        return Array.from(set);
                    }
                    return ids;
                });
                setHighlightRowId(ids[0]);
                setHighlightDurationMs(8000);
            }
        } else if (kind === 'scroll_to_row' || kind === 'open_details') {
            const rowId = Number(params.row_id ?? params.transaction_id ?? target.transaction_id ?? 0);
            if (Number.isFinite(rowId) && rowId > 0) {
                setHighlightRowId(rowId);
                setHighlightRowIds([rowId]);
                setHighlightDurationMs(kind === 'open_details' ? 6000 : 4000);
            }
        } else if (kind === 'export') {
            const fmt = String(params.format || 'xlsx').toLowerCase();
            if (fmt === 'csv' || fmt === 'json') {
                showToast('warning', 'Формат пока недоступен — выгружаю Excel.', { details: `Формат запрошен: ${fmt.toUpperCase()}` });
            }
            const exportFilters = (params.filters && typeof params.filters === 'object')
                ? params.filters as Record<string, any>
                : null;
            if (exportFilters) {
                applyFiltersPayload(exportFilters, false);
            }
            // Defer export to next tick so the freshly-applied filters land in state first.
            window.setTimeout(() => {
                void exportAllRef.current();
            }, 80);
        }

        consumeUiAction();
    }, [pendingUiAction, consumeUiAction, showToast]);

    useEffect(() => {
        const handle = window.setTimeout(() => {
            setDebouncedSearch((filters.search || '').trim());
        }, 300);
        return () => window.clearTimeout(handle);
    }, [filters.search]);

    const {
        data,
        isLoading: offlineLoading,
        isOfflineReady,
        syncProgress,
        syncFromServer,
        upsertTransactions,
        removeTransactions,
        updateTransactionFields,
        lastSyncAt,
    } = useOfflineTransactions();

    const securityStatusQuery = useQuery({
        queryKey: ['security-status'],
        queryFn: securityApi.getStatus,
        refetchInterval: 30000,
    });
    const hasSecurityStatusSnapshot = isAdmin || Boolean(securityStatusQuery.data);
    const transactionsInitQuery = useQuery({
        queryKey: ['transactions-init'],
        queryFn: transactionsApi.getInit,
        enabled: hasSecurityStatusSnapshot,
        staleTime: 60_000,
        refetchInterval: 30_000,
        retry: 1,
    });
    const scopesQuery = useQuery({
        queryKey: ['security-scopes'],
        queryFn: securityApi.listScopes,
        enabled: hasSecurityStatusSnapshot && Boolean(securityStatusQuery.data?.scopes_enabled),
        refetchInterval: 30000,
    });
    const lockedPeriodsQuery = useQuery({
        queryKey: ['security-locked-periods'],
        queryFn: securityApi.getLockedPeriods,
        refetchInterval: 60000,
        retry: false,
    });
    const securityStatusErrorDetail = (securityStatusQuery.error as any)?.response?.data?.detail;
    const securityStatusErrorText =
        typeof securityStatusErrorDetail === 'string'
            ? securityStatusErrorDetail
            : securityStatusErrorDetail?.error
                ? String(securityStatusErrorDetail.error)
                : 'Статус безопасности недоступен';

    const requestScopeCodeMutation = useMutation({
        mutationFn: async (scopeId: number) => securityApi.requestScopeCode(scopeId),
        onSuccess: (response, scopeId) => {
            const seconds = Math.max(0, Number(response.expires_in) || 0);
            setOtpScopeId(scopeId);
            setOtpCode('');
            setOtpSecondsLeft(seconds);
            setOtpExpiresAt(Date.now() + seconds * 1000);
            showToast('success', 'Код подтверждения отправлен в AuthBot');
        },
        onError: (err: any) => {
            showToast('error', err?.response?.data?.detail || 'Не удалось запросить OTP-код');
        },
    });

    const verifyScopeCodeMutation = useMutation({
        mutationFn: async (payload: { scopeId: number; code: string }) =>
            securityApi.verifyScopeCode({
                scope_id: payload.scopeId,
                code: payload.code,
            }),
        onSuccess: async () => {
            setOtpCode('');
            setOtpScopeId(null);
            setOtpSecondsLeft(0);
            setOtpExpiresAt(null);
            await Promise.all([
                securityStatusQuery.refetch(),
                transactionsInitQuery.refetch(),
            ]);
            await syncFromServer(false);
            showToast('success', 'Доступ к периоду открыт по OTP');
        },
        onError: (err: any) => {
            const detail = err?.response?.data?.detail;
            if (detail?.error === 'invalid_code') {
                showToast(
                    'error',
                    `Неверный код${typeof detail?.attempts_left === 'number' ? ` (осталось: ${detail.attempts_left})` : ''}`
                );
                return;
            }
            showToast('error', typeof detail === 'string' ? detail : 'Не удалось подтвердить OTP-код');
        },
    });

    const scopesEnabled = Boolean(securityStatusQuery.data?.scopes_enabled);
    const currentScope = securityStatusQuery.data?.current_scope || null;
    const currentScopeYears = currentScope?.years || [];
    const scopeStartDate = currentScope?.period_start ? new Date(currentScope.period_start) : null;
    const scopeEndDate = currentScope?.period_end ? new Date(currentScope.period_end) : null;
    const scopeStartYear =
        scopeStartDate && !Number.isNaN(scopeStartDate.getTime()) ? scopeStartDate.getFullYear() : null;
    const scopeEndYear =
        scopeEndDate && !Number.isNaN(scopeEndDate.getTime()) ? scopeEndDate.getFullYear() : null;
    const scopePeriodYears = buildYearRange(scopeStartYear, scopeEndYear);

    const scopedData = useMemo(() => {
        if (!scopesEnabled || !currentScope) {
            return data;
        }
        return data.filter((tx) => {
            const txDate = tx.transaction_date ? new Date(tx.transaction_date) : null;
            if (!txDate || Number.isNaN(txDate.getTime())) {
                return false;
            }
            if (currentScopeYears.length > 0 && !currentScopeYears.includes(txDate.getFullYear())) {
                return false;
            }
            if (scopeStartDate && txDate < scopeStartDate) {
                return false;
            }
            if (scopeEndDate && txDate > scopeEndDate) {
                return false;
            }
            return true;
        });
    }, [data, scopesEnabled, currentScope, currentScopeYears, scopeStartDate, scopeEndDate]);

    const availableYears = useMemo(() => {
        if (scopesEnabled) {
            const strictYearSet = new Set<number>();
            // Years from security status (always available, independent of scope token cache)
            (securityStatusQuery.data?.available_years || []).forEach((year) => strictYearSet.add(year));
            // Years from all scopes definitions (independent of scope token cache)
            (scopesQuery.data || []).forEach((scope) => {
                (scope.years || []).forEach((year) => strictYearSet.add(year));
            });
            // Years from init response (includes scope years with count=0 after D8 fix)
            (transactionsInitQuery.data?.security_status?.available_years || []).forEach((year: number) => strictYearSet.add(year));
            (transactionsInitQuery.data?.years || []).forEach((item: { year: number }) => strictYearSet.add(item.year));
            // Years from current active scope token (may be empty if cache expired)
            currentScopeYears.forEach((year) => strictYearSet.add(year));
            scopePeriodYears.forEach((year) => strictYearSet.add(year));
            const strictYears = Array.from(strictYearSet).sort((a, b) => b - a);
            if (strictYears.length) {
                return strictYears;
            }
            return [new Date().getFullYear()];
        }
        const set = new Set<number>();
        (transactionsInitQuery.data?.years || []).forEach((item) => set.add(item.year));
        (securityStatusQuery.data?.available_years || []).forEach((year) => set.add(year));
        scopedData.forEach((tx) => {
            const d = tx.transaction_date ? new Date(tx.transaction_date) : null;
            if (d && !Number.isNaN(d.getTime())) {
                set.add(d.getFullYear());
            }
        });
        if (!set.size) {
            set.add(new Date().getFullYear());
        }
        return Array.from(set).sort((a, b) => b - a);
    }, [transactionsInitQuery.data, securityStatusQuery.data, scopesQuery.data, scopedData, scopesEnabled, currentScopeYears, scopePeriodYears]);

    useEffect(() => {
        if (selectedYear === null && availableYears.length) {
            setSelectedYear(availableYears[0]);
            return;
        }
        if (selectedYear !== null && !availableYears.includes(selectedYear)) {
            // Grace period: only reset after 3+ consecutive absences (~90s at 30s refetch)
            const count = (yearMissingCountRef.current[selectedYear] || 0) + 1;
            yearMissingCountRef.current[selectedYear] = count;
            if (count >= 3 && availableYears.length) {
                setSelectedYear(availableYears[0]);
                delete yearMissingCountRef.current[selectedYear];
            }
        } else if (selectedYear !== null) {
            // Year present again — reset counter
            delete yearMissingCountRef.current[selectedYear];
        }
    }, [availableYears, selectedYear]);

    const yearBlockedByPeriod =
        selectedYear !== null &&
        ((scopeStartYear !== null && selectedYear < scopeStartYear) ||
            (scopeEndYear !== null && selectedYear > scopeEndYear));
    const yearRequiresUnlock =
        !isAdmin &&
        scopesEnabled &&
        selectedYear !== null &&
        ((currentScopeYears.length > 0 && !currentScopeYears.includes(selectedYear)) || yearBlockedByPeriod);
    const needsInitialUnlock = !isAdmin && scopesEnabled && !securityStatusQuery.data?.current_scope;
    const isLockedView = !hasSecurityStatusSnapshot || needsInitialUnlock || yearRequiresUnlock;
    const serverDateFrom = useMemo(() => {
        if (filters.dateFrom) return `${filters.dateFrom}T00:00:00`;
        if (selectedYear !== null) return isoStartOfYear(selectedYear);
        return undefined;
    }, [filters.dateFrom, selectedYear]);
    const serverDateTo = useMemo(() => {
        if (filters.dateTo) return `${filters.dateTo}T23:59:59`;
        if (selectedYear !== null) return isoEndOfYear(selectedYear);
        return undefined;
    }, [filters.dateTo, selectedYear]);
    const serverSourceType = sourceChannelToSourceType(filters.source_channel);
    const serverSourceChatIds = useMemo(
        () => (filters.source_chat_ids && filters.source_chat_ids.length ? [...filters.source_chat_ids].sort((a, b) => a - b) : undefined),
        [filters.source_chat_ids],
    );

    const triggerBlobDownload = useCallback((blob: Blob, filename: string) => {
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        link.click();
        window.URL.revokeObjectURL(url);
    }, []);

    const serverTransactionsQuery = useQuery({
        queryKey: [
            'transactions-server',
            page,
            pageSize,
            sort.sort_by,
            sort.sort_dir,
            serverDateFrom,
            serverDateTo,
            filters.operators || [],
            filters.apps || [],
            filters.amountMin || '',
            filters.amountMax || '',
            filters.transaction_type || '',
            filters.transaction_types || [],
            filters.currency || 'ALL',
            filters.card || '',
            filters.days_of_week || [],
            filters.parsing_method || '',
            filters.confidence_min ?? '',
            filters.confidence_max ?? '',
            serverSourceType || '',
            serverSourceChatIds || [],
            debouncedSearch,
            isLockedView,
        ],
        queryFn: () =>
            transactionsApi.getTransactions({
                page,
                page_size: pageSize,
                sort_by: sort.sort_by,
                sort_dir: sort.sort_dir,
                date_from: serverDateFrom,
                date_to: serverDateTo,
                operators: filters.operators,
                apps: filters.apps,
                amount_min: filters.amountMin,
                amount_max: filters.amountMax,
                transaction_type: filters.transaction_type,
                transaction_types: filters.transaction_types,
                currency: filters.currency && filters.currency !== 'ALL' ? filters.currency : undefined,
                card: filters.card,
                days_of_week: filters.days_of_week,
                parsing_method: filters.parsing_method,
                confidence_min: filters.confidence_min,
                confidence_max: filters.confidence_max,
                source_type: serverSourceType,
                source_chat_ids: serverSourceChatIds,
                search: debouncedSearch || undefined,
            }),
        enabled: !isLockedView && hasSecurityStatusSnapshot,
        retry: 1,
        staleTime: 15000,
        refetchOnWindowFocus: false,
        placeholderData: (previousData) => previousData,
    });
    const serverUnfilteredQuery = useQuery({
        queryKey: ['transactions-server-unfiltered', selectedYear, isLockedView],
        queryFn: () =>
            transactionsApi.getTransactions({
                page: 1,
                page_size: 1,
                date_from: selectedYear !== null ? isoStartOfYear(selectedYear) : undefined,
                date_to: selectedYear !== null ? isoEndOfYear(selectedYear) : undefined,
            }),
        enabled: !isLockedView && hasSecurityStatusSnapshot,
        staleTime: 30_000,
        retry: 1,
        refetchOnWindowFocus: false,
    });
    const serverModeActive = serverTransactionsQuery.isSuccess && !isLockedView;
    const backendFallbackReadOnly = !isLockedView && serverTransactionsQuery.isError;
    const localReadOnlyMode = backendFallbackReadOnly;
    const buildServerExportParams = useCallback(
        (overrides?: Partial<{
            date_from: string;
            date_to: string;
            columns: string[];
        }>) => ({
            sort_by: sort.sort_by,
            sort_dir: sort.sort_dir,
            date_from: overrides?.date_from ?? serverDateFrom,
            date_to: overrides?.date_to ?? serverDateTo,
            operators: filters.operators,
            apps: filters.apps,
            amount_min: filters.amountMin,
            amount_max: filters.amountMax,
            transaction_type: filters.transaction_type,
            transaction_types: filters.transaction_types,
            currency: filters.currency && filters.currency !== 'ALL' ? filters.currency : undefined,
            card: filters.card,
            days_of_week: filters.days_of_week,
            source_type: serverSourceType,
            source_chat_ids: serverSourceChatIds,
            search: debouncedSearch || undefined,
            columns: overrides?.columns,
        }),
        [
            sort.sort_by,
            sort.sort_dir,
            serverDateFrom,
            serverDateTo,
            filters.operators,
            filters.apps,
            filters.amountMin,
            filters.amountMax,
            filters.transaction_type,
            filters.transaction_types,
            filters.currency,
            filters.card,
            filters.days_of_week,
            serverSourceType,
            debouncedSearch,
        ]
    );

    const parseExportErrorMessage = useCallback(async (err: any) => {
        const responseData = err?.response?.data;
        if (responseData instanceof Blob) {
            try {
                const text = await responseData.text();
                const parsed = JSON.parse(text);
                const detail = parsed?.detail;
                if (detail?.error === 'export_limit_exceeded') {
                    return `Слишком много строк для экспорта (${detail.total}). Лимит: ${detail.limit}. Уточните фильтры.`;
                }
                if (typeof detail === 'string') return detail;
            } catch {
                return 'Не удалось выполнить экспорт';
            }
        }
        if (err?.response?.data?.detail?.error === 'export_limit_exceeded') {
            const detail = err.response.data.detail;
            return `Слишком много строк для экспорта (${detail.total}). Лимит: ${detail.limit}. Уточните фильтры.`;
        }
        return err?.response?.data?.detail || 'Не удалось выполнить экспорт';
    }, []);

    const handleServerExportAll = useCallback(async (columns?: string[]) => {
        try {
            const response = await transactionsApi.exportTransactions(buildServerExportParams({ columns }));
            const fallbackName = `transactions_all_${new Date().toISOString().slice(0, 10)}.xlsx`;
            triggerBlobDownload(response.blob, response.filename || fallbackName);
            showToast('success', 'Экспорт всех транзакций готов');
        } catch (err: any) {
            showToast('error', await parseExportErrorMessage(err));
        }
    }, [buildServerExportParams, parseExportErrorMessage, showToast, triggerBlobDownload]);

    useEffect(() => {
        exportAllRef.current = handleServerExportAll;
    }, [handleServerExportAll]);

    const handleServerExportByPeriod = useCallback(
        async (dateFrom: string, dateTo: string, columns?: string[]) => {
            const exportDateFrom = `${dateFrom}T00:00:00`;
            const exportDateTo = `${dateTo}T23:59:59`;
            try {
                const response = await transactionsApi.exportTransactions(
                    buildServerExportParams({ date_from: exportDateFrom, date_to: exportDateTo, columns })
                );
                const fallbackName = `transactions_${dateFrom}_${dateTo}.xlsx`;
                triggerBlobDownload(response.blob, response.filename || fallbackName);
                showToast('success', 'Экспорт за период готов');
            } catch (err: any) {
                showToast('error', await parseExportErrorMessage(err));
            }
        },
        [buildServerExportParams, parseExportErrorMessage, showToast, triggerBlobDownload]
    );

    const targetScopeForUnlock = useMemo(() => {
        const scopes = (scopesQuery.data || []).filter((scope) => scope.is_active && scope.allow_transactions);
        if (!scopes.length) {
            return null;
        }
        if (selectedYear === null) {
            return scopes[0];
        }
        return (
            scopes.find((scope) => {
                const inYears = !scope.years?.length || scope.years.includes(selectedYear);
                const periodStart = scope.period_start ? new Date(scope.period_start) : null;
                const periodEnd = scope.period_end ? new Date(scope.period_end) : null;
                const inStart = !periodStart || selectedYear >= periodStart.getFullYear();
                const inEnd = !periodEnd || selectedYear <= periodEnd.getFullYear();
                return inYears && inStart && inEnd;
            }) || scopes[0]
        );
    }, [scopesQuery.data, selectedYear]);

    useEffect(() => {
        const needsOtp = needsInitialUnlock || yearRequiresUnlock;
        if (!needsOtp || !targetScopeForUnlock) {
            autoOtpRequestKeyRef.current = null;
            return;
        }
        if (requestScopeCodeMutation.isPending) {
            return;
        }
        if (otpScopeId === targetScopeForUnlock.id && otpSecondsLeft > 0) {
            return;
        }
        const autoKey = `${selectedYear ?? 'all'}:${targetScopeForUnlock.id}`;
        if (autoOtpRequestKeyRef.current === autoKey) {
            return;
        }
        autoOtpRequestKeyRef.current = autoKey;
        requestScopeCodeMutation.mutate(targetScopeForUnlock.id);
    }, [
        needsInitialUnlock,
        yearRequiresUnlock,
        targetScopeForUnlock,
        requestScopeCodeMutation.isPending,
        requestScopeCodeMutation.mutate,
        otpScopeId,
        otpSecondsLeft,
        selectedYear,
    ]);

    const lockedBannerMessage = useMemo(() => {
        const periods = lockedPeriodsQuery.data?.periods || [];
        if (!periods.length) return '';
        const overlaps = periods.filter((period) => {
            if (selectedYear === null) return true;
            const from = new Date(period.date_from);
            const to = new Date(period.date_to);
            if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) return false;
            return selectedYear >= from.getFullYear() && selectedYear <= to.getFullYear();
        });
        if (!overlaps.length) return '';
        if (overlaps.length === 1) {
            const only = overlaps[0];
            return `Есть заблокированный период: ${only.date_from} — ${only.date_to}${only.reason ? ` (${only.reason})` : ''}.`;
        }
        return `Есть ${overlaps.length} заблокированных периодов. Экспорт и доступ к этим датам ограничены.`;
    }, [lockedPeriodsQuery.data, selectedYear]);

    useEffect(() => {
        securityApi.pruneScopeTokenCache();
    }, []);

    useEffect(() => {
        if (prevYearRef.current !== null && prevYearRef.current !== selectedYear && scopesEnabled && !isAdmin) {
            securityApi.clearScopeToken();
            void securityStatusQuery.refetch();
        }
        prevYearRef.current = selectedYear;
    }, [selectedYear, scopesEnabled, securityStatusQuery, isAdmin]);

    useEffect(() => {
        if (!otpExpiresAt) return;
        const timer = window.setInterval(() => {
            const next = Math.max(0, Math.ceil((otpExpiresAt - Date.now()) / 1000));
            setOtpSecondsLeft(next);
            if (next <= 0) {
                setOtpExpiresAt(null);
            }
        }, 1000);
        return () => window.clearInterval(timer);
    }, [otpExpiresAt]);

    useEffect(() => {
        if (!scopesEnabled || selectedYear === null) return;

        if (!isLockedView) {
            lastCachedRestoreYearRef.current = selectedYear;
            return;
        }

        if (lastCachedRestoreYearRef.current === selectedYear) return;
        lastCachedRestoreYearRef.current = selectedYear;

        const restored = securityApi.applyCachedScopeTokenForYear(selectedYear);
        if (restored) {
            Promise.all([securityStatusQuery.refetch(), transactionsInitQuery.refetch()])
                .then(() => syncFromServer(false))
                .catch(() => undefined);
        }
    }, [scopesEnabled, selectedYear, isLockedView, securityStatusQuery, transactionsInitQuery, syncFromServer]);

    const filteredData = useMemo(() => {
        if (!localReadOnlyMode) {
            return [];
        }
        const search = (filters.search || '').trim();

        const dateToEnd = filters.dateTo ? new Date(filters.dateTo) : null;
        if (dateToEnd) {
            dateToEnd.setHours(23, 59, 59, 999);
        }

        return scopedData.filter((tx: Transaction) => {
            const txDate = tx.transaction_date ? new Date(tx.transaction_date) : null;

            if (selectedYear !== null && txDate && txDate.getFullYear() !== selectedYear) return false;

            if (filters.currency && filters.currency !== 'ALL' && tx.currency !== filters.currency) return false;
            if (filters.dateFrom && txDate && txDate < new Date(filters.dateFrom)) return false;
            if (dateToEnd && txDate && txDate > dateToEnd) return false;

            if (filters.days_of_week?.length && txDate) {
                const dayIdx = txDate.getDay();
                if (!filters.days_of_week.includes(dayIdx)) return false;
            }

            const amount = tx.amount ? Math.abs(parseFloat(tx.amount)) : undefined;
            if (filters.amountMin && amount !== undefined && !Number.isNaN(amount) && amount < parseFloat(filters.amountMin)) return false;
            if (filters.amountMax && amount !== undefined && !Number.isNaN(amount) && amount > parseFloat(filters.amountMax)) return false;

            if (filters.operators?.length) {
                const op = (tx.operator_raw || '').toLowerCase();
                if (!filters.operators.some((o) => op.includes(o.toLowerCase()))) return false;
            }

            if (filters.apps?.length) {
                const app = (tx.application_mapped || '').toLowerCase();
                if (!filters.apps.some((a) => app.includes(a.toLowerCase()))) return false;
            }

            if (filters.transaction_type && tx.transaction_type !== filters.transaction_type) return false;
            if (filters.transaction_types?.length && !filters.transaction_types.includes(tx.transaction_type)) return false;
            if (filters.source_channel && tx.source_channel !== filters.source_channel) return false;
            if (filters.source_chat_ids?.length) {
                const txChatId = tx.source_chat_id ?? null;
                if (!txChatId || !filters.source_chat_ids.includes(txChatId)) return false;
            }
            if (filters.card && tx.card_last_4 !== filters.card) return false;

            if (search) {
                const tokens = search.match(/"[^"]+"|\S+/g) || [];
                const blob = `${tx.operator_raw || ''} ${tx.application_mapped || ''} ${tx.raw_message || ''} ${tx.amount || ''} ${tx.currency || ''}`.toLowerCase();
                const statusBlob = `${tx.parsing_method || ''} ${tx.transaction_type_display || ''} ${tx.source_display || ''}`.toLowerCase();
                const sellerBlob = `${tx.operator_raw || ''} ${tx.application_mapped || ''}`.toLowerCase();
                const amountVal = tx.amount ? Math.abs(parseFloat(tx.amount)).toString() : '';
                const dateStr = tx.transaction_date || '';

                const matches = tokens.every((token) => {
                    const neg = token.startsWith('-');
                    const cleanToken = token.replace(/^[-]/, '');
                    const hasField = cleanToken.includes(':');
                    const [rawKey, ...rest] = hasField ? cleanToken.split(':') : ['text', cleanToken];
                    const key = rawKey.toLowerCase();
                    const valueRaw = rest.join(':') || cleanToken;
                    const value = valueRaw.replace(/^"|"$/g, '').toLowerCase();

                    const apply = (cond: boolean) => (neg ? !cond : cond);

                    switch (key) {
                        case 'amount':
                            return apply(amountVal.includes(value));
                        case 'date':
                            return apply(dateStr.toLowerCase().includes(value));
                        case 'status':
                            return apply(statusBlob.includes(value));
                        case 'seller':
                            return apply(sellerBlob.includes(value));
                        default:
                            return apply(blob.includes(cleanToken.toLowerCase()));
                    }
                });

                if (!matches) return false;
            }

            return true;
        });
    }, [localReadOnlyMode, scopedData, filters, selectedYear]);

    const sortComparator = useCallback((key: string | undefined, dir: 'asc' | 'desc') => {
        const sortKey = key || 'transaction_date';
        const dirMultiplier = dir === 'asc' ? 1 : -1;
        const getValue = (tx: Transaction) => {
            if (['operation_number', 'date_time', 'transaction_date', 'time', 'day'].includes(sortKey)) {
                return tx.transaction_date ? new Date(tx.transaction_date).getTime() : 0;
            }
            const value = (tx as any)[sortKey];
            if (sortKey === 'amount' || sortKey === 'balance_after') {
                const num = parseFloat(value ?? '0');
                return Number.isNaN(num) ? 0 : num;
            }
            if (sortKey === 'transaction_type') {
                return String(tx.transaction_type_display || tx.transaction_type || '').toLowerCase();
            }
            if (sortKey === 'source_type') {
                return String(tx.source_chat_title || tx.source_display || tx.source_type || '').toLowerCase();
            }
            if (sortKey === 'is_p2p') {
                return tx.is_p2p ? 1 : 0;
            }
            if (typeof value === 'string') return value.toLowerCase();
            return value ?? '';
        };
        return (a: Transaction, b: Transaction) => {
            const av = getValue(a);
            const bv = getValue(b);
            if (av < bv) return -1 * dirMultiplier;
            if (av > bv) return 1 * dirMultiplier;
            return 0;
        };
    }, [sort.sort_by, sort.sort_dir]);

    const sortedData = useMemo(() => {
        return [...filteredData].sort(sortComparator(sort.sort_by, sort.sort_dir));
    }, [filteredData, sort.sort_by, sort.sort_dir, sortComparator]);

    const allSortedData = useMemo(() => {
        if (!localReadOnlyMode) {
            return [];
        }
        return [...scopedData].sort(sortComparator(sort.sort_by, sort.sort_dir));
    }, [localReadOnlyMode, scopedData, sort.sort_by, sort.sort_dir, sortComparator]);

    // Load operators from reference dictionary
    const { data: referenceData } = useQuery({
        queryKey: ['reference-operators-for-autocomplete'],
        queryFn: () => referenceApi.getOperators({ all: true }),
        staleTime: 5 * 60 * 1000, // 5 minutes
    });

    // Combine operators from transactions and reference
    const operatorOptions = useMemo(() => {
        const set = new Set<string>();
        if (localReadOnlyMode) {
            scopedData.forEach((tx) => {
                if (tx.operator_raw) set.add(tx.operator_raw);
            });
        } else {
            (transactionsInitQuery.data?.operators || []).forEach((operator) => set.add(operator));
        }
        // From reference dictionary
        referenceData?.items?.forEach((op) => {
            if (op.operator_name) set.add(op.operator_name);
        });
        return Array.from(set).sort((a, b) => a.localeCompare(b));
    }, [localReadOnlyMode, scopedData, transactionsInitQuery.data, referenceData]);

    // Combine apps from transactions and reference
    const appOptions = useMemo(() => {
        const set = new Set<string>();
        if (localReadOnlyMode) {
            scopedData.forEach((tx) => {
                if (tx.application_mapped) set.add(tx.application_mapped);
            });
        } else {
            (transactionsInitQuery.data?.applications || []).forEach((app) => set.add(app));
        }
        // From reference dictionary
        referenceData?.items?.forEach((op) => {
            if (op.application_name) set.add(op.application_name);
        });
        return Array.from(set).sort((a, b) => a.localeCompare(b));
    }, [localReadOnlyMode, scopedData, transactionsInitQuery.data, referenceData]);

    const telegramSourceOptions = useMemo(() => {
        if (!localReadOnlyMode) {
            return (transactionsInitQuery.data?.telegram_sources || []).slice().sort((a, b) => a.title.localeCompare(b.title));
        }
        const sourceMap = new Map<number, { chat_id: number; title: string; chat_type?: 'bot' | 'group' | 'supergroup' | 'channel' | 'private' | null; count: number }>();
        scopedData.forEach((tx) => {
            if (tx.source_channel !== 'TELEGRAM' || tx.source_chat_id === null || tx.source_chat_id === undefined || tx.source_chat_id === 0) {
                return;
            }
            const existing = sourceMap.get(tx.source_chat_id);
            if (existing) {
                existing.count += 1;
                return;
            }
            sourceMap.set(tx.source_chat_id, {
                chat_id: tx.source_chat_id,
                title: tx.source_chat_title || tx.source_display || `Telegram ${tx.source_chat_id}`,
                chat_type: tx.source_origin_type || null,
                count: 1,
            });
        });
        return Array.from(sourceMap.values()).sort((a, b) => a.title.localeCompare(b.title));
    }, [localReadOnlyMode, scopedData, transactionsInitQuery.data]);

    const total = sortedData.length;
    const serverTotal = serverTransactionsQuery.data?.total || 0;
    const effectiveTotal = serverModeActive ? serverTotal : (backendFallbackReadOnly ? total : 0);
    const effectiveItems = serverModeActive ? (serverTransactionsQuery.data?.items || []) : [];
    const localScopedYearData = useMemo(() => {
        return scopedData.filter((tx) => {
            if (selectedYear === null) return true;
            const txDate = tx.transaction_date ? new Date(tx.transaction_date) : null;
            return Boolean(txDate && !Number.isNaN(txDate.getTime()) && txDate.getFullYear() === selectedYear);
        });
    }, [scopedData, selectedYear]);
    const localLatestTransactionAtMs = useMemo(() => {
        return localScopedYearData.reduce<number | null>((latest, tx) => {
            const parsed = tx.transaction_date ? new Date(tx.transaction_date).getTime() : Number.NaN;
            if (!Number.isFinite(parsed)) return latest;
            if (latest === null || parsed > latest) return parsed;
            return latest;
        }, null);
    }, [localScopedYearData]);
    const serverLatestTransactionAtMs = useMemo(() => {
        const raw = serverUnfilteredQuery.data?.latest_transaction_at || serverTransactionsQuery.data?.latest_transaction_at;
        if (!raw) return null;
        const parsed = new Date(raw).getTime();
        return Number.isFinite(parsed) ? parsed : null;
    }, [serverTransactionsQuery.data?.latest_transaction_at, serverUnfilteredQuery.data?.latest_transaction_at]);
    const serverOldestTransactionAtMs = useMemo(() => {
        const raw = serverUnfilteredQuery.data?.oldest_transaction_at || serverTransactionsQuery.data?.oldest_transaction_at;
        if (!raw) return null;
        const parsed = new Date(raw).getTime();
        return Number.isFinite(parsed) ? parsed : null;
    }, [serverTransactionsQuery.data?.oldest_transaction_at, serverUnfilteredQuery.data?.oldest_transaction_at]);
    const desktopSyncLagging = useMemo(() => {
        if (serverLatestTransactionAtMs === null) return false;
        if (localLatestTransactionAtMs === null) return true;
        return localLatestTransactionAtMs < serverLatestTransactionAtMs;
    }, [localLatestTransactionAtMs, serverLatestTransactionAtMs]);

    useEffect(() => {
        setPage(1);
    }, [selectedYear]);

    useEffect(() => {
        hasScopedPageRestoreRef.current = false;
        try {
            const raw = localStorage.getItem(pageStateStorageKey);
            if (!raw) return;
            const parsed = JSON.parse(raw) as { page?: number; selectedYear?: number | null };
            const restoredPage = Number(parsed?.page);
            if (Number.isFinite(restoredPage) && restoredPage >= 1) {
                setPage(restoredPage);
                hasScopedPageRestoreRef.current = true;
            }
            if (parsed?.selectedYear === null) {
                setSelectedYear(null);
                hasScopedPageRestoreRef.current = true;
            } else if (Number.isFinite(parsed?.selectedYear)) {
                setSelectedYear(Number(parsed.selectedYear));
                hasScopedPageRestoreRef.current = true;
            }
        } catch {
            // ignore broken local storage payload
        }
    }, [pageStateStorageKey]);

    useEffect(() => {
        try {
            localStorage.setItem(
                pageStateStorageKey,
                JSON.stringify({
                    page,
                    selectedYear,
                    updatedAt: Date.now(),
                }),
            );
        } catch {
            // ignore storage write errors
        }
    }, [pageStateStorageKey, page, selectedYear]);

    useEffect(() => {
        const maxPage = Math.max(1, Math.ceil(effectiveTotal / pageSize));
        if (page > maxPage) {
            setPage(maxPage);
        }
    }, [page, pageSize, effectiveTotal]);

    const paginatedItems = useMemo(() => {
        const start = (page - 1) * pageSize;
        const end = start + pageSize;
        return sortedData.slice(start, end);
    }, [sortedData, page, pageSize]);

    const handleQueryChange = useCallback((next: Partial<FiltersState> & { sort_by?: string; sort_dir?: 'asc' | 'desc'; search?: string; filters?: any }) => {
        const currentSort = currentSortRef.current;
        const currentFilters = currentFiltersRef.current;
        const nextSort: SortState = {
            sort_by: next.sort_by || currentSort.sort_by,
            sort_dir: next.sort_dir || currentSort.sort_dir,
        };
        const nextFilters = buildNextFiltersState(next);

        const sortChanged = !areSortStatesEqual(currentSort, nextSort);
        const filtersChanged = !areFiltersStatesEqual(currentFilters, nextFilters);

        if (sortChanged) {
            currentSortRef.current = nextSort;
            setSort(nextSort);
        }
        if (filtersChanged) {
            currentFiltersRef.current = nextFilters;
            setFilters(nextFilters);
        }
        if ((sortChanged || filtersChanged) && currentPageRef.current !== 1) {
            setPage(1);
        }
    }, []);

    const handlePageChange = useCallback((nextPage: number) => {
        setPage(Math.max(1, nextPage));
    }, []);

    const handlePageSizeChange = useCallback((nextSize: number) => {
        setPageSize(nextSize);
        setPage(1);
    }, []);

    const hasActiveFilters = useMemo(() => {
        const search = (filters.search || '').trim();
        return Boolean(
            search ||
            filters.dateFrom ||
            filters.dateTo ||
            (filters.operators && filters.operators.length) ||
            (filters.apps && filters.apps.length) ||
            filters.amountMin ||
            filters.amountMax ||
            filters.transaction_type ||
            (filters.transaction_types && filters.transaction_types.length) ||
            (filters.currency && filters.currency !== 'ALL') ||
            filters.card ||
            (filters.days_of_week && filters.days_of_week.length) ||
            filters.source_channel ||
            (filters.source_chat_ids && filters.source_chat_ids.length)
        );
    }, [filters]);

    const showFilteredOutBanner =
        serverModeActive &&
        !isLockedView &&
        hasActiveFilters &&
        (serverTransactionsQuery.data?.total || 0) === 0 &&
        (serverUnfilteredQuery.data?.total || 0) > 0;

    const resetCurrentScopeViewState = useCallback(() => {
        try {
            localStorage.removeItem(pageStateStorageKey);
            localStorage.removeItem(tableStateStorageKey);
        } catch {
            // ignore storage cleanup errors
        }
        hasScopedPageRestoreRef.current = false;
        setSort({ sort_by: 'transaction_date', sort_dir: 'asc' });
        setFilters({ currency: 'ALL' });
        setPageSize(100);
        setPage(1);
        setTableResetViewToken((prev) => prev + 1);
        showToast('success', 'Фильтры и вид сброшены для текущего пользователя');
    }, [pageStateStorageKey, tableStateStorageKey, showToast]);

    const handleTransactionsUpdated = useCallback((txs: Transaction[]) => {
        upsertTransactions(txs);
    }, [upsertTransactions]);

    const handleTransactionsDeleted = useCallback((ids: number[]) => {
        removeTransactions(ids);
    }, [removeTransactions]);

    const handleTransactionsFieldsUpdated = useCallback((updates: Array<{ id: number; fields: Record<string, any> }>) => {
        updateTransactionFields(updates);
    }, [updateTransactionFields]);

    const handleCreateTransaction = useCallback(async (payload: CreateTransactionRequest) => {
        const created = await transactionsApi.createTransaction(payload);
        upsertTransactions([created]);
        const nextTotal = effectiveTotal + 1;
        const nextMaxPage = Math.max(1, Math.ceil(nextTotal / pageSize));
        setPage(nextMaxPage);
        setHighlightRowId(created.id);
        setHighlightRowIds([created.id]);
        setHighlightDurationMs(3000);
        setAddModalOpen(false);
    }, [pageSize, effectiveTotal, upsertTransactions]);

    useEffect(() => {
        if (!highlightRowId && !highlightRowIds.length) return;
        const t = setTimeout(() => {
            setHighlightRowId(null);
            setHighlightRowIds([]);
        }, highlightDurationMs);
        return () => clearTimeout(t);
    }, [highlightDurationMs, highlightRowId, highlightRowIds]);

    const tableData = isLockedView ? [] : (serverModeActive ? effectiveItems : (backendFallbackReadOnly ? paginatedItems : []));
    const tableTotal = isLockedView ? 0 : effectiveTotal;
    const tableExportViewRows = isLockedView ? [] : (serverModeActive ? effectiveItems : (backendFallbackReadOnly ? sortedData : []));
    const tableExportAllRows = isLockedView ? [] : (backendFallbackReadOnly ? allSortedData : []);
    const tableLoading =
        (offlineLoading && !isOfflineReady) ||
        verifyScopeCodeMutation.isPending ||
        requestScopeCodeMutation.isPending ||
        (!isLockedView && !serverModeActive && serverTransactionsQuery.isFetching && !backendFallbackReadOnly) ||
        (!isLockedView && serverTransactionsQuery.isLoading);

    return (
        <div className="tx-shell">
            <header className="tx-head">
                <div className="tx-head-row">
                    <div className="tx-head-text">
                        <h1 className="tx-title">
                            Транзакции
                        </h1>
                    </div>
                </div>
            </header>

            {!hasSecurityStatusSnapshot && (
                <div className="tx-banner is-warn">
                    <ShieldAlert size={16} className="tx-banner-icon" />
                    <div className="tx-banner-body">
                        <div className="tx-banner-title">Проверяем доступ…</div>
                        {securityStatusQuery.isError && (
                            <div className="tx-banner-desc">{securityStatusErrorText}</div>
                        )}
                    </div>
                </div>
            )}

            {(needsInitialUnlock || yearRequiresUnlock) && (
                <div className="tx-otp">
                    <div className="tx-otp-head">
                        <Lock size={14} style={{ color: 'var(--warning)' }} />
                        <div className="tx-otp-title">
                            Требуется OTP-код
                            {selectedYear ? (
                                <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>
                                    {' · '}папка {selectedYear}
                                </span>
                            ) : null}
                        </div>
                    </div>
                    <div className="tx-banner-desc" style={{ color: 'var(--text-secondary)', fontSize: 12.5 }}>
                        Код отправляется через AuthBot администраторам. После запроса введите код ниже.
                    </div>
                    <div className="tx-otp-form">
                        <input
                            type="text"
                            value={otpCode}
                            onChange={(e) => setOtpCode(e.target.value)}
                            placeholder="OTP-код"
                            className="tx-otp-input"
                        />
                        <button
                            type="button"
                            onClick={() => {
                                if (!targetScopeForUnlock) {
                                    showToast('error', 'Не найден активный scope для OTP');
                                    return;
                                }
                                requestScopeCodeMutation.mutate(targetScopeForUnlock.id);
                            }}
                            disabled={requestScopeCodeMutation.isPending}
                            className="tx-btn"
                        >
                            {requestScopeCodeMutation.isPending ? 'Запрос…' : 'Запросить код'}
                        </button>
                        <button
                            type="button"
                            onClick={() => {
                                if (!otpScopeId) {
                                    showToast('error', 'Сначала запросите OTP-код');
                                    return;
                                }
                                if (!otpCode.trim()) {
                                    showToast('error', 'Введите OTP-код');
                                    return;
                                }
                                verifyScopeCodeMutation.mutate({
                                    scopeId: otpScopeId,
                                    code: otpCode.trim(),
                                });
                            }}
                            disabled={verifyScopeCodeMutation.isPending}
                            className="tx-btn tx-btn-primary"
                        >
                            {verifyScopeCodeMutation.isPending ? 'Проверка…' : 'Подтвердить'}
                        </button>
                        {otpSecondsLeft > 0 && (
                            <span className="tx-otp-meta">код действует {otpSecondsLeft}с</span>
                        )}
                    </div>
                </div>
            )}

            <LockedPeriodBanner message={lockedBannerMessage} />

            {backendFallbackReadOnly && (
                <div className="tx-banner is-error">
                    <Plug size={16} className="tx-banner-icon" />
                    <div className="tx-banner-body">
                        <div className="tx-banner-title">Сервер недоступен</div>
                        <div className="tx-banner-desc">
                            Включён read-only fallback из локального кеша.
                        </div>
                    </div>
                </div>
            )}

            {showFilteredOutBanner && (
                <div className="tx-banner is-warn">
                    <AlertCircle size={16} className="tx-banner-icon" />
                    <div className="tx-banner-body">
                        <div className="tx-banner-title">Данные скрыты текущими фильтрами</div>
                        <div className="tx-banner-desc">
                            Сбросьте сохранённое состояние, чтобы увидеть весь набор данных пользователя.
                        </div>
                    </div>
                    <div className="tx-banner-actions">
                        <button
                            type="button"
                            onClick={resetCurrentScopeViewState}
                            className="tx-btn"
                        >
                            Сбросить вид
                        </button>
                    </div>
                </div>
            )}

            <div className="tx-table-wrap">
                <TransactionTable
                    data={tableData}
                    total={tableTotal}
                    page={page}
                    pageSize={pageSize}
                    stateScopeKey={stateScopeKey}
                    resetViewStateToken={tableResetViewToken}
                    selectedYear={selectedYear}
                    availableYears={availableYears}
                    onYearChange={setSelectedYear}
                    serverModeActive={serverModeActive}
                    isLoading={tableLoading}
                    exportViewRows={tableExportViewRows}
                    exportAllRows={tableExportAllRows}
                    onServerExportAll={handleServerExportAll}
                    onServerExportByPeriod={handleServerExportByPeriod}
                    highlightRowId={highlightRowId}
                    highlightRowIds={highlightRowIds}
                    focusColumnId={focusColumnId}
                    focusColumnToken={focusColumnToken}
                    onAddClick={() => {
                        if (!isLockedView) {
                            setAddModalOpen(true);
                        }
                    }}
                    onTransactionsUpdated={handleTransactionsUpdated}
                    onTransactionsDeleted={handleTransactionsDeleted}
                    onTransactionsFieldsUpdated={handleTransactionsFieldsUpdated}
                    onQueryChange={handleQueryChange}
                    onPageChange={handlePageChange}
                    onPageSizeChange={handlePageSizeChange}
                    operatorOptions={operatorOptions}
                    appOptions={appOptions}
                    telegramSourceOptions={telegramSourceOptions}
                    syncState={{
                        isSyncing: syncProgress.status === 'running',
                        progress: syncProgress,
                        lastSyncAt: lastSyncAt ? new Date(lastSyncAt).getTime() : null,
                        isOfflineReady,
                        onSync: syncFromServer,
                        freshness: {
                            serverLatestTransactionAt: serverLatestTransactionAtMs,
                            serverOldestTransactionAt: serverOldestTransactionAtMs,
                            localLatestTransactionAt: localLatestTransactionAtMs,
                            desktopLagging: desktopSyncLagging,
                        },
                    }}
                />
            </div>

            <AddTransactionModal
                isOpen={addModalOpen}
                onClose={() => setAddModalOpen(false)}
                onSubmit={handleCreateTransaction}
                operatorOptions={operatorOptions}
                appOptions={appOptions}
            />
        </div>
    );
}
