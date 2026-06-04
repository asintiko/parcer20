package uz.tbsparcer.sms.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.hilt.navigation.compose.hiltViewModel
import uz.tbsparcer.sms.data.local.SmsRecord
import uz.tbsparcer.sms.ui.theme.DisplaySerif
import uz.tbsparcer.sms.ui.theme.LocalTbs
import uz.tbsparcer.sms.ui.theme.MonoJetBrains
import uz.tbsparcer.sms.ui.theme.SansGrotesk
import uz.tbsparcer.sms.ui.vm.SmsDetailViewModel

private fun statusRu(s: String): String = when (s) {
    "pending" -> "В очереди"
    "synced", "created" -> "Обработано"
    "duplicate" -> "Дубликат"
    "skipped" -> "Пропущено"
    "error", "parse_error", "failed" -> "Ошибка"
    "auth_error" -> "Ошибка авторизации"
    else -> s
}

private fun typeRu(t: String?): String? = when (t?.uppercase()) {
    "CREDIT" -> "Доход"
    "DEBIT" -> "Расход"
    null -> null
    else -> t
}

@Composable
fun SmsDetailScreen(deviceSmsId: String, vm: SmsDetailViewModel = hiltViewModel()) {
    val p = LocalTbs.current
    LaunchedEffect(deviceSmsId) { vm.load(deviceSmsId) }
    val rec by vm.record.collectAsStateWithLifecycle()
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text("Чек", fontFamily = DisplaySerif, fontSize = 30.sp, color = p.ink)
        rec?.let { r ->
            Kv("Статус", statusRu(r.syncStatus))
            r.backendTransactionId?.let { Kv("Транзакция", "#$it") }
            Kv("Отправитель", r.sender)

            if (hasParsed(r)) {
                Spacer(Modifier.height(6.dp))
                Text("РАЗБОР", fontFamily = MonoJetBrains, fontSize = 11.sp, letterSpacing = 1.2.sp, color = p.inkSecondary)
                r.pAmount?.let { Kv("Сумма", it + (r.pCurrency?.let { c -> " $c" } ?: "")) }
                r.pTxnDate?.let { Kv("Дата операции", it) }
                r.pCardLast4?.let { Kv("Карта", "•••• $it") }
                typeRu(r.pTxnType)?.let { Kv("Тип", it) }
                r.pOperator?.let { Kv("Оператор", it) }
                r.pApplication?.let { Kv("Приложение", it) }
                r.pBalanceAfter?.let { Kv("Остаток", it + (r.pCurrency?.let { c -> " $c" } ?: "")) }
            }

            Spacer(Modifier.height(6.dp))
            Text("ТЕКСТ SMS", fontFamily = MonoJetBrains, fontSize = 11.sp, letterSpacing = 1.2.sp, color = p.inkSecondary)
            Text(r.body, fontFamily = MonoJetBrains, fontSize = 12.sp, color = p.ink)
            r.fingerprint?.let { Kv("Fingerprint", it) }
            r.errorMessage?.let { Kv("Ошибка", it) }
        } ?: Text("Загрузка…", fontFamily = SansGrotesk, fontSize = 14.sp, color = p.inkSecondary)
    }
}

private fun hasParsed(r: SmsRecord): Boolean =
    r.pAmount != null || r.pTxnDate != null || r.pCardLast4 != null || r.pOperator != null ||
        r.pTxnType != null || r.pBalanceAfter != null || r.pApplication != null

@Composable
private fun Kv(label: String, value: String) {
    val p = LocalTbs.current
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, fontFamily = SansGrotesk, fontSize = 13.sp, color = p.inkSecondary)
        Text(value, fontFamily = SansGrotesk, fontWeight = FontWeight.Medium, fontSize = 13.sp, color = p.ink)
    }
}
