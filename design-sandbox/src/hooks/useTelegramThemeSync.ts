import { useEffect, useRef } from 'react';
import { useTheme } from '../contexts/ThemeContext';

/**
 * Hook для синхронизации темы приложения с Telegram Web K iframe
 * Использует postMessage API для общения с iframe
 */
export const useTelegramThemeSync = (iframeRef: React.RefObject<HTMLIFrameElement>) => {
    const { isDark } = useTheme();
    const lastThemeRef = useRef<boolean | null>(null);

    useEffect(() => {
        const iframe = iframeRef.current;
        if (!iframe || !iframe.contentWindow) {
            return;
        }

        // Отправляем тему только если она изменилась
        if (lastThemeRef.current === isDark) {
            return;
        }

        lastThemeRef.current = isDark;

        // Метод 1: postMessage (предпочтительный)
        const sendThemeViaPostMessage = () => {
            try {
                iframe.contentWindow?.postMessage(
                    {
                        type: 'theme_changed',
                        theme: isDark ? 'dark' : 'light',
                        isDark,
                        colors: {
                            bg: isDark ? '#181818' : '#ffffff',
                            surface: isDark ? '#212121' : '#ffffff',
                            text: isDark ? '#ffffff' : '#111827',
                            primary: isDark ? '#8774E1' : '#3390ec',
                        },
                    },
                    '*' // В production лучше указать конкретный origin
                );
            } catch (error) {
                console.warn('Failed to send theme via postMessage:', error);
            }
        };

        // Метод 2: Прямое обращение к iframe (если same-origin)
        const sendThemeDirectly = () => {
            try {
                // Проверяем доступность через try-catch
                const iframeWindow = iframe.contentWindow;
                if (!iframeWindow) return;

                // Пытаемся получить доступ к themeController из Telegram Web K
                // @ts-ignore
                if (iframeWindow.themeController) {
                    // @ts-ignore
                    iframeWindow.themeController.setTheme();
                } else if (iframeWindow.document) {
                    // Альтернативный способ - установить класс напрямую
                    const iframeDoc = iframeWindow.document;
                    if (isDark) {
                        iframeDoc.documentElement.classList.add('night');
                        iframeDoc.documentElement.setAttribute('data-theme', 'dark');
                    } else {
                        iframeDoc.documentElement.classList.remove('night');
                        iframeDoc.documentElement.setAttribute('data-theme', 'light');
                    }
                }
            } catch (error) {
                // Cross-origin или другая ошибка - используем postMessage
                console.warn('Direct access failed, using postMessage:', error);
                sendThemeViaPostMessage();
            }
        };

        // Пробуем оба метода
        sendThemeDirectly();
        sendThemeViaPostMessage();


        // Слушаем сообщения от iframe (если Telegram Web K меняет тему)
        const handleMessage = (event: MessageEvent) => {
            // Проверяем origin для безопасности (в production)
            // if (event.origin !== 'expected-origin') return;

            if (event.data?.type === 'theme_changed_from_iframe') {
                // Telegram Web K изменил тему - можем синхронизировать обратно
                // Но обычно мы управляем темой из приложения
            }
        };

        window.addEventListener('message', handleMessage);

        return () => {
            window.removeEventListener('message', handleMessage);
        };
    }, [isDark, iframeRef]);

    // Отправляем тему при загрузке iframe
    useEffect(() => {
        const iframe = iframeRef.current;
        if (!iframe) return;

        const handleLoad = () => {
            // Небольшая задержка для гарантии, что iframe готов
            setTimeout(() => {
                const iframeWindow = iframe.contentWindow;
                if (iframeWindow) {
                    try {
                        iframeWindow.postMessage(
                            {
                                type: 'theme_changed',
                                theme: isDark ? 'dark' : 'light',
                                isDark,
                            },
                            '*'
                        );
                    } catch (error) {
                        console.warn('Failed to send initial theme:', error);
                    }
                }
            }, 500);
        };

        iframe.addEventListener('load', handleLoad);
        return () => {
            iframe.removeEventListener('load', handleLoad);
        };
    }, [iframeRef, isDark]);
};


