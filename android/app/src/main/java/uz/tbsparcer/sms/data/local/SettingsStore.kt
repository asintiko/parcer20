package uz.tbsparcer.sms.data.local

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import dagger.hilt.android.qualifiers.ApplicationContext
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton
import uz.tbsparcer.sms.BuildConfig

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

    // Baked in at build time from local.properties / env, never source-controlled and never shown
    // in the UI (the app is shared privately). Setter kept so the key can be rotated in-app via the
    // hidden advanced settings without rebuilding.
    var mobileKey: String
        get() = prefs.getString("mobile_key", BuildConfig.MOBILE_INGEST_KEY) ?: BuildConfig.MOBILE_INGEST_KEY
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

    // Set when the backend rejects the ingest key (HTTP 403). Surfaced in Home/Diagnostics
    // so the user fixes the key instead of the sync silently hammering a dead endpoint.
    var authError: Boolean
        get() = prefs.getBoolean("auth_error", false)
        set(v) = prefs.edit().putBoolean("auth_error", v).apply()

    companion object {
        const val DEFAULT_BASE_URL = "https://64.188.106.221.nip.io"
    }
}
