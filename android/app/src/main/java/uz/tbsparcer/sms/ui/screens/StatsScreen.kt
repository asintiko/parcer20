package uz.tbsparcer.sms.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.tbsparcer.sms.ui.components.StatCard
import uz.tbsparcer.sms.ui.components.TbsChip
import uz.tbsparcer.sms.ui.vm.StatsViewModel

@Composable
fun StatsScreen(vm: StatsViewModel = hiltViewModel()) {
    val ui by vm.ui.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { vm.load() }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Статистика", style = MaterialTheme.typography.headlineMedium)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("all" to "Все", "sms" to "SMS", "telegram" to "Telegram").forEach { (k, lbl) ->
                TbsChip(lbl, ui.source == k) { vm.setSource(k) }
            }
        }
        if (ui.source == "telegram" && ui.sources.isNotEmpty()) {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                ui.sources.take(8).forEach { src ->
                    TbsChip(src.title ?: src.chatId.toString(), ui.chatId == src.chatId) { vm.setChat(src.chatId) }
                }
            }
        }
        OutlinedTextField(ui.card, { vm.setCard(it.filter { c -> c.isDigit() }.take(4)) },
            label = { Text("Карта (4 цифры)") }, modifier = Modifier.fillMaxWidth())
        if (ui.loading) CircularProgressIndicator()
        ui.error?.let { Text("Ошибка: $it") }
        val s = ui.stats
        if (s != null) {
            StatCard("Общая сумма трат", "${s.totalVolume} ${s.currency}", modifier = Modifier.fillMaxWidth())
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                StatCard("Прошло (всего)", s.transactionCount.toString(), modifier = Modifier.weight(1f))
                StatCard("Не прошло (этот телефон)", ui.localFailed.toString(), modifier = Modifier.weight(1f))
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                StatCard("Расход", s.debitVolume, modifier = Modifier.weight(1f))
                StatCard("Доход", s.creditVolume, accent = true, modifier = Modifier.weight(1f))
            }
            s.byCard.forEach { c ->
                Text("•••• ${c.cardLast4}    ${c.volume}    (${c.count})")
            }
        }
    }
}
