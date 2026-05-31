package uz.tbsparcer.sms.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import uz.tbsparcer.sms.ui.theme.LocalTbs
import uz.tbsparcer.sms.ui.theme.MonoJetBrains

@Composable
fun TbsChip(text: String, selected: Boolean, onClick: () -> Unit) {
    val p = LocalTbs.current
    val shape = RoundedCornerShape(999.dp)
    val bg = if (selected) p.accent else p.surface
    val fg = if (selected) p.onAccent else p.ink
    Text(
        text.uppercase(),
        fontFamily = MonoJetBrains, fontSize = 11.sp, letterSpacing = 0.8.sp, color = fg,
        modifier = Modifier
            .clip(shape)
            .then(if (selected) Modifier.background(bg) else Modifier.border(BorderStroke(1.dp, p.border), shape))
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 7.dp),
    )
}
