package uz.tbsparcer.sms.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import uz.tbsparcer.sms.ui.theme.LocalTbs
import uz.tbsparcer.sms.ui.theme.MonoJetBrains

@Composable
fun StatusPill(online: Boolean, label: String) {
    val p = LocalTbs.current
    val dot = if (online) p.income else p.expense
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(6.dp).clip(CircleShape).background(dot))
        Spacer(Modifier.width(6.dp))
        Text(label.uppercase(), fontFamily = MonoJetBrains, fontSize = 10.sp,
            letterSpacing = 1.2.sp, color = p.inkSecondary)
    }
}
