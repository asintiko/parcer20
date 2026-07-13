import React, { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronUp, LogOut, Settings, User as UserIcon } from 'lucide-react';
import { Popover } from '../motion/Popover';
import { ConfirmDialog } from '../motion/ConfirmDialog';
import { useAuth } from '../../contexts/AuthContext';

interface UserMenuPopoverProps {
    collapsed?: boolean;
}

const initialsOf = (name: string): string => {
    const src = name.trim() || '?';
    const parts = src.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return src.slice(0, 2).toUpperCase();
};

export const UserMenuPopover: React.FC<UserMenuPopoverProps> = ({ collapsed }) => {
    const navigate = useNavigate();
    const { user, logout } = useAuth();
    const [open, setOpen] = useState(false);
    const [logoutOpen, setLogoutOpen] = useState(false);
    const [logoutBusy, setLogoutBusy] = useState(false);
    const triggerRef = useRef<HTMLButtonElement>(null);

    const displayName = user?.display_name || user?.username || '—';
    const initials = initialsOf(displayName);

    const handleLogoutConfirm = async () => {
        setLogoutOpen(false);
        setLogoutBusy(true);
        try {
            await logout();
        } finally {
            setLogoutBusy(false);
        }
    };

    const goto = (path: string) => {
        setOpen(false);
        navigate(path);
    };

    return (
        <>
            <button
                ref={triggerRef}
                type="button"
                className="rl-user-trigger"
                onClick={() => setOpen((v) => !v)}
                aria-haspopup="menu"
                aria-expanded={open}
                title={collapsed ? displayName : undefined}
            >
                <span className="rl-user-avatar" aria-hidden>{initials}</span>
                <span className="rl-user-meta">
                    <span className="rl-user-name">{displayName}</span>
                    <span className="rl-user-role">{user?.role || 'user'}</span>
                </span>
                <ChevronUp size={14} className="rl-user-chevron" aria-hidden />
            </button>

            <Popover
                open={open}
                anchorRef={triggerRef}
                onClose={() => setOpen(false)}
                placement="bottom-start"
                minWidth={240}
                ariaLabel="Меню пользователя"
            >
                <div className="rl-user-popover">
                    <div className="rl-user-popover-head">
                        <div className="rl-user-popover-name">{displayName}</div>
                        <div className="rl-user-popover-meta">@{user?.username} · {user?.role}</div>
                    </div>

                    <button
                        type="button"
                        role="menuitem"
                        className="sp-pop-item"
                        onClick={() => goto('/settings#profile')}
                    >
                        <UserIcon size={13} />
                        Профиль
                    </button>
                    <button
                        type="button"
                        role="menuitem"
                        className="sp-pop-item"
                        onClick={() => goto('/settings')}
                    >
                        <Settings size={13} />
                        Настройки
                    </button>

                    <div className="sp-pop-sep" />

                    <button
                        type="button"
                        role="menuitem"
                        className="sp-pop-item is-danger"
                        onClick={() => {
                            setOpen(false);
                            setLogoutOpen(true);
                        }}
                        disabled={logoutBusy}
                    >
                        <LogOut size={13} />
                        Выйти
                    </button>
                </div>
            </Popover>

            <ConfirmDialog
                open={logoutOpen}
                onClose={() => setLogoutOpen(false)}
                onConfirm={handleLogoutConfirm}
                title="Выйти из аккаунта?"
                description="Вы будете перенаправлены на страницу входа."
                tone="danger"
                confirmLabel="Выйти"
            />
        </>
    );
};
