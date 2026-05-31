import React from 'react';

/**
 * Avatar — Telegram-style.
 * Uses photo URL if provided, otherwise initials with deterministic color
 * derived from chat_id (8 colors palette).
 */

export interface AvatarProps {
    name?: string | null;
    seed?: number | string;
    photoUrl?: string | null;
    size?: 32 | 40 | 48;
    className?: string;
}

const initialsOf = (name: string): string => {
    const src = (name || '').trim();
    if (!src) return '?';
    const parts = src.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return src.slice(0, 2).toUpperCase();
};

const colorIndex = (seed: number | string | undefined): number => {
    if (seed === undefined || seed === null) return 0;
    const num = typeof seed === 'number' ? seed : Array.from(String(seed)).reduce((a, c) => a + c.charCodeAt(0), 0);
    return Math.abs(num) % 8;
};

export const Avatar: React.FC<AvatarProps> = ({ name, seed, photoUrl, size = 40, className = '' }) => {
    const displayName = name || '';
    const initials = initialsOf(displayName);
    const colorClass = `color-${colorIndex(seed ?? displayName)}`;
    const sizeClass = size === 40 ? '' : `size-${size}`;
    const cls = ['tg-avatar', sizeClass, photoUrl ? '' : colorClass, className].filter(Boolean).join(' ');

    return (
        <span className={cls} aria-hidden>
            {photoUrl ? (
                <img src={photoUrl} alt="" loading="lazy" />
            ) : (
                <span>{initials}</span>
            )}
        </span>
    );
};
