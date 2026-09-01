#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PYTHON="${ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python3"
fi
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
"$PYTHON" -m finance_controller.cli \
  --razorpay-zip fixtures/razorpay_sample/batch.zip \
  --no-llm \
  --out report
echo
echo "Investigator used rules (no LLM). Same default as the dashboard. Pass --use-llm or ?useLlm=1 to opt in."
echo "Dashboard: cd dashboard && npm install && npm run dev"
