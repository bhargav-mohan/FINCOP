import csv

from finance_controller.agent.orchestrator import orchestrate
from finance_controller.config import ReconConfig
from finance_controller.data.csv_batch import load_csv_batch, write_csv_batch
from finance_controller.data.synthetic import generate
from finance_controller.ingestion.pipeline import ingest_zip
from finance_controller.models import ExpectedStatus
from finance_controller.reconciliation.engine import predicted_exception_keys, reconcile
from finance_controller.reporting.report import compute_accuracy
from finance_controller.run_finance_controller import execute_loop, generated_config, run_finance_controller


def test_external_csv_batch_reconciles(csv_fixture_dir):
    batch = load_csv_batch(csv_fixture_dir)
    assert len(batch.ledger) >= 50
    assert batch.bank
    assert batch.psp
    config = ReconConfig(date_lag_days=5, use_llm=False)
    result = reconcile(batch.all_records, config)
    assert result.closed_group_count >= 1
    assert result.exceptions
    metrics = compute_accuracy(batch.ground_truth, result)
    actual = {g.key for g in batch.ground_truth if g.expected_status == ExpectedStatus.EXCEPTION}
    predicted = predicted_exception_keys(result)
    assert actual
    assert metrics.false_negatives == 0
    assert metrics.recall == 1.0
    # This dataset labels duplicates under plain keys, so the scorer must not
    # invent "#dup" keys for conflicts where no primary loop closed.
    assert predicted - actual == set(), f"over-flagged: {sorted(predicted - actual)}"
    assert metrics.precision == 1.0
    assert metrics.f1 == 1.0
    agg = [g for g in batch.ground_truth if g.defect == "aggregated"]
    assert agg
    assert all("|" not in g.key for g in agg)
    assert {g.key for g in agg} <= {r.batch_id for r in batch.bank if r.batch_id}


def test_external_csv_agent_cannot_close_a_utr_conflict(csv_fixture_dir):
    """The agent found a completing bank candidate for a UTR reused across two
    settlements. _block_close now gates on the duplicate_utr flag, so the
    validator refuses what the engine would have refused."""
    batch = load_csv_batch(csv_fixture_dir)
    config = ReconConfig(num_records=max(len(batch.ledger), 80), date_lag_days=5, use_llm=False)
    result = reconcile(batch.all_records, config)
    before = predicted_exception_keys(result)
    actual = {g.key for g in batch.ground_truth if g.expected_status == ExpectedStatus.EXCEPTION}
    orchestrate(result, config)
    after = predicted_exception_keys(result)
    metrics = compute_accuracy(batch.ground_truth, result)
    assert (before & actual) - after == set(), "agent must not close a labelled exception"
    assert metrics.recall == 1.0
    assert metrics.false_negatives == 0


def test_bank_reload_groups_by_payment_reference_not_utr(tmp_path):
    (tmp_path / "payments.csv").write_text(
        "payment_id,amount,customer,timestamp,status,currency\n"
        "TXN-0001,100.00,ACME,2026-01-01,success,INR\n",
        encoding="utf-8",
    )
    (tmp_path / "settlements.csv").write_text(
        "settlement_id,payment_ids,gross_amount,mdr_fee,gst_on_fee,net_amount,utr,settled_date,currency\n"
        "S1,TXN-0001,100.00,2.00,0,98.00,UTR0000000000001,2026-01-02,INR\n",
        encoding="utf-8",
    )
    (tmp_path / "bank.csv").write_text(
        "payment_reference,batch_id,utr,credited_amount,credited_date,raw_description,currency,customer\n"
        "TXN-0001,,UTR!!,98.00,2026-01-02,bank ACME,INR,ACME\n"
        "TXN-0001,,UTR0000000000001A,49.00,2026-01-02,split A,INR,ACME\n"
        "BATCH-01,BATCH-01,UTR0000000000099,10.00,2026-01-02,bank SETTLEMENT,INR,SETTLEMENT\n",
        encoding="utf-8",
    )
    batch = load_csv_batch(tmp_path)
    by_utr = {r.utr: r for r in batch.bank}
    assert by_utr["UTR!!"].reference == "TXN-0001"
    assert by_utr["UTR!!"].batch_id is None
    assert by_utr["UTR0000000000001A"].reference == "TXN-0001"
    assert by_utr["UTR0000000000099"].reference == "BATCH-01"
    assert by_utr["UTR0000000000099"].batch_id == "BATCH-01"


def test_generate_csv_roundtrip_agrees_with_in_memory(tmp_path):
    config = generated_config(seed=42, num_records=80, use_llm=False)
    mem = generate(config)
    write_csv_batch(mem, tmp_path)
    with (tmp_path / "bank.csv").open(encoding="utf-8") as fh:
        headers = next(csv.reader(fh))
    assert "payment_reference" in headers
    assert "batch_id" in headers
    assert "utr" in headers

    loaded = load_csv_batch(tmp_path)
    mem_keys = sorted((r.reference, r.batch_id or "", r.utr) for r in mem.bank)
    load_keys = sorted((r.reference, r.batch_id or "", r.utr) for r in loaded.bank)
    assert mem_keys == load_keys
    assert len(mem.all_records) == len(loaded.all_records)
    assert len(loaded.ground_truth) == len(mem.ground_truth)
    assert {g.key for g in loaded.ground_truth} == {g.key for g in mem.ground_truth}
    assert {(r.reference, r.split_id) for r in mem.bank} == {(r.reference, r.split_id) for r in loaded.bank}

    r_mem = execute_loop(config, mem).result
    r_csv = execute_loop(config, loaded).result
    mem_total = r_mem.closed_group_count + len(r_mem.exceptions)
    csv_total = r_csv.closed_group_count + len(r_csv.exceptions)
    assert mem_total == csv_total
    assert r_mem.closed_group_count == r_csv.closed_group_count

    ingested = ingest_zip(tmp_path)
    assert len(ingested.batch.all_records) == len(mem.all_records)
    dash = run_finance_controller(zip_path=str(tmp_path), use_llm=False, match_tax=False)
    assert dash["matched"] == r_mem.closed_group_count
    assert dash["total_groups"] == mem_total
