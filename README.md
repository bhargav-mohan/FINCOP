# AI Finance Controller

Python CLI that closes a multi-source reconciliation loop over a 50+ record batch (ledger, bank, PSP), then prints match rate, an honest exception list, and detection accuracy vs ground truth.

## Demo

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
./scripts/demo.sh
```

That command ingests the in-repo Razorpay Settlement Recon fixture (`fixtures/razorpay_sample/batch.zip`), runs the unchanged matching engine plus gated investigator, and writes `report.json` / exception+match CSVs. Match rate, the value block (auto-closed vs sent to analyst, estimated minutes saved), and every unresolved item are printed.

Dashboard (same review, plus ZIP upload and CSV/JSON download):

```bash
cd dashboard && npm install && npm run dev
```

That serves a production build on port 3000 (no hot-reload websocket). For live UI edits use `npm run watch` instead.

Upload `fixtures/razorpay_sample/batch.zip` on the page. The dashboard does not generate sample data — it only reviews what you upload.

## Razorpay integration

This is an **adapter**, not a live payout integration. It maps a Razorpay Settlement Recon export (same columns as `GET /v1/settlements/recon/combined`) onto the existing canonical bank / ledger / PSP files.

The join key is **`settlement_id`** (the Razorpay payout batch). `settlement_utr` is the correspondent-bank NEFT reference — useful as a bank narration, not the primary match key.

| Razorpay field | Canonical field |
| --- | --- |
| `entity_id` / `payment_id` | ledger `payment_id` |
| `amount` (paise) | ledger amount / PSP gross |
| `fee` + `tax` | PSP `mdr_fee` + `gst_on_fee` (tax stripped out of fee when included) |
| `credit` − `debit` | PSP net / bank credited amount (one NEFT per `settlement_id`) |
| `settlement_id` | PSP `settlement_id` / batch grouping |
| `settlement_utr` | bank `utr` |
| `created_at` / `settled_at` | ledger timestamp / bank credited date |
| `type=adjustment\|transfer` | skipped with a warning (not silent) |

You do **not** need Razorpay API keys. The demo and tests ingest `fixtures/razorpay_sample/` (real recon column names, synthetic rows). `--razorpay-live` exists only if you later add test keys (`rzp_test_…`); without keys it uses the same fixture and never calls the network.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m finance_controller.cli --seed 42 --num-records 80 --inject-exceptions 12 --inject-resolvable 6 --inject-edges 16 --out report

# Razorpay recon ZIP
python -m finance_controller.cli --razorpay-zip fixtures/razorpay_sample/batch.zip --no-llm --out report

# or against CSV dumps (payments.csv, settlements.csv, bank.csv, optional ground_truth.json)
python -m finance_controller.cli --data-dir fixtures/finance_synthetic_data --no-llm --out report
```

## Accuracy

Exception detection is exact — precision, recall and F1 all 1.0, with zero false positives and zero false negatives — on the Razorpay recon fixture, the external CSV dump, and eight seeded configurations from 50 to 200 records. `tests/test_accuracy.py` asserts this on every configuration, so a regression fails the suite rather than quietly lowering the number.

Each run also prints four evaluation bars:

- **Matches correct** (`match_precision`) — of the loops the engine closed, the share whose ground-truth label is MATCHED. Target **≥90%**. Closing an injected exception drops this; leaving it on the queue does not.
- **Exceptions reduced** — engine leftovers minus items still open after the investigator.
- **Processing speed** — wall time for match + investigate (`elapsed_ms`).
- **Explanation precision** — share of flagged items whose explanation cites that row (refs/amounts/reason) and matches the labeled type when ground truth has one. Target **≥90%**.

Match *rate* (closed / closed+leftover) is a different number and can sit below 90% when the batch is mostly real breaks. Unresolved items are reported, never auto-passed.

Two stages produce that figure. The deterministic engine must never miss an exception (recall 1.0 before the agent runs). The agent then recovers the cases the deterministic tiers cannot see — a settled payout whose UTR is absent from the export, identifiable only from the bank narration — and every close it proposes has to pass `validate_proposed_match` first. Match rate is lower than detection accuracy by design: an unresolved item is reported, never auto-passed.

## API key (keep this off GitHub)

Copy `.env.example` to `.env`. For GLM 5.2 set `LLM_PROVIDER=glm` and `OPENROUTER_API_KEY` (OpenRouter `sk-or-v1-…` key) with `GLM_MODEL=z-ai/glm-5.2`. Direct Z.ai uses `ZAI_API_KEY` and `GLM_MODEL=glm-5.2`. Gemini still works with `LLM_PROVIDER=gemini` and `GEMINI_API_KEY`. `.env` is gitignored. Without a key the agent still runs using the rule investigator.

If an API key has ever been pasted into chat or a ticket, rotate it before you push.

LLM calls have no wall-clock cap. One retry is allowed for a transient blip; a second failure hands over to the rule investigator, which still investigates every exception. A stalled provider can hang the run until it returns.

## Local history (SQLite)

Run history, exception aging, notes, and the append-only audit trail live in a SQLite file. `sqlite3` is in the Python standard library — there is no service to start and no extra dependency.

The file is created on first run at `data/finance_controller.db` (override with `FC_DB_PATH`). Reset with `rm data/finance_controller.db`. The db file and its WAL sidecars are gitignored.

Amounts are stored as decimal text, never floats, so money round-trips exactly. `audit_events` is append-only, enforced by SQLite triggers rather than by convention — an `UPDATE` or `DELETE` is rejected by the database. Writes are opened WAL with a 5s busy timeout, so the several Python processes a dashboard session spawns can overlap without a "database is locked" failure; SQLite is still single-writer, which is enough for one analyst and a demo, not a multi-user production queue.

`pytest` never touches this file — `tests/conftest.py` redirects every test to its own temporary database, so running the suite cannot inflate your aging counts or pollute the audit trail.

CI can fail a regression instead of printing a number:

```bash
python -m finance_controller.cli --razorpay-zip fixtures/razorpay_sample/batch.zip --no-llm --fail-under 1.0 --out report
```

## Where AI is used — and where it is not

The matching engine, GST/date/amount checks, and the close itself are **never** an LLM. A model cannot book cash.

AI runs on leftovers after rules. Matching, GST/date/amount checks, and the close itself are never an LLM — a model cannot book cash. GLM 5.2 (or Gemini) may propose a close; `validate_proposed_match` must accept it or the item stays on the exception list. Pass CLI `--no-llm` or dashboard `?useLlm=0` for rules only. Narration-only bank lines that still form a unique cash loop are closed by the **rule investigator**, not by a model.

## Tests

```bash
pytest
```
