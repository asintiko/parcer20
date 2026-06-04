package uz.tbsparcer.sms

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.Dashboard
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.lifecycle.lifecycleScope
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.*
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import uz.tbsparcer.sms.data.local.SettingsStore
import uz.tbsparcer.sms.ui.screens.*
import uz.tbsparcer.sms.ui.theme.TbsTheme
import uz.tbsparcer.sms.ui.vm.SettingsViewModel
import uz.tbsparcer.sms.work.WorkScheduler
import javax.inject.Inject

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    @Inject lateinit var settings: SettingsStore

    // EncryptedSharedPreferences decryption is blocking; read it off the main thread and let
    // the UI react. Null until loaded → fall back to the system theme without blocking.
    private val themeMode = MutableStateFlow<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WorkScheduler.schedulePeriodic(applicationContext)
        lifecycleScope.launch {
            themeMode.value = withContext(Dispatchers.IO) { settings.themeMode }
        }
        setContent {
            val mode by themeMode.collectAsState()
            val dark = when (mode) {
                "dark" -> true; "light" -> false
                else -> isSystemInDarkTheme()
            }
            TbsTheme(darkTheme = dark) { AppRoot(settings) }
        }
    }
}

@Composable
private fun AppRoot(settings: SettingsStore) {
    val nav = rememberNavController()
    fun navigateTab(route: String) {
        nav.navigate(route) {
            popUpTo(nav.graph.findStartDestination().id) { saveState = true }
            launchSingleTop = true
            restoreState = true
        }
    }
    val permLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()) {}
    LaunchedEffect(Unit) {
        val perms = mutableListOf(Manifest.permission.READ_SMS, Manifest.permission.RECEIVE_SMS)
        if (Build.VERSION.SDK_INT >= 33) perms += Manifest.permission.POST_NOTIFICATIONS
        permLauncher.launch(perms.toTypedArray())
    }
    val start = if (settings.onboardingDone) "home" else "onboarding"
    Scaffold(bottomBar = {
        if (settings.onboardingDone) NavigationBar {
            val entry by nav.currentBackStackEntryAsState()
            val route = entry?.destination?.route
            NavigationBarItem(route == "home", { navigateTab("home") },
                icon = { Icon(Icons.Filled.Dashboard, null) }, label = { Text("Сводка") })
            NavigationBarItem(route == "feed", { navigateTab("feed") },
                icon = { Icon(Icons.AutoMirrored.Filled.List, null) }, label = { Text("Лента") })
            NavigationBarItem(route == "reconcile", { navigateTab("reconcile") },
                icon = { Icon(Icons.Filled.Sync, null) }, label = { Text("Сверка") })
            NavigationBarItem(route == "stats", { navigateTab("stats") },
                icon = { Icon(Icons.Filled.BarChart, null) }, label = { Text("Статистика") })
            NavigationBarItem(route == "settings", { navigateTab("settings") },
                icon = { Icon(Icons.Filled.Settings, null) }, label = { Text("Настройки") })
        }
    }) { pad ->
        NavHost(nav, startDestination = start, modifier = Modifier.padding(pad)) {
            composable("onboarding") {
                val vm: SettingsViewModel = androidx.hilt.navigation.compose.hiltViewModel()
                OnboardingScreen(vm) { nav.navigate("home") { popUpTo("onboarding") { inclusive = true } } }
            }
            composable("home") { DashboardScreen() }
            composable("feed") { FeedScreen(onOpenDetail = { nav.navigate("detail/$it") }) }
            composable("reconcile") { ReconcileScreen(onOpenDetail = { nav.navigate("detail/$it") }) }
            composable("stats") { StatsScreen() }
            composable("settings") { SettingsScreen() }
            composable("detail/{id}") { SmsDetailScreen(it.arguments?.getString("id") ?: "") }
        }
    }
}
