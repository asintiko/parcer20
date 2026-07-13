interface TelegramWebAppUser {
  id: number;
  first_name: string;
  last_name?: string;
  username?: string;
  language_code?: string;
}

interface TelegramWebAppInitDataUnsafe {
  query_id?: string;
  user?: TelegramWebAppUser;
  start_param?: string;
}

interface TelegramWebApp {
  initData: string;
  initDataUnsafe: TelegramWebAppInitDataUnsafe;
  ready(): void;
  close(): void;
  MainButton: {
    text: string;
    show(): void;
    hide(): void;
    onClick(fn: () => void): void;
    offClick(fn: () => void): void;
    showProgress(leaveActive?: boolean): void;
    hideProgress(): void;
    enable(): void;
    disable(): void;
  };
  themeParams: Record<string, string>;
  colorScheme: 'light' | 'dark';
}

interface Window {
  Telegram?: {
    WebApp: TelegramWebApp;
  };
}
