package uz.tbsparcer.sms

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.tbsparcer.sms.data.local.ProvisioningPolicy

class ProvisioningPolicyTest {
    @Test
    fun monitoringRequiresCompletedOnboardingAndBothCanonicalCredentials() {
        val key = "k".repeat(32)

        val schema = ProvisioningPolicy.CURRENT_SCHEMA_VERSION
        assertFalse(ProvisioningPolicy.monitoringEnabled(true, schema, "", key))
        assertFalse(ProvisioningPolicy.monitoringEnabled(true, schema, "android-primary", ""))
        assertFalse(ProvisioningPolicy.monitoringEnabled(false, schema, "android-primary", key))
        assertFalse(ProvisioningPolicy.monitoringEnabled(true, 0, "android-primary", key))
        assertTrue(ProvisioningPolicy.monitoringEnabled(true, schema, "android-primary", key))
    }

    @Test
    fun credentialsMatchBackendCanonicalRules() {
        assertTrue(ProvisioningPolicy.provisioned("android-primary", "x".repeat(32)))
        assertFalse(ProvisioningPolicy.provisioned(" android-primary", "x".repeat(32)))
        assertFalse(ProvisioningPolicy.provisioned("android primary", "x".repeat(32)))
        assertFalse(ProvisioningPolicy.provisioned("android-primary", "x".repeat(31)))
        assertFalse(ProvisioningPolicy.provisioned("android-primary", " ${"x".repeat(32)}"))
    }

    @Test
    fun upgradeResetsLegacyCompletedOnboardingWhenCredentialsAreMissing() {
        assertTrue(ProvisioningPolicy.requiresUpgradeProvisioning(true, 0, "", ""))
        assertTrue(ProvisioningPolicy.requiresUpgradeProvisioning(
            true, 0, "android-primary", "legacy-short-key",
        ))
    }

    @Test
    fun upgradeRequiresExplicitSaveEvenWhenLegacyCredentialsLookValid() {
        assertTrue(ProvisioningPolicy.requiresUpgradeProvisioning(
            true, 0, "android-primary", "z".repeat(32),
        ))
    }

    @Test
    fun currentProvisioningPreservesCompletedOnboarding() {
        assertFalse(ProvisioningPolicy.requiresUpgradeProvisioning(
            true, ProvisioningPolicy.CURRENT_SCHEMA_VERSION, "android-primary", "z".repeat(32),
        ))
    }

    @Test
    fun onboardingCannotCompleteBeforeProvisioning() {
        val schema = ProvisioningPolicy.CURRENT_SCHEMA_VERSION
        assertFalse(ProvisioningPolicy.monitoringEnabled(true, schema, "", ""))
        assertFalse(ProvisioningPolicy.monitoringEnabled(false, schema, "android-primary", "z".repeat(32)))
    }
}
