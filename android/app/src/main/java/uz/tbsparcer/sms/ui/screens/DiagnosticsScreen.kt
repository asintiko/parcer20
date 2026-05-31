package uz.tbsparcer.sms.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.tbsparcer.sms.ui.vm.DiagnosticsViewModel

@Composable
fun DiagnosticsScreen(vm: DiagnosticsViewModel = hiltViewModel()) {
    val ui by vm.ui.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { vm.runChecks() }
    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Диагностика", style = MaterialTheme.typography.headlineMedium)
        if (ui.checking) CircularProgressIndicator()
        Text("Backend: " + when (ui.backendOk) { true -> "OK ${ui.latencyMs ?: 0}ms"; false -> "недоступен"; null -> "—" })
        Text("Версия: ${ui.version ?: "—"}   БД: ${ui.dbStatus ?: "—"}")
        Text("Mobile key: " + when (ui.keyValid) { true -> "валиден"; false -> "неверный"; null -> "—" })
        ui.message?.let { Text(it) }
        Button(onClick = { vm.runChecks() }) { Text("Тест связи") }
    }
}
