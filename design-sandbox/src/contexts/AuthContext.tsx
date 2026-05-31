import React, { createContext, useCallback, useContext, useEffect, useState, ReactNode } from 'react';
import {
    authApi,
    clearClientSecurityState,
    getAuthToken,
    getRefreshToken,
    securityApi,
    setAuthToken,
    setRefreshToken,
    setOnAuthSessionRevoked,
    type UserInfo,
} from '../services/api';
import { clearLocalDatabase } from '../storage/db';

interface AuthContextType {
    isAuthenticated: boolean;
    user: UserInfo | null;
    loading: boolean;
    login: (username: string, password: string) => Promise<UserInfo>;
    login2fa: (tempToken: string, code: string) => Promise<UserInfo>;
    loginWithTokens: (token: string, scopeToken?: string | null, refreshToken?: string | null, userSnapshot?: any) => Promise<UserInfo>;
    logout: () => Promise<void>;
    checkAuth: () => Promise<void>;
    hasTab: (tabName: string) => boolean;
    firstAllowedRoute: () => string;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const TAB_ROUTE_MAP: Record<string, string> = {
    dashboard: '/',
    reference: '/reference',
    userbot: '/userbot',
    logs: '/logs',
    admin: '/settings',
};

const ORDERED_TABS = ['dashboard', 'reference', 'userbot', 'logs', 'admin'];

export const useAuth = () => {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth must be used within AuthProvider');
    }
    return context;
};

interface AuthProviderProps {
    children: ReactNode;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
    const [isAuthenticated, setIsAuthenticated] = useState(false);
    const [user, setUser] = useState<UserInfo | null>(null);
    const [loading, setLoading] = useState(true);

    const userSignature = useCallback((value: UserInfo | null | undefined) => {
        if (!value) return 'anon';
        return JSON.stringify({
            id: value.id,
            role: value.role,
            username: value.username,
            display_name: value.display_name,
            permissions_version: value.permissions_version,
            allowed_tabs: value.allowed_tabs || [],
            allowed_folders: value.allowed_folders || [],
            allowed_sources: value.allowed_sources || [],
            can_toggle_sources: value.can_toggle_sources,
        });
    }, []);

    const hydrateCurrentUser = useCallback(async (fallbackUser?: UserInfo | null): Promise<UserInfo> => {
        try {
            const liveUser = await authApi.getCurrentUser();
            setUser((prev) => (userSignature(prev) === userSignature(liveUser) ? prev : liveUser));
            setIsAuthenticated(true);
            return liveUser;
        } catch {
            if (fallbackUser) {
                setUser((prev) => (userSignature(prev) === userSignature(fallbackUser) ? prev : fallbackUser));
                setIsAuthenticated(true);
                return fallbackUser;
            }
            throw new Error('user_snapshot_unavailable');
        }
    }, [userSignature]);

    const hasTab = (tabName: string): boolean => {
        if (!user) return false;
        if (user.role === 'admin') return true;
        const normalized = tabName === 'transactions' ? 'dashboard' : tabName;
        return (user.allowed_tabs || []).includes(normalized);
    };

    const firstAllowedRoute = (): string => {
        if (!user) return '/';
        if (user.role === 'admin') return '/';
        const allowed = new Set(user.allowed_tabs || []);
        for (const tab of ORDERED_TABS) {
            if (allowed.has(tab) && TAB_ROUTE_MAP[tab]) {
                return TAB_ROUTE_MAP[tab];
            }
        }
        return '/';
    };

    const checkAuth = async () => {
        setLoading(true);
        const token = getAuthToken();

        const tryRefreshSession = async (): Promise<boolean> => {
            const refreshResponse = await authApi.refresh(getRefreshToken());
            if (!refreshResponse?.ok || !refreshResponse?.token) {
                return false;
            }
            setAuthToken(refreshResponse.token);
            if ('refresh_token' in refreshResponse) {
                setRefreshToken(refreshResponse.refresh_token || null);
            }
            if ('scope_token' in refreshResponse) {
                securityApi.setScopeToken(refreshResponse.scope_token || null);
            }
            await hydrateCurrentUser(refreshResponse.user || null);
            return true;
        };

        try {
            if (token) {
                try {
                    await authApi.verifyToken();
                    await hydrateCurrentUser();
                    return;
                } catch {
                    const refreshed = await tryRefreshSession();
                    if (refreshed) {
                        return;
                    }
                }
            }

            const refreshed = await tryRefreshSession();
            if (refreshed) {
                return;
            }

            clearClientSecurityState();
            setIsAuthenticated(false);
            setUser(null);
        } catch {
            clearClientSecurityState();
            setIsAuthenticated(false);
            setUser(null);
        } finally {
            setLoading(false);
        }
    };

    const login = async (username: string, password: string): Promise<UserInfo> => {
        const response = await authApi.login({ username, password });
        if (!response.ok || !response.token) {
            const error: any = new Error(response.error || 'invalid_credentials');
            error.code = response.error || 'invalid_credentials';
            error.attempts_left = response.attempts_left;
            error.locked_seconds = response.locked_seconds;
            error.requires_2fa = Boolean(response.requires_2fa);
            error.requires_2fa_setup = Boolean(response.requires_2fa_setup);
            error.temp_token = response.temp_token || null;
            throw error;
        }

        setAuthToken(response.token);
        setRefreshToken(response.refresh_token || null);
        securityApi.setScopeToken(response.scope_token || null);
        const nextUser = await hydrateCurrentUser(response.user || null);
        return nextUser;
    };

    const login2fa = async (tempToken: string, code: string): Promise<UserInfo> => {
        const response = await authApi.login2fa({ temp_token: tempToken, code });
        if (!response.ok || !response.token) {
            const error: any = new Error(response.error || 'invalid_2fa_code');
            error.code = response.error || 'invalid_2fa_code';
            throw error;
        }

        setAuthToken(response.token);
        setRefreshToken(response.refresh_token || null);
        securityApi.setScopeToken(response.scope_token || null);
        const nextUser = await hydrateCurrentUser(response.user || null);
        return nextUser;
    };

    const loginWithTokens = async (
        token: string,
        scopeToken?: string | null,
        refreshToken?: string | null,
        userSnapshot?: any,
    ): Promise<UserInfo> => {
        setAuthToken(token);
        setRefreshToken(refreshToken || null);
        securityApi.setScopeToken(scopeToken || null);
        const nextUser = await hydrateCurrentUser(userSnapshot || null);
        return nextUser;
    };

    const logout = async () => {
        // Switch UI to logged-out state immediately so the login screen shows
        // even if the network call or local DB cleanup hangs (e.g. sandbox
        // without a backend, blocked IndexedDB).
        clearClientSecurityState();
        setIsAuthenticated(false);
        setUser(null);
        try {
            await authApi.logout();
        } catch {
            // no-op
        }
        try {
            await clearLocalDatabase();
        } catch {
            // no-op
        }
    };

    useEffect(() => {
        void checkAuth();
    }, []);

    useEffect(() => {
        setOnAuthSessionRevoked(() => {
            clearClientSecurityState();
            setIsAuthenticated(false);
            setUser(null);
        });
        return () => setOnAuthSessionRevoked(null);
    }, []);

    useEffect(() => {
        if (!isAuthenticated) return;
        let mounted = true;

        const syncSession = async () => {
            try {
                await authApi.verifyToken();
                const liveUser = await authApi.getCurrentUser();
                if (!mounted) return;
                setUser((prev) => (userSignature(prev) === userSignature(liveUser) ? prev : liveUser));
                setIsAuthenticated(true);
            } catch {
                // The API interceptor handles revocation/logout state changes.
            }
        };

        const handleFocus = () => {
            void syncSession();
        };
        const handleVisibilityChange = () => {
            if (!document.hidden) {
                void syncSession();
            }
        };

        window.addEventListener('focus', handleFocus);
        document.addEventListener('visibilitychange', handleVisibilityChange);
        const timer = window.setInterval(() => {
            void syncSession();
        }, 30000);

        return () => {
            mounted = false;
            window.removeEventListener('focus', handleFocus);
            document.removeEventListener('visibilitychange', handleVisibilityChange);
            window.clearInterval(timer);
        };
    }, [isAuthenticated, userSignature]);

    return (
        <AuthContext.Provider
            value={{ isAuthenticated, user, loading, login, login2fa, loginWithTokens, logout, checkAuth, hasTab, firstAllowedRoute }}
        >
            {children}
        </AuthContext.Provider>
    );
};
