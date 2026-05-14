#!/usr/bin/env bash
# Build signed and optionally notarized DMG for the Tauri ActivityWatch bundle.
#
# Usage:
#   scripts/package/build-signed-tauri-dmg.sh
#   scripts/package/build-signed-tauri-dmg.sh --skip-build
#   scripts/package/build-signed-tauri-dmg.sh --skip-project-build
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
#   TAURI_WATCHERS      Space-separated watcher list. Defaults to the Tauri watcher set.
#   TAURI_LOAD_ENV_FILE auto, true, or false. Defaults to auto. "auto" skips .env
#                       on GitHub Actions so repository files cannot override secrets.
#   TAURI_SIGN          auto, true, or false. Defaults to auto.
#   TAURI_NOTARIZE      auto, true, or false. Defaults to auto. "auto" skips
#                       notarization when signing credentials are incomplete.
#   TAURI_SKIP_NOTARIZE=true is also accepted for compatibility.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

SKIP_BUILD=false
SKIP_PROJECT_BUILD=false
SKIP_NOTARIZE_REQUESTED=false
for arg in "$@"; do
    case "$arg" in
        --skip-build)
            SKIP_BUILD=true
            ;;
        --skip-project-build)
            SKIP_PROJECT_BUILD=true
            ;;
        --skip-notarize)
            SKIP_NOTARIZE_REQUESTED=true
            ;;
        -h|--help)
            sed -n '1,27p' "$0"
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

# Add rustup cargo to PATH if not already present
if ! command -v cargo &>/dev/null; then
    if [[ -x "$HOME/.cargo/bin/cargo" ]]; then
        export PATH="$HOME/.cargo/bin:$PATH"
    fi
fi
if ! command -v cargo &>/dev/null; then
    echo "ERROR: cargo (Rust) not found."
    echo "       Install via: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
    echo "       Then restart your terminal and re-run this script."
    exit 1
fi

normalize_mode() {
    local value
    value="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
    case "$value" in
        auto|"")
            echo "auto"
            ;;
        1|true|yes|on)
            echo "true"
            ;;
        0|false|no|off)
            echo "false"
            ;;
        *)
            echo "ERROR: $2 must be one of: auto, true, false" >&2
            exit 1
            ;;
    esac
}

TAURI_LOAD_ENV_FILE_MODE="$(normalize_mode "${TAURI_LOAD_ENV_FILE:-auto}" "TAURI_LOAD_ENV_FILE")"
if [[ "$TAURI_LOAD_ENV_FILE_MODE" == "auto" && "${GITHUB_ACTIONS:-}" == "true" ]]; then
    TAURI_LOAD_ENV_FILE_MODE=false
fi

if [[ "$TAURI_LOAD_ENV_FILE_MODE" == "true" && -f "$ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT/.env"
    set +a
    echo "[env] Loaded .env"
elif [[ -f "$ROOT/.env" ]]; then
    echo "[env] Skipping .env"
fi

TAURI_WATCHERS="${TAURI_WATCHERS:-aw-watcher-input aw-watcher-screenshot-mini aw-odoo-sync}"
PYTHON="${PYTHON:-python}"
VERSION="$(LC_ALL=C LANG=C bash scripts/package/getversion.sh 2>/dev/null || echo "dev")"
ARCH="$(uname -m)"
APP="dist/ActivityWatch.app"
RAW_DMG="dist/ActivityWatch.dmg"
SIGNED_DMG="dist/activitywatch-tauri-${VERSION}-macos-${ARCH}.dmg"
APP_ZIP="dist/ActivityWatch.app.zip"
KEYCHAIN_PROFILE="${KEYCHAIN_PROFILE:-activitywatch-tauri-notarize}"

TAURI_SIGN_MODE="$(normalize_mode "${TAURI_SIGN:-auto}" "TAURI_SIGN")"
TAURI_NOTARIZE_MODE="$(normalize_mode "${TAURI_NOTARIZE:-auto}" "TAURI_NOTARIZE")"
if [[ "$SKIP_NOTARIZE_REQUESTED" == true ]] || [[ "$(normalize_mode "${TAURI_SKIP_NOTARIZE:-false}" "TAURI_SKIP_NOTARIZE")" == "true" ]]; then
    TAURI_NOTARIZE_MODE=false
fi

SIGN_ARTIFACTS=false
IDENTITY_KIND="none"
if [[ "$TAURI_SIGN_MODE" != "false" && -z "${APPLE_PERSONALID:-}" ]]; then
    all_certs="$(security find-identity -v -p codesigning 2>/dev/null || true)"
    cert_line="$(echo "$all_certs" | grep "Developer ID Application" | head -1 || true)"
    IDENTITY_KIND="developer-id"
    if [[ -z "$cert_line" && -n "${APPLE_TEAMID:-}" ]]; then
        cert_line="$(echo "$all_certs" | grep "Apple Development" | grep "$APPLE_TEAMID" | head -1 || true)"
        if [[ -n "$cert_line" ]]; then
            echo "[warn] Using Apple Development identity; notarization is not available for this build."
            IDENTITY_KIND="apple-development"
        fi
    fi
    if [[ -n "$cert_line" ]]; then
        APPLE_PERSONALID="$(echo "$cert_line" | sed 's/.*"\(.*\)"/\1/')"
    fi
elif [[ "$TAURI_SIGN_MODE" != "false" && -n "${APPLE_PERSONALID:-}" ]]; then
    IDENTITY_KIND="configured"
fi

if [[ "$TAURI_SIGN_MODE" != "false" && -n "${APPLE_PERSONALID:-}" ]]; then
    SIGN_ARTIFACTS=true
    export APPLE_PERSONALID
else
    unset APPLE_PERSONALID
fi

if [[ "$TAURI_SIGN_MODE" == "true" && "$SIGN_ARTIFACTS" == false ]]; then
    echo "ERROR: TAURI_SIGN=true but no codesigning identity was found. Import a Developer ID certificate or set APPLE_PERSONALID."
    exit 1
fi

notarize_missing=()
[[ -n "${APPLE_EMAIL:-}" ]] || notarize_missing+=("APPLE_EMAIL")
[[ -n "${APPLE_PASSWORD:-}" ]] || notarize_missing+=("APPLE_PASSWORD")
[[ -n "${APPLE_TEAMID:-}" ]] || notarize_missing+=("APPLE_TEAMID")

SKIP_NOTARIZE=false
case "$TAURI_NOTARIZE_MODE" in
    true)
        if [[ "$SIGN_ARTIFACTS" == false ]]; then
            echo "ERROR: TAURI_NOTARIZE=true requires a codesigning identity."
            exit 1
        fi
        if [[ "${#notarize_missing[@]}" -gt 0 ]]; then
            echo "ERROR: TAURI_NOTARIZE=true but notarization env is missing: ${notarize_missing[*]}"
            exit 1
        fi
        if [[ "$IDENTITY_KIND" == "apple-development" ]]; then
            echo "ERROR: TAURI_NOTARIZE=true requires a Developer ID Application identity, not Apple Development."
            exit 1
        fi
        ;;
    false)
        SKIP_NOTARIZE=true
        ;;
    auto)
        if [[ "$SIGN_ARTIFACTS" == false ]]; then
            echo "[warn] No codesigning identity found; building unsigned DMG and skipping notarization."
            SKIP_NOTARIZE=true
        elif [[ "$IDENTITY_KIND" == "apple-development" ]]; then
            SKIP_NOTARIZE=true
        elif [[ "${#notarize_missing[@]}" -gt 0 ]]; then
            echo "[warn] Notarization env incomplete (${notarize_missing[*]}); skipping notarization."
            SKIP_NOTARIZE=true
        fi
        ;;
esac

if [[ "$SKIP_NOTARIZE" == false ]]; then
    export APPLE_EMAIL APPLE_PASSWORD APPLE_TEAMID
fi

echo "----------------------------------------------"
echo " ActivityWatch Tauri signed DMG build"
echo " Version     : $VERSION"
echo " Arch        : $ARCH"
echo " Sign        : $( [[ "$SIGN_ARTIFACTS" == true ]] && echo "yes" || echo "skip" )"
echo " Identity    : ${APPLE_PERSONALID:-none}"
echo " Watchers    : $TAURI_WATCHERS"
echo " Notarize    : $( [[ "$SKIP_NOTARIZE" == true ]] && echo "skip" || echo "yes" )"
echo "----------------------------------------------"

if [[ "$SKIP_BUILD" == false ]]; then
    echo ""
    echo "[1/5] Building Tauri .app..."
    if [[ -f "$HOME/.nvm/nvm.sh" ]]; then
        echo "[node] Loading nvm from $HOME/.nvm/nvm.sh"
        # shellcheck disable=SC1090
        source "$HOME/.nvm/nvm.sh" || echo "[warn] Failed to source $HOME/.nvm/nvm.sh"
        if command -v nvm >/dev/null 2>&1; then
            nvm use 24 || echo "[warn] nvm could not switch to Node 24; using current PATH"
        else
            echo "[warn] nvm command was not available after sourcing nvm.sh"
        fi
    else
        echo "[node] $HOME/.nvm/nvm.sh not found; using Node from PATH"
    fi
    echo "[node] node path: $(command -v node || echo "not found")"
    node --version || true
    echo "[node] npm path: $(command -v npm || echo "not found")"
    npm --version || true

    if [[ -f "venv/bin/activate" ]]; then
        # shellcheck disable=SC1091
        source "venv/bin/activate"
    fi

    rm -rf "$APP" "$RAW_DMG" "$SIGNED_DMG" "$APP_ZIP" dist/activitywatch-*-macos-*.dmg
    if [[ "$SKIP_PROJECT_BUILD" == false ]]; then
        rm -rf dist/activitywatch
        echo "[1/5] Running make build"
        TAURI_BUILD=true TAURI_WATCHERS="$TAURI_WATCHERS" TAURI_BUNDLES=app make build PYTHON="$PYTHON"
    else
        [[ -d dist/activitywatch ]] || { echo "ERROR: dist/activitywatch not found."; exit 1; }
    fi
    echo "[1/5] Running make dist/ActivityWatch.app"
    TAURI_BUILD=true TAURI_WATCHERS="$TAURI_WATCHERS" make dist/ActivityWatch.app PYTHON="$PYTHON"
else
    echo ""
    echo "[1/5] Skipping build (--skip-build)"
    [[ -d "$APP" ]] || { echo "ERROR: $APP not found."; exit 1; }
fi

echo ""
if [[ "$SIGN_ARTIFACTS" == true ]]; then
    echo "[2/5] Verifying .app signature..."
    codesign --verify --deep --strict --verbose=2 "$APP"
    spctl --assess --type execute --verbose "$APP" 2>&1 || echo "(spctl may fail before notarization; continuing)"
else
    echo "[2/5] Skipping .app signature verification (unsigned build)"
fi

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
if [[ "$SIGN_ARTIFACTS" == true ]]; then
    codesign --force --verbose --timestamp --options runtime -s "$APPLE_PERSONALID" "$RAW_DMG"
else
    echo "[3/5] Skipping DMG signing (unsigned build)"
fi
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
