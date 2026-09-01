from finance_controller.ingestion.detect import FileRole, detect_role


def test_razorpay_recon_headers_detect():
    headers = [
        "entity_id",
        "type",
        "payment_id",
        "order_id",
        "amount",
        "fee",
        "tax",
        "settlement_id",
        "settlement_utr",
        "created_at",
        "settled_at",
        "method",
    ]
    assert detect_role("settlement_recon.csv", headers) == FileRole.RAZORPAY_RECON
    assert detect_role("razorpay_export.csv", headers) == FileRole.RAZORPAY_RECON


def test_existing_roles_unaffected():
    assert detect_role("neft_credits.csv", ["utr", "credited_amount", "credited_date"]) == FileRole.BANK
    assert detect_role("payments.csv", ["payment_id", "amount", "customer"]) == FileRole.LEDGER
    assert detect_role("settlements.csv", ["settlement_id", "payment_ids", "gross_amount"]) == FileRole.PSP
    assert detect_role("gstr.csv", ["invoice_id", "taxable_value", "gst_amount"]) == FileRole.TAX
