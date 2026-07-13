package uz.tbsparcer.sms

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.tbsparcer.sms.data.repo.UpdateTrustPolicy

class UpdateTrustPolicyTest {
    @Test
    fun `accepts only the canonical release URL`() {
        assertTrue(
            UpdateTrustPolicy.isTrustedDownloadUrl(
                "https://github.com/asintiko/parcer20-updates/releases/download/android-v1.2.3/app-release.apk",
                "1.2.3",
            ),
        )
        assertFalse(
            UpdateTrustPolicy.isTrustedDownloadUrl(
                "https://evil.example/app-release.apk",
                "1.2.3",
            ),
        )
        assertFalse(
            UpdateTrustPolicy.isTrustedDownloadUrl(
                "https://github.com/asintiko/parcer20-updates/releases/download/android-v1.2.3/app-release.apk?raw=1",
                "1.2.3",
            ),
        )
    }

    @Test
    fun `accepts a proven forward signer rotation`() {
        assertTrue(
            UpdateTrustPolicy.isTrustedSignerUpgrade(
                installedCurrent = setOf("old"),
                installedHasMultipleSigners = false,
                candidateCurrent = setOf("new"),
                candidateHistory = setOf("old", "new"),
                candidateHasMultipleSigners = false,
            ),
        )
    }

    @Test
    fun `rejects unrelated or changed multi signer identities`() {
        assertFalse(
            UpdateTrustPolicy.isTrustedSignerUpgrade(
                installedCurrent = setOf("old"),
                installedHasMultipleSigners = false,
                candidateCurrent = setOf("attacker"),
                candidateHistory = setOf("attacker"),
                candidateHasMultipleSigners = false,
            ),
        )
        assertFalse(
            UpdateTrustPolicy.isTrustedSignerUpgrade(
                installedCurrent = setOf("a", "b"),
                installedHasMultipleSigners = true,
                candidateCurrent = setOf("a", "c"),
                candidateHistory = setOf("a", "c"),
                candidateHasMultipleSigners = true,
            ),
        )
    }
}
