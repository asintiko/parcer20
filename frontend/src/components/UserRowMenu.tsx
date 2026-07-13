import React, { useRef } from 'react';
import {
    MoreHorizontal,
    KeyRound,
    Shield,
    Lock,
    Unlock,
    Send,
    PowerOff,
    Check,
} from 'lucide-react';
import { Popover } from './motion/Popover';
import type { AdminUserLike } from './UserEditorSheet';

export interface UserRowMenuProps {
    user: AdminUserLike;
    open: boolean;
    onToggle: () => void;
    onClose: () => void;
    onResetPassword: (u: AdminUserLike) => void;
    onReset2fa: (id: number) => void;
    onForce2fa: (id: number, force: boolean) => void;
    onUnlock: (id: number) => void;
    onLinkTelegram: (u: AdminUserLike) => void;
    onUnlinkTelegram: (id: number) => void;
    onActivate: (id: number) => void;
    onDeactivate: (id: number) => void;
}

export const UserRowMenu: React.FC<UserRowMenuProps> = ({
    user,
    open,
    onToggle,
    onClose,
    onResetPassword,
    onReset2fa,
    onForce2fa,
    onUnlock,
    onLinkTelegram,
    onUnlinkTelegram,
    onActivate,
    onDeactivate,
}) => {
    const anchorRef = useRef<HTMLButtonElement>(null);

    const close = () => {
        onClose();
    };

    const item = (icon: React.ReactNode, label: string, action: () => void, danger = false) => (
        <button
            type="button"
            role="menuitem"
            className={`sp-pop-item${danger ? ' is-danger' : ''}`}
            onClick={() => {
                close();
                action();
            }}
        >
            {icon}
            {label}
        </button>
    );

    return (
        <>
            <button
                ref={anchorRef}
                type="button"
                className="sp-btn sp-btn-sm sp-btn-icon"
                aria-label="Действия"
                aria-haspopup="menu"
                aria-expanded={open}
                onClick={(e) => {
                    e.stopPropagation();
                    onToggle();
                }}
            >
                <MoreHorizontal size={14} />
            </button>
            <Popover
                open={open}
                anchorRef={anchorRef}
                onClose={close}
                ariaLabel={`Действия для ${user.username}`}
                minWidth={224}
            >
                {item(<KeyRound size={13} />, 'Сбросить пароль', () => onResetPassword(user))}
                {item(<Shield size={13} />, 'Сбросить 2FA', () => onReset2fa(user.id))}
                {item(
                    <Lock size={13} />,
                    user.force_2fa ? 'Снять обязательную 2FA' : 'Сделать 2FA обязательной',
                    () => onForce2fa(user.id, !user.force_2fa)
                )}
                {item(<Unlock size={13} />, 'Разблокировать', () => onUnlock(user.id))}

                <div className="sp-pop-sep" />

                {user.telegram_id
                    ? item(<Send size={13} />, 'Отвязать Telegram', () => onUnlinkTelegram(user.id))
                    : item(<Send size={13} />, 'Привязать Telegram', () => onLinkTelegram(user))}

                <div className="sp-pop-sep" />

                {user.is_active
                    ? item(<PowerOff size={13} />, 'Деактивировать', () => onDeactivate(user.id), true)
                    : item(<Check size={13} />, 'Активировать', () => onActivate(user.id))}
            </Popover>
        </>
    );
};
