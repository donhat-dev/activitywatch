#!/usr/bin/env bash
# Build signed and optionally notarized DMG for the Tauri ActivityWatch bundle.
#
# Usage:
#   scripts/package/build-signed-tauri-dmg.sh
#   scripts/package/build-signed-tauri-dmg.sh --skip-build
#   scripts/package/build-signed-tauri-dmg.sh --skip-notarize
#
# Required for notarization:
#   APPLE_EMAIL      Apple ID email
#   APPLE_PASSWORD   App-specific password
#   APPLE_TEAMID     Apple developer team ID
#
# Optional:
#   APPLE_PERSONALID Codesigning identity. If unset, the script selects the first
#                    Developer ID Application identity and falls back to Apple
#                    Development for internal builds.
#   TAURI_WATCHERS   Space-separated watcher list. Defaults to the Tauri watcher set.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

SKIP_BUILD=false
SKIP_NOTARIZE=false
for arg in "$@"; do
    case "$arg" in
        --skip-build)
            SKIP_BUILD=true
            ;;
        --skip-notarize)
            SKIP_NOTARIZE=true
            ;;
        -h|--help)
            sed -n '1,22p' "$0"
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument: $arg"
            exit 1
            ;;
    esac
done

if [[ "$(uname)" != "Darwin" ]]; then
    echo "ERROR: this script must run on macOS."
    exit 1
fi

if [[ -f "$ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT/.env"
    set +a
    echo "[env] Loaded .env"
fi

TAURI_WATCHERS="${TAURI_WATCHERS:-aw-watcher-input aw-watcher-screenshot-mini aw-odoo-sync}"
VERSION="$(LC_ALL=C LANG=C bash scripts/package/getversion.sh 2>/dev/null || echo "dev")"
ARCH="$(uname -m)"
APP="dist/ActivityWatch.app"
RAW_DMG="dist/ActivityWatch.dmg"
SIGNED_DMG="dist/activitywatch-tauri-${VERSION}-macos-${ARCH}.dmg"
APP_ZIP="dist/ActivityWatch.app.zip"
KEYCHAIN_PROFILE="${KEYCHAIN_PROFILE:-activitywatch-tauri-notarize}"

if [[ -z "${APPLE_PERSONALID:-}" ]]; then
    all_certs="$(security find-identity -v -p codesigning 2>/dev/null || true)"
    cert_line="$(echo "$all_certs" | grep "Developer ID Application" | head -1 || true)"
    if [[ -z "$cert_line" && -n "${APPLE_TEAMID:-}" ]]; then
        cert_line="$(echo "$all_certs" | grep "Apple Development" | grep "$APPLE_TEAMID" | head -1 || true)"
        if [[ -n "$cert_line" ]]; then
            echo "[warn] Using Apple Development identity; notarization will be skipped."
            SKIP_NOTARIZE=true
        fi
    fi
    if [[ -z "$cert_line" ]]; then
        echo "ERROR: no codesigning identity found. Install a Developer ID Application certificate or set APPLE_PERSONALID."
        exit 1
    fi
    APPLE_PERSONALID="$(echo "$cert_line" | sed 's/.*"\(.*\)"/\1/')"
fi
export APPLE_PERSONALID

if [[ "$SKIP_NOTARIZE" == false ]]; then
    : "${APPLE_EMAIL:?Need APPLE_EMAIL for notarization}"
    : "${APPLE_PASSWORD:?Need APPLE_PASSWORD app-specific password for notarization}"
    : "${APPLE_TEAMID:?Need APPLE_TEAMID for notarization}"
fi

echo "----------------------------------------------"
echo " ActivityWatch Tauri signed DMG build"
echo " Version     : $VERSION"
echo " Arch        : $ARCH"
echo " Identity    : $APPLE_PERSONALID"
echo " Watchers    : $TAURI_WATCHERS"
echo " Notarize    : $( [[ "$SKIP_NOTARIZE" == true ]] && echo "skip" || echo "yes" )"
echo "----------------------------------------------"

if [[ "$SKIP_BUILD" == false ]]; then
    echo ""
    echo "[1/5] Building Tauri .app..."
    source "$HOME/.nvm/nvm.sh" 2>/dev/null || true
    nvm use 24 2>/dev/null || true

    if [[ -f "venv/bin/activate" ]]; then
        # shellcheck disable=SC1091
        source "venv/bin/activate"
    fi

    rm -rf "$APP" "$RAW_DMG" "$SIGNED_DMG" "$APP_ZIP" dist/activitywatch-*-macos-*.dmg
    TAURI_BUILD=true TAURI_WATCHERS="$TAURI_WATCHERS" make dist/ActivityWatch.app
else
    echo ""
    echo "[1/5] Skipping build (--skip-build)"
    [[ -d "$APP" ]] || { echo "ERROR: $APP not found."; exit 1; }
fi

echo ""
echo "[2/5] Verifying .app signature..."
codesign --verify --deep --strict --verbose=2 "$APP"
spctl --assess --type execute --verbose "$APP" 2>&1 || echo "(spctl may fail before notarization; continuing)"

echo ""
echo "[3/5] Building and signing DMG..."
if [[ -f "venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "venv/bin/activate"
fi
python -m pip install dmgbuild -q
rm -f "$RAW_DMG" "$SIGNED_DMG"
dmgbuild \
    -s scripts/package/dmgbuild-settings.py \
    -D app="$APP" \
    "ActivityWatch" \
    "$RAW_DMG"
codesign --force --verbose --timestamp --options runtime -s "$APPLE_PERSONALID" "$RAW_DMG"
mv "$RAW_DMG" "$SIGNED_DMG"
echo "[3/5] DMG: $SIGNED_DMG"

if [[ "$SKIP_NOTARIZE" == true ]]; then
    echo ""
    echo "[4/5] Skipping notarization"
    echo "[5/5] Skipping stapling"
    echo ""
    echo "Done: $SIGNED_DMG"
    exit 0
fi

echo ""
echo "[4/5] Notarizing .app and DMG..."
xcrun notarytool store-credentials "$KEYCHAIN_PROFILE" \
    --apple-id "$APPLE_EMAIL" \
    --team-id "$APPLE_TEAMID" \
    --password "$APPLE_PASSWORD"

ditto -c -k --keepParent "$APP" "$APP_ZIP"
xcrun notarytool submit "$APP_ZIP" --keychain-profile "$KEYCHAIN_PROFILE" --wait
rm -f "$APP_ZIP"
xcrun notarytool submit "$SIGNED_DMG" --keychain-profile "$KEYCHAIN_PROFILE" --wait

echo ""
echo "[5/5] Stapling notarization tickets..."
xcrun stapler staple "$APP"
xcrun stapler staple "$SIGNED_DMG"

echo ""
echo "----------------------------------------------"
echo " Done: $SIGNED_DMG"
echo " Gatekeeper check:"
spctl --assess --type execute --verbose "$APP"
echo "----------------------------------------------"
