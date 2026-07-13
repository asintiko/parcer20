-keep class uz.tbsparcer.sms.data.remote.** { *; }
-keepclassmembers class uz.tbsparcer.sms.data.remote.** { *; }
-keepattributes Signature
-keepattributes *Annotation*
-keep class * extends androidx.room.RoomDatabase { *; }

# Google Tink (pulled in by androidx.security-crypto) references compile-only
# errorprone annotations that are absent at runtime. They are safe to ignore.
-dontwarn com.google.errorprone.annotations.**
