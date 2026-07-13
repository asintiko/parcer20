#!/usr/bin/env bash
# Build, sign and publish the Android APK to the in-app update channel
# (public GitHub repo asintiko/parcer20-updates). After this, devices running
# >=1.0.2 pull the update via Settings → «Проверить обновления».
#
# Prereqs: JDK17, Android SDK, gh logged in as repo owner, keystore present.
# Bump versionCode/versionName in app/build.gradle.kts BEFORE running.
#
# Usage: android/scripts/publish-apk.sh
set -euo pipefail

REPO="asintiko/parcer20-updates"
ANDROID_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ANDROID_DIR"

export JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@17}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export TBS_KEYSTORE="${TBS_KEYSTORE:-$ANDROID_DIR/keystore/release.keystore}"
export TBS_KS_PASS="${TBS_KS_PASS:-$(cat "$ANDROID_DIR/keystore/.keystore-password.txt")}"
export TBS_KEY_ALIAS="${TBS_KEY_ALIAS:-tbsparcer}"
export TBS_KEY_PASS="${TBS_KEY_PASS:-$TBS_KS_PASS}"

GRADLE="./app/build.gradle.kts"
VNAME="$(grep -E 'versionName *=' "$GRADLE" | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
VCODE="$(grep -E 'versionCode *=' "$GRADLE" | head -1 | sed -E 's/[^0-9]//g')"
TAG="android-v$VNAME"
echo "Publishing versionName=$VNAME versionCode=$VCODE tag=$TAG"

echo "==> assembleRelease"
./gradlew :app:assembleRelease -q

APK="app/build/outputs/apk/release/app-release.apk"
[ -f "$APK" ] || { echo "APK not found: $APK" >&2; exit 1; }
SHA="$(shasum -a 256 "$APK" | awk '{print $1}')"
URL="https://github.com/$REPO/releases/download/$TAG/app-release.apk"
echo "sha256=$SHA"

echo "==> create release $TAG"
gh release create "$TAG" "$APK" --repo "$REPO" --title "Android SMS v$VNAME" \
  --notes "${RELEASE_NOTES:-Обновление TBSparcer SMS v$VNAME}"

echo "==> update android-latest.json"
TMP="$(mktemp)"
cat > "$TMP" <<JSON
{
  "versionCode": $VCODE,
  "versionName": "$VNAME",
  "url": "$URL",
  "sha256": "$SHA",
  "notes": "${RELEASE_NOTES:-Обновление TBSparcer SMS v$VNAME}"
}
JSON
B64="$(base64 -i "$TMP")"
EXISTING_SHA="$(gh api "repos/$REPO/contents/android-latest.json" --jq .sha 2>/dev/null || true)"
if [[ -n "$EXISTING_SHA" && "$EXISTING_SHA" != *"Not Found"* ]]; then
  gh api -X PUT "repos/$REPO/contents/android-latest.json" \
    -f message="android updater manifest v$VNAME" -f content="$B64" -f sha="$EXISTING_SHA" --jq '.commit.html_url'
else
  gh api -X PUT "repos/$REPO/contents/android-latest.json" \
    -f message="android updater manifest v$VNAME" -f content="$B64" --jq '.commit.html_url'
fi
rm -f "$TMP"
echo "Done. Devices >=1.0.2 will see v$VNAME via Settings → Проверить обновления."
