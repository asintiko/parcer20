package uz.tbsparcer.sms.ui.screens

import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.tbsparcer.sms.BuildConfig
import uz.tbsparcer.sms.data.local.ProvisioningPolicy
import uz.tbsparcer.sms.ui.components.StatusPill
import uz.tbsparcer.sms.ui.components.TbsChip
import uz.tbsparcer.sms.ui.theme.DisplaySerif
import uz.tbsparcer.sms.ui.theme.LocalTbs
import uz.tbsparcer.sms.ui.theme.MonoJetBrains
import uz.tbsparcer.sms.ui.theme.SansGrotesk
import uz.tbsparcer.sms.ui.vm.DiagnosticsViewModel
import uz.tbsparcer.sms.ui.vm.SettingsViewModel
import uz.tbsparcer.sms.ui.vm.UpdateUi
import uz.tbsparcer.sms.ui.vm.UpdateViewModel

private val themeOptions = listOf("system" to "Системная", "light" to "Светлая", "dark" to "Тёмная")

@Composable
fun SettingsScreen(
    onOpenSenders: () -> Unit = {},
    vm: SettingsViewModel = hiltViewModel(),
    diagVm: DiagnosticsViewModel = hiltViewModel(),
    updateVm: UpdateViewModel = hiltViewModel(),
) {
    val p = LocalTbs.current
    var theme by remember { mutableStateOf(vm.settings.themeMode) }
    var baseUrl by remember { mutableStateOf(vm.settings.baseUrl) }
    var deviceId by remember { mutableStateOf(vm.settings.deviceId) }
    var mobileKey by remember { mutableStateOf(vm.settings.mobileKey) }
    var saved by remember { mutableStateOf(false) }
    var saveError by remember { mutableStateOf(false) }
    var advanced by remember { mutableStateOf(false) }
    val diag by diagVm.ui.collectAsStateWithLifecycle()
    val update by updateVm.ui.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { diagVm.runChecks() }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text("Настройки", fontFamily = DisplaySerif, fontSize = 30.sp, color = p.ink)

        // Connection status (folds in the old Diagnostics screen).
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            StatusPill(
                online = diag.backendOk == true && diag.authError.not(),
                label = when (diag.backendOk) { true -> "сервер на связи"; false -> "сервер недоступен"; null -> "проверка…" },
            )
            TextButton(onClick = { diagVm.runChecks() }) {
                Text("Обновить", fontFamily = SansGrotesk, fontSize = 13.sp, color = p.ink)
            }
        }
        diag.latencyMs?.let {
            Text("Задержка ${it} мс · версия ${diag.version ?: "—"}",
                fontFamily = MonoJetBrains, fontSize = 11.sp, color = p.inkSecondary)
        }

        Text("ОБНОВЛЕНИЕ ПРИЛОЖЕНИЯ", fontFamily = MonoJetBrains, fontSize = 11.sp,
            letterSpacing = 1.2.sp, color = p.inkSecondary)
        Column(
            Modifier.fillMaxWidth().border(1.dp, p.border, MaterialTheme.shapes.medium)
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text("Текущая версия: ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})",
                fontFamily = MonoJetBrains, fontSize = 11.sp, color = p.inkSecondary)

            when (val u = update) {
                is UpdateUi.Checking -> Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp, color = p.accent)
                    Text("Проверка…", fontFamily = SansGrotesk, fontSize = 13.sp, color = p.inkSecondary)
                }
                is UpdateUi.UpToDate -> Text("Установлена последняя версия.",
                    fontFamily = SansGrotesk, fontSize = 13.sp, color = p.income)
                is UpdateUi.Available -> {
                    Text("Доступна версия ${u.manifest.versionName} (${u.manifest.versionCode})",
                        fontFamily = SansGrotesk, fontWeight = FontWeight.Medium, fontSize = 14.sp, color = p.ink)
                    u.manifest.notes?.takeIf { it.isNotBlank() }?.let {
                        Text(it, fontFamily = SansGrotesk, fontSize = 12.sp, color = p.inkSecondary)
                    }
                }
                is UpdateUi.Downloading -> {
                    Text("Загрузка ${u.percent}%", fontFamily = SansGrotesk, fontSize = 13.sp, color = p.ink)
                    LinearProgressIndicator(
                        progress = { u.percent / 100f },
                        modifier = Modifier.fillMaxWidth(),
                        color = p.accent,
                    )
                }
                is UpdateUi.NeedsPermission -> Text(
                    "Разрешите установку из этого источника в открывшихся настройках, затем нажмите «Скачать и установить» ещё раз.",
                    fontFamily = SansGrotesk, fontSize = 13.sp, color = p.expense)
                is UpdateUi.Error -> Text("Ошибка: ${u.message}",
                    fontFamily = SansGrotesk, fontSize = 13.sp, color = p.expense)
                UpdateUi.Idle -> {}
            }

            val downloading = update is UpdateUi.Downloading
            val showInstall = update is UpdateUi.Available || update is UpdateUi.Downloading ||
                update is UpdateUi.NeedsPermission
            if (showInstall) {
                Button(
                    onClick = { updateVm.downloadAndInstall() },
                    enabled = !downloading,
                    modifier = Modifier.fillMaxWidth(),
                    shape = MaterialTheme.shapes.small,
                    colors = ButtonDefaults.buttonColors(containerColor = p.accent, contentColor = p.onAccent),
                ) {
                    Text(if (downloading) "Загрузка…" else "Скачать и установить",
                        fontFamily = SansGrotesk, fontWeight = FontWeight.Medium, fontSize = 14.sp)
                }
            } else {
                OutlinedButton(
                    onClick = { updateVm.check() },
                    enabled = update !is UpdateUi.Checking,
                    modifier = Modifier.fillMaxWidth(),
                    shape = MaterialTheme.shapes.small,
                ) {
                    Text("Проверить обновления", fontFamily = SansGrotesk, fontSize = 14.sp, color = p.ink)
                }
            }
        }

        Text("ТЕМА", fontFamily = MonoJetBrains, fontSize = 11.sp, letterSpacing = 1.2.sp, color = p.inkSecondary)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            themeOptions.forEach { (key, label) ->
                TbsChip(label, theme == key) { theme = key }
            }
        }

        Button(
            onClick = {
                saved = vm.save(baseUrl, deviceId, mobileKey, theme)
                saveError = !saved
            },
            modifier = Modifier.fillMaxWidth(),
            shape = MaterialTheme.shapes.small,
            colors = ButtonDefaults.buttonColors(containerColor = p.accent, contentColor = p.onAccent),
            enabled = ProvisioningPolicy.provisioned(deviceId, mobileKey),
        ) {
            Text("Сохранить", fontFamily = SansGrotesk, fontWeight = FontWeight.Medium, fontSize = 15.sp,
                modifier = Modifier.padding(vertical = 6.dp))
        }
        if (saved) Text("Сохранено. Перезапустите приложение для смены темы.",
            fontFamily = SansGrotesk, fontSize = 12.sp, color = p.inkSecondary)
        if (saveError) Text("Проверьте ID и персональный ключ устройства.",
            fontFamily = SansGrotesk, fontSize = 12.sp, color = p.expense)

        OutlinedButton(onClick = onOpenSenders, modifier = Modifier.fillMaxWidth(),
            shape = MaterialTheme.shapes.small) {
            Text("Отправители SMS", fontFamily = SansGrotesk, fontSize = 14.sp, color = p.ink)
        }

        OutlinedButton(onClick = { vm.runBackfill() }, modifier = Modifier.fillMaxWidth(),
            shape = MaterialTheme.shapes.small) {
            Text("Пересобрать историю", fontFamily = SansGrotesk, fontSize = 14.sp, color = p.ink)
        }

        TextButton(onClick = { advanced = !advanced }) {
            Text(if (advanced) "Скрыть дополнительно" else "Дополнительно",
                fontFamily = SansGrotesk, fontSize = 13.sp, color = p.inkSecondary)
        }
        if (advanced) {
            OutlinedTextField(
                baseUrl, { baseUrl = it },
                label = { Text("Адрес сервера") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                deviceId, { deviceId = it; saved = false; saveError = false },
                label = { Text("ID этого устройства") },
                supportingText = { Text("Выдаётся администратором вместе с ключом") },
                singleLine = true,
                isError = deviceId.isNotEmpty() && !ProvisioningPolicy.validDeviceId(deviceId),
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                mobileKey, { mobileKey = it },
                label = { Text("Ключ этого устройства") },
                supportingText = { Text("Не менее 32 символов") },
                visualTransformation = PasswordVisualTransformation(),
                singleLine = true,
                isError = mobileKey.isNotEmpty() && !ProvisioningPolicy.validMobileKey(mobileKey),
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedButton(onClick = { vm.clearLocal() }, modifier = Modifier.fillMaxWidth(),
                shape = MaterialTheme.shapes.small) {
                Text("Очистить локальную базу", fontFamily = SansGrotesk, fontSize = 14.sp, color = p.expense)
            }
            Text("Устройство: ${vm.settings.deviceId}",
                fontFamily = MonoJetBrains, fontSize = 10.sp, color = p.inkSecondary)
        }
    }
}
