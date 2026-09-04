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
  --out report
echo
echo "Rules close unambiguous loops. An LLM may investigate leftovers if a key is set. Pass --no-llm for rules only."
echo "Dashboard: cd dashboard && npm install && npm run dev"
