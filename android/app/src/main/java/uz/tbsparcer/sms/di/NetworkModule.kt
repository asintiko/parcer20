package uz.tbsparcer.sms.di

import com.squareup.moshi.Moshi
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import java.util.concurrent.TimeUnit
import javax.inject.Singleton
import uz.tbsparcer.sms.data.local.SettingsStore
import uz.tbsparcer.sms.data.remote.ApiService
import uz.tbsparcer.sms.data.remote.MobileKeyInterceptor

@Singleton
class ApiProvider(private val settings: SettingsStore) {
    private var cachedUrl: String = ""
    private var service: ApiService? = null

    @Synchronized
    fun api(): ApiService {
        val url = settings.baseUrl.let { if (it.endsWith("/")) it else "$it/" }
        val cur = service
        if (cur != null && url == cachedUrl) return cur
        val moshi = Moshi.Builder().build()
        val client = OkHttpClient.Builder()
            .addInterceptor(MobileKeyInterceptor(settings))
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .build()
        val built = Retrofit.Builder()
            .baseUrl(url)
            .client(client)
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()
            .create(ApiService::class.java)
        service = built
        cachedUrl = url
        return built
    }
}

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {
    @Provides @Singleton
    fun apiProvider(settings: SettingsStore): ApiProvider = ApiProvider(settings)
}
