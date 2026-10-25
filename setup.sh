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
# macOS grants the microphone and Accessibility to the app that started a process. With a script as the
# app's program, it cannot tell which app that is and asks for Python instead. So OffSpeak.app is a tiny
# AppleScript program (osacompile comes with macOS) that runs launch-macos.sh, and Python is its child.
# It is built here, not downloaded, so Gatekeeper does not block it. It only changes when this folder
# moves, because a changed app loses the permissions the user gave it.
app="$HOME/Applications/OffSpeak.app"
plist="$app/Contents/Info.plist"
chmod +x "$root/launch-macos.sh"
if [[ -d "$app/Contents/Resources/offspeak" ]]; then
    rm -rf "$app"  # built by the first preview, with the code inside the app
fi
if [[ "$(cat "$app/Contents/Resources/offspeak-root" 2>/dev/null)" != "$root" ]]; then
    step "Building $app"
    rm -rf "$app"
    mkdir -p "$(dirname "$app")"
    osacompile -o "$app" -e "do shell script quoted form of \"$root/launch-macos.sh\""
    plutil -replace CFBundleIdentifier -string com.applirado.offspeak "$plist"
    plutil -replace CFBundleName -string OffSpeak "$plist"
    plutil -replace LSUIElement -bool true "$plist"
    plutil -replace NSMicrophoneUsageDescription -string \
        "OffSpeak records your voice while you hold Option+Space and turns it into text on this Mac." "$plist"
    plutil -remove CFBundleIconName "$plist" 2>/dev/null || true  # use applet.icns, not the asset catalog
    rm -f "$app/Contents/Resources/Assets.car"
    "$bin/python" -c "from offspeak.icons import icon_image; icon_image('ready', 1024).save('$app/Contents/Resources/applet.icns')"
    echo "$root" > "$app/Contents/Resources/offspeak-root"
    codesign --force --sign - "$app"  # ad hoc, on this Mac; editing the app broke osacompile's signature
    touch "$app"  # so Finder and the Dock pick up the new icon
fi

step "Configuring autostart"
OFFSPEAK_APP="$app" "$bin/offspeak" autostart "$autostart"

printf '\n\033[32mOffSpeak is installed.\033[0m\n'
cat <<EOF

Hold Option+Space in any app, talk, let go. The first time, macOS asks for:
  - Accessibility: open System Settings > Privacy & Security > Accessibility and turn on OffSpeak,
    so it can see the shortcut and paste the text
  - the microphone, when you dictate for the first time
OffSpeak lives in the menu bar (the cockatoo). To remove it, quit it there, drag $app
to the Bin and delete ~/Library/LaunchAgents/com.applirado.offspeak.plist.
EOF

if [[ $launch == 1 ]]; then
    open "$app"
fi
