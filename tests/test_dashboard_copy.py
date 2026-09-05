import shutil
from pathlib import Path
import subprocess


FORMAT_TS = Path(__file__).resolve().parents[1] / "dashboard" / "lib" / "format.ts"
DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard"


def _friendly_warning_src() -> str:
    text = FORMAT_TS.read_text(encoding="utf-8")
    start = text.index("export function friendlyWarning")
    end = text.index("export function csvEscape")
    return text[start:end]


def test_not_settled_is_classified_before_any_not_set_heuristic():
    src = _friendly_warning_src()
    assert 'includes("not settled")' in src
    assert src.index("not settled") < src.index("gemini_api_key")
    assert 'includes("not set")' not in src


def test_gemini_key_warning_still_matches_explicit_key_errors():
    src = _friendly_warning_src()
    assert "gemini_api_key" in src
    assert "openrouter_api_key" in src
    assert "openai_api_key" in src
    assert "anthropic_api_key" in src
    assert "api key" in src


def test_page_streams_review_behind_inner_suspense():
    assert not (DASHBOARD / "app" / "loading.tsx").exists()
    src = (DASHBOARD / "app" / "page.tsx").read_text(encoding="utf-8")
    assert "Suspense" in src
    assert "ReviewPending" in src
    assert "ReviewRun" in src
    assert "KpiStrip" in (DASHBOARD / "components" / "ReviewRun.tsx").read_text(encoding="utf-8")
    assert "CashBooks" in (DASHBOARD / "components" / "ReviewRun.tsx").read_text(encoding="utf-8")
    assert "requestId" in src
    assert "force-no-store" in src


def test_file_picker_replaces_selection_instead_of_merging():
    src = (DASHBOARD / "components" / "ZipUpload.tsx").read_text(encoding="utf-8")
    assert "setFiles(Array.from(e.target.files))" in src
    assert src.count("mergeFiles") == 2
    assert "next.set(\"n\"" in src or "next.set('n'" in src
    npm = shutil.which("npm")
    assert npm, "npm is not on PATH"
    result = subprocess.run(
        [npm, "test"],
        cwd=DASHBOARD,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_cash_and_quality_labels_do_not_restate_engine_closes():
    cash = (DASHBOARD / "components" / "CashBooks.tsx").read_text(encoding="utf-8")
    assert "Bank credited includes unmatched statement rows" in cash
    assert "fees on closed loops" in cash
    quality = (DASHBOARD / "components" / "AccuracyPanel.tsx").read_text(encoding="utf-8")
    assert "Of the {openBefore} open items" in quality
    assert "investigator added" in quality
    assert "Explanation precision" not in quality
    assert "Rules alone" not in quality
    assert "Est. minutes saved" not in quality
    strip = (DASHBOARD / "components" / "KpiStrip.tsx").read_text(encoding="utf-8")
    assert strip.count("Matches correct") == 0
    assert "Explanations right" in strip
    verdict = (DASHBOARD / "components" / "Verdict.tsx").read_text(encoding="utf-8")
    assert "Time saved" not in verdict


def test_dashboard_finds_the_windows_venv_python():
    src = (DASHBOARD / "lib" / "runFinanceController.ts").read_text(encoding="utf-8")
    assert 'Scripts", "python.exe"' in src
    assert 'platform === "win32"' in src
    serve = (DASHBOARD / "scripts" / "serve.cjs").read_text(encoding="utf-8")
    assert '"next", "dist", "bin", "next"' in serve
    assert "process.execPath" in serve
