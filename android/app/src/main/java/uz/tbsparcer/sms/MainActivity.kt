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
import androidx.compose.material.icons.filled.Bolt
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.*
import dagger.hilt.android.AndroidEntryPoint
import uz.tbsparcer.sms.data.local.SettingsStore
import uz.tbsparcer.sms.ui.screens.*
import uz.tbsparcer.sms.ui.theme.TbsTheme
import uz.tbsparcer.sms.ui.vm.SettingsViewModel
import uz.tbsparcer.sms.work.WorkScheduler
import javax.inject.Inject

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    @Inject lateinit var settings: SettingsStore

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WorkScheduler.schedulePeriodic(applicationContext)
        setContent {
            val dark = when (settings.themeMode) {
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
                icon = { Icon(Icons.AutoMirrored.Filled.List, null) }, label = { Text("Лента") })
            NavigationBarItem(route == "stats", { navigateTab("stats") },
                icon = { Icon(Icons.Filled.BarChart, null) }, label = { Text("Статистика") })
            NavigationBarItem(route == "diag", { navigateTab("diag") },
                icon = { Icon(Icons.Filled.Bolt, null) }, label = { Text("Статус") })
            NavigationBarItem(route == "settings", { navigateTab("settings") },
                icon = { Icon(Icons.Filled.Settings, null) }, label = { Text("Настройки") })
        }
    }) { pad ->
        NavHost(nav, startDestination = start, modifier = Modifier.padding(pad)) {
            composable("onboarding") {
                val vm: SettingsViewModel = androidx.hilt.navigation.compose.hiltViewModel()
                OnboardingScreen(vm) { nav.navigate("home") { popUpTo("onboarding") { inclusive = true } } }
            }
            composable("home") { HomeScreen(onOpenDetail = { nav.navigate("detail/$it") }) }
            composable("stats") { StatsScreen() }
            composable("diag") { DiagnosticsScreen() }
            composable("settings") { SettingsScreen() }
            composable("detail/{id}") { SmsDetailScreen(it.arguments?.getString("id") ?: "") }
        }
    }
}
