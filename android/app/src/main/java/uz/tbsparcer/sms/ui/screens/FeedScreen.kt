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
import uz.tbsparcer.sms.ui.components.TbsChip
import uz.tbsparcer.sms.ui.theme.DisplaySerif
import uz.tbsparcer.sms.ui.theme.LocalTbs
import uz.tbsparcer.sms.ui.theme.SansGrotesk
import uz.tbsparcer.sms.ui.vm.HomeViewModel

private val feedFilters = listOf(
    "all" to "Все", "pending" to "В очереди", "synced" to "Обработано",
    "duplicate" to "Дубликаты", "error" to "Ошибки",
)

@Composable
fun FeedScreen(onOpenDetail: (String) -> Unit, vm: HomeViewModel = hiltViewModel()) {
    val p = LocalTbs.current
    val records by vm.records.collectAsStateWithLifecycle()
    val filter by vm.filter.collectAsStateWithLifecycle()
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Text("Лента", fontFamily = DisplaySerif, fontSize = 30.sp, color = p.ink)
        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            feedFilters.forEach { (key, label) ->
                TbsChip(label, filter == key) { vm.setFilter(key) }
            }
        }
        Spacer(Modifier.height(8.dp))
        if (records.isEmpty()) {
            Box(Modifier.fillMaxSize(), contentAlignment = androidx.compose.ui.Alignment.Center) {
                Text("Пока пусто", fontFamily = SansGrotesk, fontWeight = FontWeight.Medium,
                    fontSize = 14.sp, color = p.inkSecondary)
            }
        } else {
            LazyColumn(Modifier.fillMaxSize()) {
                items(records, key = { it.deviceSmsId }) { SmsRow(it) { onOpenDetail(it.deviceSmsId) } }
            }
        }
    }
}
