# Failure log

Defects found in this repo, including the ones that made the project look better than it was. Each item is the failure, how it was found, and what changed.

## 1. Two matching stories at once

The write-up said “greedy first-claim” in one place and “unique-or-drop” in another. Both cannot be true.

**Fix.** Locked deterministic tier order M → E → T → S. Within a tier, `pair_unambiguous_by_keys`. Tests: same seed twice yields identical groupings; shuffled input yields identical groupings (`tests/test_engine.py`). Match *ids* may move; closed/exception groups must not.

## 2. Validator reimplemented the close gates

`validate_proposed_match` had its own amount and date checks and returned before `_block_close`. GST already used the engine. An agent close could in principle disagree with an engine close on the same numbers.

**Fix.** GST, date, and amount refusals all go through `_block_close`. Messages come from `_gst_block` / `_amounts_ok` / `banking_days_between`. `tests/test_validate.py` traces that the engine predicates actually run.

## 3. GST treated bankers rounding as a second legal value

The matcher accepted half-up *or* bankers, plus 0.05. That is not how the GST line is defined here.

**Fix.** Half-up only. Bankers that differ by 0.01 still pass through `GST_TOLERANCE`, not as an alternate statute. Copy in `exception_agent.py` that still said “half-up nor bankers” was updated.

## 4. Match rate used the wrong denominator

The dashboard divided closed groups by `num_records` (66/80 = 0.825 on seed 42) instead of closed / (closed + leftover) (56/79 = 0.7089). A higher rate, a different question.

**Fix.** `group_match_rate` is closed / (closed + exceptions). Comment in `reporting/report.py` names the old figure so it cannot quietly return.

## 5. Docs said the LLM was the investigator

`scripts/demo.sh` said Gemini investigates leftovers. The default path is rules; the LLM is optional and gated.

**Fix.** Demo copy and README state rules first, model on leftovers, validator always.

## 6. Config imported the agent package

`config.py` imported model-name constants from `agent.llm`. Loading the engine therefore loaded the agent layer, so “the core has no model in it” was false at import time.

**Fix.** Model ids live in `config.py`. `tests/test_architecture_boundary.py` loads `reconciliation.engine` in a subprocess and fails if `finance_controller.agent` is in `sys.modules`.

## 7. Reporting imported the agent to score explanations

`reporting/kpis.py` imported `cites_instance` from `exception_agent`. A metrics module should not depend on the investigator.

**Fix.** Citation helpers live in `reporting/citations.py`. Both sides import that.

## 8. LLM calls had no wall-clock cap

A stalled provider could hang a run until it returned. Rules would never get the leftover.

**Fix.** 12s per call, one retry, then rules finish every open exception. Documented as a bound, not as “unlimited and we are fine with that.”

## 9. A 97% match rate is the same 23 breaks on a bigger file

Keep the seed-42 inject mix (12 / 6 / 16) and raise `num_records` from 80 to 1,000. Closed groups go 56 → 973. Leftovers stay 23. Match rate goes 70.89% → 97.69%. Detection F1 stays 1.0.

The matcher did not get better. The extra 920 payments were clean. Publishing only the 97% figure would have described the dataset, not the engine.

**Fix.** README prints both rows. `tests/test_forecast.py` pins 973 / 23 / 0.9769 / F1=1.0.

## Still true, on purpose

Detection F1 = 1.0 is against labels we generated (or shipped with the fixture). It is not a claim about production recon. Match rate on seed 42 with edges is 70.89% because those edges stay on the queue. N:1 is labelled by `settlement_id`. TDS is not modelled.
