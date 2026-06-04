package uz.tbsparcer.sms.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.tbsparcer.sms.ui.components.StatusPill
import uz.tbsparcer.sms.ui.components.TbsChip
import uz.tbsparcer.sms.ui.theme.DisplaySerif
import uz.tbsparcer.sms.ui.theme.LocalTbs
import uz.tbsparcer.sms.ui.theme.MonoJetBrains
import uz.tbsparcer.sms.ui.theme.SansGrotesk
import uz.tbsparcer.sms.ui.vm.DiagnosticsViewModel
import uz.tbsparcer.sms.ui.vm.SettingsViewModel

private val themeOptions = listOf("system" to "Системная", "light" to "Светлая", "dark" to "Тёмная")

@Composable
fun SettingsScreen(
    vm: SettingsViewModel = hiltViewModel(),
    diagVm: DiagnosticsViewModel = hiltViewModel(),
) {
    val p = LocalTbs.current
    var theme by remember { mutableStateOf(vm.settings.themeMode) }
    var baseUrl by remember { mutableStateOf(vm.settings.baseUrl) }
    var saved by remember { mutableStateOf(false) }
    var advanced by remember { mutableStateOf(false) }
    val diag by diagVm.ui.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { diagVm.runChecks() }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text("Настройки", fontFamily = DisplaySerif, fontSize = 30.sp, color = p.ink)

        // Connection status (folds in the old Diagnostics screen).
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            StatusPill(
                online = diag.backendOk == true && diag.authError.not(),
                label = when (diag.backendOk) { true -> "сервер на связи"; false -> "сервер недоступен"; null -> "проверка…" },
            )
            TextButton(onClick = { diagVm.runChecks() }) {
                Text("Обновить", fontFamily = SansGrotesk, fontSize = 13.sp, color = p.ink)
            }
        }
        diag.latencyMs?.let {
            Text("Задержка ${it} мс · версия ${diag.version ?: "—"}",
                fontFamily = MonoJetBrains, fontSize = 11.sp, color = p.inkSecondary)
        }

        Text("ТЕМА", fontFamily = MonoJetBrains, fontSize = 11.sp, letterSpacing = 1.2.sp, color = p.inkSecondary)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            themeOptions.forEach { (key, label) ->
                TbsChip(label, theme == key) { theme = key }
            }
        }

        Button(
            onClick = { vm.save(baseUrl, vm.settings.mobileKey, theme); saved = true },
            modifier = Modifier.fillMaxWidth(),
            shape = MaterialTheme.shapes.small,
            colors = ButtonDefaults.buttonColors(containerColor = p.accent, contentColor = p.onAccent),
        ) {
            Text("Сохранить", fontFamily = SansGrotesk, fontWeight = FontWeight.Medium, fontSize = 15.sp,
                modifier = Modifier.padding(vertical = 6.dp))
        }
        if (saved) Text("Сохранено. Перезапустите приложение для смены темы.",
            fontFamily = SansGrotesk, fontSize = 12.sp, color = p.inkSecondary)

        OutlinedButton(onClick = { vm.runBackfill() }, modifier = Modifier.fillMaxWidth(),
            shape = MaterialTheme.shapes.small) {
            Text("Пересобрать историю", fontFamily = SansGrotesk, fontSize = 14.sp, color = p.ink)
        }

        // Advanced: server address only — the ingest key is baked into the build, never shown.
        TextButton(onClick = { advanced = !advanced }) {
            Text(if (advanced) "Скрыть дополнительно" else "Дополнительно",
                fontFamily = SansGrotesk, fontSize = 13.sp, color = p.inkSecondary)
        }
        if (advanced) {
            OutlinedTextField(
                baseUrl, { baseUrl = it },
                label = { Text("Адрес сервера") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedButton(onClick = { vm.clearLocal() }, modifier = Modifier.fillMaxWidth(),
                shape = MaterialTheme.shapes.small) {
                Text("Очистить локальную базу", fontFamily = SansGrotesk, fontSize = 14.sp, color = p.expense)
            }
            Text("Устройство: ${vm.settings.deviceId}",
                fontFamily = MonoJetBrains, fontSize = 10.sp, color = p.inkSecondary)
        }
    }
}
