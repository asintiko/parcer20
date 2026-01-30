import React from 'react';
import { useUpdater } from '../hooks/useUpdater';

export const SettingsPage: React.FC = () => {
    const { isElectron, status, version, error, progress, check, download, install } = useUpdater();

    const renderStatus = () => {
        switch (status) {
            case 'checking':
                return 'Проверка обновлений...';
            case 'available':
                return 'Найдена новая версия.';
            case 'not-available':
                return 'Установлена последняя версия.';
            case 'downloading':
                return `Скачивание... ${progress?.percent ? Math.round(progress.percent) + '%' : ''}`;
            case 'downloaded':
                return 'Обновление скачано. Можно установить.';
            case 'error':
                return error || 'Ошибка обновления.';
            default:
                return 'Готово.';
        }
    };

    return (
        <div className="p-6 space-y-4 max-w-3xl">
            <h1 className="text-xl font-semibold text-foreground">Настройки</h1>

            <div className="border border-border rounded-lg bg-surface p-4 space-y-3">
                <div className="text-sm text-foreground-secondary">
                    {isElectron ? 'Работаем в desktop-режиме Electron.' : 'Запущено в браузере — автообновления недоступны.'}
                </div>
                <div className="text-sm text-foreground">
                    Текущая версия: <span className="font-mono">{version || '—'}</span>
                </div>
                <div className="text-sm text-foreground">{renderStatus()}</div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={check}
                        disabled={!isElectron || status === 'checking'}
                        className="px-3 py-2 text-sm rounded-md border border-border bg-surface hover:bg-surface-2 disabled:opacity-50"
                    >
                        Проверить обновления
                    </button>
                    <button
                        onClick={download}
                        disabled={!isElectron || !(status === 'available')}
                        className="px-3 py-2 text-sm rounded-md border border-border bg-surface hover:bg-surface-2 disabled:opacity-50"
                    >
                        Скачать
                    </button>
                    <button
                        onClick={install}
                        disabled={!isElectron || status !== 'downloaded'}
                        className="px-3 py-2 text-sm rounded-md border border-primary text-primary hover:bg-primary/10 disabled:opacity-50"
                    >
                        Установить и перезапустить
                    </button>
                </div>
                <div className="text-xs text-foreground-muted">
                    Источник обновлений: релизы GitHub (нужно настроить publish-конфигурацию в build/publish).
                </div>
            </div>
        </div>
    );
};
