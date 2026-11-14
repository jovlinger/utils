#!/usr/bin/env bash
# Print path to PlatformIO CLI. Prefer SPINME_PIO, then spinme/.venv-tools.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -n "${SPINME_PIO:-}" ]]; then
  echo "$SPINME_PIO"
  exit 0
fi
if [[ -x "$ROOT/.venv-tools/bin/pio" ]]; then
  echo "$ROOT/.venv-tools/bin/pio"
  exit 0
fi
# Worktree: reuse main-checkout tools when present.
CANDIDATES=(
  "$HOME/github.com/jovlinger/utils/spinme/.venv-tools/bin/pio"
)
for c in "${CANDIDATES[@]}"; do
  if [[ -x "$c" ]]; then
    echo "$c"
    exit 0
  fi
done
echo "pio not found; set SPINME_PIO or create spinme/.venv-tools" >&2
exit 1
