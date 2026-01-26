# Система тем приложения

## Обзор

Приложение использует систему тем на основе CSS переменных и Tailwind CSS. Поддерживаются светлая и темная темы с автоматической синхронизацией с системной темой ОС и Telegram Web K.

## Структура

### Файлы темы

- `frontend/src/styles/theme.css` - CSS переменные для всех тем
- `frontend/src/contexts/ThemeContext.tsx` - React Context для управления темой
- `frontend/tailwind.config.js` - Конфигурация Tailwind с токенами темы

## Использование токенов темы

### CSS переменные

Все цвета определены как CSS переменные в `theme.css`:

```css
/* Основные цвета */
--bg: основной фон
--surface: поверхности (карточки, панели)
--surface-2: вторичные поверхности
--text: основной текст
--text-secondary: вторичный текст
--text-muted: приглушенный текст
--border: границы

/* Семантические цвета */
--primary: акцентный цвет
--primary-hover: акцентный цвет при наведении
--danger: цвет опасности
--warning: цвет предупреждения
--success: цвет успеха
--info: информационный цвет
```

### Использование в Tailwind

Токены доступны через классы Tailwind:

```tsx
<div className="bg-surface text-text border border-border">
  <button className="bg-primary hover:bg-primary-hover text-text-inverse">
    Кнопка
  </button>
</div>
```

### Использование в компонентах

```tsx
import { useTheme } from '../contexts/ThemeContext';

function MyComponent() {
  const { isDark, toggleTheme } = useTheme();
  
  return (
    <div className={isDark ? 'bg-surface' : 'bg-white'}>
      <button onClick={toggleTheme}>Переключить тему</button>
    </div>
  );
}
```

## Изменение цветов темы

### 1. Изменение цветов в CSS переменных

Откройте `frontend/src/styles/theme.css` и измените значения переменных:

```css
[data-theme="dark"] {
  --primary: #8774E1; /* Измените на нужный цвет */
  --bg: #181818; /* Измените фон */
  /* ... */
}
```

### 2. Добавление новых токенов

1. Добавьте переменную в `theme.css`:
```css
:root {
  --my-color: #ffffff;
}

[data-theme="dark"] {
  --my-color: #000000;
}
```

2. Добавьте в `tailwind.config.js`:
```js
colors: {
  'my-color': 'var(--my-color)',
}
```

3. Используйте в компонентах:
```tsx
<div className="bg-my-color">...</div>
```

## Синхронизация с Telegram Web K

Legacy note: iframe Telegram Web K убран из приложения. Тема теперь применяется напрямую в нативном UI, хук `useTelegramThemeSync` не используется.

## Ограничения

1. **Cross-origin iframe**: Если Telegram Web K загружен с другого домена, прямое обращение к DOM недоступно. Используется только postMessage.

2. **Синхронизация при загрузке**: Тема применяется с небольшой задержкой (500ms) после загрузки iframe для гарантии готовности.

3. **Telegram Web K внутренняя тема**: Telegram Web K имеет свою систему тем. Мы синхронизируем только базовую темную/светлую тему, но не все кастомные настройки.

## Переключение темы

### Программное переключение

```tsx
import { useTheme } from '../contexts/ThemeContext';

function MyComponent() {
  const { setTheme, toggleTheme, theme } = useTheme();
  
  // Установить конкретную тему
  setTheme('dark');
  setTheme('light');
  setTheme('system'); // Синхронизация с ОС
  
  // Переключить между light/dark
  toggleTheme();
}
```

### Компонент переключателя

Используйте готовый компонент `ThemeToggle`:

```tsx
import { ThemeToggle } from '../components/ThemeToggle';

<ThemeToggle />
```

## Проверка темы

### Проверка текущей темы

```tsx
const { isDark, theme } = useTheme();

if (isDark) {
  // Темная тема активна
}

if (theme === 'system') {
  // Используется системная тема
}
```

### Проверка в CSS

```css
[data-theme="dark"] {
  /* Стили для темной темы */
}

[data-theme="light"] {
  /* Стили для светлой темы */
}
```

## Best Practices

1. **Всегда используйте токены**: Не используйте жестко заданные цвета (`#ffffff`, `bg-white`), используйте токены (`bg-surface`, `text-text`)

2. **Состояния интерактивности**: Всегда определяйте hover/focus/active состояния:
```tsx
<button className="bg-primary hover:bg-primary-hover focus:ring-2 focus:ring-primary">
```

3. **Контрастность**: Убедитесь, что текст читаем в обеих темах. Используйте `text-text` для основного текста и `text-text-secondary` для вторичного.

4. **Границы**: Используйте `border-border` для всех границ.

5. **Фокус-состояния**: Всегда добавляйте видимые focus-состояния для accessibility:
```tsx
className="focus:outline-none focus:ring-2 focus:ring-primary"
```

## Отладка

### Проверка активной темы

В консоли браузера:
```javascript
document.documentElement.getAttribute('data-theme') // 'dark' или 'light'
```

### Проверка CSS переменных

```javascript
getComputedStyle(document.documentElement).getPropertyValue('--primary')
```

### Логирование изменений темы

В `ThemeContext.tsx` можно добавить логирование:
```typescript
useEffect(() => {
  console.log('Theme changed:', theme, isDark);
}, [theme, isDark]);
```

