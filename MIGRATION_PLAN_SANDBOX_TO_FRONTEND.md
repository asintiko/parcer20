# Migration plan: design-sandbox → frontend

Дата плана: 2026-05-24
Источник: `design-sandbox/src/`
Цель: `frontend/src/`
Метод: модульный, по фазам, через feature-flag и shadow-deploy.

---

## 0. Что мы переносим

**Новые слои (отсутствуют в frontend):**
- `components/shell/` — AppShell, AppRail, AppTopbar, MobileDrawer, UserMenuPopover
- `components/motion/` — Sheet, Dialog, ConfirmDialog, Popover, StaggerChildren
- `components/telegram/` — 12 компонентов нового TG-клиента
- `components/AccessMatrixPanel.tsx`, `PromptModal.tsx`, `TwoFactorPanel.tsx`, `UserEditorSheet.tsx`, `UserRowMenu.tsx`
- `hooks/useHiddenChatsOverlay.ts`, `hooks/useShake.ts`
- `services/mockClient.ts`, `mockData.ts`, `mockTelegram.ts` — **НЕ ПЕРЕНОСИМ** (только sandbox)
- `styles/agent.css`, `ai-agent.css`, `login.css`, `reference.css`, `settings.css`, `shell.css`, `telegram.css`, `transactions.css`

**Переписанные:** App.tsx, main.tsx, AuthContext.tsx, AddTransactionModal, AiAgent* (8 файлов), FilterDrawer, LockedPeriodBanner, PeriodsManager, ReferenceTable, SessionsManager, SystemSettingsPanel, TransactionTable, useInlineEdit, useSettingsSubscription, LoginPage, ReferencePage, SettingsPage, TransactionsPage, UserbotPage, services/api.ts, styles/theme.css, utils/plural.ts (новый)

**НЕ переносим:**
- `services/mockClient.ts`, `mockData.ts`, `mockTelegram.ts`
- `pages/UserbotPage.legacy.tsx.bak`
- `pages/AutomationPage.tsx` (мёртвая в sandbox)
- bootstrap-блок mock-токенов в `main.tsx:44-54`
- `api.ts` корневой файл sandbox-а (orphan)

---

## 1. Pre-flight (1 день)

### 1.1 Чистка design-sandbox от мусора (опционально)
- удалить `design-sandbox/src/pages/UserbotPage.legacy.tsx.bak`
- удалить `design-sandbox/src/pages/AutomationPage.tsx` (1243 строки, не подключена)
- удалить `design-sandbox/api.ts` (98KB orphan в корне)
- проверить: `npm run build` в sandbox проходит после чистки

### 1.2 Зафиксировать baseline frontend
- ветка `pre-redesign-baseline` от текущего main
- запустить полный smoke-test (login → list → создать транзакцию → log out)
- скриншоты ключевых экранов для regression

### 1.3 Подготовить feature-flag механизм
- добавить env `VITE_NEW_DESIGN=1` в `frontend/.env.development`
- в `App.tsx` сделать роутинг через флаг:
  ```tsx
  const NEW_DESIGN = import.meta.env.VITE_NEW_DESIGN === '1'
  ```
- старый shell остаётся под `VITE_NEW_DESIGN=0` до конца миграции

---

## 2. Foundation (Phase 1, ~1 день)

Перенос токенов и базовых утилит. Без visual changes пока никто не подключит.

| # | File | Action |
|---|---|---|
| 1 | `styles/theme.css` | **REPLACE**. Diff token-by-token, перенести новые токены (motion easings, z-index scale, typography, semantic colors). Light/dark обе. |
| 2 | `tailwind.config.js` | **REPLACE**. Новые color/font/shadow/radius mappings. Verify `darkMode: ['selector', '[data-theme="dark"]']`. |
| 3 | `index.css` | DIFF: смерджить. `@import` новые шрифты (Instrument Serif, Space Grotesk, JetBrains Mono). `@layer base` стили с фокус-кольцом. |
| 4 | `utils/plural.ts` | **COPY** (новый файл). |
| 5 | `vite-env.d.ts` | DIFF, добавить новые env-types если есть. |

**Verify:** старые экраны под `VITE_NEW_DESIGN=0` рендерятся идентично; токены не сломаны.

---

## 3. Motion + Shell primitives (Phase 2, ~1 день)

Перенос `components/motion/` и `components/shell/` без подключения к старому App.

| # | File | Action |
|---|---|---|
| 6 | `components/motion/Sheet.tsx` | **COPY** |
| 7 | `components/motion/Dialog.tsx` | **COPY** |
| 8 | `components/motion/ConfirmDialog.tsx` | **COPY** |
| 9 | `components/motion/Popover.tsx` | **COPY** |
| 10 | `components/motion/StaggerChildren.tsx` | **COPY** |
| 11 | `components/shell/AppShell.tsx` | **COPY** |
| 12 | `components/shell/AppRail.tsx` | **COPY** |
| 13 | `components/shell/AppTopbar.tsx` | **COPY** |
| 14 | `components/shell/MobileDrawer.tsx` | **COPY** |
| 15 | `components/shell/UserMenuPopover.tsx` | **COPY** |
| 16 | `styles/shell.css` | **COPY** |
| 17 | `package.json` | добавить `motion@^12.40.0`, проверить `@dnd-kit/*`, `@mui/material@7`, `@mui/x-date-pickers@8`, `@tanstack/react-table`, `@tanstack/react-virtual`, `dexie@4`, `react-router-dom@7`, `dayjs`, `date-fns`. Сравнить версии. |

**Тест:** в sandbox-странице `/dev/preview` отрендерить shell с фейковыми routes. Тёмная/светлая темы. Проверить в DevTools focus-rings, body scroll lock на Sheet/Dialog.

---

## 4. Telegram-стек (Phase 3, ~1 день)

Перенос 12 компонентов telegram + CSS. Используется только новой UserbotPage, не ломает старую.

| # | File | Action |
|---|---|---|
| 18 | `components/telegram/Avatar.tsx` | COPY |
| 19 | `components/telegram/ChatList.tsx` | COPY |
| 20 | `components/telegram/ChatListItem.tsx` | COPY |
| 21 | `components/telegram/ChatHeader.tsx` | COPY |
| 22 | `components/telegram/MessageStream.tsx` | COPY |
| 23 | `components/telegram/MessageBubble.tsx` | COPY |
| 24 | `components/telegram/MessageInput.tsx` | COPY |
| 25 | `components/telegram/BulkBar.tsx` | COPY |
| 26 | `components/telegram/ContextMenu.tsx` | COPY |
| 27 | `components/telegram/PeriodPicker.tsx` | COPY |
| 28 | `components/telegram/PasswordDialog.tsx` | COPY |
| 29 | `components/telegram/EmptyState.tsx` | COPY (telegram-scoped) |
| 30 | `styles/telegram.css` | COPY |
| 31 | `hooks/useHiddenChatsOverlay.ts` | COPY |
| 32 | `hooks/useShake.ts` | COPY |

**Тест:** ничего не сломано, старый UserbotPage по-прежнему открывается.

---

## 5. AI agent UI (Phase 4, ~0.5 дня)

8 переписанных AiAgent* компонентов + ai-agent CSS.

| # | File | Action |
|---|---|---|
| 33 | `components/AiAgentDrawer.tsx` | **REPLACE** (новый layout, sectioned tabs) |
| 34 | `components/AiAgentLauncher.tsx` | **REPLACE** (FAB) |
| 35 | `components/AiAgentChat.tsx` | **REPLACE** |
| 36 | `components/AiAgentConfirmationCard.tsx` | **REPLACE** |
| 37 | `components/AiAgentMessage.tsx` | **REPLACE** |
| 38 | `components/AiAgentReportCard.tsx` | **REPLACE** |
| 39 | `components/AiAgentToolCard.tsx` | **REPLACE** |
| 40 | `styles/ai-agent.css` | **COPY** |
| 41 | `styles/agent.css` | **COPY** (если ещё не в старом фронте) |

**Verify:** ai-agent ходит в **реальный** `/api/agent/*`, sandbox-mock не подключается. Проверить streaming SSE, confirm-flow, navigation_target клик.

---

## 6. Pages (Phase 5, ~2 дня) — **самая рисковая**

Перенос 5 переписанных страниц + 5 новых компонентов settings.

### 6.1 Reference + table

| # | File | Action |
|---|---|---|
| 42 | `pages/ReferencePage.tsx` | REPLACE (668 строк, density toggle, sheets) |
| 43 | `components/ReferenceTable.tsx` | REPLACE |
| 44 | `components/PromptModal.tsx` | COPY (новый) |
| 45 | `styles/reference.css` | COPY |

### 6.2 Settings + access matrix + 2FA

| # | File | Action |
|---|---|---|
| 46 | `pages/SettingsPage.tsx` | REPLACE (1012 строк, secciony sidebar) |
| 47 | `components/AccessMatrixPanel.tsx` | COPY (новый) |
| 48 | `components/TwoFactorPanel.tsx` | COPY (новый) |
| 49 | `components/UserEditorSheet.tsx` | COPY (новый) |
| 50 | `components/UserRowMenu.tsx` | COPY (новый) |
| 51 | `components/PeriodsManager.tsx` | REPLACE |
| 52 | `components/SessionsManager.tsx` | REPLACE |
| 53 | `components/SystemSettingsPanel.tsx` | REPLACE |
| 54 | `styles/settings.css` | COPY |

### 6.3 Login

| # | File | Action |
|---|---|---|
| 55 | `pages/LoginPage.tsx` | REPLACE (467 строк, motion-stager, QR в одном экране) |
| 56 | `styles/login.css` | COPY |

### 6.4 Userbot (новый Telegram-клиент)

| # | File | Action |
|---|---|---|
| 57 | `pages/UserbotPage.tsx` | REPLACE (675 строк, 3-step auth локально) |

### 6.5 Transactions (большой файл, осторожно)

| # | File | Action |
|---|---|---|
| 58 | `pages/TransactionsPage.tsx` | REPLACE (1406 строк, scoped storage v2) |
| 59 | `components/TransactionTable.tsx` | REPLACE (большой, перепроверить inline edit + history undo/redo) |
| 60 | `components/AddTransactionModal.tsx` | REPLACE |
| 61 | `components/FilterDrawer.tsx` | REPLACE |
| 62 | `components/LockedPeriodBanner.tsx` | REPLACE |
| 63 | `hooks/useInlineEdit.ts` | REPLACE |
| 64 | `hooks/useSettingsSubscription.ts` | REPLACE |
| 65 | `styles/transactions.css` | COPY |

**Verify по каждой странице:**
- логин с реальными credentials → list пустой → CRUD одна запись → logout
- проверить что фильтры/сортировка/inline-edit/excel-export работают
- network tab — нет mockClient вызовов

---

## 7. Контейнеры (Phase 6, ~0.5 дня)

| # | File | Action |
|---|---|---|
| 66 | `App.tsx` | **REPLACE с осторожностью**. Routes такие же, но wrapped в `AppShell`. Под feature-flag `NEW_DESIGN`. |
| 67 | `main.tsx` | DIFF: ВЗЯТЬ providers (`AppThemeProvider`, MUI), но **НЕ ПЕРЕНОСИТЬ** `bootstrapSystemAccess()` (mock-bootstrap токенов). Production использует реальный `LaunchGate`. |
| 68 | `contexts/AuthContext.tsx` | DIFF, перенести только новые поля (`hasTab` уже есть в проде, проверить). |
| 69 | `services/api.ts` | DIFF, **обязательно `apiClient = axios.create(...)` а не `createMockApiClient()`**. Сравнить interceptors. |

---

## 8. Cleanup (Phase 7, ~0.5 дня)

После проверки всего флота:

- удалить `components/ui/Button.tsx`, `Input.tsx`, `Modal.tsx` (мёртвые в sandbox, заменены на motion/sp-classes)
- удалить старый `BurgerMenu.tsx` (если в sandbox его нет, значит уехал в `MobileDrawer`)
- удалить `AutomationPage.tsx` если в production он тоже не используется
- проверить `LaunchGate.tsx` — он есть в sandbox как orphan, но в проде должен быть подключён в `App.tsx`. Сверить версии.
- убрать feature-flag `VITE_NEW_DESIGN`, оставить только новый shell
- запустить `tsc --noEmit` + production build, ловить unused imports

---

## 9. Регрессия и accept (Phase 8, ~1 день)

### 9.1 Smoke-tests
- [ ] `/login` (credentials, 2FA, QR)
- [ ] `/` Transactions: фильтры, сортировка, inline-edit, undo, экспорт excel, добавить новую
- [ ] `/reference` CRUD + import/export
- [ ] `/userbot` 3-step auth + chat list + message stream + bulk-process
- [ ] `/logs` фильтры
- [ ] `/audit` базовая таблица
- [ ] `/settings` все секции (профиль, 2FA, тема, пользователи, scopes, периоды, sessions)
- [ ] AI agent: открытие drawer, отправка message, confirm/reject mutation, navigation_target клик

### 9.2 Visual regression
- скриншоты до/после: light + dark mode для каждой страницы
- mobile (≤1023px): rail скрывается, drawer работает

### 9.3 Performance
- Lighthouse: page load FCP/LCP не хуже baseline
- Tab-switching latency

### 9.4 A11y check
- Tab keyboard navigation работает
- focus-rings видны
- screen-reader реакция на dialog/sheet (хотя focus-trap не реализован — отметить как дебт)

---

## 10. Известные дыры, которые НЕ закрывает миграция

(вошли как технический долг, требуют отдельного PR)

1. **Focus-trap** в Sheet/Dialog/Popover отсутствует.
2. **Keyboard-nav** в Popover (стрелки/home/end) не реализована.
3. **MessageStream не виртуализирован** — потенциальный fps-проблема на 10k+ сообщениях.
4. **Theme tab-sync** через `storage`-event не подключён.
5. **Motion easings** в JS не читают CSS-tokens — расхождение между theme.css и literals.
6. **`ui/Button|Input|Modal`** — мёртвый код, заменены на `motion/*` + `.sp-*` CSS.
7. **i18n** только русский, нет `i18next`/переключателя языков.

---

## 11. План отката

При обнаружении блокирующих регрессий:

1. Установить `VITE_NEW_DESIGN=0` в проде.
2. Старый App.tsx остаётся под флагом — пользователи видят старый UI.
3. Старая ветка `pre-redesign-baseline` остаётся, можно cherry-pick.
4. Mock-сервисы (`mockClient.ts` etc.) не попали в production — откатывать API-слой не нужно.

---

## 12. Артефакты к деплою

```
frontend/src/
  components/
    motion/        ← новая
    shell/         ← новая
    telegram/      ← новая
    Ai*.tsx        ← перезаписаны (8 файлов)
    AccessMatrixPanel.tsx, PromptModal.tsx, TwoFactorPanel.tsx,
      UserEditorSheet.tsx, UserRowMenu.tsx ← новые
    AddTransactionModal, FilterDrawer, LockedPeriodBanner,
      PeriodsManager, ReferenceTable, SessionsManager,
      SystemSettingsPanel, TransactionTable ← перезаписаны
  hooks/
    useHiddenChatsOverlay.ts, useShake.ts ← новые
    useInlineEdit.ts, useSettingsSubscription.ts ← перезаписаны
  pages/
    LoginPage, ReferencePage, SettingsPage,
      TransactionsPage, UserbotPage ← перезаписаны
  styles/
    agent.css, ai-agent.css, login.css, reference.css,
      settings.css, shell.css, telegram.css, transactions.css ← новые
    theme.css ← перезаписан
  utils/
    plural.ts ← новый
  App.tsx, main.tsx, contexts/AuthContext.tsx, services/api.ts ← перезаписаны
package.json ← обновлены deps
```

---

## 13. Оценка времени

| Phase | Время | Risk |
|---|---|
| Pre-flight | 1 день | low |
| Foundation | 1 день | low |
| Motion + Shell | 1 день | low |
| Telegram | 1 день | medium |
| AI agent | 0.5 дня | medium |
| Pages | 2 дня | high (TransactionsPage большой) |
| Container | 0.5 дня | medium |
| Cleanup | 0.5 дня | low |
| Регрессия | 1 день | low |
| **Итого** | **~8.5 дней** | |

---

## 14. Ключевые точки внимания при копировании

### `services/api.ts`
- В sandbox: `apiClient = createMockApiClient()` (line 131)
- В проде должно остаться: `apiClient = axios.create(...)` с реальным baseURL.
- Перед коммитом — `grep -r "createMockApiClient" frontend/` должно вернуть 0.

### `main.tsx`
- НЕ копировать `bootstrapSystemAccess()` из sandbox `:44-54`.
- Сохранить production-логику pre-auth gate.

### `pages/UserbotPage.tsx`
- В sandbox использует `mockTelegram.ts` для статусов чатов и сообщений.
- В проде должна ходить в реальный `/api/tg/*` через `tdlibApi`.
- Проверить: imports `mockTelegram` не должно быть в финальной версии.

### Motion easings
- Если хочется правильно — добавить `lib/motion-tokens.ts` с константами:
  ```ts
  export const EASE_OUT = [0.16, 1, 0.3, 1] as const;
  export const EASE_IN = [0.4, 0, 1, 1] as const;
  ```
  и использовать вместо литералов в каждом motion-компоненте.

### `package.json`
- Сравнить `motion@^12.40.0` (новый) vs `framer-motion@^11.x` (старый). Удалить старый, поставить новый. Изменения import пути с `framer-motion` → `motion/react`.

### CSS namespace
- `.rl-*` (shell) — новые префиксы, не пересекаются.
- `.tg-*` (telegram) — могут пересекаться с существующими в frontend, проверить.
- `.sp-*` (settings/sheet/popover) — общий префикс, проверить collisions.

---

## 15. После миграции

1. Релиз через `feature-flag` → постепенный rollout 10% → 50% → 100% юзеров.
2. Сбор feedback в первую неделю.
3. Закрыть техдолг (focus-trap, virtualization, motion-tokens).
4. Удалить feature-flag и старый код.
