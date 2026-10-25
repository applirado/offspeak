#!/bin/bash
# Started by OffSpeak.app (see setup.sh). Python runs as a child of the app, so macOS asks for the
# microphone and for Accessibility in OffSpeak's name and not in Python's.
root="$(cd "$(dirname "$0")" && pwd)"
log="$HOME/Library/Application Support/Offspeak/launcher.log"
mkdir -p "$(dirname "$log")"
# native: under Rosetta (x86_64) Python cannot load the packages uv installed for Apple Silicon
arch=x86_64
[[ "$(sysctl -n hw.optional.arm64 2>/dev/null)" == 1 ]] && arch=arm64
cd "$root" || exit 1
echo "$(date '+%Y-%m-%d %H:%M:%S') starting ($arch)" >> "$log"
/usr/bin/arch "-$arch" "$root/.venv/bin/python" -m offspeak run >> "$log" 2>&1
status=$?
echo "$(date '+%Y-%m-%d %H:%M:%S') exited with $status" >> "$log"
