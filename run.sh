#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Error: virtual env not found at $VENV_DIR" >&2
    exit 1
fi

export PATH="$VENV_DIR/bin:$PATH"

# stockpush 使用 -m 方式运行（与 systemd service 一致）
exec python3 -m stockpush.worker "$@"
