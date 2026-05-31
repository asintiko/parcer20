package uz.tbsparcer.sms.ui.components

import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import uz.tbsparcer.sms.ui.theme.DisplaySerif
import uz.tbsparcer.sms.ui.theme.LocalTbs
import uz.tbsparcer.sms.ui.theme.MonoJetBrains

@Composable
fun StatCard(label: String, value: String, accent: Boolean = false, modifier: Modifier = Modifier) {
    val p = LocalTbs.current
    Column(
        modifier
            .border(1.dp, p.border, RoundedCornerShape(6.dp))
            .padding(horizontal = 14.dp, vertical = 12.dp),
    ) {
        Text(label.uppercase(), fontFamily = MonoJetBrains, fontSize = 10.sp,
            letterSpacing = 1.2.sp, color = p.inkSecondary)
        Spacer(Modifier.height(4.dp))
        Text(value, fontFamily = DisplaySerif, fontSize = 26.sp, fontWeight = FontWeight.Normal,
            color = if (accent) p.income else p.ink)
    }
}
