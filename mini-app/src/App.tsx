import { useEffect, useRef, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

type Status = 'init' | 'confirming' | 'success' | 'error' | 'no_params';

export function App() {
  const [status, setStatus] = useState<Status>('init');
  const [message, setMessage] = useState('');
  const [userName, setUserName] = useState('');
  const confirmedRef = useRef(false);

  useEffect(() => {
    const tg = window.Telegram?.WebApp;
    if (!tg) {
      setStatus('error');
      setMessage('Откройте через Telegram');
      return;
    }

    tg.ready();

    const startParam = tg.initDataUnsafe.start_param;
    const initData = tg.initData;

    if (!startParam || !initData) {
      setStatus('no_params');
      setMessage('Отсканируйте QR-код в приложении PARCER 2.0');
      return;
    }

    const sepIdx = startParam.indexOf('_');
    if (sepIdx < 1) {
      setStatus('error');
      setMessage('Неверная ссылка. Отсканируйте QR-код заново.');
      return;
    }

    const sessionId = startParam.slice(0, sepIdx);
    const secret = startParam.slice(sepIdx + 1);

    if (confirmedRef.current) return;
    confirmedRef.current = true;

    setStatus('confirming');
    setMessage('Подтверждаем вход...');

    const user = tg.initDataUnsafe.user;
    if (user?.first_name) {
      setUserName(user.first_name);
    }

    confirmLogin(sessionId, secret, initData, tg);
  }, []);

  async function confirmLogin(
    sessionId: string,
    secret: string,
    initData: string,
    tg: TelegramWebApp,
  ) {
    try {
      const resp = await fetch(`${API_BASE}/api/auth/qr/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          secret,
          init_data: initData,
        }),
      });

      if (!resp.ok) {
        const data = await resp.json().catch(() => null);
        const detail = data?.detail || `Ошибка ${resp.status}`;
        setStatus('error');
        setMessage(typeof detail === 'string' ? detail : JSON.stringify(detail));
        return;
      }

      setStatus('success');
      setMessage('Вход подтверждён!');

      setTimeout(() => {
        tg.close();
      }, 1500);
    } catch (err) {
      setStatus('error');
      setMessage('Не удалось подключиться к серверу');
    }
  }

  return (
    <div style={styles.container}>
      <div style={styles.card}>
        <div style={styles.logo}>P</div>
        <h1 style={styles.title}>PARCER 2.0</h1>

        {userName && status === 'confirming' && (
          <p style={styles.greeting}>
            Привет, {userName}!
          </p>
        )}

        <div style={{ ...styles.statusBlock, ...statusStyles[status] }}>
          {status === 'confirming' && <Spinner />}
          {status === 'success' && <CheckMark />}
          {status === 'error' && <CrossMark />}
          {status === 'no_params' && <InfoMark />}
          <p style={styles.message}>{message}</p>
        </div>

        {status === 'success' && userName && (
          <p style={styles.subtext}>
            {userName}, вход выполнен. Окно закроется автоматически.
          </p>
        )}
      </div>
    </div>
  );
}

function Spinner() {
  return (
    <svg width="32" height="32" viewBox="0 0 24 24" style={{ animation: 'spin 1s linear infinite' }}>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" fill="none" strokeDasharray="40 60" strokeLinecap="round" />
    </svg>
  );
}

function CheckMark() {
  return (
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#34C759" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 6L9 17l-5-5" />
    </svg>
  );
}

function CrossMark() {
  return (
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#FF3B30" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 6L6 18M6 6l12 12" />
    </svg>
  );
}

function InfoMark() {
  return (
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#007AFF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <path d="M12 16v-4M12 8h.01" />
    </svg>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    minHeight: '100vh',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '16px',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    background: 'var(--tg-theme-bg-color, #f5f5f5)',
    color: 'var(--tg-theme-text-color, #1c1c1e)',
  },
  card: {
    width: '100%',
    maxWidth: '360px',
    textAlign: 'center' as const,
    padding: '32px 24px',
    borderRadius: '16px',
    background: 'var(--tg-theme-secondary-bg-color, #fff)',
    boxShadow: '0 2px 16px rgba(0,0,0,0.08)',
  },
  logo: {
    width: '56px',
    height: '56px',
    borderRadius: '14px',
    background: 'var(--tg-theme-button-color, #007AFF)',
    color: 'var(--tg-theme-button-text-color, #fff)',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: '28px',
    fontWeight: 700,
    marginBottom: '12px',
  },
  title: {
    fontSize: '22px',
    fontWeight: 600,
    margin: '0 0 24px',
    letterSpacing: '1px',
  },
  greeting: {
    fontSize: '15px',
    marginBottom: '16px',
    opacity: 0.7,
  },
  statusBlock: {
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'center',
    gap: '12px',
    padding: '20px',
    borderRadius: '12px',
    marginBottom: '12px',
  },
  message: {
    margin: 0,
    fontSize: '15px',
    lineHeight: 1.4,
  },
  subtext: {
    fontSize: '13px',
    opacity: 0.5,
    marginTop: '8px',
  },
};

const statusStyles: Record<Status, React.CSSProperties> = {
  init: { background: 'transparent' },
  confirming: { background: 'rgba(0,122,255,0.08)', color: 'var(--tg-theme-text-color, #007AFF)' },
  success: { background: 'rgba(52,199,89,0.1)', color: '#34C759' },
  error: { background: 'rgba(255,59,48,0.1)', color: '#FF3B30' },
  no_params: { background: 'rgba(0,122,255,0.06)', color: 'var(--tg-theme-text-color, #333)' },
};
