package uz.tbsparcer.sms.receiver

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import uz.tbsparcer.sms.data.repo.SmsRepository
import uz.tbsparcer.sms.domain.SmsLocalId
import uz.tbsparcer.sms.work.WorkScheduler

class SmsReceiver : BroadcastReceiver() {

    @EntryPoint
    @InstallIn(SingletonComponent::class)
    interface ReceiverEntryPoint { fun smsRepository(): SmsRepository }

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
        val msgs = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        val sender = msgs.firstOrNull()?.originatingAddress ?: return
        val body = msgs.joinToString("") { it.messageBody ?: "" }
        val ts = msgs.firstOrNull()?.timestampMillis ?: System.currentTimeMillis()
        val deviceSmsId = SmsLocalId.of(sender, ts, body)

        val repo = EntryPointAccessors
            .fromApplication(context.applicationContext, ReceiverEntryPoint::class.java)
            .smsRepository()

        val pending = goAsync()
        val handler = CoroutineExceptionHandler { _, _ -> }
        CoroutineScope(Dispatchers.IO + handler).launch {
            try {
                repo.insertRealtime(deviceSmsId, sender, body, ts)
                WorkScheduler.syncNow(context.applicationContext)
            } finally {
                pending.finish()
            }
        }
    }
}
