package uz.tbsparcer.sms.data.local

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import dagger.hilt.android.qualifiers.ApplicationContext
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class SettingsStore @Inject constructor(@ApplicationContext ctx: Context) {
    private val prefs = run {
        val key = MasterKey.Builder(ctx).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
        EncryptedSharedPreferences.create(
            ctx, "tbs_secure", key,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    var baseUrl: String
        get() = prefs.getString("base_url", DEFAULT_BASE_URL) ?: DEFAULT_BASE_URL
        set(v) = prefs.edit().putString("base_url", v).apply()

    var mobileKey: String
        get() = prefs.getString("mobile_key", DEFAULT_MOBILE_KEY) ?: DEFAULT_MOBILE_KEY
        set(v) = prefs.edit().putString("mobile_key", v).apply()

    val deviceId: String
        @Synchronized get() {
            val existing = prefs.getString("device_id", null)
            if (existing != null) return existing
            val id = "android-" + UUID.randomUUID().toString().take(12)
            prefs.edit().putString("device_id", id).commit()
            return id
        }

    var backfillSinceMillis: Long
        get() = prefs.getLong("backfill_since", 0L)
        set(v) = prefs.edit().putLong("backfill_since", v).apply()

    var onboardingDone: Boolean
        get() = prefs.getBoolean("onboarding_done", false)
        set(v) = prefs.edit().putBoolean("onboarding_done", v).apply()

    var themeMode: String  // system | light | dark
        get() = prefs.getString("theme_mode", "system") ?: "system"
        set(v) = prefs.edit().putString("theme_mode", v).apply()

    companion object {
        const val DEFAULT_BASE_URL = "https://64.188.106.221.nip.io"
        const val DEFAULT_MOBILE_KEY = "yTr6C1RoVvJw6ODpzuEaoaS7CqlyPIBi4esOqlr3drE"
    }
}
