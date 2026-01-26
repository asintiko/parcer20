import React, { useEffect, useRef } from 'react';

interface ContextMenuProps {
    x: number;
    y: number;
    onClose: () => void;
    onAlign: (alignment: 'left' | 'center' | 'right') => void;
    onColor: (color: string) => void;
    onHideColumn?: () => void;
    onDelete?: () => void;
}

// Colors for cell background - light theme values
// These will be visible on both themes, but work better with dark theme borders
const COLORS = [
    { label: 'Нет', value: 'transparent' },
    { label: 'Красный', value: 'rgba(255, 89, 90, 0.2)' }, // danger-light dark theme
    { label: 'Зеленый', value: 'rgba(92, 200, 94, 0.2)' }, // success-light dark theme
    { label: 'Синий', value: 'rgba(51, 144, 236, 0.2)' }, // info-light dark theme
    { label: 'Желтый', value: 'rgba(255, 165, 0, 0.2)' }, // warning-light dark theme
    { label: 'Серый', value: 'rgba(42, 42, 42, 0.5)' }, // surface-2 dark theme
    { label: 'Оранж', value: 'rgba(255, 165, 0, 0.15)' }, // warning-light variant
];

export const ContextMenu: React.FC<ContextMenuProps> = ({ x, y, onClose, onAlign, onColor, onHideColumn, onDelete }) => {
    const menuRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
                onClose();
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
        };
    }, [onClose]);

    return (
        <div
            ref={menuRef}
            className="fixed z-50 bg-context-menu-bg border border-context-menu-border shadow-xl rounded-md py-2 min-w-[180px]"
            style={{ top: y, left: x }}
        >
            {/* Alignment Section */}
            <div className="px-3 py-1 text-xs font-semibold text-context-menu-text-secondary uppercase tracking-wider mb-1">
                Выравнивание
            </div>
            <div className="flex justify-around px-2 mb-2">
                <button
                    className="p-1.5 hover:bg-context-menu-hover rounded text-context-menu-text"
                    onClick={() => onAlign('left')}
                    title="По левому краю"
                >
                    L
                </button>
                <button
                    className="p-1.5 hover:bg-context-menu-hover rounded text-context-menu-text"
                    onClick={() => onAlign('center')}
                    title="По центру"
                >
                    C
                </button>
                <button
                    className="p-1.5 hover:bg-context-menu-hover rounded text-context-menu-text"
                    onClick={() => onAlign('right')}
                    title="По правому краю"
                >
                    R
                </button>
            </div>

            <div className="border-t border-context-menu-border my-1"></div>

            {/* Color Section */}
            <div className="px-3 py-1 text-xs font-semibold text-context-menu-text-secondary uppercase tracking-wider mb-1">
                Заливка
            </div>
            <div className="grid grid-cols-4 gap-2 px-3 pb-1">
                {COLORS.map((color) => (
                    <button
                        key={color.value}
                        className="w-6 h-6 rounded-full border border-context-menu-border shadow-sm hover:scale-110 transition-transform"
                        style={{ backgroundColor: color.value }}
                        onClick={() => onColor(color.value)}
                        title={color.label}
                    >
                        {color.value === 'transparent' && (
                            <span className="block w-full h-full border border-danger rounded-full relative overflow-hidden">
                                <span className="absolute top-1/2 left-0 w-full h-[1px] bg-danger -rotate-45"></span>
                            </span>
                        )}
                    </button>
                ))}
            </div>

            {onHideColumn && (
                <>
                    <div className="border-t border-context-menu-border my-2"></div>
                    <button
                        className="w-full text-left px-3 py-2 text-sm text-context-menu-text hover:bg-context-menu-hover"
                        onClick={() => {
                            onHideColumn();
                            onClose();
                        }}
                    >
                        Скрыть колонку
                    </button>
                </>
            )}

            {onDelete && (
                <>
                    <div className="border-t border-context-menu-border my-2"></div>
                    <button
                        className="w-full text-left px-3 py-2 text-sm text-danger hover:bg-danger/10"
                        onClick={() => {
                            onDelete();
                            onClose();
                        }}
                    >
                        Удалить строку
                    </button>
                </>
            )}
        </div>
    );
};
