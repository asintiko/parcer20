/**
 * API client for backend communication
 */
import axios from 'axios';

const normalizeBaseUrl = (url?: string) => {
    if (!url) return undefined;
    try {
        const parsed = new URL(url);
        if (parsed.hostname === 'localhost') {
            parsed.hostname = '127.0.0.1';
        }
        return parsed.toString().replace(/\/$/, '');
    } catch {
        return url;
    }
};

const envApiUrl = normalizeBaseUrl((import.meta as any).env?.VITE_API_URL);
const defaultHost =
    typeof window !== 'undefined'
        ? (window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname || '127.0.0.1')
        : '127.0.0.1';
const API_BASE_URL = envApiUrl || `http://${defaultHost}:8000`;

export const apiClient = axios.create({
    baseURL: API_BASE_URL,
    headers: {
        'Content-Type': 'application/json',
    },
});

// Types
export interface Transaction {
    id: number;
    transaction_date: string;
    amount: string;
    currency: string;
    card_last_4: string | null;
    operator_raw: string | null;
    application_mapped: string | null;
    transaction_type: 'DEBIT' | 'CREDIT' | 'CONVERSION' | 'REVERSAL';
    balance_after: string | null;
    source_type: 'MANUAL' | 'AUTO';
    parsing_method: string | null;
    parsing_confidence: number | null;
    is_p2p?: boolean;
    created_at: string;
    raw_message?: string | null;
}

export interface TransactionListResponse {
    total: number;
    page: number;
    page_size: number;
    items: Transaction[];
}

export interface TransactionsQueryParams {
    page?: number;
    page_size?: number;
    sort_by?: string;
    sort_dir?: 'asc' | 'desc';
    date_from?: string;
    date_to?: string;
    operators?: string[];
    apps?: string[];
    operator?: string;
    app?: string;
    amount_min?: string;
    amount_max?: string;
    parsing_method?: string;
    confidence_min?: number;
    confidence_max?: number;
    search?: string;
    source_type?: 'AUTO' | 'MANUAL';
    transaction_type?: 'DEBIT' | 'CREDIT' | 'CONVERSION' | 'REVERSAL';
    transaction_types?: string[];
    currency?: 'UZS' | 'USD';
    card?: string;
    days_of_week?: number[];
}

// Update/Delete types
export interface TransactionUpdateRequest {
    transaction_date?: string;
    operator_raw?: string;
    application_mapped?: string;
    amount?: string;
    balance_after?: string;
    card_last_4?: string;
    transaction_type?: 'DEBIT' | 'CREDIT' | 'CONVERSION' | 'REVERSAL';
    currency?: 'UZS' | 'USD';
    source_type?: 'AUTO' | 'MANUAL';
    parsing_method?: string;
    parsing_confidence?: number;
}

export interface TransactionUpdateResponse {
    success: boolean;
    message: string;
    transaction: Transaction;
}

export interface DeleteResponse {
    success: boolean;
    message: string;
    deleted_id: number;
}

export interface BulkDeleteRequest {
    ids: number[];
}

export interface BulkDeleteResponse {
    success: boolean;
    deleted_count: number;
    failed_ids: number[];
    errors: string[];
}

export interface BulkUpdatePayload {
    updates: Array<{
        id: number;
        fields: Record<string, any>;
    }>;
}

export interface BulkUpdateResponse {
    success: boolean;
    updated_count: number;
    failed_ids: number[];
    errors: string[];
}

export interface CreateTransactionRequest {
    datetime: string;
    operator: string;
    amount: string;
    card_last4: string;
    transaction_type: 'DEBIT' | 'CREDIT' | 'CONVERSION' | 'REVERSAL';
    currency: 'UZS' | 'USD';
    app?: string | null;
    balance?: string | null;
    is_p2p?: boolean;
    raw_text?: string | null;
}

export interface TopAgentResponse {
    period_start: string;
    period_end: string;
    transaction_count: number;
    top_application: string | null;
    top_application_count: number;
    top_application_volume: string;
    total_volume: string;
    insight: string;
}

export interface SummaryResponse {
    total_transactions: number;
    debit_count: number;
    credit_count: number;
    gpt_parsed_count: number;
    gpt_usage_percentage: number;
    total_volume_uzs: string;
    average_confidence: number;
}

// API methods
export const transactionsApi = {
    getTransactions: async (params: TransactionsQueryParams): Promise<TransactionListResponse> => {
        const query: Record<string, any> = {
            page: params.page,
            page_size: params.page_size,
            sort_by: params.sort_by,
            sort_dir: params.sort_dir,
            date_from: params.date_from,
            date_to: params.date_to,
            operator: params.operator,
            app: params.app,
            amount_min: params.amount_min,
            amount_max: params.amount_max,
            parsing_method: params.parsing_method,
            confidence_min: params.confidence_min,
            confidence_max: params.confidence_max,
            search: params.search,
            source_type: params.source_type,
            transaction_type: params.transaction_type,
            currency: params.currency,
            card: params.card,
        };

        if (params.operators?.length) {
            query.operators = params.operators.join(',');
        }
        if (params.apps?.length) {
            query.apps = params.apps.join(',');
        }
        if (params.transaction_types?.length) {
            query.transaction_types = params.transaction_types.join(',');
        }
        if (params.days_of_week?.length) {
            query.days_of_week = params.days_of_week.join(',');
        }

        const response = await apiClient.get<TransactionListResponse>('/api/transactions/', { params: query });
        return response.data;
    },

    getTransaction: async (id: number): Promise<Transaction> => {
        const response = await apiClient.get<Transaction>(`/api/transactions/${id}`);
        return response.data;
    },

    updateTransaction: async (id: number, data: TransactionUpdateRequest): Promise<TransactionUpdateResponse> => {
        const response = await apiClient.put<TransactionUpdateResponse>(`/api/transactions/${id}`, data);
        return response.data;
    },

    deleteTransaction: async (id: number): Promise<DeleteResponse> => {
        const response = await apiClient.delete<DeleteResponse>(`/api/transactions/${id}`);
        return response.data;
    },

    bulkDeleteTransactions: async (ids: number[]): Promise<BulkDeleteResponse> => {
        const response = await apiClient.post<BulkDeleteResponse>('/api/transactions/bulk-delete', { ids });
        return response.data;
    },

    bulkUpdateTransactions: async (payload: BulkUpdatePayload): Promise<BulkUpdateResponse> => {
        const response = await apiClient.patch<BulkUpdateResponse>('/api/transactions/bulk-update', payload);
        return response.data;
    },

    createTransaction: async (payload: CreateTransactionRequest): Promise<Transaction> => {
        const response = await apiClient.post<Transaction>('/api/transactions/', payload);
        return response.data;
    },
};

export const analyticsApi = {
    getTopAgent: async (): Promise<TopAgentResponse> => {
        const response = await apiClient.get<TopAgentResponse>('/api/analytics/top-agent');
        return response.data;
    },

    getSummary: async (): Promise<SummaryResponse> => {
        const response = await apiClient.get<SummaryResponse>('/api/analytics/summary');
        return response.data;
    },
};

// Reference types
export interface OperatorReference {
    id: number;
    operator_name: string;
    application_name: string;
    is_p2p: boolean;
    is_active: boolean;
}

export interface OperatorReferenceListResponse {
    total: number;
    page: number;
    page_size: number;
    items: OperatorReference[];
}

export interface OperatorReferenceCreate {
    operator_name: string;
    application_name: string;
    is_p2p?: boolean;
    is_active?: boolean;
}

export interface OperatorReferenceUpdate {
    operator_name?: string;
    application_name?: string;
    is_p2p?: boolean;
    is_active?: boolean;
}

// Reference API methods
export const referenceApi = {
    getOperators: async (params: {
        page?: number;
        page_size?: number;
        search?: string;
        application?: string;
        is_p2p?: boolean;
        is_active?: boolean;
    }): Promise<OperatorReferenceListResponse> => {
        const response = await apiClient.get<OperatorReferenceListResponse>('/api/reference', { params });
        return response.data;
    },

    createOperator: async (operator: OperatorReferenceCreate): Promise<OperatorReference> => {
        const response = await apiClient.post<OperatorReference>('/api/reference', operator);
        return response.data;
    },

    updateOperator: async (id: number, operator: OperatorReferenceUpdate): Promise<OperatorReference> => {
        const response = await apiClient.put<OperatorReference>(`/api/reference/${id}`, operator);
        return response.data;
    },

    deleteOperator: async (id: number): Promise<void> => {
        await apiClient.delete(`/api/reference/${id}`);
    },

    getApplications: async (): Promise<string[]> => {
        const response = await apiClient.get<string[]>('/api/reference/applications');
        return response.data;
    },

    exportToExcel: async (): Promise<Blob> => {
        const response = await apiClient.get('/api/reference/export/excel', {
            responseType: 'blob',
        });
        return response.data;
    },

    importFromExcel: async (file: File): Promise<{ imported: number; skipped: number; errors: string[] }> => {
        const formData = new FormData();
        formData.append('file', file);
        const response = await apiClient.post('/api/reference/import/excel', formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        });
        return response.data;
    },
};

// Automation types
export interface AnalyzeRequest {
    limit?: number;
    only_unmapped?: boolean;
    currency_filter?: string;
}

export interface AnalyzeResponse {
    task_id: string;
    status: string;
    message: string;
}

export interface AnalyzeStatusResponse {
    task_id: string;
    status: string;
    progress: {
        total: number;
        processed: number;
        percent: number;
    };
    results?: {
        suggestions_count: number;
        high_confidence: number;
        low_confidence: number;
    };
}

export interface AISuggestion {
    id: string;
    transaction_id: string;
    operator_raw: string;
    current_application: string | null;
    suggested_application: string;
    confidence: number;
    reasoning: string;
    is_new_application: boolean;
    is_p2p: boolean;
    status: string;
    created_at: string;
}

// Automation API methods
export const automationApi = {
    analyzeTransactions: async (request: AnalyzeRequest): Promise<AnalyzeResponse> => {
        const response = await apiClient.post<AnalyzeResponse>('/api/automation/analyze-transactions', request);
        return response.data;
    },

    getAnalyzeStatus: async (taskId: string): Promise<AnalyzeStatusResponse> => {
        const response = await apiClient.get<AnalyzeStatusResponse>(`/api/automation/analyze-status/${taskId}`);
        return response.data;
    },

    getSuggestions: async (params: {
        status?: string;
        confidence_min?: number;
        task_id?: string;
    }): Promise<AISuggestion[]> => {
        const response = await apiClient.get<AISuggestion[]>('/api/automation/suggestions', { params });
        return response.data;
    },

    applySuggestion: async (suggestionId: string): Promise<{ success: boolean; transaction_id: string }> => {
        const response = await apiClient.post(`/api/automation/suggestions/${suggestionId}/apply`);
        return response.data;
    },

    rejectSuggestion: async (suggestionId: string): Promise<{ success: boolean }> => {
        const response = await apiClient.post(`/api/automation/suggestions/${suggestionId}/reject`);
        return response.data;
    },

    batchApplySuggestions: async (suggestionIds: string[]): Promise<{
        success: boolean;
        applied: number;
        errors: Array<{ suggestion_id: string; error: string }>;
    }> => {
        const response = await apiClient.post('/api/automation/suggestions/batch-apply', suggestionIds);
        return response.data;
    },
};

// Userbot types
export interface UserbotConfig {
    api_id: string;
    api_hash: string;
    phone_number: string;
    target_chat_ids: string[];
}

export interface UserbotStatus {
    is_connected: boolean;
    phone_number?: string;
    monitored_chats?: string[];
}

// Userbot API methods
export const userbotApi = {
    getConfig: async (): Promise<UserbotConfig> => {
        const response = await apiClient.get<UserbotConfig>('/api/userbot/config');
        return response.data;
    },

    updateConfig: async (config: UserbotConfig): Promise<{ success: boolean }> => {
        const response = await apiClient.post('/api/userbot/config', config);
        return response.data;
    },

    getStatus: async (): Promise<UserbotStatus> => {
        const response = await apiClient.get<UserbotStatus>('/api/userbot/status');
        return response.data;
    },

    connect: async (): Promise<{ success: boolean; message: string }> => {
        const response = await apiClient.post('/api/userbot/connect');
        return response.data;
    },

    disconnect: async (): Promise<{ success: boolean; message: string }> => {
        const response = await apiClient.post('/api/userbot/disconnect');
        return response.data;
    },
};

// Auth types
export interface QRLoginResponse {
    session_id: string;
    qr_code: string;
    url: string;
    expires_in: number;
}

export interface LoginStatusResponse {
    status: string;
    message?: string;
    token?: string;
    user?: {
        id: number;
        first_name: string;
        last_name?: string;
        username?: string;
        phone?: string;
    };
}

export interface UserInfo {
    user_id: number;
    phone: string;
    exp: number;
}

// Auth API methods
export const authApi = {
    generateQR: async (): Promise<QRLoginResponse> => {
        const response = await apiClient.post<QRLoginResponse>('/api/auth/qr/generate');
        return response.data;
    },

    checkQRStatus: async (sessionId: string): Promise<LoginStatusResponse> => {
        const response = await apiClient.get<LoginStatusResponse>(`/api/auth/qr/status/${sessionId}`);
        return response.data;
    },

    cleanupSession: async (sessionId: string): Promise<{ success: boolean }> => {
        const response = await apiClient.delete(`/api/auth/qr/cleanup/${sessionId}`);
        return response.data;
    },

    logout: async (): Promise<{ success: boolean; message: string }> => {
        const token = localStorage.getItem('auth_token');
        const response = await apiClient.post('/api/auth/logout', {}, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        return response.data;
    },

    getCurrentUser: async (): Promise<UserInfo> => {
        const token = localStorage.getItem('auth_token');
        const response = await apiClient.get<UserInfo>('/api/auth/me', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        return response.data;
    },

    verifyToken: async (): Promise<{ valid: boolean; user_id: number }> => {
        const token = localStorage.getItem('auth_token');
        const response = await apiClient.get('/api/auth/verify', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        return response.data;
    },
};
