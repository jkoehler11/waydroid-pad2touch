#!/bin/bash
# Build UniteMapper.apk with the Android SDK only (no Gradle, no dependencies).
#
#   ./build.sh                 # uses $ANDROID_HOME, $ANDROID_SDK_ROOT, or ~/android-sdk
#   ANDROID_HOME=/opt/android-sdk ./build.sh
#
# Output: ./UniteMapper.apk
set -euo pipefail

SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/android-sdk}}"
[ -d "$SDK" ] || { echo "Android SDK not found at $SDK (set ANDROID_HOME)"; exit 1; }

BT=$(ls -d "$SDK"/build-tools/* 2>/dev/null | sort -V | tail -1)
PLAT=$(ls -d "$SDK"/platforms/android-* 2>/dev/null | sort -V | tail -1)
[ -n "$BT" ] && [ -n "$PLAT" ] || { echo "need build-tools and a platform in $SDK"; exit 1; }

echo "sdk:        $SDK"
echo "build-tools:$BT"
echo "platform:   $PLAT"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
cp -r AndroidManifest.xml res src "$WORK"/
cd "$WORK"
mkdir -p obj dex

"$BT/aapt2" compile --dir res -o res.zip
"$BT/aapt2" link -o base.apk -I "$PLAT/android.jar" \
    --manifest AndroidManifest.xml -R res.zip --auto-add-overlay

javac --release 11 -nowarn -cp "$PLAT/android.jar" -d obj $(find src -name '*.java')
"$BT/d8" --lib "$PLAT/android.jar" --output dex $(find obj -name '*.class')
(cd dex && zip -q ../base.apk classes.dex)

"$BT/zipalign" -f 4 base.apk aligned.apk
[ -f debug.keystore ] || keytool -genkeypair -keystore debug.keystore -storepass android \
    -keypass android -alias dk -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=debug" >/dev/null 2>&1
"$BT/apksigner" sign --ks debug.keystore --ks-pass pass:android --key-pass pass:android \
    --out UniteMapper.apk aligned.apk

cp UniteMapper.apk "$OLDPWD/" 2>/dev/null || cp UniteMapper.apk "${OLDPWD:-.}/"
echo "built: ${OLDPWD:-.}/UniteMapper.apk"
