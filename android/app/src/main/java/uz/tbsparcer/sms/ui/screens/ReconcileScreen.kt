package uz.tbsparcer.sms.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.tbsparcer.sms.ui.components.SmsRow
import uz.tbsparcer.sms.ui.components.StatCard
import uz.tbsparcer.sms.ui.theme.DisplaySerif
import uz.tbsparcer.sms.ui.theme.LocalTbs
import uz.tbsparcer.sms.ui.theme.MonoJetBrains
import uz.tbsparcer.sms.ui.theme.SansGrotesk
import uz.tbsparcer.sms.ui.vm.ReconcileViewModel
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

private val rDayFmt = SimpleDateFormat("dd.MM.yyyy", Locale.US)
private const val R_DAY_MS = 24L * 60 * 60 * 1000

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ReconcileScreen(onOpenDetail: (String) -> Unit, vm: ReconcileViewModel = hiltViewModel()) {
    val p = LocalTbs.current
    var from by remember { mutableStateOf(System.currentTimeMillis() - 7 * R_DAY_MS) }
    var to by remember { mutableStateOf(System.currentTimeMillis()) }
    var picker by remember { mutableStateOf<String?>(null) }

    val started by vm.started.collectAsStateWithLifecycle()
    val counts by vm.counts.collectAsStateWithLifecycle()
    val records by vm.records.collectAsStateWithLifecycle()

    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Сверка", fontFamily = DisplaySerif, fontSize = 30.sp, color = p.ink)
        Text(
            "Перечитать SMS за период и сверить с сервером. Уже известные чеки (в т.ч. из Telegram) " +
                "пометятся дубликатами — заново не добавятся.",
            fontFamily = SansGrotesk, fontSize = 13.sp, color = p.inkSecondary,
        )
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            RDateField("С", from, Modifier.weight(1f)) { picker = "from" }
            RDateField("По", to, Modifier.weight(1f)) { picker = "to" }
        }
        Button(
            onClick = { vm.reconcile(rStartOfDay(from), rEndOfDay(to)) },
            modifier = Modifier.fillMaxWidth(),
            shape = MaterialTheme.shapes.small,
            colors = ButtonDefaults.buttonColors(containerColor = p.accent, contentColor = p.onAccent),
        ) {
            Text("Сверить", fontFamily = SansGrotesk, fontWeight = FontWeight.Medium, fontSize = 15.sp,
                modifier = Modifier.padding(vertical = 6.dp))
        }

        if (started) {
            val synced = counts["synced"] ?: 0
            val duplicate = counts["duplicate"] ?: 0
            val errors = (counts["error"] ?: 0) + (counts["failed"] ?: 0)
            val pending = counts["pending"] ?: 0
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                StatCard("Новые", synced.toString(), accent = true, modifier = Modifier.weight(1f))
                StatCard("Дубликаты", duplicate.toString(), modifier = Modifier.weight(1f))
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                StatCard("Ошибки", errors.toString(), modifier = Modifier.weight(1f))
                StatCard("В очереди", pending.toString(), modifier = Modifier.weight(1f))
            }
            Text("SMS ЗА ПЕРИОД · ${records.size}", fontFamily = MonoJetBrains, fontSize = 11.sp,
                letterSpacing = 1.2.sp, color = p.inkSecondary)
            LazyColumn(Modifier.fillMaxSize()) {
                items(records, key = { it.deviceSmsId }) { SmsRow(it) { onOpenDetail(it.deviceSmsId) } }
            }
        }
    }

    if (picker != null) {
        val target = picker!!
        val state = rememberDatePickerState(
            initialSelectedDateMillis = if (target == "from") from else to,
        )
        DatePickerDialog(
            onDismissRequest = { picker = null },
            confirmButton = {
                TextButton(onClick = {
                    state.selectedDateMillis?.let { if (target == "from") from = it else to = it }
                    picker = null
                }) { Text("ОК") }
            },
            dismissButton = { TextButton(onClick = { picker = null }) { Text("Отмена") } },
        ) { DatePicker(state = state) }
    }
}

@Composable
private fun RDateField(label: String, millis: Long, modifier: Modifier, onClick: () -> Unit) {
    val p = LocalTbs.current
    OutlinedButton(onClick = onClick, modifier = modifier, shape = MaterialTheme.shapes.small) {
        Column(horizontalAlignment = androidx.compose.ui.Alignment.Start) {
            Text(label, fontFamily = MonoJetBrains, fontSize = 10.sp, color = p.inkSecondary)
            Text(rDayFmt.format(Date(millis)), fontFamily = SansGrotesk, fontSize = 14.sp, color = p.ink)
        }
    }
}

private fun rStartOfDay(millis: Long): Long = Calendar.getInstance().apply {
    timeInMillis = millis
    set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
}.timeInMillis

private fun rEndOfDay(millis: Long): Long = Calendar.getInstance().apply {
    timeInMillis = millis
    set(Calendar.HOUR_OF_DAY, 23); set(Calendar.MINUTE, 59); set(Calendar.SECOND, 59); set(Calendar.MILLISECOND, 999)
}.timeInMillis
