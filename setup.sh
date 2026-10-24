#!/usr/bin/env bash
# Installs Offspeak on macOS for the current user: uv, Python 3.12, all packages and the Parakeet voice model.
# Safe to run again to update or repair. Options: --no-model (skip the voice model download).
set -euo pipefail

root="$(cd "$(dirname "$0")" && pwd)"
default_voice_model="parakeet-tdt-0.6b-v3"  # matches Mode.voice_model in config.py
with_model=1
for arg in "$@"; do
    case "$arg" in
        --no-model) with_model=0 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This setup is for macOS; on Windows run setup.cmd." >&2
    exit 1
fi
if [[ "$(uname -m)" != "arm64" ]]; then
    echo "Warning: Offspeak is tested on Apple Silicon only; Intel Macs may lack prebuilt packages." >&2
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
step "Installing Python 3.12 and Offspeak's packages (this can take a few minutes the first time)"
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

printf '\n\033[32mOffspeak is installed.\033[0m\n'
cat <<EOF

Try it in the terminal (the menu bar app follows later):

  $bin/offspeak listen

macOS asks once for microphone access for your terminal app; allow it, then run the command again.
EOF
