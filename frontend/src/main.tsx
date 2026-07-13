import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient } from '@tanstack/react-query'
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client'
import { createSyncStoragePersister } from '@tanstack/query-sync-storage-persister'
import { ThemeProvider as AppThemeProvider } from './contexts/ThemeContext'
import { AuthProvider } from './contexts/AuthContext'
import { AiAgentProvider } from './contexts/AiAgentContext'
import { ToastProvider } from './components/Toast'
import { CssBaseline, ThemeProvider as MuiThemeProvider } from '@mui/material'
import App from './App.tsx'
import './index.css'
import { muiTheme } from './styles/muiTheme'
import { initializeElectronSecurityState } from './services/api'

const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            refetchOnWindowFocus: false,
            retry: 1,
            staleTime: 30000, // 30 seconds
        },
    },
})

/**
 * Cross-session cache only for light reference/meta queries. Transactions live
 * in Dexie (see syncManager) and MUST NOT be persisted here — they are heavy,
 * scope-sensitive and already incrementally mirrored. Server-paginated list
 * queries are excluded so a restart never replays a full /api/transactions load.
 */
const PERSISTED_QUERY_KEYS = new Set<string>([
    'security-status',
    'security-scopes',
    'security-locked-periods',
    'transactions-init',
    'reference-operators-for-autocomplete',
])

const queryPersister = createSyncStoragePersister({
    storage: typeof window !== 'undefined' ? window.localStorage : undefined,
    key: 'tbsparcer-query-cache',
    throttleTime: 2000,
})

const renderApp = () => {
    ReactDOM.createRoot(document.getElementById('root')!).render(
        <React.StrictMode>
            <AppThemeProvider>
                <MuiThemeProvider theme={muiTheme}>
                    <CssBaseline />
                    <PersistQueryClientProvider
                        client={queryClient}
                        persistOptions={{
                            persister: queryPersister,
                            // Bump cache identity on every app version so a schema/shape
                            // change after auto-update silently discards the old cache.
                            buster: __APP_VERSION__,
                            maxAge: 24 * 60 * 60 * 1000,
                            dehydrateOptions: {
                                shouldDehydrateQuery: (query) => {
                                    const rootKey = String(query.queryKey?.[0] ?? '')
                                    return query.state.status === 'success' && PERSISTED_QUERY_KEYS.has(rootKey)
                                },
                            },
                        }}
                    >
                        <AuthProvider>
                            <AiAgentProvider>
                                <ToastProvider>
                                    <App />
                                </ToastProvider>
                            </AiAgentProvider>
                        </AuthProvider>
                    </PersistQueryClientProvider>
                </MuiThemeProvider>
            </AppThemeProvider>
        </React.StrictMode>,
    )
}

void initializeElectronSecurityState().finally(renderApp)
