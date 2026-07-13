package uz.tbsparcer.sms.ui.screens

import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.tbsparcer.sms.ui.components.StatCard
import uz.tbsparcer.sms.ui.components.TbsChip
import uz.tbsparcer.sms.ui.theme.DisplaySerif
import uz.tbsparcer.sms.ui.theme.LocalTbs
import uz.tbsparcer.sms.ui.theme.MonoJetBrains
import uz.tbsparcer.sms.ui.theme.SansGrotesk
import uz.tbsparcer.sms.ui.vm.StatsViewModel

@Composable
fun StatsScreen(vm: StatsViewModel = hiltViewModel()) {
    val p = LocalTbs.current
    val ui by vm.ui.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { vm.load() }
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Статистика", fontFamily = DisplaySerif, fontSize = 30.sp, color = p.ink)

        SectionLabel("Источник")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("all" to "Все", "sms" to "SMS", "telegram" to "Telegram").forEach { (k, lbl) ->
                TbsChip(lbl, ui.source == k) { vm.setSource(k) }
            }
        }
        if (ui.source == "telegram" && ui.sources.isNotEmpty()) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                ui.sources.take(8).forEach { src ->
                    TbsChip(src.title ?: src.chatId.toString(), ui.chatId == src.chatId) { vm.setChat(src.chatId) }
                }
            }
        }

        OutlinedTextField(
            ui.card, { vm.setCard(it.filter { c -> c.isDigit() }.take(4)) },
            label = { Text("Карта (4 цифры)", fontFamily = SansGrotesk) },
            singleLine = true,
            shape = MaterialTheme.shapes.small,
            modifier = Modifier.fillMaxWidth(),
        )

        when {
            ui.loading && ui.stats == null ->
                Box(Modifier.fillMaxWidth().padding(top = 32.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(color = p.accent, strokeWidth = 2.dp)
                }
            ui.error != null && ui.stats == null ->
                Text("Не удалось загрузить: ${ui.error}", fontFamily = SansGrotesk, fontSize = 13.sp, color = p.expense)
        }

        val s = ui.stats
        if (s != null) {
            ui.error?.let {
                Text("Данные могли устареть: $it", fontFamily = SansGrotesk, fontSize = 12.sp, color = p.inkSecondary)
            }
            StatCard("Общая сумма трат", "${s.totalVolume} ${s.currency}", modifier = Modifier.fillMaxWidth())
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                StatCard("Прошло (всего)", s.transactionCount.toString(), modifier = Modifier.weight(1f))
                StatCard("Не прошло (этот телефон)", ui.localFailed.toString(), modifier = Modifier.weight(1f))
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                StatCard("Расход", s.debitVolume, modifier = Modifier.weight(1f))
                StatCard("Доход", s.creditVolume, accent = true, modifier = Modifier.weight(1f))
            }

            if (s.byCard.isNotEmpty()) {
                Spacer(Modifier.height(4.dp))
                SectionLabel("По картам")
                Column(
                    Modifier.fillMaxWidth().border(1.dp, p.border, MaterialTheme.shapes.medium),
                ) {
                    s.byCard.forEachIndexed { i, c ->
                        if (i > 0) HorizontalDivider(color = p.border)
                        Row(
                            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 12.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text("•••• ${c.cardLast4}", fontFamily = MonoJetBrains, fontSize = 13.sp, color = p.ink)
                            Spacer(Modifier.weight(1f))
                            Text(c.volume, fontFamily = MonoJetBrains, fontSize = 13.sp,
                                fontWeight = FontWeight.Medium, color = p.ink,
                                maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Spacer(Modifier.width(12.dp))
                            Text("${c.count}", fontFamily = MonoJetBrains, fontSize = 11.sp, color = p.inkSecondary)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SectionLabel(text: String) {
    val p = LocalTbs.current
    Text(text.uppercase(), fontFamily = MonoJetBrains, fontSize = 11.sp,
        letterSpacing = 1.2.sp, color = p.inkSecondary)
}
