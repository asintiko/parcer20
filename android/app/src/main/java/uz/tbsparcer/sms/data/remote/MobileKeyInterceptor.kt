package uz.tbsparcer.sms.data.remote

import okhttp3.Interceptor
import okhttp3.Response
import uz.tbsparcer.sms.data.local.SettingsStore

class MobileKeyInterceptor(private val settings: SettingsStore) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val builder = chain.request().newBuilder()
        if (settings.isProvisioned) {
            builder.header("X-Mobile-Device-Id", settings.deviceId)
            builder.header("X-Mobile-Ingest-Key", settings.mobileKey)
        }
        val req = builder.build()
        return chain.proceed(req)
    }
}
