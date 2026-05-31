import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
    Home,
    BookOpen,
    Bot,
    FileClock,
    Settings as SettingsIcon,
    ShieldCheck,
    Sun,
    Moon,
    Monitor,
    PanelLeftClose,
    type LucideIcon,
} from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import { useTheme } from '../../contexts/ThemeContext';
import { UserMenuPopover } from './UserMenuPopover';

export interface NavItem {
    key: string;
    path: string;
    label: string;
    icon: LucideIcon;
    tab: string;
    section: 'main' | 'admin';
    badge?: number | string;
}

export const NAV_ITEMS: NavItem[] = [
    { key: 'transactions', path: '/', label: 'Транзакции', icon: Home, tab: 'dashboard', section: 'main' },
    { key: 'reference', path: '/reference', label: 'Справочник', icon: BookOpen, tab: 'reference', section: 'main' },
    { key: 'userbot', path: '/userbot', label: 'Telegram-клиент', icon: Bot, tab: 'userbot', section: 'main' },
    { key: 'logs', path: '/logs', label: 'Логи', icon: FileClock, tab: 'logs', section: 'main' },
    { key: 'settings', path: '/settings', label: 'Настройки', icon: SettingsIcon, tab: 'admin', section: 'admin' },
    { key: 'audit', path: '/audit', label: 'Аудит', icon: ShieldCheck, tab: 'admin', section: 'admin' },
];

interface AppRailProps {
    collapsed: boolean;
    onToggleCollapse: () => void;
    /** Render in mobile drawer (skip rail-specific behaviors) */
    mobile?: boolean;
    /** Called when nav item clicked (used by drawer to close) */
    onNavigate?: () => void;
}

export const AppRail: React.FC<AppRailProps> = ({ collapsed, onToggleCollapse, mobile, onNavigate }) => {
    const location = useLocation();
    const { hasTab } = useAuth();
    const { theme, setTheme } = useTheme();

    const visibleItems = NAV_ITEMS.filter((it) => hasTab(it.tab));
    const mainItems = visibleItems.filter((it) => it.section === 'main');
    const adminItems = visibleItems.filter((it) => it.section === 'admin');

    const isActive = (path: string) => {
        if (path === '/') return location.pathname === '/';
        return location.pathname.startsWith(path);
    };

    const renderNavItem = (item: NavItem) => {
        const active = isActive(item.path);
        const Icon = item.icon;
        return (
            <Link
                key={item.key}
                to={item.path}
                className={`rl-nav-item${active ? ' is-active' : ''}`}
                aria-current={active ? 'page' : undefined}
                title={collapsed && !mobile ? item.label : undefined}
                onClick={onNavigate}
            >
                <Icon size={18} className="rl-nav-icon" aria-hidden />
                <span className="rl-nav-label">{item.label}</span>
                {item.badge ? <span className="rl-nav-badge">{item.badge}</span> : null}
            </Link>
        );
    };

    const themeOptions: { key: 'light' | 'dark' | 'system'; Icon: LucideIcon; label: string }[] = [
        { key: 'light', Icon: Sun, label: 'Свет' },
        { key: 'dark', Icon: Moon, label: 'Тьма' },
        { key: 'system', Icon: Monitor, label: 'Авто' },
    ];

    return (
        <aside className="rl-rail" aria-label="Главная навигация">
            <div className="rl-rail-inner">
                <div className="rl-rail-head">
                    {!mobile && collapsed ? (
                        <button
                            type="button"
                            className="rl-logo-mark rl-logo-mark-btn"
                            onClick={onToggleCollapse}
                            aria-label="Развернуть навигацию"
                            aria-expanded={false}
                        >
                            TBS
                        </button>
                    ) : (
                        <Link to="/" className="rl-logo" onClick={onNavigate}>
                            <span className="rl-logo-mark" aria-hidden>TBS</span>
                            <span className="rl-logo-text">Receipt Parcer</span>
                        </Link>
                    )}
                    {!mobile && !collapsed ? (
                        <button
                            type="button"
                            className="rl-collapse-btn"
                            onClick={onToggleCollapse}
                            aria-label="Свернуть навигацию"
                            aria-expanded={true}
                        >
                            <PanelLeftClose size={16} />
                        </button>
                    ) : null}
                </div>

                <nav className="rl-nav">
                    {mainItems.length > 0 ? (
                        <>
                            <div className="rl-nav-section-label">Основное</div>
                            {mainItems.map(renderNavItem)}
                        </>
                    ) : null}

                    {adminItems.length > 0 ? (
                        <>
                            <div className="rl-nav-section-label">Администрирование</div>
                            {adminItems.map(renderNavItem)}
                        </>
                    ) : null}
                </nav>

                <div className="rl-rail-foot">
                    <div className="rl-theme-row" role="radiogroup" aria-label="Тема интерфейса">
                        {themeOptions.map(({ key, Icon, label }) => (
                            <button
                                key={key}
                                type="button"
                                role="radio"
                                aria-checked={theme === key}
                                className={`rl-theme-btn${theme === key ? ' is-active' : ''}`}
                                onClick={() => setTheme(key)}
                                title={label}
                            >
                                <Icon size={13} />
                                <span className="rl-theme-btn-label">{label}</span>
                            </button>
                        ))}
                    </div>

                    <UserMenuPopover collapsed={collapsed && !mobile} />
                </div>
            </div>
        </aside>
    );
};
