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
    result = subprocess.run(
        ["npm", "test"],
        cwd=DASHBOARD,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
