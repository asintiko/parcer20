package uz.tbsparcer.sms.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

data class TbsPalette(
    val bg: Color, val surface: Color, val surface2: Color, val border: Color,
    val ink: Color, val inkSecondary: Color, val accent: Color, val onAccent: Color,
    val income: Color, val expense: Color, val dark: Boolean,
)

val LocalTbs = staticCompositionLocalOf {
    TbsPalette(LBg, LSurface, LSurface2, LBorder, LInk, LInkSecondary, LAccent, LOnAccent, IncomeLight, ExpenseLight, false)
}

private val tbsTypography = Typography(
    bodyMedium = TextStyle(fontFamily = SansGrotesk, fontSize = 14.sp),
    labelSmall = TextStyle(fontFamily = MonoJetBrains, fontSize = 11.sp, letterSpacing = 1.2.sp),
    headlineMedium = TextStyle(fontFamily = DisplaySerif, fontSize = 28.sp, fontWeight = FontWeight.Normal),
)

@Composable
fun TbsTheme(darkTheme: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    val palette = if (darkTheme)
        TbsPalette(DBg, DSurface, DSurface2, DBorder, DInk, DInkSecondary, DAccent, DOnAccent, IncomeDark, ExpenseDark, true)
    else
        TbsPalette(LBg, LSurface, LSurface2, LBorder, LInk, LInkSecondary, LAccent, LOnAccent, IncomeLight, ExpenseLight, false)

    val scheme = if (darkTheme)
        darkColorScheme(background = DBg, surface = DSurface, primary = DAccent, onPrimary = DOnAccent, onBackground = DInk, onSurface = DInk, outline = DBorder)
    else
        lightColorScheme(background = LBg, surface = LSurface, primary = LAccent, onPrimary = LOnAccent, onBackground = LInk, onSurface = LInk, outline = LBorder)

    CompositionLocalProvider(LocalTbs provides palette) {
        MaterialTheme(colorScheme = scheme, typography = tbsTypography, content = content)
    }
}
