package uz.tbsparcer.sms.data.local

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import android.content.SharedPreferences
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import javax.inject.Inject
import javax.inject.Singleton

object ProvisioningPolicy {
    const val CURRENT_SCHEMA_VERSION = 1
    private val deviceIdPattern = Regex("^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

    fun validDeviceId(value: String): Boolean =
        value == value.trim() && deviceIdPattern.matches(value)

    fun validMobileKey(value: String): Boolean =
        value == value.trim() && value.length >= 32

    fun provisioned(deviceId: String, mobileKey: String): Boolean =
        validDeviceId(deviceId) && validMobileKey(mobileKey)

    fun provisionedForCurrentSchema(schemaVersion: Int, deviceId: String, mobileKey: String): Boolean =
        schemaVersion >= CURRENT_SCHEMA_VERSION && provisioned(deviceId, mobileKey)

    fun monitoringEnabled(
        onboardingDone: Boolean,
        schemaVersion: Int,
        deviceId: String,
        mobileKey: String,
    ): Boolean = onboardingDone && provisionedForCurrentSchema(schemaVersion, deviceId, mobileKey)

    fun requiresUpgradeProvisioning(
        onboardingDone: Boolean,
        schemaVersion: Int,
        deviceId: String,
        mobileKey: String,
    ): Boolean = onboardingDone &&
        (schemaVersion < CURRENT_SCHEMA_VERSION || !provisioned(deviceId, mobileKey))
}

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

    init {
        migrateLegacyProvisioningState()
    }

    var baseUrl: String
        get() = prefs.getString("base_url", DEFAULT_BASE_URL) ?: DEFAULT_BASE_URL
        set(v) = prefs.edit().putString("base_url", v).apply()

    // Provisioned per device and encrypted at rest. Release artifacts never contain credentials.
    val mobileKey: String
        get() = prefs.getString("mobile_key", "") ?: ""

    val deviceId: String
        get() = prefs.getString("device_id", "") ?: ""

    var backfillSinceMillis: Long
        get() = prefs.getLong("backfill_since", 0L)
        set(v) = prefs.edit().putLong("backfill_since", v).apply()

    val onboardingDone: Boolean
        get() = prefs.getBoolean("onboarding_done", false)

    val isProvisioned: Boolean
        get() = ProvisioningPolicy.provisionedForCurrentSchema(
            prefs.getInt(KEY_PROVISIONING_SCHEMA_VERSION, 0), deviceId, mobileKey,
        )

    val monitoringEnabled: Boolean
        get() = onboardingDone && isProvisioned

    val provisioningMigrationRequired: Boolean
        get() = prefs.getBoolean(KEY_PROVISIONING_MIGRATION_REQUIRED, false)

    fun saveProvisioning(rawDeviceId: String, rawMobileKey: String): Boolean {
        val normalizedDeviceId = rawDeviceId.trim()
        val normalizedMobileKey = rawMobileKey.trim()
        if (!ProvisioningPolicy.provisioned(normalizedDeviceId, normalizedMobileKey)) return false
        return prefs.edit()
            .putString("device_id", normalizedDeviceId)
            .putString("mobile_key", normalizedMobileKey)
            .putInt(KEY_PROVISIONING_SCHEMA_VERSION, ProvisioningPolicy.CURRENT_SCHEMA_VERSION)
            .putBoolean("auth_error", false)
            .putBoolean(KEY_PROVISIONING_MIGRATION_REQUIRED, false)
            .commit()
    }

    fun completeOnboarding(): Boolean {
        if (!isProvisioned) {
            prefs.edit().putBoolean("onboarding_done", false).commit()
            return false
        }
        return prefs.edit().putBoolean("onboarding_done", true).commit()
    }

    var themeMode: String  // system | light | dark
        get() = prefs.getString("theme_mode", "system") ?: "system"
        set(v) = prefs.edit().putString("theme_mode", v).apply()

    // Set when the backend rejects the ingest key (HTTP 403). Surfaced in Home/Diagnostics
    // so the user fixes the key instead of the sync silently hammering a dead endpoint.
    var authError: Boolean
        get() = prefs.getBoolean("auth_error", false)
        set(v) = prefs.edit().putBoolean("auth_error", v).apply()

    // Phone-side allowlist of SMS senders to collect from. Stored as normalized (trim+lowercase)
    // keys; matching in SmsRepository normalizes the incoming address the same way. Empty set =
    // collect from ALL senders (back-compat with installs that predate the picker).
    var selectedSenders: Set<String>
        get() = prefs.getStringSet(KEY_SELECTED_SENDERS, emptySet())?.toSet() ?: emptySet()
        set(v) = prefs.edit().putStringSet(KEY_SELECTED_SENDERS, v).apply()

    /** Emits the current allowlist and every subsequent change. */
    fun selectedSendersFlow(): Flow<Set<String>> = callbackFlow {
        trySend(selectedSenders)
        val listener = SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
            if (key == KEY_SELECTED_SENDERS) trySend(selectedSenders)
        }
        prefs.registerOnSharedPreferenceChangeListener(listener)
        awaitClose { prefs.unregisterOnSharedPreferenceChangeListener(listener) }
    }

    private fun migrateLegacyProvisioningState() {
        val wasComplete = prefs.getBoolean("onboarding_done", false)
        val schemaVersion = prefs.getInt(KEY_PROVISIONING_SCHEMA_VERSION, 0)
        val storedDeviceId = prefs.getString("device_id", "").orEmpty()
        val storedMobileKey = prefs.getString("mobile_key", "").orEmpty()
        if (ProvisioningPolicy.requiresUpgradeProvisioning(
                wasComplete, schemaVersion, storedDeviceId, storedMobileKey,
            )) {
            prefs.edit()
                .putBoolean("onboarding_done", false)
                .putBoolean(KEY_PROVISIONING_MIGRATION_REQUIRED, true)
                .commit()
        }
    }

    companion object {
        private const val KEY_SELECTED_SENDERS = "selected_senders"
        private const val KEY_PROVISIONING_MIGRATION_REQUIRED = "provisioning_migration_required"
        private const val KEY_PROVISIONING_SCHEMA_VERSION = "provisioning_schema_version"
        const val DEFAULT_BASE_URL = "https://64.188.106.221.nip.io"
    }
}
