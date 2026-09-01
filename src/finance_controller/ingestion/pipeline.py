from __future__ import annotations

from dataclasses import dataclass, field
import csv
import json
from pathlib import Path
import tempfile

import zipfile

from finance_controller.data.csv_batch import apply_ground_truth, load_csv_batch, normalize_truth_rows
from finance_controller.data.synthetic import SyntheticBatch
from finance_controller.ingestion.detect import CANONICAL_NAMES, FileRole, detect_role
from finance_controller.ingestion.normalize import fill_psp_from_payments, remap_row, write_canonical
from finance_controller.ingestion.validate import validate_detected, validate_rows
from finance_controller.ingestion.xlsx import explode_xlsx, is_xlsx_package
from finance_controller.ingestion.zipfile_extract import IngestError, extract_zip
from finance_controller.razorpay.adapter import razorpay_recon_to_canonical, write_adapted_canonical
from finance_controller.tax_matching.models import TaxLine


@dataclass
class IngestResult:
    batch: SyntheticBatch
    tax_lines: list[TaxLine] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    work_dir: str = ""


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            with path.open(newline="", encoding=encoding) as fh:
                reader = csv.DictReader(fh)
                headers = list(reader.fieldnames or [])
                rows = list(reader)
            return headers, rows
        except UnicodeDecodeError as exc:
            last_error = exc
    raise IngestError(f"could not decode CSV {path.name}") from last_error


def _truth_payload(path: Path) -> list | dict:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    _, rows = _read_csv(path)
    return rows


def _iter_seed_files(src: Path) -> list[Path]:
    if src.is_file():
        return [src]
    return [
        path
        for path in src.rglob("*")
        if path.is_file()
        and not path.name.startswith(".")
        and "_expanded" not in path.parts
    ]


def _expand_one(path: Path, dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".xlsx", ".xlsm"} or is_xlsx_package(path):
        return explode_xlsx(path, dest)
    if zipfile.is_zipfile(path):
        nested: list[Path] = []
        for j, child in enumerate(extract_zip(path, dest / "zip")):
            nested.extend(_expand_one(child, dest / f"n{j}"))
        return nested
    return [path]


def collect_ingest_files(src: Path, dest: Path) -> list[Path]:
    """Flatten a zip, xlsx, folder, or loose files into CSVs/JSON the role detector can read."""
    dest.mkdir(parents=True, exist_ok=True)
    expand_root = dest / "_expanded"
    out: list[Path] = []
    for i, path in enumerate(_iter_seed_files(src)):
        out.extend(_expand_one(path, expand_root / f"s{i}"))
    if not out:
        raise IngestError("upload contained no usable files")
    return out


def ingest_zip(zip_path: str | Path, *, work_dir: str | Path | None = None) -> IngestResult:
    dest = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="fc-ingest-"))
    files = collect_ingest_files(Path(zip_path), dest)
    assigned: dict[FileRole, Path] = {}
    warnings: list[str] = []
    for path in files:
        if path.suffix.lower() == ".json":
            role = detect_role(path.name)
            if role == FileRole.GROUND_TRUTH:
                if role in assigned:
                    raise IngestError(f"duplicate {role.value} file: {path.name}")
                assigned[role] = path
            continue
        if path.suffix.lower() != ".csv":
            if path.name.lower().startswith("readme"):
                continue
            warnings.append(f"skipped non-csv file: {path.name}")
            continue
        headers, _ = _read_csv(path)
        role = detect_role(path.name, headers)
        if role == FileRole.UNKNOWN:
            if path.stem.lower().startswith("readme"):
                continue
            warnings.append(f"skipped unknown-role file: {path.name}")
            continue
        if role in assigned:
            raise IngestError(f"duplicate {role.value} file: {path.name}")
        assigned[role] = path

    warnings.extend(validate_detected(assigned))
    canon_dir = dest / "canonical"
    canon_dir.mkdir(exist_ok=True)

    files_meta: dict[str, str] = {}
    if FileRole.RAZORPAY_RECON in assigned:
        recon_src = assigned[FileRole.RAZORPAY_RECON]
        files_meta[FileRole.RAZORPAY_RECON.value] = recon_src.name
        _, recon_rows = _read_csv(recon_src)
        if not recon_rows:
            raise IngestError("razorpay recon file has no data rows")
        adapted = razorpay_recon_to_canonical(recon_rows)
        warnings.extend(adapted.warnings)
        write_adapted_canonical(canon_dir, adapted)
        batch = adapted.batch
        gt = assigned.get(FileRole.GROUND_TRUTH)
        if gt is not None:
            files_meta[FileRole.GROUND_TRUTH.value] = gt.name
            payload = _truth_payload(gt)
            (canon_dir / CANONICAL_NAMES[FileRole.GROUND_TRUTH]).write_text(
                json.dumps(normalize_truth_rows(payload)),
                encoding="utf-8",
            )
            apply_ground_truth(batch, payload)
        tax_src = assigned.get(FileRole.TAX)
        if tax_src is not None:
            files_meta[FileRole.TAX.value] = tax_src.name
            _, tax_rows = _read_csv(tax_src)
            mapped_tax = [remap_row(FileRole.TAX, row) for row in tax_rows]
            validate_rows(FileRole.TAX, mapped_tax)
            write_canonical(canon_dir / CANONICAL_NAMES[FileRole.TAX], FileRole.TAX, mapped_tax)
    else:
        raw: dict[FileRole, list[dict[str, str]]] = {}
        for role, src in assigned.items():
            files_meta[role.value] = src.name
            if role == FileRole.GROUND_TRUTH:
                payload = _truth_payload(src)
                (canon_dir / CANONICAL_NAMES[role]).write_text(
                    json.dumps(normalize_truth_rows(payload)),
                    encoding="utf-8",
                )
                continue
            _, rows = _read_csv(src)
            raw[role] = rows
        if FileRole.PSP in raw and FileRole.LEDGER in raw:
            fill_psp_from_payments(raw[FileRole.PSP], raw[FileRole.LEDGER])
        for role, rows in raw.items():
            mapped = [remap_row(role, row) for row in rows]
            validate_rows(role, mapped)
            write_canonical(canon_dir / CANONICAL_NAMES[role], role, mapped)
        batch = load_csv_batch(canon_dir)
    tax_lines: list[TaxLine] = []
    tax_path = canon_dir / CANONICAL_NAMES[FileRole.TAX]
    if tax_path.exists():
        with tax_path.open(newline="", encoding="utf-8") as fh:
            for i, row in enumerate(csv.DictReader(fh), start=1):
                try:
                    tax_lines.append(TaxLine.from_row(row, index=i))
                except (ValueError, KeyError) as exc:
                    raise IngestError(f"tax row {i}: {exc}") from exc

    return IngestResult(
        batch=batch,
        tax_lines=tax_lines,
        files=files_meta,
        warnings=warnings,
        work_dir=str(dest),
    )


def ingest_razorpay_rows(
    rows: list[dict[str, str]],
    *,
    ground_truth_path: str | Path | None = None,
    work_dir: str | Path | None = None,
) -> IngestResult:
    dest = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="fc-rzp-"))
    canon_dir = dest / "canonical"
    adapted = razorpay_recon_to_canonical(rows)
    write_adapted_canonical(canon_dir, adapted)
    warnings = list(adapted.warnings)
    files_meta = {"razorpay_recon": "inline"}
    if ground_truth_path:
        src = Path(ground_truth_path)
        payload = json.loads(src.read_text(encoding="utf-8"))
        (canon_dir / CANONICAL_NAMES[FileRole.GROUND_TRUTH]).write_bytes(src.read_bytes())
        files_meta["ground_truth"] = src.name
        apply_ground_truth(adapted.batch, payload)
    return IngestResult(
        batch=adapted.batch,
        files=files_meta,
        warnings=warnings,
        work_dir=str(dest),
    )
