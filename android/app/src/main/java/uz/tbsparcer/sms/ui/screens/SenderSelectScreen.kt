package uz.tbsparcer.sms.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.tbsparcer.sms.data.repo.SenderInfo
import uz.tbsparcer.sms.data.repo.SmsRepository
import uz.tbsparcer.sms.ui.theme.DisplaySerif
import uz.tbsparcer.sms.ui.theme.LocalTbs
import uz.tbsparcer.sms.ui.theme.MonoJetBrains
import uz.tbsparcer.sms.ui.theme.SansGrotesk
import uz.tbsparcer.sms.ui.vm.SenderSelectViewModel

/**
 * Allowlist picker. Reused in onboarding (embedded under the date step) and in Settings
 * (standalone editing). [onDone] fires after the selection is persisted.
 */
@Composable
fun SenderSelectScreen(
    onDone: () -> Unit,
    vm: SenderSelectViewModel = hiltViewModel(),
    embedded: Boolean = false,
    doneLabel: String = "Готово",
) {
    val p = LocalTbs.current
    val ui by vm.ui.collectAsStateWithLifecycle()

    Column(
        Modifier.fillMaxSize().padding(if (embedded) 0.dp else 16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (!embedded) {
            Text("Отправители SMS", fontFamily = DisplaySerif, fontSize = 30.sp, color = p.ink)
        }
        Text(
            "Отметьте отправителей, с которых собирать чеки. Снятые игнорируются полностью.",
            fontFamily = SansGrotesk, fontSize = 13.sp, color = p.inkSecondary,
        )

        val hasBanks = ui.senders.any { it.looksBank }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (hasBanks) {
                ActionLink("Выбрать все банковские") { vm.selectAllBanks() }
            }
        }

        when {
            ui.loading -> {
                Box(Modifier.fillMaxWidth().padding(top = 24.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(color = p.accent, strokeWidth = 2.dp)
                }
            }
            ui.senders.isEmpty() -> {
                Text(
                    "Не нашли SMS в инбоксе. Проверьте разрешение на чтение SMS и попробуйте снова.",
                    fontFamily = SansGrotesk, fontSize = 13.sp, color = p.inkSecondary,
                )
            }
            else -> {
                LazyColumn(
                    Modifier.weight(1f, fill = false),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(ui.senders, key = { it.address }) { s ->
                        SenderItem(
                            sender = s,
                            checked = SmsRepository.normalizeSender(s.address) in ui.selected,
                            onToggle = { vm.toggle(s.address) },
                        )
                    }
                }
            }
        }

        Spacer(Modifier.height(4.dp))
        Button(
            onClick = { vm.save(); onDone() },
            modifier = Modifier.fillMaxWidth(),
            shape = MaterialTheme.shapes.small,
            enabled = !ui.loading,
            colors = ButtonDefaults.buttonColors(containerColor = p.accent, contentColor = p.onAccent),
        ) {
            Text(doneLabel, fontFamily = SansGrotesk, fontWeight = FontWeight.Medium, fontSize = 15.sp,
                modifier = Modifier.padding(vertical = 6.dp))
        }
        Text(
            "Если ничего не выбрать — собираются чеки со всех отправителей.",
            fontFamily = SansGrotesk, fontSize = 12.sp, color = p.inkSecondary,
        )
    }
}

@Composable
private fun ActionLink(text: String, onClick: () -> Unit) {
    val p = LocalTbs.current
    val shape = RoundedCornerShape(999.dp)
    Text(
        text.uppercase(),
        fontFamily = MonoJetBrains, fontSize = 11.sp, letterSpacing = 0.8.sp, color = p.ink,
        modifier = Modifier
            .clip(shape)
            .border(BorderStroke(1.dp, p.border), shape)
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 7.dp),
    )
}

@Composable
private fun SenderItem(sender: SenderInfo, checked: Boolean, onToggle: () -> Unit) {
    val p = LocalTbs.current
    Row(
        Modifier
            .fillMaxWidth()
            .clip(MaterialTheme.shapes.small)
            .clickable(onClick = onToggle)
            .padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Checkbox(
            checked = checked,
            onCheckedChange = { onToggle() },
            colors = CheckboxDefaults.colors(checkedColor = p.accent, checkmarkColor = p.onAccent),
        )
        Spacer(Modifier.width(4.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(sender.address, fontFamily = SansGrotesk, fontSize = 14.sp,
                    fontWeight = FontWeight.Medium, color = p.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (sender.looksBank) BankBadge()
            }
            Spacer(Modifier.height(2.dp))
            Text(sender.sampleText, fontFamily = SansGrotesk, fontSize = 12.sp, color = p.inkSecondary,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Spacer(Modifier.width(8.dp))
        Text("${sender.count}", fontFamily = MonoJetBrains, fontSize = 11.sp, color = p.inkSecondary)
    }
}

@Composable
private fun BankBadge() {
    val p = LocalTbs.current
    Text(
        "БАНК",
        fontFamily = MonoJetBrains, fontSize = 9.sp, letterSpacing = 1.sp, color = p.onAccent,
        modifier = Modifier
            .clip(MaterialTheme.shapes.extraSmall)
            .background(p.accent)
            .padding(horizontal = 6.dp, vertical = 2.dp),
    )
}
