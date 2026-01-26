import React, { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { X, Home, Settings, Workflow, Book, Bot, FileText } from 'lucide-react';
import { ThemeToggle } from './ThemeToggle';

interface BurgerMenuProps {
    isOpen: boolean;
    onClose: () => void;
}

export const BurgerMenu: React.FC<BurgerMenuProps> = ({ isOpen, onClose }) => {
    const navigate = useNavigate();
    const location = useLocation();
    const [isMounted, setIsMounted] = useState(false);
    const [isVisible, setIsVisible] = useState(false);

    useEffect(() => {
        if (isOpen) {
            setIsMounted(true);
            // Use double RAF or simplified timeout to ensure DOM mount -> paint -> transition
            const timer = setTimeout(() => {
                setIsVisible(true);
            }, 10);
            return () => clearTimeout(timer);
        } else {
            setIsVisible(false);
            const timer = setTimeout(() => {
                setIsMounted(false);
            }, 300); // Wait for transition duration
            return () => clearTimeout(timer);
        }
    }, [isOpen]);

    if (!isMounted) return null;

    return (
        <div className="fixed inset-0 z-50 flex">
            {/* Backdrop with Blur */}
            <div
                className={`fixed inset-0 bg-black/30 backdrop-blur-sm transition-opacity duration-300 ease-in-out ${isVisible ? 'opacity-100' : 'opacity-0'
                    }`}
                onClick={onClose}
            />

            {/* Side Drawer */}
            <div
                className={`relative flex flex-col w-64 h-full bg-surface shadow-2xl transform transition-transform duration-300 ease-in-out border-r border-border ${isVisible ? 'translate-x-0' : '-translate-x-full'
                    }`}
            >
                {/* Header */}
                <div className="flex items-center justify-between p-4 border-b border-border">
                    <h2 className="text-xl font-semibold tracking-wide text-foreground">
                        PARCER 2.0
                    </h2>
                    <button
                        onClick={onClose}
                        className="p-1 rounded-full hover:bg-surface-2 transition-colors focus:outline-none focus:ring-2 focus:ring-primary"
                    >
                        <X className="w-6 h-6 text-foreground-secondary" />
                    </button>
                </div>

                {/* Navigation Items */}
                <div className="flex-1 overflow-y-auto py-4">
                    <nav className="space-y-1 px-2">
                        <MenuItem
                            icon={<Home size={20} />}
                            label="Дашборд"
                            isActive={location.pathname === '/'}
                            onClick={() => {
                                navigate('/');
                                onClose();
                            }}
                        />
                        <MenuItem
                            icon={<Workflow size={20} />}
                            label="Автоматизация"
                            isActive={location.pathname === '/automation'}
                            onClick={() => {
                                navigate('/automation');
                                onClose();
                            }}
                        />
                        <MenuItem
                            icon={<Book size={20} />}
                            label="Справочник"
                            isActive={location.pathname === '/reference'}
                            onClick={() => {
                                navigate('/reference');
                                onClose();
                            }}
                        />
                        <MenuItem
                            icon={<Bot size={20} />}
                            label="Telegram Bots"
                            isActive={location.pathname === '/userbot'}
                            onClick={() => {
                                navigate('/userbot');
                                onClose();
                            }}
                        />
                        <MenuItem
                            icon={<FileText size={20} />}
                            label="Логи"
                            isActive={location.pathname === '/logs'}
                            onClick={() => {
                                navigate('/logs');
                                onClose();
                            }}
                        />
                        <div className="pt-4 mt-4 border-t border-border">
                            <MenuItem icon={<Settings size={20} />} label="Настройки" />
                        </div>
                    </nav>
                </div>

                {/* Theme Toggle */}
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
        className={`flex items-center gap-3 w-full px-4 py-3 text-left text-sm font-medium rounded-lg transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-primary ${isActive
            ? 'bg-primary-light text-primary shadow-sm ring-1 ring-primary/20'
            : 'text-foreground-secondary hover:bg-surface-2 hover:text-foreground'
            }`}
    >
        {icon}
        {label}
    </button>
);
