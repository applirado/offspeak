#!/usr/bin/env bash
# Installs OffSpeak on macOS for the current user: uv, Python 3.12, all packages, the Parakeet voice model,
# OffSpeak.app (in ~/Applications, or the app this folder lives in) and autostart at login.
# Safe to run again to update or repair. Options: --no-model, --no-autostart, --no-launch.
set -euo pipefail

root="$(cd "$(dirname "$0")" && pwd)"
default_voice_model="parakeet-tdt-0.6b-v3"  # matches Mode.voice_model in config.py
with_model=1 autostart=on launch=1
for arg in "$@"; do
    case "$arg" in
        --no-model) with_model=0 ;;
        --no-autostart) autostart=off ;;
        --no-launch) launch=0 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This setup is for macOS; on Windows run setup.cmd." >&2
    exit 1
fi
if [[ "$(uname -m)" != "arm64" ]]; then
    echo "Warning: OffSpeak is tested on Apple Silicon only; Intel Macs may lack prebuilt packages." >&2
fi

# -- uv (installs and manages Python itself) ------------------------------------
step "Checking for uv"
uv="$(command -v uv || true)"
if [[ -z "$uv" ]]; then
    uv="$HOME/.local/bin/uv"
    if [[ ! -x "$uv" ]]; then
        echo "uv not found, installing it from astral.sh"
        curl -LsSf https://astral.sh/uv/install.sh | sh
    fi
    [[ -x "$uv" ]] || { echo "uv was not installed to $uv; install it from https://docs.astral.sh/uv/ and run setup again." >&2; exit 1; }
fi
"$uv" --version

# -- Python 3.12 and packages ----------------------------------------------------
step "Installing Python 3.12 and OffSpeak's packages (this can take a few minutes the first time)"
pkill -f "$root/.venv/bin/python -m offspeak run" 2>/dev/null || true  # an update replaces files the app uses
(cd "$root" && "$uv" sync --frozen --no-dev)
bin="$root/.venv/bin"

# -- voice model -----------------------------------------------------------------
if [[ $with_model == 1 ]]; then
    step "Checking for the voice model '$default_voice_model'"
    if "$bin/python" -c "import sys; from offspeak import models; from offspeak.config import Config; \
sys.exit(0 if '$default_voice_model' in models.voice_models(Config().settings.model_dirs()) else 1)"; then
        echo "Already installed."
    else
        echo "Downloading '$default_voice_model'"
        "$bin/offspeak" download-model "$default_voice_model"
    fi
fi

# -- OffSpeak.app ------------------------------------------------------------------
# A small app that starts OffSpeak from this folder. It is built here, not downloaded, so Gatekeeper does
# not block it, and macOS asks for microphone and Accessibility permission in OffSpeak's name.
if [[ "$root" == */OffSpeak.app/Contents/Resources/* ]]; then
    app="${root%%/OffSpeak.app/*}/OffSpeak.app"  # install.sh keeps the code inside the app
else
    app="$HOME/Applications/OffSpeak.app"
fi
step "Building $app"
version="$(sed -n 's/^version = "\(.*\)"/\1/p' "$root/pyproject.toml")"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cat > "$app/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>OffSpeak</string>
    <key>CFBundleDisplayName</key><string>OffSpeak</string>
    <key>CFBundleIdentifier</key><string>com.applirado.offspeak</string>
    <key>CFBundleExecutable</key><string>OffSpeak</string>
    <key>CFBundleIconFile</key><string>OffSpeak</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>$version</string>
    <key>CFBundleVersion</key><string>$version</string>
    <key>LSMinimumSystemVersion</key><string>12.0</string>
    <key>LSUIElement</key><true/>
    <key>NSMicrophoneUsageDescription</key>
    <string>OffSpeak records your voice while you hold Option+Space and turns it into text on this Mac.</string>
</dict>
</plist>
EOF
cat > "$app/Contents/MacOS/OffSpeak" <<EOF
#!/bin/bash
# Starts OffSpeak from $root. Python runs as a child process, so macOS keeps treating
# OffSpeak.app as the app that asks for the microphone and for Accessibility.
export OFFSPEAK_APP="$app"
cd "$root" || exit 1
"$bin/python" -m offspeak run
EOF
chmod +x "$app/Contents/MacOS/OffSpeak"
"$bin/python" -c "from offspeak.icons import icon_image; icon_image('ready', 1024).save('$app/Contents/Resources/OffSpeak.icns')"
touch "$app"  # so Finder and the Dock pick up the new icon

step "Configuring autostart"
OFFSPEAK_APP="$app" "$bin/offspeak" autostart "$autostart"

printf '\n\033[32mOffSpeak is installed.\033[0m\n'
cat <<EOF

Hold Option+Space in any app, talk, let go. The first time, macOS asks for:
  - Accessibility: open System Settings > Privacy & Security > Accessibility and turn on OffSpeak,
    so it can see the shortcut and paste the text
  - the microphone, when you dictate for the first time
OffSpeak lives in the menu bar (the cockatoo). To remove it, quit it there and drag
$app to the Bin.
EOF

if [[ $launch == 1 ]]; then
    open "$app"
fi
