import React from 'react';
import { Menu } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { NAV_ITEMS } from './AppRail';

interface AppTopbarProps {
    onOpenMobileDrawer: () => void;
    /** Right-side widgets (sync, status, etc.) */
    rightSlot?: React.ReactNode;
}

const titleFor = (pathname: string): string => {
    const item = NAV_ITEMS.find((it) => {
        if (it.path === '/') return pathname === '/';
        return pathname.startsWith(it.path);
    });
    return item?.label || 'Receipt Parcer';
};

export const AppTopbar: React.FC<AppTopbarProps> = ({ onOpenMobileDrawer, rightSlot }) => {
    const location = useLocation();
    const title = titleFor(location.pathname);

    return (
        <header className="rl-topbar">
            <button
                type="button"
                className="rl-burger"
                onClick={onOpenMobileDrawer}
                aria-label="Открыть навигацию"
            >
                <Menu size={18} />
            </button>
            <h1 className="rl-topbar-title">{title}</h1>
            <span className="rl-topbar-spacer" />
            <div className="rl-topbar-actions">
                {rightSlot}
            </div>
        </header>
    );
};
