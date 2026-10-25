#!/usr/bin/env bash
# Installs or updates the OffSpeak preview for macOS:
#     curl -fsSL https://raw.githubusercontent.com/applirado/offspeak/macos/install.sh | bash
# Downloads the source code into ~/Applications/OffSpeak.app/Contents/Resources/offspeak and runs its setup.sh,
# which installs uv, Python, the packages and the voice model for the current user. No admin rights needed.
set -euo pipefail

branch="${OFFSPEAK_BRANCH:-macos}"  # the macOS preview lives on this branch until it is released
app="$HOME/Applications/OffSpeak.app"
code="$app/Contents/Resources/offspeak"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

if [[ -n "${OFFSPEAK_SOURCE_TAR:-}" ]]; then  # for tests: a local .tar.gz of the source tree
    cp "$OFFSPEAK_SOURCE_TAR" "$tmp/offspeak.tar.gz"
else
    echo "Downloading OffSpeak ($branch)"
    curl -fsSL "https://github.com/applirado/offspeak/archive/refs/heads/$branch.tar.gz" -o "$tmp/offspeak.tar.gz"
fi

# replace the code, keep .venv so an update does not download all packages again
mkdir -p "$code"
rm -rf "$code/src"
tar -xzf "$tmp/offspeak.tar.gz" -C "$code" --strip-components 1

bash "$code/setup.sh"
