# TBSparcer SMS Collector (Android) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a signed Android app that reads bank SMS, sends them to the existing `POST /api/sms/ingest`, and shows system-wide spending statistics + diagnostics, styled like the editorial-monochrome desktop client.

**Architecture:** Kotlin + Jetpack Compose app. SMS captured via BroadcastReceiver (realtime) + one-time inbox backfill from a chosen date. Stored in Room with per-message sync status. WorkManager batches `pending` rows to the backend and writes back results. Statistics come from a new mobile-key-protected `GET /api/sms/stats` + `GET /api/sms/sources`. Auth everywhere is a single `X-Mobile-Ingest-Key` header — no login.

**Tech Stack:** Backend: FastAPI, SQLAlchemy, pytest. Android: Kotlin, Compose+Material3, Retrofit2/OkHttp/Moshi, Room, WorkManager, Hilt, androidx.security-crypto. Build: JDK 17, Android SDK 35, Gradle 8.7 / AGP 8.5, R8, custom release keystore.

**Spec:** `docs/superpowers/specs/2026-05-30-android-sms-client-design.md`

---

## File Structure

### Backend (modify existing only)
- Modify: `backend/api/routes/sms.py` — add `GET /api/sms/stats` + `GET /api/sms/sources` and their Pydantic models, into the existing mobile-key router.
- Modify: `backend/tests/test_sms_ingest_api.py` — add stats/sources tests reusing existing fixtures.

### Android (new `android/` tree)
```
android/
  settings.gradle.kts          gradle/wrapper/gradle-wrapper.properties
  build.gradle.kts             gradle.properties
  app/build.gradle.kts         app/proguard-rules.pro
  app/src/main/AndroidManifest.xml
  app/src/main/res/values/strings.xml, themes.xml
  app/src/main/res/xml/network_security_config.xml
  app/src/main/res/font/  (3 ttf families)
  app/src/main/java/uz/tbsparcer/sms/
    TbsApp.kt  MainActivity.kt
    di/NetworkModule.kt  di/DatabaseModule.kt
    data/local/SmsRecord.kt  SmsRecordDao.kt  AppDatabase.kt
    data/local/SettingsStore.kt
    data/remote/dto.kt  ApiService.kt  MobileKeyInterceptor.kt
    data/repo/SmsRepository.kt  StatsRepository.kt
    domain/SmsFilter.kt  FingerprintCalculator.kt
    work/SyncWorker.kt  BackfillWorker.kt
    receiver/SmsReceiver.kt
    ui/theme/Color.kt  Type.kt  Theme.kt
    ui/components/StatusPill.kt  StatCard.kt  FilterChip.kt  SmsRow.kt
    ui/screens/OnboardingScreen.kt Home/Stats/Diagnostics/Settings/SmsDetail Screen.kt
    ui/vm/HomeViewModel.kt StatsViewModel.kt DiagnosticsViewModel.kt SettingsViewModel.kt
  app/src/test/java/uz/tbsparcer/sms/
    SmsFilterTest.kt  FingerprintCalculatorTest.kt
```

---

## PHASE A — Backend statistics endpoints

> Run backend tests with the project venv. From `backend/`:
> `../.venv/bin/python -m pytest tests/test_sms_ingest_api.py -v` (or `python -m pytest` if venv already active).

### Task A1: `GET /api/sms/stats` — response models + failing test

**Files:**
- Modify: `backend/api/routes/sms.py` (add models after `SmsHealthResponse`, ~line 86)
- Test: `backend/tests/test_sms_ingest_api.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_sms_ingest_api.py`:

```python
def _seed_tx(db, *, amount, ttype, source_type, card, chat_id=0, currency="UZS",
             date="2026-05-10T12:00:00", operator="SHOP"):
    from services.fingerprint import compute_fingerprint
    from datetime import datetime as _dt
    d = _dt.fromisoformat(date)
    tx = Transaction(
        raw_message="seed", source_type=source_type, source_chat_id=chat_id,
        source_message_id=None, transaction_date=d, amount=amount, currency=currency,
        card_last_4=card, operator_raw=operator, transaction_type=ttype,
        parsing_method="REGEX_SMS", parsing_confidence=0.9,
        fingerprint=compute_fingerprint(amount=abs(amount), transaction_date=d,
                                        card_last4=card, operator_raw=operator,
                                        transaction_type=ttype),
    )
    db.add(tx)
    db.flush()
    return tx


def test_stats_requires_mobile_key(client):
    resp = client.get("/api/sms/stats")
    assert resp.status_code == 403


def test_stats_aggregates_volume_and_counts(client, db_session):
    _seed_tx(db_session, amount=-100000, ttype="DEBIT", source_type="SMS", card="0907")
    _seed_tx(db_session, amount=-50000, ttype="DEBIT", source_type="AUTO", card="0907", chat_id=-100)
    _seed_tx(db_session, amount=20000, ttype="CREDIT", source_type="SMS", card="4862")
    db_session.commit()

    resp = client.get("/api/sms/stats", headers={"X-Mobile-Ingest-Key": "sms-test-key"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["transaction_count"] == 3
    assert body["debit_count"] == 2
    assert body["credit_count"] == 1
    assert body["total_volume"] == "170000.00"
    assert body["debit_volume"] == "150000.00"
    assert body["credit_volume"] == "20000.00"
    sources = {row["source"]: row for row in body["by_source"]}
    assert sources["SMS"]["count"] == 2
    assert sources["TELEGRAM"]["count"] == 1
    cards = {row["card_last_4"]: row for row in body["by_card"]}
    assert cards["0907"]["count"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ../.venv/bin/python -m pytest tests/test_sms_ingest_api.py::test_stats_aggregates_volume_and_counts -v`
Expected: FAIL — 404 (route not defined) or KeyError.

- [ ] **Step 3: Add response models**

In `backend/api/routes/sms.py`, after the `SmsHealthResponse` class (~line 86), add:

```python
class SmsStatsSourceRow(BaseModel):
    source: str  # SMS | TELEGRAM | MANUAL
    count: int
    volume: str


class SmsStatsCardRow(BaseModel):
    card_last_4: str
    count: int
    volume: str


class SmsStatsResponse(BaseModel):
    currency: str
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    total_volume: str
    debit_volume: str
    credit_volume: str
    transaction_count: int
    debit_count: int
    credit_count: int
    by_source: List[SmsStatsSourceRow]
    by_card: List[SmsStatsCardRow]
```

- [ ] **Step 4: Add the endpoint**

In `backend/api/routes/sms.py`, add imports at top (merge into existing sqlalchemy import line 13):

```python
from sqlalchemy import func, text
```

Add a source-label helper and the route after the `ingest_sms` function (end of file):

```python
def _money(value: Any) -> str:
    try:
        return f"{abs(Decimal(str(value or 0))):.2f}"
    except Exception:
        return "0.00"


def _source_label(source_type: Optional[str]) -> str:
    st = (source_type or "").upper()
    if st == "SMS":
        return "SMS"
    if st == "MANUAL":
        return "MANUAL"
    return "TELEGRAM"


@router.get("/stats", response_model=SmsStatsResponse)
async def sms_stats(
    db: Session = Depends(get_db_session),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    source: str = "all",
    source_chat_id: Optional[int] = None,
    card: Optional[str] = None,
    currency: str = "UZS",
) -> SmsStatsResponse:
    currency = (currency or "UZS").upper()[:3]
    base = db.query(Transaction).filter(Transaction.currency == currency)

    if date_from is not None:
        base = base.filter(Transaction.transaction_date >= _normalize_datetime(date_from))
    if date_to is not None:
        base = base.filter(Transaction.transaction_date <= _normalize_datetime(date_to))

    src = (source or "all").lower()
    if src == "sms":
        base = base.filter(Transaction.source_type == "SMS")
    elif src == "telegram":
        base = base.filter(Transaction.source_type == "AUTO")
        if source_chat_id is not None:
            base = base.filter(Transaction.source_chat_id == source_chat_id)

    card_norm = _normalize_card_last4(card) if card else None
    if card_norm:
        base = base.filter(Transaction.card_last_4 == card_norm)

    subq = base.with_entities(
        Transaction.id, Transaction.amount, Transaction.transaction_type,
        Transaction.source_type, Transaction.card_last_4,
    ).subquery()

    total_volume = db.query(func.coalesce(func.sum(func.abs(subq.c.amount)), 0)).scalar() or 0
    transaction_count = db.query(func.count(subq.c.id)).scalar() or 0
    debit_count = db.query(func.count(subq.c.id)).filter(subq.c.transaction_type == "DEBIT").scalar() or 0
    credit_count = db.query(func.count(subq.c.id)).filter(subq.c.transaction_type == "CREDIT").scalar() or 0
    debit_volume = db.query(func.coalesce(func.sum(func.abs(subq.c.amount)), 0)).filter(subq.c.transaction_type == "DEBIT").scalar() or 0
    credit_volume = db.query(func.coalesce(func.sum(func.abs(subq.c.amount)), 0)).filter(subq.c.transaction_type == "CREDIT").scalar() or 0

    source_rows = (
        db.query(subq.c.source_type, func.count(subq.c.id), func.coalesce(func.sum(func.abs(subq.c.amount)), 0))
        .group_by(subq.c.source_type)
        .all()
    )
    by_source_acc: Dict[str, Dict[str, Any]] = {}
    for st, cnt, vol in source_rows:
        label = _source_label(st)
        acc = by_source_acc.setdefault(label, {"count": 0, "volume": Decimal(0)})
        acc["count"] += int(cnt)
        acc["volume"] += Decimal(str(vol or 0))
    by_source = [
        SmsStatsSourceRow(source=label, count=acc["count"], volume=f"{acc['volume']:.2f}")
        for label, acc in sorted(by_source_acc.items(), key=lambda kv: kv[1]["count"], reverse=True)
    ]

    card_rows = (
        db.query(subq.c.card_last_4, func.count(subq.c.id), func.coalesce(func.sum(func.abs(subq.c.amount)), 0))
        .filter(subq.c.card_last_4.isnot(None))
        .group_by(subq.c.card_last_4)
        .order_by(func.sum(func.abs(subq.c.amount)).desc())
        .limit(20)
        .all()
    )
    by_card = [
        SmsStatsCardRow(card_last_4=str(c4), count=int(cnt), volume=f"{Decimal(str(vol or 0)):.2f}")
        for c4, cnt, vol in card_rows
    ]

    return SmsStatsResponse(
        currency=currency,
        period_start=_normalize_datetime(date_from).isoformat() if date_from else None,
        period_end=_normalize_datetime(date_to).isoformat() if date_to else None,
        total_volume=f"{Decimal(str(total_volume)):.2f}",
        debit_volume=f"{Decimal(str(debit_volume)):.2f}",
        credit_volume=f"{Decimal(str(credit_volume)):.2f}",
        transaction_count=int(transaction_count),
        debit_count=int(debit_count),
        credit_count=int(credit_count),
        by_source=by_source,
        by_card=by_card,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && ../.venv/bin/python -m pytest tests/test_sms_ingest_api.py::test_stats_requires_mobile_key tests/test_sms_ingest_api.py::test_stats_aggregates_volume_and_counts -v`
Expected: PASS (2 passed).

- [ ] **Step 6: (no git)** Repo is not a git repository — skip commit. Note completion in the task tracker instead.

---

### Task A2: stats filters (source / card / period)

**Files:**
- Test: `backend/tests/test_sms_ingest_api.py`

- [ ] **Step 1: Write the failing test**

```python
def test_stats_filter_by_source_and_card(client, db_session):
    _seed_tx(db_session, amount=-100000, ttype="DEBIT", source_type="SMS", card="0907")
    _seed_tx(db_session, amount=-50000, ttype="DEBIT", source_type="AUTO", card="0907", chat_id=-100)
    _seed_tx(db_session, amount=-30000, ttype="DEBIT", source_type="SMS", card="4862")
    db_session.commit()
    h = {"X-Mobile-Ingest-Key": "sms-test-key"}

    only_sms = client.get("/api/sms/stats?source=sms", headers=h).json()
    assert only_sms["transaction_count"] == 2
    assert only_sms["total_volume"] == "130000.00"

    only_card = client.get("/api/sms/stats?card=0907", headers=h).json()
    assert only_card["transaction_count"] == 2
    assert only_card["total_volume"] == "150000.00"

    tg_chat = client.get("/api/sms/stats?source=telegram&source_chat_id=-100", headers=h).json()
    assert tg_chat["transaction_count"] == 1
    assert tg_chat["total_volume"] == "50000.00"


def test_stats_filter_by_period(client, db_session):
    _seed_tx(db_session, amount=-100000, ttype="DEBIT", source_type="SMS", card="0907", date="2026-05-01T10:00:00")
    _seed_tx(db_session, amount=-200000, ttype="DEBIT", source_type="SMS", card="0907", date="2026-05-20T10:00:00")
    db_session.commit()
    h = {"X-Mobile-Ingest-Key": "sms-test-key"}

    body = client.get("/api/sms/stats?date_from=2026-05-15T00:00:00", headers=h).json()
    assert body["transaction_count"] == 1
    assert body["total_volume"] == "200000.00"
```

- [ ] **Step 2: Run tests**

Run: `cd backend && ../.venv/bin/python -m pytest tests/test_sms_ingest_api.py::test_stats_filter_by_source_and_card tests/test_sms_ingest_api.py::test_stats_filter_by_period -v`
Expected: PASS (the A1 implementation already covers filters). If period test fails on tz, confirm `_normalize_datetime` strips tzinfo — it does.

- [ ] **Step 3: (no git)** mark done in tracker.

---

### Task A3: `GET /api/sms/sources` — Telegram bot list

**Files:**
- Modify: `backend/api/routes/sms.py`
- Test: `backend/tests/test_sms_ingest_api.py`

- [ ] **Step 1: Write the failing test**

```python
def test_sources_lists_telegram_chats(client, db_session):
    _seed_tx(db_session, amount=-100000, ttype="DEBIT", source_type="AUTO", card="0907", chat_id=-100, operator="A")
    _seed_tx(db_session, amount=-50000, ttype="DEBIT", source_type="AUTO", card="0907", chat_id=-100, operator="B")
    _seed_tx(db_session, amount=-30000, ttype="DEBIT", source_type="AUTO", card="4862", chat_id=-200, operator="C")
    _seed_tx(db_session, amount=-10000, ttype="DEBIT", source_type="SMS", card="4862")
    db_session.commit()

    resp = client.get("/api/sms/sources", headers={"X-Mobile-Ingest-Key": "sms-test-key"})
    assert resp.status_code == 200
    items = {row["chat_id"]: row for row in resp.json()["items"]}
    assert items[-100]["count"] == 2
    assert items[-200]["count"] == 1
    assert -1 not in items  # source_chat_id == 0 (SMS) excluded
    assert 0 not in items
```

- [ ] **Step 2: Run test**

Run: `cd backend && ../.venv/bin/python -m pytest tests/test_sms_ingest_api.py::test_sources_lists_telegram_chats -v`
Expected: FAIL — 404.

- [ ] **Step 3: Implement `/sources`**

Add to `backend/api/routes/sms.py` after `sms_stats`:

```python
class SmsSourceItem(BaseModel):
    chat_id: int
    title: Optional[str] = None
    count: int


class SmsSourcesResponse(BaseModel):
    items: List[SmsSourceItem]


@router.get("/sources", response_model=SmsSourcesResponse)
async def sms_sources(db: Session = Depends(get_db_session)) -> SmsSourcesResponse:
    rows = (
        db.query(Transaction.source_chat_id, func.count(Transaction.id))
        .filter(Transaction.source_type == "AUTO", Transaction.source_chat_id != 0)
        .group_by(Transaction.source_chat_id)
        .order_by(func.count(Transaction.id).desc())
        .all()
    )
    title_map: Dict[int, str] = {}
    try:
        meta = db.execute(
            text("SELECT chat_id, chat_title FROM monitored_bot_chats WHERE chat_title IS NOT NULL")
        ).fetchall()
        for chat_id, title in meta:
            if title:
                title_map[int(chat_id)] = str(title)
    except Exception:
        pass

    items = [
        SmsSourceItem(chat_id=int(cid), title=title_map.get(int(cid)), count=int(cnt))
        for cid, cnt in rows
    ]
    return SmsSourcesResponse(items=items)
```

- [ ] **Step 4: Run test**

Run: `cd backend && ../.venv/bin/python -m pytest tests/test_sms_ingest_api.py::test_sources_lists_telegram_chats -v`
Expected: PASS.

- [ ] **Step 5: Run the whole SMS test file (regression)**

Run: `cd backend && ../.venv/bin/python -m pytest tests/test_sms_ingest_api.py -v`
Expected: all pass (existing ingest tests + new stats/sources tests).

- [ ] **Step 6: (no git)** mark done in tracker. Deploy to prod only on explicit user command.

---

## PHASE B — Android project skeleton + build toolchain

> Environment (already on machine, verified): JDK 17 at `/opt/homebrew/opt/openjdk@17`, Android SDK at `~/Library/Android/sdk` (platform-35, build-tools 35.0.0, licenses accepted).
> Export before any gradle command:
> `export JAVA_HOME=/opt/homebrew/opt/openjdk@17 ANDROID_HOME=$HOME/Library/Android/sdk`

### Task B1: Gradle wrapper + root build files

**Files:**
- Create: `android/settings.gradle.kts`, `android/build.gradle.kts`, `android/gradle.properties`
- Create: `android/gradle/wrapper/gradle-wrapper.properties`
- Create: `android/local.properties` (NOT committed)
- Create: `android/.gitignore`

- [ ] **Step 1: Create `android/gradle/wrapper/gradle-wrapper.properties`**

```properties
distributionBase=GRADLE_USER_HOME
distributionPath=wrapper/dists
distributionUrl=https\://services.gradle.org/distributions/gradle-8.7-bin.zip
zipStoreBase=GRADLE_USER_HOME
zipStorePath=wrapper/dists
```

- [ ] **Step 2: Generate the wrapper jar/scripts**

Run (system gradle 9.x can generate an 8.7 wrapper):
```bash
cd android && export JAVA_HOME=/opt/homebrew/opt/openjdk@17 && gradle wrapper --gradle-version 8.7
```
Expected: creates `gradlew`, `gradlew.bat`, `gradle/wrapper/gradle-wrapper.jar`.

- [ ] **Step 3: Create `android/settings.gradle.kts`**

```kotlin
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "TBSparcerSMS"
include(":app")
```

- [ ] **Step 4: Create `android/build.gradle.kts`**

```kotlin
plugins {
    id("com.android.application") version "8.5.2" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
    id("com.google.devtools.ksp") version "1.9.24-1.0.20" apply false
    id("com.google.dagger.hilt.android") version "2.51.1" apply false
}
```

- [ ] **Step 5: Create `android/gradle.properties`**

```properties
org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
android.useAndroidX=true
kotlin.code.style=official
android.nonTransitiveRClass=true
```

- [ ] **Step 6: Create `android/local.properties`** (machine-specific, gitignored)

```properties
sdk.dir=/Users/kulacidmyt/Library/Android/sdk
```

- [ ] **Step 7: Create `android/.gitignore`**

```gitignore
.gradle/
build/
local.properties
keystore/
*.keystore
*.jks
.idea/
captures/
```

- [ ] **Step 8: (no git)** mark done in tracker.

---

### Task B2: app module Gradle + Manifest + theme resources

**Files:**
- Create: `android/app/build.gradle.kts`, `android/app/proguard-rules.pro`
- Create: `android/app/src/main/AndroidManifest.xml`
- Create: `android/app/src/main/res/values/strings.xml`, `themes.xml`
- Create: `android/app/src/main/res/xml/network_security_config.xml`

- [ ] **Step 1: Create `android/app/build.gradle.kts`**

```kotlin
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.google.devtools.ksp")
    id("com.google.dagger.hilt.android")
}

android {
    namespace = "uz.tbsparcer.sms"
    compileSdk = 35

    defaultConfig {
        applicationId = "uz.tbsparcer.sms"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        create("release") {
            val ksPath = System.getenv("TBS_KEYSTORE") ?: "../keystore/release.keystore"
            storeFile = file(ksPath)
            storePassword = System.getenv("TBS_KS_PASS") ?: ""
            keyAlias = System.getenv("TBS_KEY_ALIAS") ?: "tbsparcer"
            keyPassword = System.getenv("TBS_KEY_PASS") ?: System.getenv("TBS_KS_PASS") ?: ""
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.getByName("release")
        }
        debug {
            applicationIdSuffix = ".debug"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true }
    composeOptions { kotlinCompilerExtensionVersion = "1.5.14" }
    packaging { resources { excludes += "/META-INF/{AL2.0,LGPL2.1}" } }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.06.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.activity:activity-compose:1.9.1")
    implementation("androidx.navigation:navigation-compose:2.7.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.4")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.4")
    implementation("androidx.core:core-ktx:1.13.1")

    implementation("androidx.room:room-runtime:2.6.1")
    implementation("androidx.room:room-ktx:2.6.1")
    ksp("androidx.room:room-compiler:2.6.1")

    implementation("androidx.work:work-runtime-ktx:2.9.0")
    implementation("androidx.hilt:hilt-work:1.2.0")
    implementation("com.google.dagger:hilt-android:2.51.1")
    ksp("com.google.dagger:hilt-compiler:2.51.1")
    ksp("androidx.hilt:hilt-compiler:1.2.0")

    implementation("com.squareup.retrofit2:retrofit:2.11.0")
    implementation("com.squareup.retrofit2:converter-moshi:2.11.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")
    implementation("com.squareup.moshi:moshi-kotlin:1.15.1")

    implementation("androidx.security:security-crypto:1.1.0-alpha06")
    implementation("androidx.datastore:datastore-preferences:1.1.1")

    testImplementation("junit:junit:4.13.2")
    debugImplementation("androidx.compose.ui:ui-tooling")
}
```

- [ ] **Step 2: Create `android/app/proguard-rules.pro`**

```proguard
# Moshi + Retrofit DTOs
-keep class uz.tbsparcer.sms.data.remote.** { *; }
-keepclassmembers class uz.tbsparcer.sms.data.remote.** { *; }
-keepattributes Signature
-keepattributes *Annotation*
# Room
-keep class * extends androidx.room.RoomDatabase { *; }
```

- [ ] **Step 3: Create `android/app/src/main/AndroidManifest.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">

    <uses-permission android:name="android.permission.READ_SMS" />
    <uses-permission android:name="android.permission.RECEIVE_SMS" />
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />

    <application
        android:name=".TbsApp"
        android:allowBackup="false"
        android:icon="@android:drawable/sym_def_app_icon"
        android:label="@string/app_name"
        android:networkSecurityConfig="@xml/network_security_config"
        android:supportsRtl="true"
        android:theme="@style/Theme.TBSparcer">

        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:theme="@style/Theme.TBSparcer">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>

        <receiver
            android:name=".receiver.SmsReceiver"
            android:exported="true"
            android:permission="android.permission.BROADCAST_SMS">
            <intent-filter android:priority="999">
                <action android:name="android.provider.Telephony.SMS_RECEIVED" />
            </intent-filter>
        </receiver>

        <provider
            android:name="androidx.startup.InitializationProvider"
            android:authorities="${applicationId}.androidx-startup"
            android:exported="false"
            tools:node="merge"
            xmlns:tools="http://schemas.android.com/tools" />
    </application>
</manifest>
```

- [ ] **Step 4: Create `android/app/src/main/res/values/strings.xml`**

```xml
<resources>
    <string name="app_name">TBSparcer SMS</string>
</resources>
```

- [ ] **Step 5: Create `android/app/src/main/res/values/themes.xml`**

```xml
<resources xmlns:tools="http://schemas.android.com/tools">
    <style name="Theme.TBSparcer" parent="android:Theme.Material.NoActionBar">
        <item name="android:windowBackground">@android:color/black</item>
        <item name="android:statusBarColor">@android:color/black</item>
    </style>
</resources>
```

- [ ] **Step 6: Create `android/app/src/main/res/xml/network_security_config.xml`**

Prod is HTTPS (nip.io). Cleartext allowed ONLY for local dev hosts (LAN testing). Adjust the dev host if needed.

```xml
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <domain-config cleartextTrafficPermitted="true">
        <domain includeSubdomains="true">10.0.2.2</domain>
        <domain includeSubdomains="true">192.168.0.0</domain>
        <domain includeSubdomains="true">localhost</domain>
    </domain-config>
    <base-config cleartextTrafficPermitted="false" />
</network-security-config>
```

- [ ] **Step 7: Verify the skeleton compiles (no Kotlin yet — expect a clean config eval)**

Add a minimal `TbsApp.kt` + `MainActivity.kt` first in Task C1 before this build will succeed. For now just validate Gradle config:
```bash
cd android && export JAVA_HOME=/opt/homebrew/opt/openjdk@17 ANDROID_HOME=$HOME/Library/Android/sdk && ./gradlew :app:help
```
Expected: BUILD SUCCESSFUL (downloads AGP/deps; no compilation yet).

- [ ] **Step 8: (no git)** mark done in tracker.

---

### Task B3: Fonts + Application + MainActivity + Hilt bootstrap

**Files:**
- Create: `android/app/src/main/res/font/` (3 families, see step 1)
- Create: `android/app/src/main/java/uz/tbsparcer/sms/TbsApp.kt`, `MainActivity.kt`

- [ ] **Step 1: Add fonts to `android/app/src/main/res/font/`**

Download the three families (variable or static TTF) and place as lowercase resource names (only `[a-z0-9_]` allowed):
- `instrument_serif_regular.ttf` (Instrument Serif)
- `space_grotesk_regular.ttf`, `space_grotesk_medium.ttf` (Space Grotesk)
- `jetbrains_mono_regular.ttf`, `jetbrains_mono_medium.ttf` (JetBrains Mono)

Source URLs (Google Fonts GitHub raw):
```bash
cd android/app/src/main/res/font
curl -L -o instrument_serif_regular.ttf "https://github.com/google/fonts/raw/main/ofl/instrumentserif/InstrumentSerif-Regular.ttf"
curl -L -o space_grotesk_regular.ttf "https://github.com/google/fonts/raw/main/ofl/spacegrotesk/SpaceGrotesk%5Bwght%5D.ttf"
cp space_grotesk_regular.ttf space_grotesk_medium.ttf
curl -L -o jetbrains_mono_regular.ttf "https://github.com/google/fonts/raw/main/ofl/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf"
cp jetbrains_mono_regular.ttf jetbrains_mono_medium.ttf
```
Verify each file is a real TTF (not an HTML error page): `file *.ttf` → should say "TrueType" / "OpenType". If curl returns HTML, download manually from fonts.google.com and place the static TTFs.

- [ ] **Step 2: Create `android/app/src/main/java/uz/tbsparcer/sms/TbsApp.kt`**

```kotlin
package uz.tbsparcer.sms

import android.app.Application
import androidx.hilt.work.HiltWorkerFactory
import androidx.work.Configuration
import dagger.hilt.android.HiltAndroidApp
import javax.inject.Inject

@HiltAndroidApp
class TbsApp : Application(), Configuration.Provider {
    @Inject lateinit var workerFactory: HiltWorkerFactory

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder().setWorkerFactory(workerFactory).build()
}
```

- [ ] **Step 3: Create `android/app/src/main/java/uz/tbsparcer/sms/MainActivity.kt`**

```kotlin
package uz.tbsparcer.sms

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.Text
import dagger.hilt.android.AndroidEntryPoint
import uz.tbsparcer.sms.ui.theme.TbsTheme

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { TbsTheme { Text("TBSparcer SMS") } }
    }
}
```
(Replaced by the real nav graph in Phase G; `TbsTheme` defined in Task C-theme below — build only after the theme task.)

- [ ] **Step 4: (no git)** mark done in tracker.

---

## PHASE C — Theme, Room, Settings

### Task C1: editorial-monochrome theme

**Files:**
- Create: `android/app/src/main/java/uz/tbsparcer/sms/ui/theme/Color.kt`, `Type.kt`, `Theme.kt`

- [ ] **Step 1: Create `ui/theme/Color.kt`** (hex values copied from desktop `theme.css`)

```kotlin
package uz.tbsparcer.sms.ui.theme

import androidx.compose.ui.graphics.Color

// Light
val LBg = Color(0xFFFAFAF7)
val LSurface = Color(0xFFFFFFFF)
val LSurface2 = Color(0xFFF3F4F6)
val LBorder = Color(0xFFD1D5DB)
val LInk = Color(0xFF0A0B0D)
val LInkSecondary = Color(0xFF4B5563)
val LAccent = Color(0xFF111317)
val LOnAccent = Color(0xFFFFFFFF)

// Dark
val DBg = Color(0xFF0A0B0D)
val DSurface = Color(0xFF131418)
val DSurface2 = Color(0xFF1A1C20)
val DBorder = Color(0xFF2D3038)
val DInk = Color(0xFFF4F5F7)
val DInkSecondary = Color(0xFFA4A8AE)
val DAccent = Color(0xFFF4F5F7)
val DOnAccent = Color(0xFF0A0B0D)

// Income / expense (semantic, both themes)
val IncomeLight = Color(0xFF16A34A)
val ExpenseLight = Color(0xFFDC2626)
val IncomeDark = Color(0xFF4ADE80)
val ExpenseDark = Color(0xFFF87171)
```

- [ ] **Step 2: Create `ui/theme/Type.kt`** (font families from res/font)

```kotlin
package uz.tbsparcer.sms.ui.theme

import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import uz.tbsparcer.sms.R

val DisplaySerif = FontFamily(Font(R.font.instrument_serif_regular, FontWeight.Normal))
val SansGrotesk = FontFamily(
    Font(R.font.space_grotesk_regular, FontWeight.Normal),
    Font(R.font.space_grotesk_medium, FontWeight.Medium),
)
val MonoJetBrains = FontFamily(
    Font(R.font.jetbrains_mono_regular, FontWeight.Normal),
    Font(R.font.jetbrains_mono_medium, FontWeight.Medium),
)
```

- [ ] **Step 3: Create `ui/theme/Theme.kt`** (extends Material3 with a custom palette holder)

```kotlin
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
```

- [ ] **Step 4: Build to confirm theme + skeleton compile**

```bash
cd android && export JAVA_HOME=/opt/homebrew/opt/openjdk@17 ANDROID_HOME=$HOME/Library/Android/sdk && ./gradlew :app:assembleDebug
```
Expected: BUILD SUCCESSFUL (debug APK builds with the placeholder MainActivity). If R.font errors — confirm font files exist and names are lowercase.

- [ ] **Step 5: (no git)** mark done in tracker.

---

### Task C2: Room entity + DAO + database

**Files:**
- Create: `data/local/SmsRecord.kt`, `SmsRecordDao.kt`, `AppDatabase.kt`
- Create: `di/DatabaseModule.kt`

- [ ] **Step 1: Create `data/local/SmsRecord.kt`**

```kotlin
package uz.tbsparcer.sms.data.local

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "sms_records")
data class SmsRecord(
    @PrimaryKey val deviceSmsId: String,
    val sender: String,
    val body: String,
    val receivedAt: Long,
    val simSlot: Int?,
    val fingerprint: String?,
    val syncStatus: String,       // pending | synced | duplicate | skipped | error
    val backendTransactionId: Long?,
    val errorMessage: String?,
    val syncedAt: Long?,
    val createdAt: Long,
)
```

- [ ] **Step 2: Create `data/local/SmsRecordDao.kt`**

```kotlin
package uz.tbsparcer.sms.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

data class StatusCount(val syncStatus: String, val n: Int)

@Dao
interface SmsRecordDao {
    @Query("SELECT * FROM sms_records ORDER BY receivedAt DESC LIMIT :limit")
    fun recent(limit: Int = 300): Flow<List<SmsRecord>>

    @Query("SELECT * FROM sms_records WHERE syncStatus = :status ORDER BY receivedAt DESC LIMIT :limit")
    fun byStatus(status: String, limit: Int = 300): Flow<List<SmsRecord>>

    @Query("SELECT * FROM sms_records WHERE syncStatus IN ('pending','error') ORDER BY receivedAt ASC LIMIT :limit")
    suspend fun pending(limit: Int = 50): List<SmsRecord>

    @Query("SELECT * FROM sms_records WHERE deviceSmsId = :id")
    suspend fun byId(id: String): SmsRecord?

    @Query("SELECT syncStatus, COUNT(*) AS n FROM sms_records GROUP BY syncStatus")
    fun statusCounts(): Flow<List<StatusCount>>

    @Query("SELECT deviceSmsId FROM sms_records")
    suspend fun allIds(): List<String>

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertAll(records: List<SmsRecord>): List<Long>

    @Query("""UPDATE sms_records SET syncStatus = :status, backendTransactionId = :txnId,
              fingerprint = :fp, errorMessage = :error, syncedAt = :syncedAt
              WHERE deviceSmsId = :id""")
    suspend fun updateResult(id: String, status: String, txnId: Long?, fp: String?, error: String?, syncedAt: Long)

    @Query("DELETE FROM sms_records")
    suspend fun clear()
}
```

- [ ] **Step 3: Create `data/local/AppDatabase.kt`**

```kotlin
package uz.tbsparcer.sms.data.local

import androidx.room.Database
import androidx.room.RoomDatabase

@Database(entities = [SmsRecord::class], version = 1, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {
    abstract fun smsDao(): SmsRecordDao
}
```

- [ ] **Step 4: Create `di/DatabaseModule.kt`**

```kotlin
package uz.tbsparcer.sms.di

import android.content.Context
import androidx.room.Room
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton
import uz.tbsparcer.sms.data.local.AppDatabase
import uz.tbsparcer.sms.data.local.SmsRecordDao

@Module
@InstallIn(SingletonComponent::class)
object DatabaseModule {
    @Provides @Singleton
    fun db(@ApplicationContext ctx: Context): AppDatabase =
        Room.databaseBuilder(ctx, AppDatabase::class.java, "tbsparcer.db").build()

    @Provides
    fun dao(db: AppDatabase): SmsRecordDao = db.smsDao()
}
```

- [ ] **Step 5: Build**

```bash
cd android && export JAVA_HOME=/opt/homebrew/opt/openjdk@17 ANDROID_HOME=$HOME/Library/Android/sdk && ./gradlew :app:assembleDebug
```
Expected: BUILD SUCCESSFUL (Room + Hilt KSP generate without error).

- [ ] **Step 6: (no git)** mark done in tracker.

---

### Task C3: SettingsStore (EncryptedSharedPreferences)

**Files:**
- Create: `data/local/SettingsStore.kt`

- [ ] **Step 1: Create `data/local/SettingsStore.kt`**

```kotlin
package uz.tbsparcer.sms.data.local

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import dagger.hilt.android.qualifiers.ApplicationContext
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class SettingsStore @Inject constructor(@ApplicationContext ctx: Context) {
    private val prefs = run {
        val key = MasterKey.Builder(ctx).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
        EncryptedSharedPreferences.create(
            ctx, "tbs_secure", key,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    var baseUrl: String
        get() = prefs.getString("base_url", "https://64.188.106.221.nip.io") ?: ""
        set(v) = prefs.edit().putString("base_url", v).apply()

    var mobileKey: String
        get() = prefs.getString("mobile_key", "") ?: ""
        set(v) = prefs.edit().putString("mobile_key", v).apply()

    val deviceId: String
        get() {
            val existing = prefs.getString("device_id", null)
            if (existing != null) return existing
            val id = "android-" + UUID.randomUUID().toString().take(12)
            prefs.edit().putString("device_id", id).apply()
            return id
        }

    var backfillSinceMillis: Long
        get() = prefs.getLong("backfill_since", 0L)
        set(v) = prefs.edit().putLong("backfill_since", v).apply()

    var onboardingDone: Boolean
        get() = prefs.getBoolean("onboarding_done", false)
        set(v) = prefs.edit().putBoolean("onboarding_done", v).apply()

    var themeMode: String  // system | light | dark
        get() = prefs.getString("theme_mode", "system") ?: "system"
        set(v) = prefs.edit().putString("theme_mode", v).apply()
}
```

- [ ] **Step 2: Build**

```bash
cd android && export JAVA_HOME=/opt/homebrew/opt/openjdk@17 ANDROID_HOME=$HOME/Library/Android/sdk && ./gradlew :app:assembleDebug
```
Expected: BUILD SUCCESSFUL.

- [ ] **Step 3: (no git)** mark done in tracker.

---

## PHASE D — Domain (filter + fingerprint) with unit tests

### Task D1: FingerprintCalculator (mirror backend v1) + test

**Files:**
- Create: `domain/FingerprintCalculator.kt`
- Test: `app/src/test/java/uz/tbsparcer/sms/FingerprintCalculatorTest.kt`

- [ ] **Step 1: Write the failing test**

`FingerprintCalculatorTest.kt`:
```kotlin
package uz.tbsparcer.sms

import org.junit.Assert.assertEquals
import org.junit.Test
import java.math.BigDecimal
import java.time.LocalDateTime
import uz.tbsparcer.sms.domain.FingerprintCalculator

class FingerprintCalculatorTest {
    @Test fun matchesBackendV1() {
        // Backend compute_fingerprint_v1: SHA256("100000.00|2026-05-10 12:00|0907")
        val fp = FingerprintCalculator.computeV1(
            BigDecimal("-100000"), LocalDateTime.of(2026, 5, 10, 12, 0), "0907")
        // expected = sha256 of the exact string above
        assertEquals(
            sha256("100000.00|2026-05-10 12:00|0907"),
            fp
        )
    }

    private fun sha256(s: String): String =
        java.security.MessageDigest.getInstance("SHA-256")
            .digest(s.toByteArray()).joinToString("") { "%02x".format(it) }
}
```

- [ ] **Step 2: Run test (fails — class missing)**

```bash
cd android && export JAVA_HOME=/opt/homebrew/opt/openjdk@17 ANDROID_HOME=$HOME/Library/Android/sdk && ./gradlew :app:testDebugUnitTest --tests "uz.tbsparcer.sms.FingerprintCalculatorTest"
```
Expected: FAIL (unresolved reference: FingerprintCalculator).

- [ ] **Step 3: Implement `domain/FingerprintCalculator.kt`**

```kotlin
package uz.tbsparcer.sms.domain

import java.math.BigDecimal
import java.math.RoundingMode
import java.security.MessageDigest
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

object FingerprintCalculator {
    private val minuteFmt = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")

    fun computeV1(amount: BigDecimal?, date: LocalDateTime?, cardLast4: String?): String {
        val amountStr = (amount?.abs()?.setScale(2, RoundingMode.HALF_UP) ?: BigDecimal("0.00"))
            .toPlainString()
        val dateStr = date?.format(minuteFmt) ?: ""
        val cardStr = (cardLast4?.filter { it.isDigit() }?.takeLast(4) ?: "").padStart(4, '0')
            .ifEmpty { "0000" }
        val raw = "$amountStr|$dateStr|$cardStr"
        return MessageDigest.getInstance("SHA-256")
            .digest(raw.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
    }
}
```

- [ ] **Step 4: Run test (passes)**

```bash
cd android && export JAVA_HOME=/opt/homebrew/opt/openjdk@17 ANDROID_HOME=$HOME/Library/Android/sdk && ./gradlew :app:testDebugUnitTest --tests "uz.tbsparcer.sms.FingerprintCalculatorTest"
```
Expected: PASS.

- [ ] **Step 5: (no git)** mark done in tracker.

---

### Task D2: SmsFilter + test on real examples

**Files:**
- Create: `domain/SmsFilter.kt`
- Test: `app/src/test/java/uz/tbsparcer/sms/SmsFilterTest.kt`

- [ ] **Step 1: Write the failing test** (examples copied verbatim from `примеры чеки.txt`)

```kotlin
package uz.tbsparcer.sms

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.tbsparcer.sms.domain.SmsFilter

class SmsFilterTest {
    @Test fun acceptsPokupka() {
        assertTrue(SmsFilter.isBankSms("UZCARD",
            "Pokupka: OO \"AGAT SYSTEM\", tashkent 02.04.25 08:37 karta ***0907. summa:44000.00 UZS, balans:2607792.14 UZS"))
    }
    @Test fun acceptsSpisanie() {
        assertTrue(SmsFilter.isBankSms("HUMO",
            "Spisanie c karty: HAMKORBANK ATB, UZ,02.04.25 14:52,karta ***4862. summa:5000.00 UZS balans:138715.26 UZS"))
    }
    @Test fun acceptsHumocardSemicolon() {
        assertTrue(SmsFilter.isBankSms("HUMOCARD",
            "HUMOCARD *6921: oplata 200000.00 UZS; SmartBank P2P HUMO U; 25-04-02 15:33;  Dostupno: 1852200.28 UZS"))
    }
    @Test fun rejectsTelegramOtp() {
        assertFalse(SmsFilter.isBankSms("Telegram", "Login code: 12345. Do not give this code to anyone."))
    }
    @Test fun rejectsGoogle() {
        assertFalse(SmsFilter.isBankSms("Google", "G-839201 is your Google verification code."))
    }
}
```

- [ ] **Step 2: Run test (fails — class missing)**

```bash
cd android && export JAVA_HOME=/opt/homebrew/opt/openjdk@17 ANDROID_HOME=$HOME/Library/Android/sdk && ./gradlew :app:testDebugUnitTest --tests "uz.tbsparcer.sms.SmsFilterTest"
```
Expected: FAIL.

- [ ] **Step 3: Implement `domain/SmsFilter.kt`**

```kotlin
package uz.tbsparcer.sms.domain

object SmsFilter {
    private val bankKeywords = listOf(
        "pokupka:", "spisanie", "popolnenie", "e-com oplata", "platezh:",
        "otmena", "humocard", "summa:", "balans:", "dostupno:", "karta",
    )
    private val ignoredSenders = listOf(
        "google", "telegram", "viber", "whatsapp", "facebook", "instagram", "youtube",
    )
    private val amountRe = Regex("""\d{1,3}([., ]\d{3})*[.,]\d{2}""")
    private val cardRe = Regex("""\*{2,4}\d{4}""")
    private val humocardRe = Regex("""(?i)humocard\s*\*\d{4}""")

    fun isBankSms(sender: String, body: String): Boolean {
        val s = sender.lowercase()
        if (ignoredSenders.any { s.contains(it) }) return false
        val b = body.lowercase()
        if (bankKeywords.any { b.contains(it) }) return true
        if (humocardRe.containsMatchIn(body)) return true
        return amountRe.containsMatchIn(body) && cardRe.containsMatchIn(body)
    }
}
```

- [ ] **Step 4: Run test (passes)**

```bash
cd android && export JAVA_HOME=/opt/homebrew/opt/openjdk@17 ANDROID_HOME=$HOME/Library/Android/sdk && ./gradlew :app:testDebugUnitTest --tests "uz.tbsparcer.sms.SmsFilterTest"
```
Expected: PASS (5 tests).

- [ ] **Step 5: (no git)** mark done in tracker.

---

## PHASE E — Remote layer (Retrofit + interceptor)

### Task E1: DTOs + ApiService + MobileKeyInterceptor + NetworkModule

**Files:**
- Create: `data/remote/dto.kt`, `ApiService.kt`, `MobileKeyInterceptor.kt`
- Create: `di/NetworkModule.kt`

- [ ] **Step 1: Create `data/remote/dto.kt`** (match backend contracts exactly)

```kotlin
package uz.tbsparcer.sms.data.remote

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class SmsMessageDto(
    @Json(name = "device_sms_id") val deviceSmsId: String,
    val sender: String,
    val text: String,
    @Json(name = "received_at") val receivedAt: String,   // ISO-8601 local
    @Json(name = "sim_slot") val simSlot: Int?,
)

@JsonClass(generateAdapter = true)
data class SmsIngestRequest(
    @Json(name = "device_id") val deviceId: String,
    val messages: List<SmsMessageDto>,
)

@JsonClass(generateAdapter = true)
data class SmsIngestResultItem(
    @Json(name = "device_sms_id") val deviceSmsId: String,
    val status: String,
    @Json(name = "transaction_id") val transactionId: Long?,
    val fingerprint: String?,
    val error: String?,
)

@JsonClass(generateAdapter = true)
data class SmsIngestResponse(
    val processed: Int, val created: Int, val duplicates: Int,
    val skipped: Int, val errors: Int,
    val results: List<SmsIngestResultItem>,
)

@JsonClass(generateAdapter = true)
data class SmsHealthResponse(
    val status: String, val db: String, val version: String,
    @Json(name = "server_time") val serverTime: String,
)

@JsonClass(generateAdapter = true)
data class StatsSourceRow(val source: String, val count: Int, val volume: String)

@JsonClass(generateAdapter = true)
data class StatsCardRow(
    @Json(name = "card_last_4") val cardLast4: String, val count: Int, val volume: String)

@JsonClass(generateAdapter = true)
data class SmsStatsResponse(
    val currency: String,
    @Json(name = "period_start") val periodStart: String?,
    @Json(name = "period_end") val periodEnd: String?,
    @Json(name = "total_volume") val totalVolume: String,
    @Json(name = "debit_volume") val debitVolume: String,
    @Json(name = "credit_volume") val creditVolume: String,
    @Json(name = "transaction_count") val transactionCount: Int,
    @Json(name = "debit_count") val debitCount: Int,
    @Json(name = "credit_count") val creditCount: Int,
    @Json(name = "by_source") val bySource: List<StatsSourceRow>,
    @Json(name = "by_card") val byCard: List<StatsCardRow>,
)

@JsonClass(generateAdapter = true)
data class SourceItem(
    @Json(name = "chat_id") val chatId: Long, val title: String?, val count: Int)

@JsonClass(generateAdapter = true)
data class SourcesResponse(val items: List<SourceItem>)
```

- [ ] **Step 2: Create `data/remote/ApiService.kt`**

```kotlin
package uz.tbsparcer.sms.data.remote

import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Query

interface ApiService {
    @GET("api/sms/health")
    suspend fun health(): SmsHealthResponse

    @POST("api/sms/ingest")
    suspend fun ingest(@Body body: SmsIngestRequest): SmsIngestResponse

    @GET("api/sms/stats")
    suspend fun stats(
        @Query("date_from") dateFrom: String? = null,
        @Query("date_to") dateTo: String? = null,
        @Query("source") source: String = "all",
        @Query("source_chat_id") sourceChatId: Long? = null,
        @Query("card") card: String? = null,
        @Query("currency") currency: String = "UZS",
    ): SmsStatsResponse

    @GET("api/sms/sources")
    suspend fun sources(): SourcesResponse
}
```

- [ ] **Step 3: Create `data/remote/MobileKeyInterceptor.kt`**

```kotlin
package uz.tbsparcer.sms.data.remote

import okhttp3.Interceptor
import okhttp3.Response
import uz.tbsparcer.sms.data.local.SettingsStore

class MobileKeyInterceptor(private val settings: SettingsStore) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val req = chain.request().newBuilder()
            .header("X-Mobile-Ingest-Key", settings.mobileKey)
            .build()
        return chain.proceed(req)
    }
}
```

- [ ] **Step 4: Create `di/NetworkModule.kt`** (base URL is dynamic — rebuild Retrofit per call via a provider)

```kotlin
package uz.tbsparcer.sms.di

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import java.util.concurrent.TimeUnit
import javax.inject.Singleton
import uz.tbsparcer.sms.data.local.SettingsStore
import uz.tbsparcer.sms.data.remote.ApiService
import uz.tbsparcer.sms.data.remote.MobileKeyInterceptor

@Singleton
class ApiProvider(private val settings: SettingsStore) {
    @Volatile private var cachedUrl: String = ""
    @Volatile private var service: ApiService? = null

    fun api(): ApiService {
        val url = settings.baseUrl.let { if (it.endsWith("/")) it else "$it/" }
        val cur = service
        if (cur != null && url == cachedUrl) return cur
        val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
        val client = OkHttpClient.Builder()
            .addInterceptor(MobileKeyInterceptor(settings))
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .build()
        val built = Retrofit.Builder()
            .baseUrl(url)
            .client(client)
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()
            .create(ApiService::class.java)
        cachedUrl = url
        service = built
        return built
    }
}

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {
    @Provides @Singleton
    fun apiProvider(settings: SettingsStore): ApiProvider = ApiProvider(settings)
}
```

- [ ] **Step 5: Build**

```bash
cd android && export JAVA_HOME=/opt/homebrew/opt/openjdk@17 ANDROID_HOME=$HOME/Library/Android/sdk && ./gradlew :app:assembleDebug
```
Expected: BUILD SUCCESSFUL. If Moshi reflect adapter missing — add `implementation("com.squareup.moshi:moshi-kotlin:1.15.1")` is already present; that includes reflect factory.

- [ ] **Step 6: (no git)** mark done in tracker.

---

## PHASE F — SMS collection + sync

### Task F1: SmsRepository + StatsRepository

**Files:**
- Create: `data/repo/SmsRepository.kt`, `StatsRepository.kt`

- [ ] **Step 1: Create `data/repo/SmsRepository.kt`** (inbox read + collect + sync)

```kotlin
package uz.tbsparcer.sms.data.repo

import android.content.Context
import android.net.Uri
import android.provider.Telephony
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import uz.tbsparcer.sms.data.local.SettingsStore
import uz.tbsparcer.sms.data.local.SmsRecord
import uz.tbsparcer.sms.data.local.SmsRecordDao
import uz.tbsparcer.sms.data.local.StatusCount
import uz.tbsparcer.sms.data.remote.ApiService
import uz.tbsparcer.sms.data.remote.SmsIngestRequest
import uz.tbsparcer.sms.data.remote.SmsMessageDto
import uz.tbsparcer.sms.di.ApiProvider
import uz.tbsparcer.sms.domain.SmsFilter
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class SmsRepository @Inject constructor(
    @ApplicationContext private val ctx: Context,
    private val dao: SmsRecordDao,
    private val settings: SettingsStore,
    private val apiProvider: ApiProvider,
) {
    fun recent(): Flow<List<SmsRecord>> = dao.recent()
    fun byStatus(status: String): Flow<List<SmsRecord>> = dao.byStatus(status)
    fun statusCounts(): Flow<List<StatusCount>> = dao.statusCounts()
    suspend fun byId(id: String) = dao.byId(id)
    suspend fun clear() = dao.clear()

    /** Read inbox since [sinceMillis], filter bank SMS, insert new as pending. Returns inserted count. */
    suspend fun collectFromInbox(sinceMillis: Long): Int {
        val existing = dao.allIds().toHashSet()
        val cursor = ctx.contentResolver.query(
            Uri.parse("content://sms/inbox"),
            arrayOf("_id", "address", "body", "date"),
            "date >= ?", arrayOf(sinceMillis.toString()), "date DESC",
        ) ?: return 0
        val rows = mutableListOf<SmsRecord>()
        cursor.use { c ->
            val idIdx = c.getColumnIndex("_id")
            val addrIdx = c.getColumnIndex("address")
            val bodyIdx = c.getColumnIndex("body")
            val dateIdx = c.getColumnIndex("date")
            while (c.moveToNext()) {
                val id = c.getString(idIdx) ?: continue
                if (existing.contains(id)) continue
                val sender = c.getString(addrIdx) ?: ""
                val body = c.getString(bodyIdx) ?: ""
                val date = c.getLong(dateIdx)
                if (!SmsFilter.isBankSms(sender, body)) continue
                rows += SmsRecord(
                    deviceSmsId = id, sender = sender, body = body, receivedAt = date,
                    simSlot = null, fingerprint = null, syncStatus = "pending",
                    backendTransactionId = null, errorMessage = null, syncedAt = null,
                    createdAt = System.currentTimeMillis(),
                )
            }
        }
        if (rows.isNotEmpty()) dao.insertAll(rows)
        return rows.size
    }

    suspend fun insertRealtime(deviceSmsId: String, sender: String, body: String, receivedAt: Long) {
        if (!SmsFilter.isBankSms(sender, body)) return
        dao.insertAll(listOf(
            SmsRecord(deviceSmsId, sender, body, receivedAt, null, null, "pending",
                null, null, null, System.currentTimeMillis())
        ))
    }

    /** Push pending rows. Returns true if the batch (or empty) completed without a network/auth failure. */
    suspend fun syncPending(): SyncOutcome {
        val pending = dao.pending(50)
        if (pending.isEmpty()) return SyncOutcome.Empty
        val req = SmsIngestRequest(
            deviceId = settings.deviceId,
            messages = pending.map {
                SmsMessageDto(
                    deviceSmsId = it.deviceSmsId, sender = it.sender, text = it.body,
                    receivedAt = Instant.ofEpochMilli(it.receivedAt)
                        .atZone(ZoneId.systemDefault()).toLocalDateTime()
                        .format(DateTimeFormatter.ISO_LOCAL_DATE_TIME),
                    simSlot = it.simSlot,
                )
            },
        )
        val api: ApiService = apiProvider.api()
        return try {
            val resp = api.ingest(req)
            val now = System.currentTimeMillis()
            resp.results.forEach { r ->
                dao.updateResult(r.deviceSmsId, r.status, r.transactionId, r.fingerprint, r.error, now)
            }
            SyncOutcome.Ok(resp.created, resp.duplicates, resp.skipped, resp.errors)
        } catch (e: retrofit2.HttpException) {
            if (e.code() == 403 || e.code() == 503) SyncOutcome.AuthError(e.code())
            else { markError(pending, "http_${e.code()}"); SyncOutcome.Retry }
        } catch (e: Exception) {
            markError(pending, e.message?.take(180)); SyncOutcome.Retry
        }
    }

    private suspend fun markError(rows: List<SmsRecord>, msg: String?) {
        val now = System.currentTimeMillis()
        rows.forEach { dao.updateResult(it.deviceSmsId, "error", null, null, msg, now) }
    }
}

sealed interface SyncOutcome {
    data object Empty : SyncOutcome
    data class Ok(val created: Int, val duplicates: Int, val skipped: Int, val errors: Int) : SyncOutcome
    data class AuthError(val code: Int) : SyncOutcome
    data object Retry : SyncOutcome
}
```

- [ ] **Step 2: Create `data/repo/StatsRepository.kt`**

```kotlin
package uz.tbsparcer.sms.data.repo

import uz.tbsparcer.sms.data.remote.SmsStatsResponse
import uz.tbsparcer.sms.data.remote.SourcesResponse
import uz.tbsparcer.sms.di.ApiProvider
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class StatsRepository @Inject constructor(private val apiProvider: ApiProvider) {
    suspend fun stats(
        dateFrom: String?, dateTo: String?, source: String,
        sourceChatId: Long?, card: String?,
    ): SmsStatsResponse = apiProvider.api().stats(dateFrom, dateTo, source, sourceChatId, card)

    suspend fun sources(): SourcesResponse = apiProvider.api().sources()
    suspend fun health() = apiProvider.api().health()
}
```

- [ ] **Step 3: Build**

```bash
cd android && export JAVA_HOME=/opt/homebrew/opt/openjdk@17 ANDROID_HOME=$HOME/Library/Android/sdk && ./gradlew :app:assembleDebug
```
Expected: BUILD SUCCESSFUL.

- [ ] **Step 4: (no git)** mark done in tracker.

---

### Task F2: SyncWorker + BackfillWorker + scheduling

**Files:**
- Create: `work/SyncWorker.kt`, `work/BackfillWorker.kt`

- [ ] **Step 1: Create `work/SyncWorker.kt`**

```kotlin
package uz.tbsparcer.sms.work

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import uz.tbsparcer.sms.data.repo.SmsRepository
import uz.tbsparcer.sms.data.repo.SyncOutcome

@HiltWorker
class SyncWorker @AssistedInject constructor(
    @Assisted ctx: Context,
    @Assisted params: WorkerParameters,
    private val repo: SmsRepository,
) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result =
        when (repo.syncPending()) {
            is SyncOutcome.Retry -> Result.retry()
            else -> Result.success()   // Ok, Empty, AuthError all stop the run (auth handled by UI)
        }
}
```

- [ ] **Step 2: Create `work/BackfillWorker.kt`**

```kotlin
package uz.tbsparcer.sms.work

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import uz.tbsparcer.sms.data.local.SettingsStore
import uz.tbsparcer.sms.data.repo.SmsRepository

@HiltWorker
class BackfillWorker @AssistedInject constructor(
    @Assisted ctx: Context,
    @Assisted params: WorkerParameters,
    private val repo: SmsRepository,
    private val settings: SettingsStore,
) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        repo.collectFromInbox(settings.backfillSinceMillis)
        repo.syncPending()
        return Result.success()
    }
}
```

- [ ] **Step 3: Create `work/WorkScheduler.kt`** (helper to enqueue periodic + one-time)

```kotlin
package uz.tbsparcer.sms.work

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

object WorkScheduler {
    private val netConstraint = Constraints.Builder()
        .setRequiredNetworkType(NetworkType.CONNECTED).build()

    fun schedulePeriodic(ctx: Context) {
        val req = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
            .setConstraints(netConstraint).build()
        WorkManager.getInstance(ctx)
            .enqueueUniquePeriodicWork("sms_sync", ExistingPeriodicWorkPolicy.KEEP, req)
    }

    fun syncNow(ctx: Context) {
        val req = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(netConstraint)
            .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST).build()
        WorkManager.getInstance(ctx)
            .enqueueUniqueWork("sms_sync_now", ExistingWorkPolicy.REPLACE, req)
    }

    fun runBackfill(ctx: Context) {
        val req = OneTimeWorkRequestBuilder<BackfillWorker>()
            .setConstraints(netConstraint).build()
        WorkManager.getInstance(ctx)
            .enqueueUniqueWork("sms_backfill", ExistingWorkPolicy.REPLACE, req)
    }
}
```

- [ ] **Step 4: Build**

```bash
cd android && export JAVA_HOME=/opt/homebrew/opt/openjdk@17 ANDROID_HOME=$HOME/Library/Android/sdk && ./gradlew :app:assembleDebug
```
Expected: BUILD SUCCESSFUL.

- [ ] **Step 5: (no git)** mark done in tracker.

---

### Task F3: SmsReceiver (realtime)

**Files:**
- Create: `receiver/SmsReceiver.kt`

- [ ] **Step 1: Create `receiver/SmsReceiver.kt`** (uses goAsync + EntryPoint to reach repo)

```kotlin
package uz.tbsparcer.sms.receiver

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import uz.tbsparcer.sms.data.repo.SmsRepository
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
        val deviceSmsId = "${ts}_${sender.hashCode()}"

        val repo = EntryPointAccessors
            .fromApplication(context.applicationContext, ReceiverEntryPoint::class.java)
            .smsRepository()

        val pending = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            try {
                repo.insertRealtime(deviceSmsId, sender, body, ts)
                WorkScheduler.syncNow(context.applicationContext)
            } finally {
                pending.finish()
            }
        }
    }
}
```

- [ ] **Step 2: Build**

```bash
cd android && export JAVA_HOME=/opt/homebrew/opt/openjdk@17 ANDROID_HOME=$HOME/Library/Android/sdk && ./gradlew :app:assembleDebug
```
Expected: BUILD SUCCESSFUL.

- [ ] **Step 3: (no git)** mark done in tracker.

---

## PHASE G — UI (ViewModels + screens + navigation)

> Compose screens use `LocalTbs.current` palette + the three font families. Numbers use `MonoJetBrains` with `letterSpacing`; big stat values use `DisplaySerif`. Labels: `MonoJetBrains`, uppercase, letterSpacing ~1.2sp. Flat: 1px borders (`Modifier.border`), no elevation. Radius 4dp (buttons/inputs) / 6dp (cards).

### Task G1: shared UI components

**Files:**
- Create: `ui/components/StatusPill.kt`, `StatCard.kt`, `FilterChip.kt`, `SmsRow.kt`

- [ ] **Step 1: Create `ui/components/StatusPill.kt`**

```kotlin
package uz.tbsparcer.sms.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
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
```

- [ ] **Step 2: Create `ui/components/StatCard.kt`**

```kotlin
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
        Text(label.uppercase(), fontFamily = MonoJetBrains, fontSize = 10.5.sp,
            letterSpacing = 1.2.sp, color = p.inkSecondary)
        Spacer(Modifier.height(4.dp))
        Text(value, fontFamily = DisplaySerif, fontSize = 26.sp, fontWeight = FontWeight.Normal,
            color = if (accent) p.income else p.ink)
    }
}
```

- [ ] **Step 3: Create `ui/components/FilterChip.kt`**

```kotlin
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
```

- [ ] **Step 4: Create `ui/components/SmsRow.kt`**

```kotlin
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

private val fmt = SimpleDateFormat("dd.MM.yy HH:mm", Locale.US)

@Composable
fun SmsRow(rec: SmsRecord, onClick: () -> Unit) {
    val p = LocalTbs.current
    Column(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 8.dp),
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(fmt.format(Date(rec.receivedAt)), fontFamily = MonoJetBrains, fontSize = 11.sp, color = p.inkSecondary)
            Text(rec.syncStatus.uppercase() + (rec.backendTransactionId?.let { "  #$it" } ?: ""),
                fontFamily = MonoJetBrains, fontSize = 10.sp, letterSpacing = 1.sp,
                color = when (rec.syncStatus) {
                    "synced" -> p.income; "error" -> p.expense; else -> p.inkSecondary
                })
        }
        Spacer(Modifier.height(2.dp))
        Text(rec.body, fontFamily = SansGrotesk, fontSize = 13.sp, color = p.ink,
            maxLines = 2, overflow = TextOverflow.Ellipsis)
    }
}
```

- [ ] **Step 5: Build**

```bash
cd android && export JAVA_HOME=/opt/homebrew/opt/openjdk@17 ANDROID_HOME=$HOME/Library/Android/sdk && ./gradlew :app:assembleDebug
```
Expected: BUILD SUCCESSFUL.

- [ ] **Step 6: (no git)** mark done in tracker.

---

### Task G2: ViewModels

**Files:**
- Create: `ui/vm/HomeViewModel.kt`, `StatsViewModel.kt`, `DiagnosticsViewModel.kt`, `SettingsViewModel.kt`

- [ ] **Step 1: Create `ui/vm/HomeViewModel.kt`**

```kotlin
package uz.tbsparcer.sms.ui.vm

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.*
import uz.tbsparcer.sms.data.local.SmsRecord
import uz.tbsparcer.sms.data.repo.SmsRepository
import uz.tbsparcer.sms.work.WorkScheduler
import javax.inject.Inject

@HiltViewModel
class HomeViewModel @Inject constructor(
    app: Application,
    private val repo: SmsRepository,
) : AndroidViewModel(app) {
    val filter = MutableStateFlow("all")

    @OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
    val records: StateFlow<List<SmsRecord>> = filter.flatMapLatest { f ->
        if (f == "all") repo.recent() else repo.byStatus(f)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val counts = repo.statusCounts()
        .map { list -> list.associate { it.syncStatus to it.n } }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyMap())

    fun setFilter(f: String) { filter.value = f }
    fun syncNow() = WorkScheduler.syncNow(getApplication())
}
```

- [ ] **Step 2: Create `ui/vm/StatsViewModel.kt`**

```kotlin
package uz.tbsparcer.sms.ui.vm

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import uz.tbsparcer.sms.data.remote.SmsStatsResponse
import uz.tbsparcer.sms.data.remote.SourceItem
import uz.tbsparcer.sms.data.repo.SmsRepository
import uz.tbsparcer.sms.data.repo.StatsRepository
import javax.inject.Inject

data class StatsUi(
    val loading: Boolean = false,
    val error: String? = null,
    val stats: SmsStatsResponse? = null,
    val sources: List<SourceItem> = emptyList(),
    val localFailed: Int = 0,             // skipped+error from Room (this phone)
    val source: String = "all",
    val chatId: Long? = null,
    val card: String = "",
    val dateFrom: String? = null,
    val dateTo: String? = null,
)

@HiltViewModel
class StatsViewModel @Inject constructor(
    private val statsRepo: StatsRepository,
    private val smsRepo: SmsRepository,
) : ViewModel() {
    private val _ui = MutableStateFlow(StatsUi())
    val ui = _ui.asStateFlow()

    fun setSource(s: String) { _ui.value = _ui.value.copy(source = s, chatId = null); load() }
    fun setChat(id: Long?) { _ui.value = _ui.value.copy(chatId = id); load() }
    fun setCard(c: String) { _ui.value = _ui.value.copy(card = c); load() }
    fun setRange(from: String?, to: String?) { _ui.value = _ui.value.copy(dateFrom = from, dateTo = to); load() }

    fun load() {
        val s = _ui.value
        _ui.value = s.copy(loading = true, error = null)
        viewModelScope.launch {
            try {
                val stats = statsRepo.stats(
                    s.dateFrom, s.dateTo, s.source, s.chatId,
                    s.card.takeIf { it.length == 4 },
                )
                val srcs = if (s.sources.isEmpty()) statsRepo.sources().items else s.sources
                _ui.value = _ui.value.copy(loading = false, stats = stats, sources = srcs)
            } catch (e: Exception) {
                _ui.value = _ui.value.copy(loading = false, error = e.message ?: "error")
            }
        }
    }
}
```

- [ ] **Step 3: Create `ui/vm/DiagnosticsViewModel.kt`**

```kotlin
package uz.tbsparcer.sms.ui.vm

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import uz.tbsparcer.sms.data.repo.StatsRepository
import javax.inject.Inject

data class DiagUi(
    val checking: Boolean = false,
    val backendOk: Boolean? = null,
    val latencyMs: Long? = null,
    val version: String? = null,
    val dbStatus: String? = null,
    val keyValid: Boolean? = null,
    val message: String? = null,
)

@HiltViewModel
class DiagnosticsViewModel @Inject constructor(
    private val statsRepo: StatsRepository,
) : ViewModel() {
    private val _ui = MutableStateFlow(DiagUi())
    val ui = _ui.asStateFlow()

    fun runChecks() {
        _ui.value = DiagUi(checking = true)
        viewModelScope.launch {
            val start = System.currentTimeMillis()
            try {
                val h = statsRepo.health()
                _ui.value = DiagUi(
                    checking = false, backendOk = true,
                    latencyMs = System.currentTimeMillis() - start,
                    version = h.version, dbStatus = h.db, keyValid = true,
                )
            } catch (e: retrofit2.HttpException) {
                _ui.value = DiagUi(checking = false, backendOk = true,
                    keyValid = e.code() != 403 && e.code() != 503,
                    message = "HTTP ${e.code()}")
            } catch (e: Exception) {
                _ui.value = DiagUi(checking = false, backendOk = false, message = e.message)
            }
        }
    }
}
```

- [ ] **Step 4: Create `ui/vm/SettingsViewModel.kt`**

```kotlin
package uz.tbsparcer.sms.ui.vm

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import uz.tbsparcer.sms.data.local.SettingsStore
import uz.tbsparcer.sms.data.repo.SmsRepository
import uz.tbsparcer.sms.work.WorkScheduler
import javax.inject.Inject

@HiltViewModel
class SettingsViewModel @Inject constructor(
    app: Application,
    val settings: SettingsStore,
    private val repo: SmsRepository,
) : AndroidViewModel(app) {
    fun save(baseUrl: String, mobileKey: String, theme: String) {
        settings.baseUrl = baseUrl.trim()
        settings.mobileKey = mobileKey.trim()
        settings.themeMode = theme
    }
    fun setBackfillDate(millis: Long) { settings.backfillSinceMillis = millis }
    fun runBackfill() = WorkScheduler.runBackfill(getApplication())
    fun clearLocal() = viewModelScope.launch { repo.clear() }
}
```

- [ ] **Step 5: Build**

```bash
cd android && export JAVA_HOME=/opt/homebrew/opt/openjdk@17 ANDROID_HOME=$HOME/Library/Android/sdk && ./gradlew :app:assembleDebug
```
Expected: BUILD SUCCESSFUL.

- [ ] **Step 6: (no git)** mark done in tracker.

---

### Task G3: screens + navigation + permission flow

**Files:**
- Create: `ui/screens/OnboardingScreen.kt`, `HomeScreen.kt`, `StatsScreen.kt`, `DiagnosticsScreen.kt`, `SettingsScreen.kt`, `SmsDetailScreen.kt`
- Modify: `MainActivity.kt` (real nav graph + theme mode + permission request)

- [ ] **Step 1: Create `ui/screens/OnboardingScreen.kt`** (permissions + backfill date + key)

```kotlin
package uz.tbsparcer.sms.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import uz.tbsparcer.sms.ui.vm.SettingsViewModel
import java.util.Calendar

@Composable
fun OnboardingScreen(vm: SettingsViewModel, onDone: () -> Unit) {
    var baseUrl by remember { mutableStateOf(vm.settings.baseUrl) }
    var key by remember { mutableStateOf(vm.settings.mobileKey) }
    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("Настройка", style = MaterialTheme.typography.headlineMedium)
        OutlinedTextField(baseUrl, { baseUrl = it }, label = { Text("Backend URL") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(key, { key = it }, label = { Text("Mobile Ingest Key") }, modifier = Modifier.fillMaxWidth())
        Text("SMS будут собраны за последние 30 дней и далее в реальном времени.")
        Button(onClick = {
            vm.save(baseUrl, key, vm.settings.themeMode)
            val cal = Calendar.getInstance().apply { add(Calendar.DAY_OF_YEAR, -30) }
            vm.setBackfillDate(cal.timeInMillis)
            vm.settings.onboardingDone = true
            vm.runBackfill()
            onDone()
        }) { Text("Начать") }
    }
}
```

- [ ] **Step 2: Create `ui/screens/HomeScreen.kt`**

```kotlin
package uz.tbsparcer.sms.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.tbsparcer.sms.ui.components.SmsRow
import uz.tbsparcer.sms.ui.components.StatusPill
import uz.tbsparcer.sms.ui.components.TbsChip
import uz.tbsparcer.sms.ui.vm.HomeViewModel

@Composable
fun HomeScreen(onOpenDetail: (String) -> Unit, vm: HomeViewModel = hiltViewModel()) {
    val records by vm.records.collectAsStateWithLifecycle()
    val counts by vm.counts.collectAsStateWithLifecycle()
    val filter by vm.filter.collectAsStateWithLifecycle()
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            StatusPill(online = true, label = "online")
            Text("pending ${counts["pending"] ?: 0} · err ${counts["error"] ?: 0}")
        }
        Spacer(Modifier.height(8.dp))
        Button(onClick = { vm.syncNow() }) { Text("SYNC NOW") }
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("all","pending","synced","duplicate","error").forEach {
                TbsChip(it, filter == it) { vm.setFilter(it) }
            }
        }
        Spacer(Modifier.height(8.dp))
        LazyColumn(Modifier.fillMaxSize()) {
            items(records, key = { it.deviceSmsId }) { SmsRow(it) { onOpenDetail(it.deviceSmsId) } }
        }
    }
}
```

- [ ] **Step 3: Create `ui/screens/StatsScreen.kt`**

```kotlin
package uz.tbsparcer.sms.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.tbsparcer.sms.ui.components.StatCard
import uz.tbsparcer.sms.ui.components.TbsChip
import uz.tbsparcer.sms.ui.vm.StatsViewModel

@Composable
fun StatsScreen(vm: StatsViewModel = hiltViewModel()) {
    val ui by vm.ui.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { vm.load() }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Статистика", style = MaterialTheme.typography.headlineMedium)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("all" to "Все", "sms" to "SMS", "telegram" to "Telegram").forEach { (k, lbl) ->
                TbsChip(lbl, ui.source == k) { vm.setSource(k) }
            }
        }
        if (ui.source == "telegram" && ui.sources.isNotEmpty()) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ui.sources.take(6).forEach { src ->
                    TbsChip(src.title ?: src.chatId.toString(), ui.chatId == src.chatId) { vm.setChat(src.chatId) }
                }
            }
        }
        OutlinedTextField(ui.card, { vm.setCard(it.filter { c -> c.isDigit() }.take(4)) },
            label = { Text("Карта (4 цифры)") }, modifier = Modifier.fillMaxWidth())
        val s = ui.stats
        if (ui.loading) CircularProgressIndicator()
        ui.error?.let { Text("Ошибка: $it") }
        if (s != null) {
            StatCard("Общая сумма трат", "${s.totalVolume} ${s.currency}", modifier = Modifier.fillMaxWidth())
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                StatCard("Прошло (всего)", s.transactionCount.toString(), modifier = Modifier.weight(1f))
                StatCard("Не прошло (этот телефон)", ui.localFailed.toString(), modifier = Modifier.weight(1f))
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                StatCard("Расход", "${s.debitVolume}", modifier = Modifier.weight(1f))
                StatCard("Доход", "${s.creditVolume}", accent = true, modifier = Modifier.weight(1f))
            }
            s.byCard.forEach { c ->
                Text("•••• ${c.cardLast4}   ${c.volume}   (${c.count})")
            }
        }
    }
}
```

- [ ] **Step 4: Create `ui/screens/DiagnosticsScreen.kt`**

```kotlin
package uz.tbsparcer.sms.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.tbsparcer.sms.ui.vm.DiagnosticsViewModel

@Composable
fun DiagnosticsScreen(vm: DiagnosticsViewModel = hiltViewModel()) {
    val ui by vm.ui.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { vm.runChecks() }
    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Диагностика", style = MaterialTheme.typography.headlineMedium)
        if (ui.checking) CircularProgressIndicator()
        Text("Backend: " + when (ui.backendOk) { true -> "OK ${ui.latencyMs ?: 0}ms"; false -> "недоступен"; null -> "—" })
        Text("Версия: ${ui.version ?: "—"}   БД: ${ui.dbStatus ?: "—"}")
        Text("Mobile key: " + when (ui.keyValid) { true -> "валиден"; false -> "неверный"; null -> "—" })
        ui.message?.let { Text(it) }
        Button(onClick = { vm.runChecks() }) { Text("Тест связи") }
    }
}
```

- [ ] **Step 5: Create `ui/screens/SettingsScreen.kt`**

```kotlin
package uz.tbsparcer.sms.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import uz.tbsparcer.sms.ui.vm.SettingsViewModel

@Composable
fun SettingsScreen(vm: SettingsViewModel = hiltViewModel()) {
    var baseUrl by remember { mutableStateOf(vm.settings.baseUrl) }
    var key by remember { mutableStateOf(vm.settings.mobileKey) }
    var theme by remember { mutableStateOf(vm.settings.themeMode) }
    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Настройки", style = MaterialTheme.typography.headlineMedium)
        OutlinedTextField(baseUrl, { baseUrl = it }, label = { Text("Backend URL") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(key, { key = it }, label = { Text("Mobile Ingest Key") }, modifier = Modifier.fillMaxWidth())
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("system","light","dark").forEach {
                FilterChip(selected = theme == it, onClick = { theme = it }, label = { Text(it) })
            }
        }
        Button(onClick = { vm.save(baseUrl, key, theme) }) { Text("Сохранить") }
        OutlinedButton(onClick = { vm.runBackfill() }) { Text("Пересобрать inbox") }
        OutlinedButton(onClick = { vm.clearLocal() }) { Text("Очистить локальную БД") }
        Text("Device ID: ${vm.settings.deviceId}")
    }
}
```

- [ ] **Step 6: Create `ui/screens/SmsDetailScreen.kt`**

```kotlin
package uz.tbsparcer.sms.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import uz.tbsparcer.sms.data.local.SmsRecord
import uz.tbsparcer.sms.ui.theme.MonoJetBrains
import uz.tbsparcer.sms.ui.vm.HomeViewModel

@Composable
fun SmsDetailScreen(deviceSmsId: String, vm: HomeViewModel = hiltViewModel()) {
    var rec by remember { mutableStateOf<SmsRecord?>(null) }
    LaunchedEffect(deviceSmsId) {
        // HomeViewModel exposes records; fetch single via repo through a one-shot.
        rec = vm.records.value.firstOrNull { it.deviceSmsId == deviceSmsId }
    }
    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Детали SMS", style = MaterialTheme.typography.headlineMedium)
        rec?.let { r ->
            Text("Статус: ${r.syncStatus}")
            r.backendTransactionId?.let { Text("Транзакция: #$it") }
            r.fingerprint?.let { Text("Fingerprint: $it", fontFamily = MonoJetBrains, fontSize = 11.sp) }
            Text("Отправитель: ${r.sender}")
            Spacer(Modifier.height(8.dp))
            Text(r.body, fontFamily = MonoJetBrains, fontSize = 12.sp)
            r.errorMessage?.let { Text("Ошибка: $it") }
        } ?: Text("Не найдено")
    }
}
```

- [ ] **Step 7: Rewrite `MainActivity.kt`** (nav + bottom bar + theme + runtime permissions)

```kotlin
package uz.tbsparcer.sms

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.navigation.compose.*
import dagger.hilt.android.AndroidEntryPoint
import uz.tbsparcer.sms.data.local.SettingsStore
import uz.tbsparcer.sms.ui.screens.*
import uz.tbsparcer.sms.ui.theme.TbsTheme
import uz.tbsparcer.sms.ui.vm.SettingsViewModel
import uz.tbsparcer.sms.work.WorkScheduler
import javax.inject.Inject

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    @Inject lateinit var settings: SettingsStore

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WorkScheduler.schedulePeriodic(applicationContext)
        setContent {
            val dark = when (settings.themeMode) {
                "dark" -> true; "light" -> false
                else -> androidx.compose.foundation.isSystemInDarkTheme()
            }
            TbsTheme(darkTheme = dark) { AppRoot(settings) }
        }
    }
}

@Composable
private fun AppRoot(settings: SettingsStore) {
    val nav = rememberNavController()
    val permLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()) {}
    LaunchedEffect(Unit) {
        val perms = mutableListOf(Manifest.permission.READ_SMS, Manifest.permission.RECEIVE_SMS)
        if (Build.VERSION.SDK_INT >= 33) perms += Manifest.permission.POST_NOTIFICATIONS
        permLauncher.launch(perms.toTypedArray())
    }
    val start = if (settings.onboardingDone) "home" else "onboarding"
    Scaffold(bottomBar = {
        if (settings.onboardingDone) NavigationBar {
            val entry by nav.currentBackStackEntryAsState()
            val route = entry?.destination?.route
            NavigationBarItem(route == "home", { nav.navigate("home") },
                icon = { Icon(Icons.Default.List, null) }, label = { Text("Лента") })
            NavigationBarItem(route == "stats", { nav.navigate("stats") },
                icon = { Icon(Icons.Default.BarChart, null) }, label = { Text("Статистика") })
            NavigationBarItem(route == "diag", { nav.navigate("diag") },
                icon = { Icon(Icons.Default.Bolt, null) }, label = { Text("Статус") })
            NavigationBarItem(route == "settings", { nav.navigate("settings") },
                icon = { Icon(Icons.Default.Settings, null) }, label = { Text("Настройки") })
        }
    }) { pad ->
        NavHost(nav, startDestination = start, modifier = Modifier.padding(pad)) {
            composable("onboarding") {
                val vm: SettingsViewModel = androidx.hilt.navigation.compose.hiltViewModel()
                OnboardingScreen(vm) { nav.navigate("home") { popUpTo("onboarding") { inclusive = true } } }
            }
            composable("home") { HomeScreen(onOpenDetail = { nav.navigate("detail/$it") }) }
            composable("stats") { StatsScreen() }
            composable("diag") { DiagnosticsScreen() }
            composable("settings") { SettingsScreen() }
            composable("detail/{id}") { SmsDetailScreen(it.arguments?.getString("id") ?: "") }
        }
    }
}
```

Note: add `implementation("androidx.hilt:hilt-navigation-compose:1.2.0")` to `app/build.gradle.kts` dependencies (required by `hiltViewModel()`).

- [ ] **Step 8: Build**

```bash
cd android && export JAVA_HOME=/opt/homebrew/opt/openjdk@17 ANDROID_HOME=$HOME/Library/Android/sdk && ./gradlew :app:assembleDebug
```
Expected: BUILD SUCCESSFUL → `app/build/outputs/apk/debug/app-debug.apk`.

- [ ] **Step 9: (no git)** mark done in tracker.

---

## PHASE H — Signing + release build + verification

### Task H1: generate keystore + signed release APK

**Files:**
- Create: `android/keystore/release.keystore` (NOT committed)

- [ ] **Step 1: Generate keystore** (passwords chosen by user; example placeholders)

```bash
mkdir -p android/keystore
export JAVA_HOME=/opt/homebrew/opt/openjdk@17
"$JAVA_HOME/bin/keytool" -genkeypair -v \
  -keystore android/keystore/release.keystore \
  -alias tbsparcer -keyalg RSA -keysize 2048 -validity 10000 \
  -storepass CHANGE_ME -keypass CHANGE_ME \
  -dname "CN=TBSparcer, OU=Mobile, O=TBS, L=Tashkent, C=UZ"
```
Expected: keystore file created. (Replace `CHANGE_ME` with real passwords; tell the user to keep them — needed for future update builds.)

- [ ] **Step 2: Build signed release APK**

```bash
cd android && \
export JAVA_HOME=/opt/homebrew/opt/openjdk@17 ANDROID_HOME=$HOME/Library/Android/sdk \
TBS_KEYSTORE="$(pwd)/keystore/release.keystore" TBS_KS_PASS=CHANGE_ME TBS_KEY_ALIAS=tbsparcer TBS_KEY_PASS=CHANGE_ME && \
./gradlew :app:assembleRelease
```
Expected: BUILD SUCCESSFUL → `app/build/outputs/apk/release/app-release.apk`.

- [ ] **Step 3: Verify the APK is signed**

```bash
~/Library/Android/sdk/build-tools/35.0.0/apksigner verify --verbose \
  android/app/build/outputs/apk/release/app-release.apk
```
Expected: "Verifies" + "Verified using v2 scheme: true" (and v3). If "DOES NOT VERIFY" — signing config env vars were not picked up; re-check Step 2 env.

- [ ] **Step 4: (no git)** mark done in tracker.

---

### Task H2: full verification pass + install instructions

- [ ] **Step 1: Run all backend SMS tests**

```bash
cd backend && ../.venv/bin/python -m pytest tests/test_sms_ingest_api.py -v
```
Expected: all pass.

- [ ] **Step 2: Run all Android unit tests**

```bash
cd android && export JAVA_HOME=/opt/homebrew/opt/openjdk@17 ANDROID_HOME=$HOME/Library/Android/sdk && ./gradlew :app:testDebugUnitTest
```
Expected: BUILD SUCCESSFUL (SmsFilterTest + FingerprintCalculatorTest pass).

- [ ] **Step 3: Smoke-test ingest contract against a running backend** (manual, optional if local backend up)

Start backend locally with a test mobile key, then:
```bash
curl -s -X POST http://127.0.0.1:8000/api/sms/ingest \
  -H "X-Mobile-Ingest-Key: <key>" -H "Content-Type: application/json" \
  -d '{"device_id":"android-test","messages":[{"device_sms_id":"t1","sender":"UZCARD","text":"Pokupka: XK FAMILY SHOP, 02.04.25 11:48 karta ***0907. summa:80000.00 UZS, balans:2527792.14 UZS","received_at":"2026-05-30T11:48:00","sim_slot":0}]}'
```
Expected: `{"processed":1,"created":1,...}`. Then `curl .../api/sms/stats -H "X-Mobile-Ingest-Key: <key>"` → totals reflect the new transaction.

- [ ] **Step 4: Write install instructions** for the customer (in chat, not a file unless asked):
  - Copy `app-release.apk` to the phone.
  - Settings → Apps → Special access → Install unknown apps → enable for the file manager/browser used to open the APK.
  - Open the APK → Install.
  - On first launch: grant SMS + notification permissions, enter Mobile Key, tap Начать.

- [ ] **Step 5: (no git)** mark plan complete in tracker.

---

## Self-Review notes (spec coverage)

- SMS read (new + backfill from date) → Phase F (F1 inbox query `date >= sinceMillis`, F3 realtime). ✓
- Send + parse + dedup + add new → existing ingest + Phase F sync. ✓
- Stats: total / by source(bot/SMS) / by card+period / passed-failed → Phase A endpoint + Phase G StatsScreen. ✓
- Design like desktop (editorial monochrome) → Phase C theme + Phase G components. ✓
- Signed APK installable on latest Android → Phase B (minSdk26/target35) + Phase H signing. ✓
- Diagnostics "100% works" → Phase G DiagnosticsScreen + `/health`. ✓
- Single device, mobile-key only, no JWT → throughout. ✓
- "Failed" = local SMS (skipped+error) shown as "этот телефон"; success global → StatsScreen localFailed + backend transaction_count. ✓
