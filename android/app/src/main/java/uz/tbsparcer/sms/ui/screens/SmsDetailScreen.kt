package uz.tbsparcer.sms.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.hilt.navigation.compose.hiltViewModel
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import uz.tbsparcer.sms.data.local.SmsRecord
import uz.tbsparcer.sms.data.repo.SmsRepository
import uz.tbsparcer.sms.ui.theme.MonoJetBrains
import javax.inject.Inject

@HiltViewModel
class SmsDetailViewModel @Inject constructor(private val repo: SmsRepository) : ViewModel() {
    val record = MutableStateFlow<SmsRecord?>(null)
    fun load(id: String) { viewModelScope.launch { record.value = repo.byId(id) } }
}

@Composable
fun SmsDetailScreen(deviceSmsId: String, vm: SmsDetailViewModel = hiltViewModel()) {
    LaunchedEffect(deviceSmsId) { vm.load(deviceSmsId) }
    val rec by vm.record.collectAsStateWithLifecycle()
    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Детали SMS", style = MaterialTheme.typography.headlineMedium)
        rec?.let { r ->
            Text("Статус: ${r.syncStatus}")
            r.backendTransactionId?.let { Text("Транзакция: #$it") }
            r.fingerprint?.let { Text("Fingerprint: $it", fontFamily = MonoJetBrains, fontSize = 11.sp) }
            Text("Отправитель: ${r.sender}")
            Spacer(Modifier.height(8.dp))
            Text(r.body, fontFamily = MonoJetBrains, fontSize = 12.sp)
            r.errorMessage?.let { Text("Ошибка: $it") }
        } ?: Text("Загрузка…")
    }
}
