#!/usr/bin/env bash
# Reproduce published figures from a cold clone. No API key.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PYTHON="${ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python3"
fi
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"

echo "== tests =="
"$PYTHON" -m pytest tests -q --tb=line

echo
echo "== published figures =="
"$PYTHON" "${ROOT}/scripts/verify.py"

echo
echo "ok  verify.sh"
