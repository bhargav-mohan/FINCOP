#!/usr/bin/env bash
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
"$PYTHON" "${ROOT}/scripts/demo.py" "$@"
echo
echo "Rules close unambiguous loops. An LLM may investigate leftovers if a key is set. Pass --no-llm for rules only."
echo "Dashboard: cd dashboard && npm install && npm run dev"
