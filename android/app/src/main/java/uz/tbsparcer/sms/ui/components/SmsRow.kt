package uz.tbsparcer.sms.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import uz.tbsparcer.sms.data.local.SmsRecord
import uz.tbsparcer.sms.ui.theme.LocalTbs
import uz.tbsparcer.sms.ui.theme.MonoJetBrains
import uz.tbsparcer.sms.ui.theme.SansGrotesk
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private val rowFmt = SimpleDateFormat("dd.MM.yy HH:mm", Locale.US)

@Composable
fun SmsRow(rec: SmsRecord, onClick: () -> Unit) {
    val p = LocalTbs.current
    Column(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 8.dp),
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(rowFmt.format(Date(rec.receivedAt)), fontFamily = MonoJetBrains, fontSize = 11.sp, color = p.inkSecondary)
            Text(rec.syncStatus.uppercase() + (rec.backendTransactionId?.let { "  #$it" } ?: ""),
                fontFamily = MonoJetBrains, fontSize = 10.sp, letterSpacing = 1.sp,
                color = when (rec.syncStatus) {
                    "synced", "created" -> p.income
                    "error", "parse_error" -> p.expense
                    else -> p.inkSecondary
                })
        }
        Spacer(Modifier.height(2.dp))
        Text(rec.body, fontFamily = SansGrotesk, fontSize = 13.sp, color = p.ink,
            maxLines = 2, overflow = TextOverflow.Ellipsis)
    }
}
