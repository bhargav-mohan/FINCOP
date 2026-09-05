#!/usr/bin/env bash
# Reproduce published figures from a cold clone. No API key.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PYTHON=""
if [[ -x "${ROOT}/.venv/Scripts/python.exe" ]]; then
  PYTHON="${ROOT}/.venv/Scripts/python.exe"
elif [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PYTHON="${ROOT}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  PYTHON="python"
fi
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

echo "== tests =="
"$PYTHON" -m pytest tests -q --tb=line

echo
echo "== published figures =="
"$PYTHON" "${ROOT}/scripts/verify.py"

echo
echo "ok  verify.sh"
