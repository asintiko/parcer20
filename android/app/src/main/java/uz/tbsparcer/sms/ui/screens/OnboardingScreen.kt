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
import uz.tbsparcer.sms.ui.components.TbsChip
import uz.tbsparcer.sms.ui.theme.DisplaySerif
import uz.tbsparcer.sms.ui.theme.LocalTbs
import uz.tbsparcer.sms.ui.theme.MonoJetBrains
import uz.tbsparcer.sms.ui.theme.SansGrotesk
import uz.tbsparcer.sms.ui.vm.SettingsViewModel
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

private val dayFmt = SimpleDateFormat("dd.MM.yyyy", Locale.US)
private const val DAY_MS = 24L * 60 * 60 * 1000

private fun daysAgo(d: Int): Long = System.currentTimeMillis() - d.toLong() * DAY_MS

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun OnboardingScreen(vm: SettingsViewModel, onDone: () -> Unit) {
    val p = LocalTbs.current
    // preset: "7" | "30" | "90" | "all" | "custom"
    var preset by remember { mutableStateOf("30") }
    var customFrom by remember { mutableStateOf<Long?>(null) }
    var customTo by remember { mutableStateOf<Long?>(null) }
    var picker by remember { mutableStateOf<String?>(null) } // "from" | "to" | null

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        Spacer(Modifier.height(24.dp))
        Text("TBSparcer", fontFamily = DisplaySerif, fontSize = 40.sp, color = p.ink)
        Text(
            "Резервный сбор чеков по SMS. Выберите, за какой период подтянуть и сверить чеки с сервером.",
            fontFamily = SansGrotesk, fontSize = 14.sp, color = p.inkSecondary,
        )

        Text("ПЕРИОД", fontFamily = MonoJetBrains, fontSize = 11.sp, letterSpacing = 1.2.sp, color = p.inkSecondary)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            TbsChip("7 дней", preset == "7") { preset = "7" }
            TbsChip("30 дней", preset == "30") { preset = "30" }
            TbsChip("90 дней", preset == "90") { preset = "90" }
            TbsChip("Всё время", preset == "all") { preset = "all" }
            TbsChip("Свой период", preset == "custom") { preset = "custom" }
        }

        if (preset == "custom") {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                DateField("С", customFrom) { picker = "from" }
                DateField("По", customTo) { picker = "to" }
                Text(
                    "Если выбрать обе даты — будет сверка строго за этот период.",
                    fontFamily = SansGrotesk, fontSize = 12.sp, color = p.inkSecondary,
                )
            }
        }

        Spacer(Modifier.weight(1f))
        Button(
            onClick = {
                val custom = preset == "custom" && customFrom != null
                val from = when {
                    custom -> startOfDay(customFrom!!)
                    preset == "7" -> daysAgo(7)
                    preset == "90" -> daysAgo(90)
                    preset == "all" -> 0L
                    else -> daysAgo(30)
                }
                vm.setBackfillDate(from)
                vm.settings.onboardingDone = true
                val to = customTo?.let { endOfDay(it) }
                if (custom && to != null && to < System.currentTimeMillis()) {
                    vm.runReconcile(from, to)
                } else {
                    vm.runBackfill()
                }
                onDone()
            },
            modifier = Modifier.fillMaxWidth(),
            shape = MaterialTheme.shapes.small,
            colors = ButtonDefaults.buttonColors(containerColor = p.accent, contentColor = p.onAccent),
            enabled = preset != "custom" || customFrom != null,
        ) {
            Text("Начать", fontFamily = SansGrotesk, fontWeight = FontWeight.Medium, fontSize = 15.sp,
                modifier = Modifier.padding(vertical = 6.dp))
        }
    }

    if (picker != null) {
        val target = picker!!
        val state = rememberDatePickerState(
            initialSelectedDateMillis = (if (target == "from") customFrom else customTo) ?: System.currentTimeMillis(),
        )
        DatePickerDialog(
            onDismissRequest = { picker = null },
            confirmButton = {
                TextButton(onClick = {
                    state.selectedDateMillis?.let { if (target == "from") customFrom = it else customTo = it }
                    picker = null
                }) { Text("ОК") }
            },
            dismissButton = { TextButton(onClick = { picker = null }) { Text("Отмена") } },
        ) { DatePicker(state = state) }
    }
}

@Composable
private fun DateField(label: String, millis: Long?, onClick: () -> Unit) {
    val p = LocalTbs.current
    OutlinedButton(onClick = onClick, modifier = Modifier.fillMaxWidth(), shape = MaterialTheme.shapes.small) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(label, fontFamily = MonoJetBrains, fontSize = 12.sp, color = p.inkSecondary)
            Text(millis?.let { dayFmt.format(Date(it)) } ?: "выбрать",
                fontFamily = SansGrotesk, fontSize = 14.sp, color = p.ink)
        }
    }
}

private fun startOfDay(millis: Long): Long = Calendar.getInstance().apply {
    timeInMillis = millis
    set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
}.timeInMillis

private fun endOfDay(millis: Long): Long = Calendar.getInstance().apply {
    timeInMillis = millis
    set(Calendar.HOUR_OF_DAY, 23); set(Calendar.MINUTE, 59); set(Calendar.SECOND, 59); set(Calendar.MILLISECOND, 999)
}.timeInMillis
