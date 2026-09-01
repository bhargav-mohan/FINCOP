from finance_controller.razorpay.live_fetch import fetch_recon


def test_live_fetch_falls_back_without_keys(monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)

    def _fail(*_a, **_k):  # pragma: no cover
        raise AssertionError("must not hit the network without keys")

    monkeypatch.setattr("finance_controller.razorpay.live_fetch.urlopen", _fail)
    result = fetch_recon()
    assert result.source == "fixture"
    assert result.rows
    assert any("not set" in w or "offline fixture" in w for w in result.warnings)
    assert result.zip_path is not None
    assert result.zip_path.exists()


def test_live_fetch_refuses_non_test_key(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_not_allowed")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "secret")

    def _fail(*_a, **_k):  # pragma: no cover
        raise AssertionError("must not hit the network with a live key")

    monkeypatch.setattr("finance_controller.razorpay.live_fetch.urlopen", _fail)
    result = fetch_recon()
    assert result.source == "fixture"
    assert any("test key" in w for w in result.warnings)
