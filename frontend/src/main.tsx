import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider as AppThemeProvider } from './contexts/ThemeContext'
import { AuthProvider } from './contexts/AuthContext'
import { AiAgentProvider } from './contexts/AiAgentContext'
import { ToastProvider } from './components/Toast'
import { CssBaseline, ThemeProvider as MuiThemeProvider } from '@mui/material'
import App from './App.tsx'
import './index.css'
import { muiTheme } from './styles/muiTheme'

const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            refetchOnWindowFocus: false,
            retry: 1,
            staleTime: 30000, // 30 seconds
        },
    },
})

const renderApp = () => {
    ReactDOM.createRoot(document.getElementById('root')!).render(
        <React.StrictMode>
            <AppThemeProvider>
                <MuiThemeProvider theme={muiTheme}>
                    <CssBaseline />
                    <QueryClientProvider client={queryClient}>
                        <AuthProvider>
                            <AiAgentProvider>
                                <ToastProvider>
                                    <App />
                                </ToastProvider>
                            </AiAgentProvider>
                        </AuthProvider>
                    </QueryClientProvider>
                </MuiThemeProvider>
            </AppThemeProvider>
        </React.StrictMode>,
    )
}

const bootstrapSystemAccess = async () => {
    if (typeof window === 'undefined') return
    if ((window as any).electronAPI?.isElectron) return
    try {
        const response = await fetch('/client-access.json', {
            method: 'GET',
            cache: 'no-store',
        })
        if (!response.ok) return
        const contentType = response.headers.get('content-type') || ''
        const raw = await response.text()
        if (!raw.trim()) return
        const looksJson =
            contentType.toLowerCase().includes('application/json') ||
            raw.trim().startsWith('{')
        if (!looksJson) return
        const parsed = JSON.parse(raw) as { system_access_token?: string }
        const token = String(parsed.system_access_token || '').trim()
        if (!token) return
        window.localStorage.setItem('system_access_token', token)
        window.sessionStorage.removeItem('system_access_token')
    } catch {
        // ignore browser bootstrap failures; the API layer has a fallback loader
    }
}

void bootstrapSystemAccess().finally(renderApp)
