package uz.tbsparcer.sms.data.repo

import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.content.pm.Signature
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import com.squareup.moshi.Moshi
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import uz.tbsparcer.sms.BuildConfig
import uz.tbsparcer.sms.data.remote.AppUpdateManifest
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

sealed interface UpdateStatus {
    data class UpToDate(val current: String) : UpdateStatus
    data class Available(val manifest: AppUpdateManifest) : UpdateStatus
    data class Error(val message: String) : UpdateStatus
}

@Singleton
class UpdateRepository @Inject constructor(
    @ApplicationContext private val ctx: Context,
) {
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .build()
    private val moshi = Moshi.Builder().build()

    suspend fun check(): UpdateStatus = withContext(Dispatchers.IO) {
        try {
            val req = Request.Builder().url(MANIFEST_URL).build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) return@withContext UpdateStatus.Error("HTTP ${resp.code}")
                val body = resp.body?.string() ?: return@withContext UpdateStatus.Error("Пустой ответ")
                val manifest = moshi.adapter(AppUpdateManifest::class.java).fromJson(body)
                    ?: return@withContext UpdateStatus.Error("Некорректный манифест")
                UpdateTrustPolicy.validateManifest(manifest)
                if (manifest.versionCode > BuildConfig.VERSION_CODE) UpdateStatus.Available(manifest)
                else UpdateStatus.UpToDate(BuildConfig.VERSION_NAME)
            }
        } catch (e: Exception) {
            UpdateStatus.Error(e.message?.take(160) ?: "Ошибка сети")
        }
    }

    suspend fun download(manifest: AppUpdateManifest, onProgress: (Int) -> Unit): File =
        withContext(Dispatchers.IO) {
            UpdateTrustPolicy.validateManifest(manifest)
            val dir = File(ctx.cacheDir, "updates").apply { mkdirs() }
            val out = File(dir, "tbsparcer-${manifest.versionCode}.apk")
            if (out.exists() && !out.delete()) throw IllegalStateException("Не удалось очистить старое обновление")
            val req = Request.Builder().url(manifest.url).build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) throw IllegalStateException("Загрузка не удалась: HTTP ${resp.code}")
                val body = resp.body ?: throw IllegalStateException("Пустой ответ при загрузке")
                val total = body.contentLength()
                body.byteStream().use { input ->
                    out.outputStream().use { output ->
                        val buf = ByteArray(64 * 1024)
                        var read: Int
                        var done = 0L
                        var lastPct = -1
                        while (input.read(buf).also { read = it } != -1) {
                            output.write(buf, 0, read)
                            done += read
                            if (total > 0) {
                                val pct = (done * 100 / total).toInt()
                                if (pct != lastPct) { lastPct = pct; onProgress(pct) }
                            }
                        }
                    }
                }
            }
            try {
                verifyUpdateArtifact(out, manifest)
            } catch (error: Exception) {
                out.delete()
                throw error
            }
            out
        }

    /** Returns true if install was launched; false if unknown-sources permission must be granted first. */
    suspend fun install(file: File, manifest: AppUpdateManifest): Boolean {
        withContext(Dispatchers.IO) { verifyUpdateArtifact(file, manifest) }
        return withContext(Dispatchers.Main) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
            !ctx.packageManager.canRequestPackageInstalls()
        ) {
            val intent = Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES)
                .setData(Uri.parse("package:${ctx.packageName}"))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            ctx.startActivity(intent)
            return@withContext false
        }
        val uri = FileProvider.getUriForFile(ctx, "${ctx.packageName}.fileprovider", file)
        val intent = Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, "application/vnd.android.package-archive")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        ctx.startActivity(intent)
        true
        }
    }

    private fun verifyUpdateArtifact(file: File, manifest: AppUpdateManifest) {
        UpdateTrustPolicy.validateManifest(manifest)
        if (!file.isFile || !sha256Hex(file).equals(manifest.sha256, ignoreCase = true)) {
            throw IllegalStateException("Контрольная сумма не совпала")
        }

        val candidate = packageArchiveInfo(file)
            ?: throw IllegalStateException("APK не содержит проверяемую подпись")
        if (candidate.packageName != UpdateTrustPolicy.TRUSTED_PACKAGE_NAME) {
            throw IllegalStateException("APK имеет неверный идентификатор приложения")
        }
        val installed = installedPackageInfo()
        val installedIdentity = signingIdentity(installed)
        val candidateIdentity = signingIdentity(candidate)
        if (!UpdateTrustPolicy.isTrustedSignerUpgrade(
                installedIdentity.current,
                installedIdentity.multiple,
                candidateIdentity.current,
                candidateIdentity.history,
                candidateIdentity.multiple,
            )
        ) {
            throw IllegalStateException("Подпись APK не принадлежит доверенной цепочке")
        }
    }

    @Suppress("DEPRECATION")
    private fun packageArchiveInfo(file: File): PackageInfo? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            ctx.packageManager.getPackageArchiveInfo(
                file.absolutePath,
                PackageManager.PackageInfoFlags.of(PackageManager.GET_SIGNING_CERTIFICATES.toLong()),
            )
        } else {
            val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                PackageManager.GET_SIGNING_CERTIFICATES
            } else {
                PackageManager.GET_SIGNATURES
            }
            ctx.packageManager.getPackageArchiveInfo(file.absolutePath, flags)
        }

    @Suppress("DEPRECATION")
    private fun installedPackageInfo(): PackageInfo =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            ctx.packageManager.getPackageInfo(
                UpdateTrustPolicy.TRUSTED_PACKAGE_NAME,
                PackageManager.PackageInfoFlags.of(PackageManager.GET_SIGNING_CERTIFICATES.toLong()),
            )
        } else {
            val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                PackageManager.GET_SIGNING_CERTIFICATES
            } else {
                PackageManager.GET_SIGNATURES
            }
            ctx.packageManager.getPackageInfo(UpdateTrustPolicy.TRUSTED_PACKAGE_NAME, flags)
        }

    private data class SigningIdentity(
        val current: Set<String>,
        val history: Set<String>,
        val multiple: Boolean,
    )

    @Suppress("DEPRECATION")
    private fun signingIdentity(info: PackageInfo): SigningIdentity {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            val signingInfo = info.signingInfo
                ?: throw IllegalStateException("APK не содержит signingInfo")
            val current = signingInfo.apkContentsSigners.orEmpty().mapTo(linkedSetOf(), ::signatureSha256)
            val multiple = signingInfo.hasMultipleSigners()
            val history = if (multiple) current else {
                signingInfo.signingCertificateHistory.orEmpty().mapTo(linkedSetOf(), ::signatureSha256)
            }
            return SigningIdentity(current, history, multiple)
        }
        val current = info.signatures.orEmpty().mapTo(linkedSetOf(), ::signatureSha256)
        return SigningIdentity(current, current, current.size > 1)
    }

    private fun signatureSha256(signature: Signature): String =
        MessageDigest.getInstance("SHA-256")
            .digest(signature.toByteArray())
            .joinToString("") { "%02x".format(it) }

    private fun sha256Hex(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buf = ByteArray(64 * 1024)
            var read: Int
            while (input.read(buf).also { read = it } != -1) digest.update(buf, 0, read)
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private companion object {
        const val MANIFEST_URL =
            "https://raw.githubusercontent.com/asintiko/parcer20-updates/main/android-latest.json"
    }
}
