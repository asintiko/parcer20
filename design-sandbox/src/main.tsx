import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider as AppThemeProvider } from './contexts/ThemeContext'
import { AuthProvider } from './contexts/AuthContext'
import { AiAgentProvider } from './contexts/AiAgentContext'
import { ToastProvider } from './components/Toast'
import { CssBaseline, ThemeProvider as MuiThemeProvider } from '@mui/material'
import App from './App.tsx'
import { ReelPage } from './pages/ReelPage'
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

const isReelMode = () =>
    typeof window !== 'undefined' &&
    new URLSearchParams(window.location.search).has('reel');

const renderApp = () => {
    const reel = isReelMode();
    ReactDOM.createRoot(document.getElementById('root')!).render(
        <React.StrictMode>
            <AppThemeProvider>
                <MuiThemeProvider theme={muiTheme}>
                    <CssBaseline />
                    <QueryClientProvider client={queryClient}>
                        <AuthProvider>
                            <AiAgentProvider>
                                <ToastProvider>
                                    {reel ? <ReelPage /> : <App />}
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
    // Design sandbox: auto-login as admin so reload doesn't kick you out
    // to the login screen. Real auth/2FA flows are demoed via the Login page
    // in isolation when needed.
    window.localStorage.setItem('auth_token', 'mock-access-token')
    window.localStorage.setItem('auth_refresh_token', 'mock-refresh-token')
    window.localStorage.setItem('system_access_token', 'design-sandbox')
}

void bootstrapSystemAccess().finally(renderApp)
