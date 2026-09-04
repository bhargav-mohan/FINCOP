# Architecture

Deterministic code owns financial truth. The agent proposes and explains. It cannot book cash.

## Layers

```
ingestion → normalize → match tiers → _block_close → leftovers
                                              ↓
                                    rule investigator
                                              ↓
                                    optional LLM (12s cap)
                                              ↓
                                    validate_proposed_match → _block_close
                                              ↓
                                    report / dashboard / read-only Q&A
```

The core (`reconciliation/`, `ingestion/`, `razorpay/`, `tax_matching/validate.py`, `qa/`) must not import `finance_controller.agent`. `tests/test_architecture_boundary.py` walks the AST and loads the engine in a clean subprocess.

`python -m finance_controller.qa` reads a frozen `Report`. It has no import of the engine close path and no tool that writes `closed_record_ids`.

## Matching contract

Tiers, in this order: **M → E → T → S** (`many_to_one`, `exact`, `tolerant`, `one_to_many`).

Within a tier, a pair must be unique on both sides. Ambiguous keys are dropped, not first-claimed. Competing banks sort by record id. Same records produce the same closed/exception *groupings*; match ids (`E0001`) may move if the input list is shuffled.

A **close** is:

- 1 bank + 1 ledger + 1 PSP, or
- 1 bank + N PSP + N ledger (batched settlement), or
- N banks + 1 ledger + 1 PSP (split credits)

then `_block_close`: GST half-up 18% of MDR (±0.05), banking-day window, amounts, UTR, status.

`validate_proposed_match` does not reimplement those gates. It calls `_block_close` and explains the hit with the same predicates.

## Batched settlement (N:1)

Razorpay pays out many captured payments as one NEFT. The recon export already prints `settlement_id` on every line. We group by that id, sum PSP nets, and compare to the bank credit.

That is labelled N:1, not naked N:1. Decomposing a single bank credit with no settlement id — refunds and chargebacks already netted in, paise traps on per-line tolerance — is not built. Unconstrained subset-sum on amounts is how two unrelated ₹10,000 settlements on the same day become a false match. We refuse that.

1:N (one booking, several bank credits) is implemented as `one_to_many`.

## Forward cash

Open ledger rows are projected forward by `date_lag_days` banking days from their txn date. Amounts due after the batch's latest date sit in `due_within_window`; amounts that should already have landed sit in `stuck_past_window`. `as_of` is the statement date in the file, not wall-clock today.

## GST

Half-up to paise. `GST_TOLERANCE = 0.05`. Bankers rounding that lands 0.01 away still passes *via tolerance*, not as a second statutory value.

TDS under s.194-O / 393 is not in this control plane.

## Investigator

Rules try unique leftover completions first (narration-only bank lines that still form one cash loop). The LLM, if enabled, may call `reconcile`. The workbench always validates and always refuses competing alternatives. A model that says “close it” against an amount break gets `ok: false` and the group stays open.

## Operator surfaces

- CLI report: match rate, detection P/R/F1, cash buckets, every exception.
- Dashboard: ZIP upload, rupee books, leftovers, notes, aging, append-only SQLite audit.
- Q&A: retrieve figures from `report.json`. Mutation phrasing is refused.
