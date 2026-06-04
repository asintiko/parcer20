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
import uz.tbsparcer.sms.ui.components.StatCard
import uz.tbsparcer.sms.ui.components.StatusPill
import uz.tbsparcer.sms.ui.theme.DisplaySerif
import uz.tbsparcer.sms.ui.theme.LocalTbs
import uz.tbsparcer.sms.ui.theme.MonoJetBrains
import uz.tbsparcer.sms.ui.theme.SansGrotesk
import uz.tbsparcer.sms.ui.vm.DashboardViewModel
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private val syncFmt = SimpleDateFormat("dd.MM HH:mm", Locale.US)

@Composable
fun DashboardScreen(vm: DashboardViewModel = hiltViewModel()) {
    val p = LocalTbs.current
    val ui by vm.ui.collectAsStateWithLifecycle()
    val money by vm.money.collectAsStateWithLifecycle()

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Сводка", fontFamily = DisplaySerif, fontSize = 30.sp, color = p.ink)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            StatusPill(online = ui.online, label = if (ui.online) "онлайн" else "оффлайн")
            Text(
                "обновлено " + (ui.lastSyncedAt?.let { syncFmt.format(Date(it)) } ?: "—"),
                fontFamily = MonoJetBrains, fontSize = 10.sp, letterSpacing = 1.sp, color = p.inkSecondary,
            )
        }

        if (ui.authError) {
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer)) {
                Text(
                    "Сервер отклоняет запросы (ошибка авторизации). Сбор приостановлен — обратитесь к администратору.",
                    color = MaterialTheme.colorScheme.onErrorContainer,
                    fontFamily = SansGrotesk, fontSize = 13.sp,
                    modifier = Modifier.padding(12.dp),
                )
            }
        }

        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            StatCard("Всего SMS", ui.total.toString(), modifier = Modifier.weight(1f))
            StatCard("Обработано", ui.synced.toString(), accent = true, modifier = Modifier.weight(1f))
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            StatCard("Дубликаты", ui.duplicate.toString(), modifier = Modifier.weight(1f))
            StatCard("Пропущено", ui.skipped.toString(), modifier = Modifier.weight(1f))
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            StatCard("Ошибки", ui.errors.toString(), modifier = Modifier.weight(1f))
            StatCard("В очереди", ui.pending.toString(), modifier = Modifier.weight(1f))
        }
        StatCard("Точность парсинга", "${ui.accuracyPct}%", modifier = Modifier.fillMaxWidth())

        Spacer(Modifier.height(4.dp))
        Text("ДЕНЬГИ · ВСЕ ИСТОЧНИКИ", fontFamily = MonoJetBrains, fontSize = 11.sp,
            letterSpacing = 1.2.sp, color = p.inkSecondary)
        val cur = money.currency
        StatCard("Сумма трат", money.totalVolume?.let { "$it $cur" } ?: "—", modifier = Modifier.fillMaxWidth())
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            StatCard("Расход", money.debitVolume ?: "—", modifier = Modifier.weight(1f))
            StatCard("Доход", money.creditVolume ?: "—", accent = true, modifier = Modifier.weight(1f))
        }

        Spacer(Modifier.height(4.dp))
        Button(
            onClick = { vm.syncNow() },
            modifier = Modifier.fillMaxWidth(),
            shape = MaterialTheme.shapes.small,
            colors = ButtonDefaults.buttonColors(containerColor = p.accent, contentColor = p.onAccent),
        ) {
            Text("Синхронизировать", fontFamily = SansGrotesk, fontWeight = FontWeight.Medium,
                fontSize = 15.sp, modifier = Modifier.padding(vertical = 6.dp))
        }
    }
}
