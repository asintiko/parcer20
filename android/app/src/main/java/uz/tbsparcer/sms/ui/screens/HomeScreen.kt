package uz.tbsparcer.sms.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.tbsparcer.sms.ui.components.SmsRow
import uz.tbsparcer.sms.ui.components.StatusPill
import uz.tbsparcer.sms.ui.components.TbsChip
import uz.tbsparcer.sms.ui.vm.HomeViewModel

@Composable
fun HomeScreen(onOpenDetail: (String) -> Unit, vm: HomeViewModel = hiltViewModel()) {
    val records by vm.records.collectAsStateWithLifecycle()
    val counts by vm.counts.collectAsStateWithLifecycle()
    val filter by vm.filter.collectAsStateWithLifecycle()
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            StatusPill(online = true, label = "online")
            Text("pending ${counts["pending"] ?: 0} · err ${counts["error"] ?: 0}")
        }
        Spacer(Modifier.height(8.dp))
        Button(onClick = { vm.syncNow() }) { Text("SYNC NOW") }
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("all","pending","synced","duplicate","error").forEach {
                TbsChip(it, filter == it) { vm.setFilter(it) }
            }
        }
        Spacer(Modifier.height(8.dp))
        LazyColumn(Modifier.fillMaxSize()) {
            items(records, key = { it.deviceSmsId }) { SmsRow(it) { onOpenDetail(it.deviceSmsId) } }
        }
    }
}
