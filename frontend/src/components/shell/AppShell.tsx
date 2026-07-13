import React, { useEffect, useState } from 'react';
import { AppRail } from './AppRail';
import { AppTopbar } from './AppTopbar';
import { MobileDrawer } from './MobileDrawer';
import '../../styles/shell.css';

const COLLAPSED_KEY = 'app-rail-collapsed';

interface AppShellProps {
    rightSlot?: React.ReactNode;
    children: React.ReactNode;
}

export const AppShell: React.FC<AppShellProps> = ({ rightSlot, children }) => {
    const [collapsed, setCollapsed] = useState<boolean>(() => {
        try {
            return localStorage.getItem(COLLAPSED_KEY) === '1';
        } catch {
            return false;
        }
    });
    const [drawerOpen, setDrawerOpen] = useState(false);

    useEffect(() => {
        try {
            localStorage.setItem(COLLAPSED_KEY, collapsed ? '1' : '0');
        } catch {
            // ignore
        }
    }, [collapsed]);

    return (
        <div className={`rl-shell${collapsed ? ' is-collapsed' : ''}`}>
            <AppRail
                collapsed={collapsed}
                onToggleCollapse={() => setCollapsed((v) => !v)}
            />

            <div className="rl-main">
                <AppTopbar
                    onOpenMobileDrawer={() => setDrawerOpen(true)}
                    rightSlot={rightSlot}
                />
                <div className="rl-content">{children}</div>
            </div>

            <MobileDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
        </div>
    );
};
