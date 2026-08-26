# Android-приложение TBSparcer SMS Collector

**Дата:** 2026-02-14

---

## Назначение

Мобильное приложение для Android, которое:
- Читает SMS с телефона (все банковские уведомления)
- Фильтрует: пропускает уведомления от ботов, оставляет банковские SMS
- Отправляет сырой текст на backend для парсинга
- Backend парсит через существующий `ParserOrchestrator` (regex каскад + GPT fallback)
- Дедупликация: локальная (Room DB) + серверная (fingerprint SHA256)
- Показывает статус работы: что отправлено, что в очереди, что ошибка

---

## Стек технологий

| Компонент | Технология |
|-----------|-----------|
| Язык | Kotlin |
| UI | Jetpack Compose + Material 3 (dark theme) |
| HTTP | Retrofit 2 + OkHttp (interceptors для auth) |
| Локальная БД | Room (SQLite) |
| Фоновая работа | WorkManager (периодическая синхронизация) |
| Реальное время | SmsReceiver (BroadcastReceiver для входящих SMS) |
| DI | Hilt |
| Сериализация | kotlinx.serialization или Moshi |

---

## Архитектура

```
[SMS Inbox / BroadcastReceiver]
        |
        v
[SmsCollector] -- фильтрация по ключевым словам
        |
        v
[LocalDeduplicator] -- проверка Room DB (уже отправляли?)
        |
        v
[SyncQueue] -- Room таблица pending_sms
        |
        v
[SyncWorker] -- WorkManager / ручной триггер
        |
        v
[BackendApi] -- POST /api/sms/ingest
        |
        v
[Room DB update] -- пометка synced/duplicate/error
```

---

## Фаза 1: Новый backend endpoint

### POST /api/sms/ingest

Новый endpoint в backend. Принимает пачку SMS, прогоняет через существующий `ParserOrchestrator`, дедуплицирует через fingerprint.

**Файл:** `backend/api/routes/sms.py` (новый)

**Регистрация:** в `backend/api/main.py` добавить `app.include_router(sms_router, prefix="/api/sms")`

### Request

```python
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class SmsMessage(BaseModel):
    device_sms_id: str = Field(..., max_length=128)
    sender: str = Field(..., max_length=64)
    text: str = Field(..., min_length=1, max_length=4096)
    received_at: datetime
    sim_slot: Optional[int] = None


class SmsIngestRequest(BaseModel):
    device_id: str = Field(..., max_length=128)
    messages: List[SmsMessage] = Field(..., max_length=50)
```

### Response

```python
class SmsIngestResultItem(BaseModel):
    device_sms_id: str
    status: str  # "created" | "duplicate" | "skipped" | "parse_error"
    transaction_id: Optional[int] = None
    fingerprint: Optional[str] = None
    error: Optional[str] = None


class SmsIngestResponse(BaseModel):
    processed: int
    created: int
    duplicates: int
    skipped: int
    errors: int
    results: List[SmsIngestResultItem]
```

### Логика endpoint (псевдокод)

```python
from parsers.parser_orchestrator import ParserOrchestrator
from services.fingerprint import compute_fingerprint

@router.post("/ingest", response_model=SmsIngestResponse)
async def ingest_sms(
    request: SmsIngestRequest,
    db: Session = Depends(get_db),
    _gate: None = Depends(require_launch_session),
):
    orchestrator = ParserOrchestrator(db)
    results = []

    for msg in request.messages:
        # 1. Попытка парсинга
        parsed = orchestrator.parse_text(msg.text)
        if parsed is None:
            results.append(SmsIngestResultItem(
                device_sms_id=msg.device_sms_id,
                status="skipped",
                error="not_a_transaction",
            ))
            continue

        # 2. Fingerprint
        fp = compute_fingerprint(
            amount=parsed.amount,
            transaction_date=parsed.transaction_date,
            card_last4=parsed.card_last4,
        )

        # 3. Проверка дубликата в БД
        existing = db.query(Transaction).filter(
            Transaction.fingerprint == fp
        ).first()

        if existing:
            results.append(SmsIngestResultItem(
                device_sms_id=msg.device_sms_id,
                status="duplicate",
                transaction_id=existing.id,
                fingerprint=fp,
            ))
            continue

        # 4. Создание транзакции
        txn = Transaction(
            raw_message=msg.text,
            source_type="AUTO",
            source_chat_id=0,         # 0 = SMS source
            source_message_id=None,
            transaction_date=parsed.transaction_date,
            amount=parsed.amount,
            currency=parsed.currency or "UZS",
            card_last_4=parsed.card_last4,
            operator_raw=parsed.operator,
            application_mapped=parsed.application,
            transaction_type=parsed.transaction_type,
            balance_after=parsed.balance,
            receiver_name=parsed.receiver_name,
            receiver_card=parsed.receiver_card,
            is_p2p=parsed.is_p2p or False,
            parsing_method=parsed.method,
            parsing_confidence=parsed.confidence,
            fingerprint=fp,
        )
        db.add(txn)
        db.flush()

        results.append(SmsIngestResultItem(
            device_sms_id=msg.device_sms_id,
            status="created",
            transaction_id=txn.id,
            fingerprint=fp,
        ))

    db.commit()

    return SmsIngestResponse(
        processed=len(results),
        created=sum(1 for r in results if r.status == "created"),
        duplicates=sum(1 for r in results if r.status == "duplicate"),
        skipped=sum(1 for r in results if r.status == "skipped"),
        errors=sum(1 for r in results if r.status == "parse_error"),
        results=results,
    )
```

### Адаптация ParserOrchestrator

Сейчас `ParserOrchestrator.process()` принимает `raw_text` и возвращает `ParsedTransaction`. Нужно добавить метод `parse_text(text: str)` который:
- Вызывает `RegexParser.parse(text)` напрямую
- Если regex не справился — вызывает GPT parser
- Возвращает `ParsedTransaction` или `None`

Это минимальная обёртка над существующей логикой. Основные парсеры (`parse_sms_inline`, `parse_humo_notification`, `parse_cardxabar`, `parse_semicolon_format`) уже работают с текстом SMS.

### Защита endpoint

- Проходит через `LaunchSessionMiddleware` (требует `X-Launch-Session` header)
- Проходит через `SystemAccessMiddleware` (требует `X-System-Access` header)
- Rate limit: максимум 50 SMS за запрос, максимум 10 запросов в минуту

---

## Фаза 2: Android-приложение — структура проекта

```
app/
  src/main/
    java/com/tbsparcer/sms/
      di/                          # Hilt modules
        AppModule.kt
        NetworkModule.kt
        DatabaseModule.kt
      data/
        local/
          AppDatabase.kt           # Room DB
          SmsRecordDao.kt          # DAO
          SmsRecord.kt             # Entity
        remote/
          ApiService.kt            # Retrofit interface
          ApiModels.kt             # Request/Response модели
          AuthInterceptor.kt       # OkHttp interceptor (добавляет headers)
        repository/
          SmsRepository.kt         # Единая точка доступа к данным
      domain/
        SmsFilter.kt               # Фильтрация банковских SMS
        FingerprintCalculator.kt   # Локальный SHA256 fingerprint
      worker/
        SmsSyncWorker.kt           # WorkManager periodic sync
      receiver/
        SmsReceiver.kt             # BroadcastReceiver для входящих
      ui/
        theme/
          Theme.kt                 # Dark theme
          Colors.kt
          Typography.kt
        screens/
          MainScreen.kt            # Главный экран — список SMS
          SettingsScreen.kt        # Настройки (URL, токен)
          StatusScreen.kt          # Статус подключения, статистика
        components/
          SmsListItem.kt           # Элемент списка
          StatusBar.kt             # Верхняя панель статуса
          SyncButton.kt            # Кнопка синхронизации
        viewmodel/
          MainViewModel.kt
          SettingsViewModel.kt
      App.kt                       # Application class (Hilt)
      MainActivity.kt
    res/
      values/
        themes.xml                 # Dark theme по умолчанию
```

---

## Фаза 3: Локальная база данных (Room)

### Entity: SmsRecord

```kotlin
@Entity(tableName = "sms_records")
data class SmsRecord(
    @PrimaryKey
    val deviceSmsId: String,        // уникальный ID SMS на устройстве

    val sender: String,             // номер отправителя
    val body: String,               // текст SMS
    val receivedAt: Long,           // timestamp получения (millis)
    val simSlot: Int?,              // слот SIM (0, 1)

    val fingerprint: String?,       // локально вычисленный SHA256
    val syncStatus: String,         // "pending" | "synced" | "duplicate" | "skipped" | "error"
    val backendTransactionId: Int?, // ID транзакции на сервере (после sync)
    val errorMessage: String?,      // текст ошибки если есть
    val syncedAt: Long?,            // timestamp последней синхронизации
    val createdAt: Long             // timestamp добавления в Room
)
```

### DAO

```kotlin
@Dao
interface SmsRecordDao {

    @Query("SELECT * FROM sms_records ORDER BY receivedAt DESC LIMIT :limit")
    fun getRecent(limit: Int = 200): Flow<List<SmsRecord>>

    @Query("SELECT * FROM sms_records WHERE syncStatus = 'pending' ORDER BY receivedAt ASC LIMIT :limit")
    suspend fun getPending(limit: Int = 50): List<SmsRecord>

    @Query("SELECT COUNT(*) FROM sms_records WHERE syncStatus = 'pending'")
    fun getPendingCount(): Flow<Int>

    @Query("SELECT COUNT(*) FROM sms_records WHERE syncStatus = 'synced'")
    fun getSyncedCount(): Flow<Int>

    @Query("SELECT COUNT(*) FROM sms_records WHERE syncStatus = 'error'")
    fun getErrorCount(): Flow<Int>

    @Query("SELECT deviceSmsId FROM sms_records")
    suspend fun getAllIds(): List<String>

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertAll(records: List<SmsRecord>): List<Long>

    @Query("""
        UPDATE sms_records
        SET syncStatus = :status,
            backendTransactionId = :txnId,
            fingerprint = :fingerprint,
            errorMessage = :error,
            syncedAt = :syncedAt
        WHERE deviceSmsId = :smsId
    """)
    suspend fun updateSyncResult(
        smsId: String,
        status: String,
        txnId: Int?,
        fingerprint: String?,
        error: String?,
        syncedAt: Long
    )
}
```

---

## Фаза 4: Фильтрация SMS

### SmsFilter.kt

Фильтрует банковские SMS от мусора. Используем те же ключевые слова что и backend `regex_parser.py`.

```kotlin
object SmsFilter {

    // Ключевые слова банковских SMS (из regex_parser.py)
    private val BANK_KEYWORDS = listOf(
        "pokupka:", "spisanie", "popolnenie", "e-com oplata",
        "platezh:", "otmena", "perevod", "transfer",
        "cardxabar", "humocard",
        "summa:", "balans:", "karta",
    )

    // Эмодзи-паттерны Humo (из regex_parser.py parse_humo_notification)
    private val HUMO_EMOJIS = listOf(
        "\uD83D\uDCB8",  // money with wings
        "\uD83D\uDCB3",  // credit card
        "\uD83D\uDCCD",  // location pin
        "\uD83D\uDD53",  // clock
    )

    // Отправители-боты которые надо пропускать
    private val IGNORED_SENDERS = listOf(
        "google", "telegram", "viber", "whatsapp",
        "facebook", "instagram", "youtube",
    )

    fun isBankSms(sender: String, body: String): Boolean {
        val lowerSender = sender.lowercase()
        if (IGNORED_SENDERS.any { lowerSender.contains(it) }) {
            return false
        }

        val lowerBody = body.lowercase()

        // Проверка ключевых слов
        if (BANK_KEYWORDS.any { lowerBody.contains(it) }) {
            return true
        }

        // Проверка эмодзи Humo
        if (HUMO_EMOJIS.count { body.contains(it) } >= 2) {
            return true
        }

        // Проверка паттерна суммы + карты
        val hasAmount = Regex("""\d{1,3}([., ]\d{3})*[.,]\d{2}""").containsMatchIn(body)
        val hasCard = Regex("""\*{2,3}\d{4}""").containsMatchIn(body)
        if (hasAmount && hasCard) {
            return true
        }

        return false
    }
}
```

---

## Фаза 5: Локальный fingerprint

### FingerprintCalculator.kt

Повторяет логику `backend/services/fingerprint.py` для локальной дедупликации.

```kotlin
import java.math.BigDecimal
import java.math.RoundingMode
import java.security.MessageDigest
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

object FingerprintCalculator {

    private val dateFormat = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")

    /**
     * Вычисляет fingerprint идентично backend:
     * SHA256("{amount_abs_2dec}|{date_YYYY-MM-DD HH:MM}|{card4}")
     *
     * Используется для ЛОКАЛЬНОЙ дедупликации до отправки на сервер.
     * Сервер вычисляет свой fingerprint и проверяет повторно.
     */
    fun compute(
        amount: BigDecimal?,
        transactionDate: LocalDateTime?,
        cardLast4: String?
    ): String {
        val amountStr = amount
            ?.abs()
            ?.setScale(2, RoundingMode.HALF_UP)
            ?.toPlainString()
            ?: "0.00"

        val dateStr = transactionDate
            ?.format(dateFormat)
            ?: "1970-01-01 00:00"

        val cardStr = cardLast4?.takeLast(4)?.padStart(4, '0') ?: "0000"

        val raw = "$amountStr|$dateStr|$cardStr"
        val digest = MessageDigest.getInstance("SHA-256")
        return digest.digest(raw.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
    }
}
```

Fingerprint нужен на клиенте только для быстрой локальной проверки "это SMS уже точно отправляли". Основная проверка — на сервере.

---

## Фаза 6: Сбор SMS с устройства

### Чтение из ContentResolver (существующие SMS)

```kotlin
class SmsCollector(
    private val context: Context,
    private val dao: SmsRecordDao
) {

    /**
     * Читает SMS из inbox, фильтрует банковские,
     * сохраняет новые в Room со статусом "pending".
     */
    suspend fun collectFromInbox() {
        val existingIds = dao.getAllIds().toHashSet()
        val cursor = context.contentResolver.query(
            Uri.parse("content://sms/inbox"),
            arrayOf("_id", "address", "body", "date", "sim_id"),
            null, null,
            "date DESC"
        ) ?: return

        val newRecords = mutableListOf<SmsRecord>()

        cursor.use {
            while (it.moveToNext()) {
                val id = it.getString(0) ?: continue
                if (existingIds.contains(id)) continue

                val sender = it.getString(1) ?: ""
                val body = it.getString(2) ?: ""
                val date = it.getLong(3)
                val simSlot = try { it.getInt(4) } catch (_: Exception) { null }

                if (!SmsFilter.isBankSms(sender, body)) continue

                newRecords.add(
                    SmsRecord(
                        deviceSmsId = id,
                        sender = sender,
                        body = body,
                        receivedAt = date,
                        simSlot = simSlot,
                        fingerprint = null,
                        syncStatus = "pending",
                        backendTransactionId = null,
                        errorMessage = null,
                        syncedAt = null,
                        createdAt = System.currentTimeMillis()
                    )
                )
            }
        }

        if (newRecords.isNotEmpty()) {
            dao.insertAll(newRecords)
        }
    }
}
```

### BroadcastReceiver (входящие SMS в реальном времени)

```kotlin
class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return

        val messages = Telephony.Sms.Intents.getMessagesFromIntent(intent)
        for (sms in messages) {
            val sender = sms.originatingAddress ?: continue
            val body = sms.messageBody ?: continue

            if (!SmsFilter.isBankSms(sender, body)) continue

            // Enqueue для сохранения в Room
            val workRequest = OneTimeWorkRequestBuilder<SmsInsertWorker>()
                .setInputData(workDataOf(
                    "sender" to sender,
                    "body" to body,
                    "received_at" to sms.timestampMillis,
                    "device_sms_id" to "${sms.timestampMillis}_${sender.hashCode()}"
                ))
                .build()

            WorkManager.getInstance(context).enqueue(workRequest)
        }
    }
}
```

### AndroidManifest.xml (permissions и receiver)

```xml
<uses-permission android:name="android.permission.READ_SMS" />
<uses-permission android:name="android.permission.RECEIVE_SMS" />
<uses-permission android:name="android.permission.INTERNET" />

<application ...>
    <receiver
        android:name=".receiver.SmsReceiver"
        android:exported="true"
        android:permission="android.permission.BROADCAST_SMS">
        <intent-filter>
            <action android:name="android.provider.Telephony.SMS_RECEIVED" />
        </intent-filter>
    </receiver>
</application>
```

---

## Фаза 7: Синхронизация с backend

### ApiService.kt (Retrofit)

```kotlin
interface ApiService {

    @POST("/api/sms/ingest")
    suspend fun ingestSms(
        @Body request: SmsIngestRequest
    ): SmsIngestResponse

    @GET("/api/security/status")
    suspend fun getSecurityStatus(): SecurityStatusResponse

    @POST("/api/security/app/verify-launch")
    suspend fun verifyLaunch(
        @Body request: VerifyLaunchRequest
    ): VerifyLaunchResponse
}
```

### AuthInterceptor.kt

```kotlin
class AuthInterceptor(
    private val settingsStore: SettingsStore
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val original = chain.request()

        val builder = original.newBuilder()

        // System access token (из client-access.json или настроек)
        settingsStore.systemAccessToken?.let {
            builder.header("X-System-Access", it)
        }

        // Launch session token
        settingsStore.launchSessionToken?.let {
            builder.header("X-Launch-Session", it)
        }

        return chain.proceed(builder.build())
    }
}
```

### SmsSyncWorker.kt (WorkManager)

```kotlin
@HiltWorker
class SmsSyncWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val dao: SmsRecordDao,
    private val api: ApiService,
    private val settings: SettingsStore,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        // 1. Собрать новые SMS из inbox
        SmsCollector(applicationContext, dao).collectFromInbox()

        // 2. Взять pending записи
        val pending = dao.getPending(limit = 50)
        if (pending.isEmpty()) return Result.success()

        // 3. Сформировать запрос
        val request = SmsIngestRequest(
            deviceId = settings.deviceId,
            messages = pending.map { sms ->
                SmsMessageDto(
                    deviceSmsId = sms.deviceSmsId,
                    sender = sms.sender,
                    text = sms.body,
                    receivedAt = Instant.ofEpochMilli(sms.receivedAt)
                        .atZone(ZoneId.systemDefault())
                        .toLocalDateTime()
                        .toString(),
                    simSlot = sms.simSlot,
                )
            }
        )

        // 4. Отправить на backend
        val response = try {
            api.ingestSms(request)
        } catch (e: Exception) {
            // Пометить все как error, retry позже
            val now = System.currentTimeMillis()
            pending.forEach { sms ->
                dao.updateSyncResult(
                    smsId = sms.deviceSmsId,
                    status = "error",
                    txnId = null,
                    fingerprint = null,
                    error = e.message?.take(200),
                    syncedAt = now,
                )
            }
            return Result.retry()
        }

        // 5. Обновить локальную БД по результатам
        val now = System.currentTimeMillis()
        for (item in response.results) {
            dao.updateSyncResult(
                smsId = item.deviceSmsId,
                status = item.status,
                txnId = item.transactionId,
                fingerprint = item.fingerprint,
                error = item.error,
                syncedAt = now,
            )
        }

        return Result.success()
    }
}
```

### Регистрация периодической синхронизации

```kotlin
// В Application.onCreate или при первом запуске
fun schedulePeriodicSync(context: Context) {
    val constraints = Constraints.Builder()
        .setRequiredNetworkType(NetworkType.CONNECTED)
        .build()

    val request = PeriodicWorkRequestBuilder<SmsSyncWorker>(
        15, TimeUnit.MINUTES  // минимальный интервал WorkManager
    )
        .setConstraints(constraints)
        .setBackoffCriteria(
            BackoffPolicy.EXPONENTIAL,
            1, TimeUnit.MINUTES
        )
        .build()

    WorkManager.getInstance(context).enqueueUniquePeriodicWork(
        "sms_sync",
        ExistingPeriodicWorkPolicy.KEEP,
        request,
    )
}
```

---

## Фаза 8: Проверка дубликатов — три уровня

### Уровень 1: device_sms_id (локальный)

При сборе SMS из inbox, каждой SMS присваивается `_id` из ContentResolver. Если `_id` уже есть в Room — пропускаем. Это предотвращает повторную обработку одних и тех же SMS.

### Уровень 2: fingerprint (локальный)

Опциональная локальная проверка. Если SMS удалось распарсить на клиенте (быстрая regex проверка), вычисляем fingerprint и проверяем — нет ли в Room записи с таким же fingerprint и статусом "synced". Это актуально когда одна и та же транзакция приходит как SMS и как Telegram-уведомление (уже на сервере).

Для этого добавить в Room:
```kotlin
@Query("SELECT COUNT(*) FROM sms_records WHERE fingerprint = :fp AND syncStatus = 'synced'")
suspend fun countByFingerprint(fp: String): Int
```

### Уровень 3: fingerprint (серверный)

Backend вычисляет fingerprint по формуле `SHA256(amount|date|card_last4)` и проверяет в таблице `transactions`. Если fingerprint совпадает — возвращает `status: "duplicate"` и ID существующей транзакции. Это ловит дубликаты между SMS и Telegram-каналом.

### Схема проверки

```
SMS приходит
    |
    v
[device_sms_id в Room?] --да--> ПРОПУСК (уже обработано)
    | нет
    v
[SmsFilter.isBankSms?] --нет--> ПРОПУСК (не банковское)
    | да
    v
[Сохранить в Room, status=pending]
    |
    v
[SmsSyncWorker отправляет на backend]
    |
    v
[Backend: парсинг -> fingerprint -> проверка в transactions]
    |
    +--> parse_error: не удалось распарсить
    +--> duplicate: fingerprint уже есть в БД
    +--> created: новая транзакция создана
    +--> skipped: не транзакция (не нашлось паттерна)
    |
    v
[Room: обновить status + transaction_id]
```

---

## Фаза 9: UI — дизайн и экраны

### Тема

- Тёмная тема по умолчанию, без переключения
- Цвета: фон `#121212`, карточки `#1E1E1E`, текст `#E0E0E0`, акцент `#4CAF50`
- Шрифт: системный, без кастомных
- Без эмодзи, без анимаций, без градиентов

### Экран 1: Главный (MainScreen)

```
+------------------------------------------+
| TBSparcer SMS                    [gear]  |
+------------------------------------------+
| CONNECTION: OK     PENDING: 12    ERR: 0 |
+------------------------------------------+
| [SYNC NOW]                               |
+------------------------------------------+
| [ALL] [PENDING] [SYNCED] [ERRORS]        |
+------------------------------------------+
|                                          |
| 14.02.2026  10:32      SYNCED     #4521  |
| +998712345678                             |
| Pokupka: XK FAMILY SHOP, summa:80000...  |
| ---                                      |
| 14.02.2026  10:15      PENDING           |
| +998712345678                             |
| Spisanie: UZCARD ONLINE, summa:150000... |
| ---                                      |
| 14.02.2026  09:48      DUPLICATE  #4519  |
| +998712345678                             |
| Popolnenie: karta ***0907, summa:500...  |
|                                          |
+------------------------------------------+
```

Элементы:
- Верхняя панель: название, кнопка настроек
- Строка статуса: подключение, количество pending, ошибок
- Кнопка "SYNC NOW" — запускает немедленную синхронизацию
- Табы фильтрации: All / Pending / Synced / Errors
- Список SMS: дата, статус, ID транзакции (если есть), отправитель, начало текста

### Экран 2: Детали SMS (по нажатию на элемент)

```
+------------------------------------------+
| [<- Back]             SMS Detail         |
+------------------------------------------+
|                                          |
| Status: SYNCED                           |
| Transaction ID: #4521                    |
| Fingerprint: a3f8c2...                   |
| Synced at: 14.02.2026 10:33             |
|                                          |
| --- Original Text ---                    |
|                                          |
| Pokupka: XK FAMILY SHOP, TOSHKENT,      |
| 14.02.26 10:32                           |
| karta ***0907. summa:80000.00 UZS,       |
| balans:2527792.14 UZS                    |
|                                          |
| --- Metadata ---                         |
|                                          |
| Sender: +998712345678                    |
| Received: 14.02.2026 10:32:15           |
| SIM: slot 0                             |
| Device SMS ID: 15823                     |
|                                          |
+------------------------------------------+
```

### Экран 3: Настройки (SettingsScreen)

```
+------------------------------------------+
| [<- Back]            Settings            |
+------------------------------------------+
|                                          |
| Backend URL                              |
| [http://192.168.1.100:8000_________]     |
|                                          |
| System Access Token                      |
| [********************************]       |
|                                          |
| Launch Password                          |
| [********]      [VERIFY]                 |
|                                          |
| --- Status ---                           |
| Connection: OK                           |
| Launch Session: Active (exp 15.02 10:00) |
| Last Sync: 14.02.2026 10:33             |
| Sync Interval: 15 min                   |
|                                          |
| --- Stats ---                            |
| Total SMS collected: 847                 |
| Synced: 812                              |
| Duplicates: 23                           |
| Skipped: 8                               |
| Errors: 4                                |
|                                          |
| [CLEAR LOCAL DB]    [FORCE FULL RESCAN]  |
|                                          |
+------------------------------------------+
```

### Экран 4: Проверка работы (StatusScreen)

Доступен по нажатию на строку статуса в MainScreen.

```
+------------------------------------------+
| [<- Back]         Diagnostics            |
+------------------------------------------+
|                                          |
| --- Connection Tests ---                 |
|                                          |
| Backend reachable:     OK    (45ms)      |
| System access valid:   OK                |
| Launch session valid:  OK    (exp 23h)   |
| SMS permission:        OK                |
|                                          |
| --- Sync Status ---                      |
|                                          |
| WorkManager status:    ENQUEUED          |
| Last sync attempt:     10:33 (2 min ago) |
| Last sync result:      SUCCESS           |
| Next scheduled sync:   ~10:48            |
|                                          |
| --- Queue ---                            |
|                                          |
| Pending SMS:           12                |
| Errors (retriable):   2                  |
| Errors (permanent):   0                  |
|                                          |
| [RUN CONNECTIVITY TEST]                  |
| [TRIGGER MANUAL SYNC]                    |
| [RETRY ALL ERRORS]                       |
|                                          |
+------------------------------------------+
```

Тест подключения выполняет:
1. Ping backend (`GET /api/security/status`)
2. Проверка System Access Token
3. Проверка Launch Session (если expired — показать поле ввода пароля)
4. Проверка SMS permission (`READ_SMS`, `RECEIVE_SMS`)

---

## Фаза 10: Авторизация и безопасность

### Хранение токенов

- `system_access_token` — из настроек, хранится в `EncryptedSharedPreferences`
- `launch_session_token` — JWT, получается через `POST /api/security/app/verify-launch`
- Оба токена отправляются с каждым запросом через `AuthInterceptor`

### Launch Session Flow

1. При первом запуске или когда session expired:
   - Показать экран ввода пароля (аналог LaunchGate на фронтенде)
   - `POST /api/security/app/verify-launch` с паролем
   - Получить `session_token`, сохранить
   - Показать главный экран

2. Если backend вернул 403 `launch_expired`:
   - Показать экран ввода пароля
   - После ввода — продолжить синхронизацию

3. WorkManager при 403: помечает result как `Result.retry()`, показывает notification "Session expired"

### EncryptedSharedPreferences

```kotlin
val masterKey = MasterKey.Builder(context)
    .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
    .build()

val prefs = EncryptedSharedPreferences.create(
    context,
    "tbsparcer_secure_prefs",
    masterKey,
    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
)
```

---

## Фаза 11: Обработка 403 — сессия отозвана через бот

Аналогично фронтенду. Если бот убил сессию:

1. Следующий запрос к backend вернёт 403 `launch_expired`
2. OkHttp interceptor перехватывает:
   ```kotlin
   class SessionExpiredInterceptor(...) : Interceptor {
       override fun intercept(chain: Interceptor.Chain): Response {
           val response = chain.proceed(chain.request())
           if (response.code == 403) {
               val body = response.peekBody(1024).string()
               if (body.contains("launch_expired") || body.contains("launch_required")) {
                   settings.clearLaunchSession()
                   // Отправить broadcast / event для UI
                   EventBus.post(SessionExpiredEvent)
               }
           }
           return response
       }
   }
   ```
3. UI ловит event, показывает экран ввода пароля

---

## Порядок реализации

| Шаг | Что делать | Оценка |
|-----|-----------|--------|
| 1 | Backend: `POST /api/sms/ingest` endpoint | 2-3 часа |
| 2 | Backend: `parse_text()` метод в ParserOrchestrator | 1 час |
| 3 | Android: проект, Hilt, Room, тема | 2-3 часа |
| 4 | Android: SmsFilter + SmsCollector | 2 часа |
| 5 | Android: Retrofit + AuthInterceptor | 1-2 часа |
| 6 | Android: SmsSyncWorker + WorkManager setup | 2-3 часа |
| 7 | Android: MainScreen (список SMS + фильтры) | 3-4 часа |
| 8 | Android: SettingsScreen + EncryptedPrefs | 2 часа |
| 9 | Android: StatusScreen (диагностика) | 2 часа |
| 10 | Android: SmsReceiver (реальное время) | 1 час |
| 11 | Android: обработка 403, Launch Gate | 2 часа |
| 12 | Тестирование полного цикла | 3-4 часа |

Общая оценка: 22-28 часов разработки.

---

## Зависимости (build.gradle)

```groovy
dependencies {
    // Core
    implementation "androidx.core:core-ktx:1.12.0"
    implementation "androidx.lifecycle:lifecycle-runtime-ktx:2.7.0"
    implementation "androidx.activity:activity-compose:1.8.2"

    // Compose
    implementation platform("androidx.compose:compose-bom:2024.01.00")
    implementation "androidx.compose.ui:ui"
    implementation "androidx.compose.material3:material3"
    implementation "androidx.compose.ui:ui-tooling-preview"
    implementation "androidx.navigation:navigation-compose:2.7.6"

    // Room
    implementation "androidx.room:room-runtime:2.6.1"
    implementation "androidx.room:room-ktx:2.6.1"
    kapt "androidx.room:room-compiler:2.6.1"

    // WorkManager
    implementation "androidx.work:work-runtime-ktx:2.9.0"

    // Hilt
    implementation "com.google.dagger:hilt-android:2.50"
    kapt "com.google.dagger:hilt-compiler:2.50"
    implementation "androidx.hilt:hilt-work:1.1.0"
    kapt "androidx.hilt:hilt-compiler:1.1.0"

    // Network
    implementation "com.squareup.retrofit2:retrofit:2.9.0"
    implementation "com.squareup.retrofit2:converter-moshi:2.9.0"
    implementation "com.squareup.okhttp3:okhttp:4.12.0"
    implementation "com.squareup.okhttp3:logging-interceptor:4.12.0"
    implementation "com.squareup.moshi:moshi-kotlin:1.15.0"
    kapt "com.squareup.moshi:moshi-kotlin-codegen:1.15.0"

    // Security
    implementation "androidx.security:security-crypto:1.1.0-alpha06"
}
```
