package uz.tbsparcer.sms.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import uz.tbsparcer.sms.ui.vm.SettingsViewModel
import java.util.Calendar

@Composable
fun OnboardingScreen(vm: SettingsViewModel, onDone: () -> Unit) {
    var baseUrl by remember { mutableStateOf(vm.settings.baseUrl) }
    var key by remember { mutableStateOf(vm.settings.mobileKey) }
    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("Настройка", style = MaterialTheme.typography.headlineMedium)
        OutlinedTextField(baseUrl, { baseUrl = it }, label = { Text("Backend URL") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(key, { key = it }, label = { Text("Mobile Ingest Key") }, modifier = Modifier.fillMaxWidth())
        Text("SMS будут собраны за последние 30 дней и далее в реальном времени.")
        Button(onClick = {
            vm.save(baseUrl, key, vm.settings.themeMode)
            val cal = Calendar.getInstance().apply { add(Calendar.DAY_OF_YEAR, -30) }
            vm.setBackfillDate(cal.timeInMillis)
            vm.settings.onboardingDone = true
            vm.runBackfill()
            onDone()
        }) { Text("Начать") }
    }
}
