# TBSparcer SMS Collector — Android-клиент (дизайн)

**Дата:** 2026-05-30
**Статус:** утверждён к реализации
**Заменяет:** `ANDROID_APP.md` (2026-02-14) — устаревший план, писался ДО реализации backend.

---

## 1. Назначение

Android-приложение на одном устройстве заказчика:

1. Читает банковские SMS с телефона (реалтайм + разовый бэкфилл из inbox за выбранную дату).
2. Фильтрует банковские SMS от мусора (по тем же ключевым словам, что и backend regex).
3. Шлёт сырой текст SMS батчами на прод-backend `POST /api/sms/ingest`.
4. Backend парсит каскадом `regex → DeepSeek`, дедуплицирует по SHA256-fingerprint, кладёт новые в `transactions` (`source_type='SMS'`).
5. Приложение хранит локальный журнал каждой SMS со статусом (`pending/synced/duplicate/skipped/error`).
6. Показывает статистику (суммы по фильтрам, прошло/не прошло) и диагностику работоспособности.

Дизайн — **editorial monochrome** desktop-клиента (НЕ зелёный Material из старого плана).

---

## 2. Что уже есть на backend (не трогаем)

`backend/api/routes/sms.py` — работает на проде:

- `POST /api/sms/ingest` — батч до 50 SMS, синхронный парсинг, дедуп, ответ с per-item статусами.
- `GET /api/sms/health` — `{status, db, version, server_time}`.
- Авторизация всего роутера: заголовок `X-Mobile-Ingest-Key` (env `MOBILE_SMS_INGEST_KEY`, `secrets.compare_digest`). SMS-роутер освобождён от `X-System-Access`/JWT в middleware.
- Rate-limit: `MOBILE_SMS_INGEST_RATE_LIMIT_PER_MIN` (дефолт 10), батч-кап `MOBILE_SMS_INGEST_MAX_BATCH` (дефолт 50).

### Контракты (точные, из кода)

Request `POST /api/sms/ingest`:
```json
{
  "device_id": "string (опц., max 128)",
  "messages": [
    {
      "device_sms_id": "string (max 128)",
      "sender": "string (max 64)",
      "text": "string (1..4096)",
      "received_at": "ISO-8601 datetime",
      "sim_slot": 0
    }
  ]
}
```
`messages`: 1..50. `received_at` — ISO без таймзоны трактуется как Asia/Tashkent.

Response:
```json
{
  "processed": 3, "created": 1, "duplicates": 1, "skipped": 1, "errors": 0,
  "results": [
    {"device_sms_id":"...","status":"created","transaction_id":4521,"fingerprint":"...","error":null}
  ]
}
```
`status` ∈ `created | duplicate | skipped | parse_error`. HTTP: 200 успех, 403 неверный ключ, 503 ключ не настроен, 422 батч>лимита, 429 rate-limit.

---

## 3. Backend: новый эндпоинт статистики

Добавляется в существующий `backend/api/routes/sms.py` (тот же роутер, та же mobile-key защита, без JWT). Переиспользует фильтр-конвенции из `transactions.py` и колонки модели `Transaction`.

### 3.1 `GET /api/sms/stats`

Query-параметры (все опциональны):

| Параметр | Тип | Назначение |
|---|---|---|
| `date_from` | ISO datetime | начало периода (по `transaction_date`) |
| `date_to` | ISO datetime | конец периода |
| `source` | `all\|sms\|telegram` | фильтр по происхождению; `sms`→`source_type='SMS'`, `telegram`→`source_type='AUTO'` |
| `source_chat_id` | int | конкретный Telegram-бот (`source_chat_id=`); только при `source=telegram` |
| `card` | str (4 цифры) | `card_last_4 = card` |
| `currency` | `UZS\|USD` | дефолт UZS |

Ответ:
```json
{
  "currency": "UZS",
  "period_start": "2026-05-01T00:00:00",
  "period_end": "2026-05-30T23:59:59",
  "total_volume": "12500000.00",
  "debit_volume": "12000000.00",
  "credit_volume": "500000.00",
  "transaction_count": 342,
  "debit_count": 300,
  "credit_count": 42,
  "by_source": [
    {"source": "SMS", "count": 200, "volume": "8000000.00"},
    {"source": "TELEGRAM", "count": 142, "volume": "4500000.00"}
  ],
  "by_card": [
    {"card_last_4": "0907", "count": 120, "volume": "5000000.00"}
  ]
}
```

Реализация: агрегаты через `func.sum(func.abs(Transaction.amount))` / `func.count`, фильтры через тот же подход что `_build_filtered_transactions_query`. `volume` всегда по `abs(amount)` (знак не важен для «трат»). `by_source` группирует `source_type` (`SMS` отдельно, всё телеграмное `AUTO` → метка `TELEGRAM`). `by_card` — топ карт по объёму (limit 20).

«Прошло» = `transaction_count` (вся система — SMS + Telegram). «Не прошло по SMS» backend не хранит надёжно → считается **локально на телефоне** (Room: `skipped+error`), на экране подписано «не прошло (этот телефон)».

### 3.2 `GET /api/sms/sources`

Список Telegram-ботов для UI-фильтра (чтобы заказчик выбирал из списка, не вводил chat_id):
```json
{"items": [{"chat_id": -100123, "title": "UBpay bot", "count": 142}]}
```
Берётся из `Transaction.source_chat_id` (где `source_type='AUTO'` и `source_chat_id != 0`) + названия из `MonitoredBotChat`/`HiddenBotChat` (как в `transactions/init`). Без названия — fallback `chat_id` строкой.

### 3.3 Тесты backend

Расширить `backend/tests/test_sms_ingest_api.py`:
- `/api/sms/stats` без ключа → 403.
- агрегаты по seed-данным (объём/счётчики).
- фильтр `source=sms`, `card=`, `date_from/to`.
- `/api/sms/sources` отдаёт список.

### 3.4 Деплой

Только локальный код + тесты в этой работе. Выкатка на прод (`64.188.106.221`, docker cp) — **по явной команде пользователя** (как обычно, без rebuild).

---

## 4. Android: структура проекта

```
android/                                 # новый каталог в корне репо
  settings.gradle.kts, build.gradle.kts, gradle.properties
  gradle/wrapper/ (gradle-wrapper.properties → Gradle 8.x)
  local.properties (sdk.dir, НЕ в git)
  keystore/ (release.keystore — НЕ в git)
  app/
    build.gradle.kts
    src/main/AndroidManifest.xml
    src/main/res/font/ (Instrument Serif, Space Grotesk, JetBrains Mono .ttf)
    src/main/java/uz/tbsparcer/sms/
      TbsApp.kt                          # Application (Hilt)
      MainActivity.kt
      di/                AppModule, NetworkModule, DatabaseModule
      data/local/        SmsRecord (Entity), SmsRecordDao, AppDatabase
      data/remote/       ApiService (Retrofit), dto/*, MobileKeyInterceptor
      data/repo/         SmsRepository, StatsRepository, SettingsStore (EncryptedSharedPreferences)
      domain/            SmsFilter, FingerprintCalculator
      work/              SyncWorker, BackfillWorker
      receiver/          SmsReceiver (BroadcastReceiver)
      ui/theme/          Color.kt, Type.kt, Theme.kt (editorial monochrome)
      ui/components/      StatCard, StatusPill, FilterChip, SmsRow, SectionHeader
      ui/screens/         OnboardingScreen, HomeScreen, StatsScreen, DiagnosticsScreen, SettingsScreen, SmsDetailScreen
      ui/vm/              HomeViewModel, StatsViewModel, DiagnosticsViewModel, SettingsViewModel
    src/test/            SmsFilterTest, FingerprintCalculatorTest (зеркало backend)
```

### Стек
Kotlin, Jetpack Compose + Material3 (как контейнер тем, но с кастомными токенами), Retrofit2 + OkHttp + Moshi, Room, WorkManager, Hilt, androidx.security-crypto (EncryptedSharedPreferences).
`minSdk 26`, `targetSdk 35`, `compileSdk 35`. JDK 17. AGP/Gradle совместимые (Gradle 8.7+, AGP 8.5+).

---

## 5. Сбор SMS

### Onboarding (первый запуск)
1. Запрос разрешений `READ_SMS`, `RECEIVE_SMS`, `POST_NOTIFICATIONS` (Android 13+).
2. Date-picker «собрать SMS начиная с …» (по умолчанию — сегодня минус 30 дней).
3. Ввод/проверка настроек: Backend URL (дефолт прод), Mobile Ingest Key.
4. Тест связи (`/api/sms/health`) → запуск `BackfillWorker`.

### BackfillWorker
Читает `content://sms/inbox` с `date >= выбранная_дата_millis`, фильтрует через `SmsFilter`, кладёт новые в Room (`status=pending`). `device_sms_id` = `_id` из ContentResolver (PK → дедуп повторного бэкфилла).

### SmsReceiver (реалтайм)
`BroadcastReceiver` на `SMS_RECEIVED`. Фильтрует, кладёт в Room (`device_sms_id = "${timestampMillis}_${sender.hashCode()}"`), триггерит `SyncWorker` (expedited one-time).

### SmsFilter (зеркало backend regex_parser)
- Пропускает отправителей: google, telegram, viber, whatsapp, facebook, instagram, youtube.
- Ловит ключевые слова: `pokupka:`, `spisanie`, `popolnenie`, `e-com oplata`, `platezh:`, `otmena`, `humocard`, `summa:`, `balans:`, `karta`, `dostupno:`.
- Эвристика: (сумма-паттерн `\d{1,3}([., ]\d{3})*[.,]\d{2}`) И (карта-паттерн `\*{2,4}\d{4}` или `humocard *\d{4}`).
- Unit-тест на реальных примерах из `примеры чеки.txt`.

---

## 6. Синхронизация

### SyncWorker (WorkManager)
- Периодический: каждые 15 мин (мин. интервал WorkManager), constraint = сеть.
- Ручной: «SYNC NOW» (expedited) + после каждого `SmsReceiver`.
- Логика: взять `pending` (limit 50) → собрать `SmsIngestRequest` → `POST /ingest` → обновить Room по `results[].status` + `transaction_id`/`fingerprint`/`error`. При сетевой ошибке — пометить `error`, `Result.retry()` (экспоненциальный backoff).
- 403 (неверный ключ) / 503 (ключ не настроен) → НЕ retry, показать уведомление «проверь Mobile Key в настройках».

### MobileKeyInterceptor (OkHttp)
Добавляет `X-Mobile-Ingest-Key` из `SettingsStore` ко всем запросам. Ключ хранится в `EncryptedSharedPreferences`.

### Дедуп (3 уровня)
1. `device_sms_id` (PK Room) — не обрабатываем одну SMS дважды.
2. локальный fingerprint (опц., быстрая проверка «уже synced») через `FingerprintCalculator` (зеркало `fingerprint.py` v1).
3. серверный fingerprint (основной) — backend вернёт `duplicate`.

---

## 7. UI-экраны

### Дизайн-токены (editorial monochrome → Compose)
Шрифты в `res/font`: Instrument Serif (крупные числа/заголовки), Space Grotesk (UI), JetBrains Mono (лейблы/цифры, uppercase + letter-spacing).
Light: bg `#fafaf7`, surface `#ffffff`, ink `#0a0b0d`, accent `#111317`, border `#d1d5db`.
Dark: bg `#0a0b0d`, surface `#131418`, ink `#f4f5f7`, accent `#f4f5f7`, border `#2d3038`.
Доход `#16a34a`/`#4ade80`, расход `#dc2626`/`#f87171`. Радиусы: 4px (кнопки/инпуты), 6px (карточки). Плоско — бордеры 1px, не elevation. Тема: светлая/тёмная/системная.

### Home
Топбар (название + статус-пила online/offline + шестерёнка). Полоса статуса: pending / synced / errors. Кнопка SYNC NOW. Табы фильтра: All/Pending/Synced/Duplicate/Errors. Лента SmsRow (дата, статус-бейдж, txn_id, отправитель, начало текста). Тап → SmsDetail.

### Stats
- Карточка «Общая сумма трат» (Instrument Serif крупно).
- Фильтр-чипы `Все / SMS / Telegram` + выбор бота (из `/api/sms/sources`) при Telegram.
- Период (date-range picker) + ввод 4 цифр карты.
- Пара метрик «Прошло» (created, вся система) / «Не прошло» (локально SMS).
- Метрики debit/credit volume + count.
- Списки by_card / by_source.
Данные с `GET /api/sms/stats` (+ локальный счёт «не прошло» из Room).

### SmsDetail
Статус, transaction_id, fingerprint, synced_at, сырой текст SMS (mono, border-left), метаданные (sender, received, sim, device_sms_id).

### Diagnostics («100% работоспособность»)
- Backend доступен (`/api/sms/health` → ms, версия, статус БД).
- Mobile-key валиден (200/403/503).
- Разрешения SMS (READ/RECEIVE) выданы.
- SyncWorker: статус, последняя/следующая синхронизация.
- Очередь: pending / errors.
- Кнопки: «Тест связи», «Синхронизировать сейчас», «Повторить ошибки».

### Settings
Backend URL, Mobile Ingest Key (masked), device_id (генерируется), интервал синка, дата бэкфилла, переключатель темы. Кнопки: «Очистить локальную БД», «Полный пересбор inbox». Локальная статистика (collected/synced/duplicate/skipped/error).

---

## 8. Сборка, подпись, установка

Проблема прошлого раза: ставили debug/неподписанный APK или через adb → Android блокировал.

Решение:
1. `signingConfigs.release` с собственным `release.keystore` (генерирую через `keytool`, пароли — пользователю, в git не коммитим).
2. `buildTypes.release` с `isMinifyEnabled` (R8) + подпись release-ключом.
3. Сборка: `./gradlew :app:assembleRelease` → подписанный `app-release.apk`.
4. Инструкция заказчику: «Настройки → Приложения → Спец. доступ → Установка неизвестных приложений → разрешить для файлового менеджера/браузера» → открыть APK → установить.
5. Тулчейн: JDK 17 (`/opt/homebrew/opt/openjdk@17`), Android SDK (`~/Library/Android/sdk`, platform-35, build-tools 35) — уже на машине. Android Studio не требуется.

---

## 9. Безопасность

- Mobile Ingest Key в `EncryptedSharedPreferences` (не plaintext).
- `SmsReceiver` защищён `android:permission="android.permission.BROADCAST_SMS"`.
- INTERNET + cleartext: прод по HTTPS (nip.io TLS) → cleartext не нужен; для локального теста — `network_security_config` с явным allow только на dev-хост.
- Mobile-key даёт доступ только к `/api/sms/*` (ingest+health+stats+sources). Чужие данные/админка недоступны.
- `.gitignore`: keystore, local.properties, любые секреты.

---

## 10. Что НЕ делаем (YAGNI)

- Нет JWT-логина/launch-session (старый план — устарел).
- Нет мультидевайс-агрегации (одно устройство).
- Нет правки/удаления транзакций с телефона (только ingest + просмотр статистики).
- Нет auto-update APK (ставим вручную).
- Backend «не прошло по Telegram» глобально не добавляем (только SMS-fail локально, успех глобально).

---

## 11. Порядок реализации (для плана)

1. Backend: `GET /api/sms/stats` + `GET /api/sms/sources` в `sms.py` + тесты (локально).
2. Android: скелет проекта (Gradle, Hilt, Manifest, тема, шрифты).
3. Android: Room (SmsRecord/Dao/DB) + SettingsStore.
4. Android: domain (SmsFilter, FingerprintCalculator) + unit-тесты.
5. Android: remote (Retrofit ApiService, DTO, MobileKeyInterceptor).
6. Android: сбор SMS (BackfillWorker, SmsReceiver) + SyncWorker.
7. Android: UI (Onboarding, Home, Stats, Diagnostics, Settings, SmsDetail) + ViewModels.
8. Сборка: keystore + signingConfig + подписанный release APK + инструкция установки.
9. Верификация: unit-тесты, сборка APK, smoke-проверка контракта против backend.
```
