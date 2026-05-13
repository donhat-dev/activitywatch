#!/usr/bin/env bash
# Build signed + notarized DMG for macOS distribution.
# Usage:
#   ./scripts/build-signed-dmg.sh              # full build + sign + notarize
#   ./scripts/build-signed-dmg.sh --skip-build # reuse existing .app, only sign + notarize
#   ./scripts/build-signed-dmg.sh --skip-notarize # sign only, skip notarize
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

# ── Load .env if present ─────────────────────────────────────────────────────
if [ -f "$ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT/.env"
    set +a
    echo "[env] Loaded .env"
fi

# ── Config ───────────────────────────────────────────────────────────────────
SKIP_BUILD=false
SKIP_NOTARIZE=false
for arg in "$@"; do
    case $arg in
        --skip-build)     SKIP_BUILD=true ;;
        --skip-notarize)  SKIP_NOTARIZE=true ;;
    esac
done

: "${APPLE_EMAIL:?   Need APPLE_EMAIL}"
: "${APPLE_PASSWORD:?  Need APPLE_PASSWORD (app-specific password)}"
: "${APPLE_TEAMID:?   Need APPLE_TEAMID}"
: "${APPLE_PERSONALID:=${APPLE_TEAMID}}"

# Prefer Developer ID Application; fall back to Apple Development
_ALL_CERTS="$(security find-identity -v -p codesigning 2>/dev/null || true)"
_CERT_LINE="$(echo "$_ALL_CERTS" | grep "Developer ID Application" | head -1 || true)"
if [ -z "$_CERT_LINE" ]; then
    _CERT_LINE="$(echo "$_ALL_CERTS" | grep "Apple Development" | grep "${APPLE_TEAMID}" | head -1 || true)"
    if [ -z "$_CERT_LINE" ]; then
        echo "ERROR: No valid codesigning identity found in Keychain."
        echo "       Create a Developer ID Application cert at developer.apple.com"
        exit 1
    fi
    echo "[warn] No 'Developer ID Application' cert found — using 'Apple Development' (internal only, notarize will be skipped)"
    SKIP_NOTARIZE=true
fi
CERT="$(echo "$_CERT_LINE" | sed 's/.*"\(.*\)"/\1/')"

VERSION="$(LC_ALL=C LANG=C bash scripts/package/getversion.sh 2>/dev/null || echo "dev")"
ARCH="$(uname -m)"
APP="dist/ActivityWatch.app"
SIGNED_DMG="dist/activitywatch-${VERSION}-macos-${ARCH}.dmg"
ENTITLEMENTS="scripts/package/entitlements.plist"

echo "──────────────────────────────────────────────"
echo " ActivityWatch signed DMG build"
echo " Version  : $VERSION"
echo " Arch     : $ARCH"
echo " Cert     : $CERT"
echo " Notarize : $( [ "$SKIP_NOTARIZE" = true ] && echo "skip" || echo "yes" )"
echo "──────────────────────────────────────────────"

# ── Step 1: Build ─────────────────────────────────────────────────────────────
if [ "$SKIP_BUILD" = false ]; then
    echo ""
    echo "[1/5] Building webui..."
    source ~/.nvm/nvm.sh 2>/dev/null || true
    nvm use 24 2>/dev/null || true

    source venv/bin/activate

    make -C aw-server/aw-webui build
    rm -rf aw-server/aw_server/static/*
    cp -r aw-server/aw-webui/dist/* aw-server/aw_server/static/

    echo "[1/5] Building .app via PyInstaller..."
    rm -rf dist/ActivityWatch.app dist/ActivityWatch.dmg dist/activitywatch-*-unsigned.dmg
    LC_ALL=C LANG=C python -m PyInstaller --clean --noconfirm aw.spec
else
    echo "[1/5] Skipping build (--skip-build)"
    [ -d "$APP" ] || { echo "ERROR: $APP not found. Run without --skip-build first."; exit 1; }
fi

# ── Step 2: Sign .app ────────────────────────────────────────────────────────
echo ""
echo "[2/5] Signing .app with Hardened Runtime..."
codesign --deep --force --verbose \
    --options runtime \
    --entitlements "$ENTITLEMENTS" \
    -s "$CERT" \
    "$APP"

echo "[2/5] Verifying signature..."
codesign --verify --deep --strict --verbose=2 "$APP"
spctl --assess --type execute --verbose "$APP" 2>&1 || echo "(spctl assess may fail before notarize — expected)"

# ── Step 3: Build DMG ────────────────────────────────────────────────────────
echo ""
echo "[3/5] Building DMG..."
source venv/bin/activate
python -m pip install dmgbuild -q

rm -f dist/ActivityWatch.dmg "$SIGNED_DMG"
dmgbuild \
    -s scripts/package/dmgbuild-settings.py \
    -D app="$APP" \
    "ActivityWatch" \
    dist/ActivityWatch.dmg

# Sign the DMG itself
codesign --force --verbose \
    --options runtime \
    -s "$CERT" \
    dist/ActivityWatch.dmg

mv dist/ActivityWatch.dmg "$SIGNED_DMG"
echo "[3/5] DMG: $SIGNED_DMG"

# ── Step 4: Notarize ─────────────────────────────────────────────────────────
if [ "$SKIP_NOTARIZE" = true ]; then
    echo ""
    echo "[4/5] Skipping notarization (--skip-notarize)"
    echo "[5/5] Skipping staple"
    echo ""
    echo "Done: $SIGNED_DMG (signed, not notarized)"
    exit 0
fi

KEYCHAIN_PROFILE="activitywatch-notarize"

echo ""
echo "[4/5] Storing notarization credentials in keychain..."
xcrun notarytool store-credentials "$KEYCHAIN_PROFILE" \
    --apple-id "$APPLE_EMAIL" \
    --team-id "$APPLE_TEAMID" \
    --password "$APPLE_PASSWORD"

echo "[4/5] Submitting .app for notarization..."
APP_ZIP="dist/ActivityWatch.app.zip"
ditto -c -k --keepParent "$APP" "$APP_ZIP"

xcrun notarytool submit "$APP_ZIP" \
    --keychain-profile "$KEYCHAIN_PROFILE" \
    --wait
rm -f "$APP_ZIP"

echo "[4/5] Submitting DMG for notarization..."
xcrun notarytool submit "$SIGNED_DMG" \
    --keychain-profile "$KEYCHAIN_PROFILE" \
    --wait

# ── Step 5: Staple ───────────────────────────────────────────────────────────
echo ""
echo "[5/5] Stapling notarization ticket..."
xcrun stapler staple "$APP"
xcrun stapler staple "$SIGNED_DMG"

echo ""
echo "──────────────────────────────────────────────"
echo " Done: $SIGNED_DMG"
echo " Gatekeeper check:"
spctl --assess --type execute --verbose "$APP"
echo "──────────────────────────────────────────────"
