package uz.tbsparcer.sms.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import uz.tbsparcer.sms.ui.vm.SettingsViewModel

@Composable
fun SettingsScreen(vm: SettingsViewModel = hiltViewModel()) {
    var baseUrl by remember { mutableStateOf(vm.settings.baseUrl) }
    var key by remember { mutableStateOf(vm.settings.mobileKey) }
    var theme by remember { mutableStateOf(vm.settings.themeMode) }
    var saved by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Настройки", style = MaterialTheme.typography.headlineMedium)
        OutlinedTextField(baseUrl, { baseUrl = it }, label = { Text("Backend URL") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(key, { key = it }, label = { Text("Mobile Ingest Key") }, modifier = Modifier.fillMaxWidth())
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("system","light","dark").forEach {
                FilterChip(selected = theme == it, onClick = { theme = it }, label = { Text(it) })
            }
        }
        Button(onClick = { vm.save(baseUrl, key, theme); saved = true }) { Text("Сохранить") }
        if (saved) Text("Сохранено. Перезапустите для смены темы.")
        OutlinedButton(onClick = { vm.runBackfill() }) { Text("Пересобрать inbox") }
        OutlinedButton(onClick = { vm.clearLocal() }) { Text("Очистить локальную БД") }
        Text("Device ID: ${vm.settings.deviceId}")
    }
}
