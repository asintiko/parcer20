package uz.tbsparcer.sms.data.repo

import uz.tbsparcer.sms.data.remote.AppUpdateManifest
import java.net.URI

internal object UpdateTrustPolicy {
    const val TRUSTED_PACKAGE_NAME = "uz.tbsparcer.sms"
    private const val RELEASE_HOST = "github.com"
    private val digestPattern = Regex("^[0-9a-fA-F]{64}$")
    private val versionPattern = Regex("^[0-9]+(?:\\.[0-9]+){1,3}$")

    fun validateManifest(manifest: AppUpdateManifest) {
        require(manifest.versionCode > 0) { "Некорректный номер версии" }
        require(versionPattern.matches(manifest.versionName)) { "Некорректное имя версии" }
        require(digestPattern.matches(manifest.sha256)) { "Обязательная SHA-256 отсутствует или некорректна" }
        require(isTrustedDownloadUrl(manifest.url, manifest.versionName)) { "URL обновления не разрешён" }
    }

    fun isTrustedDownloadUrl(rawUrl: String, versionName: String): Boolean = try {
        val uri = URI(rawUrl)
        val expectedPath =
            "/asintiko/parcer20-updates/releases/download/android-v$versionName/app-release.apk"
        uri.scheme == "https" &&
            uri.host?.lowercase() == RELEASE_HOST &&
            uri.port == -1 &&
            uri.userInfo == null &&
            uri.rawQuery == null &&
            uri.rawFragment == null &&
            uri.rawPath == expectedPath
    } catch (_: Exception) {
        false
    }

    fun isTrustedSignerUpgrade(
        installedCurrent: Set<String>,
        installedHasMultipleSigners: Boolean,
        candidateCurrent: Set<String>,
        candidateHistory: Set<String>,
        candidateHasMultipleSigners: Boolean,
    ): Boolean {
        if (installedCurrent.isEmpty() || candidateCurrent.isEmpty()) return false
        if (installedHasMultipleSigners || candidateHasMultipleSigners) {
            return installedHasMultipleSigners &&
                candidateHasMultipleSigners &&
                installedCurrent == candidateCurrent
        }
        return candidateCurrent.size == 1 && installedCurrent.all(candidateHistory::contains)
    }
}
