package uz.tbsparcer.sms.data.remote

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class SmsMessageDto(
    @Json(name = "device_sms_id") val deviceSmsId: String,
    val sender: String,
    val text: String,
    @Json(name = "received_at") val receivedAt: String,
    @Json(name = "sim_slot") val simSlot: Int?,
)

@JsonClass(generateAdapter = true)
data class SmsIngestRequest(
    @Json(name = "device_id") val deviceId: String,
    val messages: List<SmsMessageDto>,
)

@JsonClass(generateAdapter = true)
data class SmsParsedDto(
    val amount: String?,
    val currency: String?,
    @Json(name = "transaction_date") val transactionDate: String?,
    @Json(name = "card_last_4") val cardLast4: String?,
    val operator: String?,
    @Json(name = "transaction_type") val transactionType: String?,
    @Json(name = "balance_after") val balanceAfter: String?,
    val application: String?,
)

@JsonClass(generateAdapter = true)
data class SmsIngestResultItem(
    @Json(name = "device_sms_id") val deviceSmsId: String,
    val status: String,
    @Json(name = "transaction_id") val transactionId: Long?,
    val fingerprint: String?,
    val error: String?,
    val parsed: SmsParsedDto? = null,
)

@JsonClass(generateAdapter = true)
data class SmsIngestResponse(
    val processed: Int, val created: Int, val duplicates: Int,
    val skipped: Int, val errors: Int,
    val results: List<SmsIngestResultItem>,
)

@JsonClass(generateAdapter = true)
data class SmsHealthResponse(
    val status: String, val db: String, val version: String,
    @Json(name = "server_time") val serverTime: String,
)

@JsonClass(generateAdapter = true)
data class StatsSourceRow(val source: String, val count: Int, val volume: String)

@JsonClass(generateAdapter = true)
data class StatsCardRow(
    @Json(name = "card_last_4") val cardLast4: String, val count: Int, val volume: String)

@JsonClass(generateAdapter = true)
data class SmsStatsResponse(
    val currency: String,
    @Json(name = "period_start") val periodStart: String?,
    @Json(name = "period_end") val periodEnd: String?,
    @Json(name = "total_volume") val totalVolume: String,
    @Json(name = "debit_volume") val debitVolume: String,
    @Json(name = "credit_volume") val creditVolume: String,
    @Json(name = "transaction_count") val transactionCount: Int,
    @Json(name = "debit_count") val debitCount: Int,
    @Json(name = "credit_count") val creditCount: Int,
    @Json(name = "by_source") val bySource: List<StatsSourceRow>,
    @Json(name = "by_card") val byCard: List<StatsCardRow>,
)

@JsonClass(generateAdapter = true)
data class SourceItem(
    @Json(name = "chat_id") val chatId: Long, val title: String?, val count: Int)

@JsonClass(generateAdapter = true)
data class SourcesResponse(val items: List<SourceItem>)
