import React, { createContext, useContext, useEffect, useState, ReactNode } from 'react';

type Theme = 'light' | 'dark' | 'system';

interface ThemeContextValue {
    theme: Theme;
    isDark: boolean;
    setTheme: (theme: Theme) => void;
    toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const THEME_STORAGE_KEY = 'app-theme';

export const ThemeProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
    const [theme, setThemeState] = useState<Theme>(() => {
        // Проверяем localStorage
        const stored = localStorage.getItem(THEME_STORAGE_KEY) as Theme | null;
        if (stored && (stored === 'light' || stored === 'dark' || stored === 'system')) {
            return stored;
        }
        // По умолчанию используем системную тему
        return 'system';
    });

    const [isDark, setIsDark] = useState(() => {
        if (theme === 'system') {
            return window.matchMedia('(prefers-color-scheme: dark)').matches;
        }
        return theme === 'dark';
    });

    // Применение темы к документу
    useEffect(() => {
        const root = document.documentElement;
        
        if (theme === 'system') {
            const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            root.setAttribute('data-theme', systemDark ? 'dark' : 'light');
            setIsDark(systemDark);
        } else {
            root.setAttribute('data-theme', theme);
            setIsDark(theme === 'dark');
        }
    }, [theme]);

    // Слушаем изменения системной темы
    useEffect(() => {
        if (theme !== 'system') return;

        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
        const handleChange = (e: MediaQueryListEvent) => {
            const root = document.documentElement;
            root.setAttribute('data-theme', e.matches ? 'dark' : 'light');
            setIsDark(e.matches);
        };

        // Современный способ
        if (mediaQuery.addEventListener) {
            mediaQuery.addEventListener('change', handleChange);
            return () => mediaQuery.removeEventListener('change', handleChange);
        } else {
            // Fallback для старых браузеров
            mediaQuery.addListener(handleChange);
            return () => mediaQuery.removeListener(handleChange);
        }
    }, [theme]);

    const setTheme = (newTheme: Theme) => {
        setThemeState(newTheme);
        localStorage.setItem(THEME_STORAGE_KEY, newTheme);
    };

    const toggleTheme = () => {
        if (theme === 'system') {
            // Если системная, переключаем на противоположную текущей
            const currentIsDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            setTheme(currentIsDark ? 'light' : 'dark');
        } else {
            // Переключаем между light и dark
            setTheme(theme === 'light' ? 'dark' : 'light');
        }
    };

    return (
        <ThemeContext.Provider value={{ theme, isDark, setTheme, toggleTheme }}>
            {children}
        </ThemeContext.Provider>
    );
};

export const useTheme = () => {
    const context = useContext(ThemeContext);
    if (!context) {
        throw new Error('useTheme must be used within ThemeProvider');
    }
    return context;
};


