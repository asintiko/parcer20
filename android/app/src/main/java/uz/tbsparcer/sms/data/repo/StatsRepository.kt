package uz.tbsparcer.sms.data.repo

import uz.tbsparcer.sms.data.remote.SmsStatsResponse
import uz.tbsparcer.sms.data.remote.SourcesResponse
import uz.tbsparcer.sms.di.ApiProvider
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class StatsRepository @Inject constructor(private val apiProvider: ApiProvider) {
    suspend fun stats(
        dateFrom: String?, dateTo: String?, source: String,
        sourceChatId: Long?, card: String?,
    ): SmsStatsResponse = apiProvider.api().stats(dateFrom, dateTo, source, sourceChatId, card)

    suspend fun sources(): SourcesResponse = apiProvider.api().sources()
    suspend fun health() = apiProvider.api().health()
}
