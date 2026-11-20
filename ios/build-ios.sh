#!/bin/bash
# Builds the iOS app.  Usage:  ./build-ios.sh sim      -> build/LIFCCompliance.app for the iOS Simulator
#                             ./build-ios.sh device   -> build/LIFCCompliance.ipa for a real iPhone (needs signing identity + profile)
# For "device": export SIGN_ID="Apple Distribution: …" PROFILE=/path/to/profile.mobileprovision
set -euo pipefail
cd "$(dirname "$0")"; MODE=${1:-sim}; OUT=build; rm -rf $OUT; mkdir -p $OUT
if [ "$MODE" = sim ]; then SDK=iphonesimulator; TGT=arm64-apple-ios16.0-simulator; else SDK=iphoneos; TGT=arm64-apple-ios16.0; fi
SDKP=$(xcrun --sdk $SDK --show-sdk-path)
APP=$OUT/LIFCCompliance.app; mkdir -p $APP
xcrun swiftc -sdk "$SDKP" -target $TGT -O -parse-as-library -module-name LIFCCompliance -o $APP/LIFCCompliance App/App.swift 2>&1 | grep -v "^$" || true
[ -f $APP/LIFCCompliance ] || { echo "compile failed"; exit 1; }
cp App/Info.plist $APP/Info.plist
if [ "$MODE" = sim ]; then codesign --force --sign - $APP; echo "Built $APP"
else
  : "${SIGN_ID:?set SIGN_ID}"; : "${PROFILE:?set PROFILE}"
  cp "$PROFILE" $APP/embedded.mobileprovision
  security cms -D -i "$PROFILE" > $OUT/p.plist; /usr/libexec/PlistBuddy -x -c 'Print :Entitlements' $OUT/p.plist > $OUT/ent.plist
  codesign --force --sign "$SIGN_ID" --entitlements $OUT/ent.plist $APP
  mkdir -p $OUT/Payload && cp -R $APP $OUT/Payload/ && (cd $OUT && zip -qr LIFCCompliance.ipa Payload) && echo "Built $OUT/LIFCCompliance.ipa"
fi
