package uz.tbsparcer.sms.data.remote

import okhttp3.Interceptor
import okhttp3.Response
import uz.tbsparcer.sms.data.local.SettingsStore

class MobileKeyInterceptor(private val settings: SettingsStore) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val req = chain.request().newBuilder()
            .header("X-Mobile-Ingest-Key", settings.mobileKey)
            .build()
        return chain.proceed(req)
    }
}
