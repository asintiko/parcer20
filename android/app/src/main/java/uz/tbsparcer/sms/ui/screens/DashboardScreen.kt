package uz.tbsparcer.sms.ui.screens

import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.vector.ImageVector
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
fun DashboardScreen(
    onOpenFeed: () -> Unit = {},
    onOpenStats: () -> Unit = {},
    onOpenReconcile: () -> Unit = {},
    vm: DashboardViewModel = hiltViewModel(),
) {
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
        if (money.error != null && money.totalVolume == null) {
            Text("Не удалось получить суммы с сервера.", fontFamily = SansGrotesk, fontSize = 12.sp, color = p.inkSecondary)
        }

        Spacer(Modifier.height(4.dp))
        Text("РАЗДЕЛЫ", fontFamily = MonoJetBrains, fontSize = 11.sp,
            letterSpacing = 1.2.sp, color = p.inkSecondary)
        NavRow("Лента", "Поток входящих SMS", Icons.AutoMirrored.Filled.List, onOpenFeed)
        NavRow("Статистика", "Суммы и разрезы с сервера", Icons.Filled.BarChart, onOpenStats)
        NavRow("Сверка", "Сопоставление локальных и серверных записей", Icons.Filled.Sync, onOpenReconcile)

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

@Composable
private fun NavRow(title: String, subtitle: String, icon: ImageVector, onClick: () -> Unit) {
    val p = LocalTbs.current
    Row(
        Modifier
            .fillMaxWidth()
            .border(1.dp, p.border, MaterialTheme.shapes.medium)
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Icon(icon, null, tint = p.ink)
        Column(Modifier.weight(1f)) {
            Text(title, fontFamily = SansGrotesk, fontWeight = FontWeight.Medium, fontSize = 15.sp, color = p.ink)
            Text(subtitle, fontFamily = SansGrotesk, fontSize = 12.sp, color = p.inkSecondary)
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = p.inkSecondary)
    }
}
