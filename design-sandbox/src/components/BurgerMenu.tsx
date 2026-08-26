import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { X, Home, Book, Bot, FileClock, Settings, ShieldCheck } from 'lucide-react';
import { ThemeToggle } from './ThemeToggle';
import { useAuth } from '../contexts/AuthContext';
import { ru } from '../i18n/ru';

interface BurgerMenuProps {
    isOpen: boolean;
    onClose: () => void;
}

export const BurgerMenu: React.FC<BurgerMenuProps> = ({ isOpen, onClose }) => {
    const navigate = useNavigate();
    const location = useLocation();
    const { hasTab } = useAuth();
    const [isMounted, setIsMounted] = useState(false);
    const [isVisible, setIsVisible] = useState(false);
    const prevPathnameRef = useRef(location.pathname);

    useEffect(() => {
        if (isOpen) {
            setIsMounted(true);
            const timer = setTimeout(() => {
                setIsVisible(true);
            }, 10);
            return () => clearTimeout(timer);
        }
        setIsVisible(false);
        const timer = setTimeout(() => {
            setIsMounted(false);
        }, 300);
        return () => clearTimeout(timer);
    }, [isOpen]);

    useEffect(() => {
        if (prevPathnameRef.current !== location.pathname && isOpen) {
            onClose();
        }
        prevPathnameRef.current = location.pathname;
    }, [location.pathname, isOpen, onClose]);

    if (!isMounted) return null;

    return (
        <div className={`fixed inset-0 z-50 flex ${isVisible ? 'pointer-events-auto' : 'pointer-events-none'}`}>
            <div
                className={`fixed inset-0 bg-black/30 backdrop-blur-sm transition-opacity duration-300 ease-in-out ${isVisible ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'}`}
                onClick={onClose}
            />

            <div
                className={`relative flex flex-col w-64 h-full bg-surface shadow-2xl transform transition-transform duration-300 ease-in-out border-r border-border ${isVisible ? 'translate-x-0 pointer-events-auto' : '-translate-x-full pointer-events-none'}`}
            >
                <div className="flex items-center justify-between p-4 border-b border-border">
                    <h2 className="text-xl font-semibold tracking-wide text-foreground">PARCER 2.0</h2>
                    <button
                        onClick={onClose}
                        className="p-1 rounded-full hover:bg-surface-2 transition-colors focus:outline-none focus:ring-2 focus:ring-primary"
                    >
                        <X className="w-6 h-6 text-foreground-secondary" />
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto py-4">
                    <nav className="space-y-1 px-2">
                        {hasTab('dashboard') && (
                            <MenuItem
                                icon={<Home size={20} />}
                                label={ru.nav.transactions}
                                isActive={location.pathname === '/'}
                                onClick={() => {
                                    navigate('/');
                                    onClose();
                                }}
                            />
                        )}
                        {hasTab('reference') && (
                            <MenuItem
                                icon={<Book size={20} />}
                                label={ru.nav.reference}
                                isActive={location.pathname === '/reference'}
                                onClick={() => {
                                    navigate('/reference');
                                    onClose();
                                }}
                            />
                        )}
                        {hasTab('userbot') && (
                            <MenuItem
                                icon={<Bot size={20} />}
                                label={ru.nav.telegramClient}
                                isActive={location.pathname === '/userbot'}
                                onClick={() => {
                                    navigate('/userbot');
                                    onClose();
                                }}
                            />
                        )}
                        {hasTab('logs') && (
                            <MenuItem
                                icon={<FileClock size={20} />}
                                label={ru.nav.logs}
                                isActive={location.pathname === '/logs'}
                                onClick={() => {
                                    navigate('/logs');
                                    onClose();
                                }}
                            />
                        )}
                        {hasTab('admin') && (
                            <MenuItem
                                icon={<Settings size={20} />}
                                label={ru.nav.settings}
                                isActive={location.pathname === '/settings'}
                                onClick={() => {
                                    navigate('/settings');
                                    onClose();
                                }}
                            />
                        )}
                        {hasTab('admin') && (
                            <MenuItem
                                icon={<ShieldCheck size={20} />}
                                label={ru.nav.audit}
                                isActive={location.pathname === '/audit'}
                                onClick={() => {
                                    navigate('/audit');
                                    onClose();
                                }}
                            />
                        )}
                    </nav>
                </div>

                <div className="p-4 border-t border-border">
                    <ThemeToggle />
                </div>
            </div>
        </div>
    );
};

interface MenuItemProps {
    icon: React.ReactNode;
    label: string;
    isActive?: boolean;
    onClick?: () => void;
}

const MenuItem: React.FC<MenuItemProps> = ({ icon, label, isActive, onClick }) => (
    <button
        onClick={onClick}
        className={`flex items-center gap-3 w-full px-4 py-3 text-left text-sm font-medium rounded-lg transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-primary ${
            isActive
                ? 'bg-primary-light text-primary shadow-sm ring-1 ring-primary/20'
                : 'text-foreground-secondary hover:bg-surface-2 hover:text-foreground'
        }`}
    >
        {icon}
        {label}
    </button>
);
