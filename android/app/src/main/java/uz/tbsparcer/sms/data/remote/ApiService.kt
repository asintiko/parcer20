package uz.tbsparcer.sms.data.remote

import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Query

interface ApiService {
    @GET("api/sms/health")
    suspend fun health(): SmsHealthResponse

    @POST("api/sms/ingest")
    suspend fun ingest(@Body body: SmsIngestRequest): SmsIngestResponse

    @GET("api/sms/stats")
    suspend fun stats(
        @Query("date_from") dateFrom: String? = null,
        @Query("date_to") dateTo: String? = null,
        @Query("source") source: String = "all",
        @Query("source_chat_id") sourceChatId: Long? = null,
        @Query("card") card: String? = null,
        @Query("currency") currency: String = "UZS",
    ): SmsStatsResponse

    @GET("api/sms/sources")
    suspend fun sources(): SourcesResponse
}
