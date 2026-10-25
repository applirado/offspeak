#!/usr/bin/env bash
# Installs or updates OffSpeak on macOS (preview, Apple Silicon):
#     curl -fsSL https://applirado.github.io/offspeak/install.sh | bash
# Downloads the source code of the latest release into ~/Library/Application Support/Offspeak/app and runs its
# setup.sh, which installs uv, Python, the packages and the voice model for the current user and builds
# ~/Applications/OffSpeak.app. No admin rights needed.
set -euo pipefail

code="$HOME/Library/Application Support/Offspeak/app"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

if [[ -n "${OFFSPEAK_SOURCE_TAR:-}" ]]; then  # for tests: a local .tar.gz of the source tree
    cp "$OFFSPEAK_SOURCE_TAR" "$tmp/offspeak.tar.gz"
else
    if [[ -n "${OFFSPEAK_BRANCH:-}" ]]; then  # for trying out a branch
        ref="heads/$OFFSPEAK_BRANCH"
    else
        tag="$(curl -fsSL https://api.github.com/repos/applirado/offspeak/releases/latest |
            sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p')"
        [[ -n "$tag" ]] || { echo "Could not find the latest OffSpeak release." >&2; exit 1; }
        ref="tags/$tag"
    fi
    echo "Downloading OffSpeak (${ref#*/})"
    curl -fsSL "https://github.com/applirado/offspeak/archive/refs/$ref.tar.gz" -o "$tmp/offspeak.tar.gz"
fi

# replace the code, keep .venv so an update does not download all packages again
mkdir -p "$code"
rm -rf "$code/src"
tar -xzf "$tmp/offspeak.tar.gz" -C "$code" --strip-components 1

bash "$code/setup.sh"
