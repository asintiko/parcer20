import React from 'react';
import { Sun, Moon } from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext';

export const ThemeToggle: React.FC = () => {
    const { isDark, toggleTheme } = useTheme();

    return (
        <button
            onClick={toggleTheme}
            className="flex items-center gap-2 px-4 py-2 rounded-lg hover:bg-surface-2 text-foreground-secondary hover:text-foreground transition-colors focus:outline-none focus:ring-2 focus:ring-primary"
            aria-label={isDark ? 'Переключить на светлую тему' : 'Переключить на темную тему'}
        >
            {isDark ? (
                <>
                    <Sun className="w-5 h-5" />
                    <span className="text-sm font-medium">Светлая тема</span>
                </>
            ) : (
                <>
                    <Moon className="w-5 h-5" />
                    <span className="text-sm font-medium">Темная тема</span>
                </>
            )}
        </button>
    );
};


