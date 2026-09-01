from __future__ import annotations

from pathlib import Path
import zipfile


class IngestError(ValueError):
    pass


MAX_ENTRY_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024


def extract_zip(zip_path: str | Path, dest: str | Path) -> list[Path]:
    src = Path(zip_path)
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        raise IngestError(f"zip not found: {src}")
    extracted: list[Path] = []
    total = 0
    seen_names: set[str] = set()
    try:
        zf_ctx = zipfile.ZipFile(src)
    except zipfile.BadZipFile as exc:
        raise IngestError(f"corrupt or non-zip file: {src}") from exc
    with zf_ctx as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename).name
            if not name or name.startswith("."):
                continue
            if "__macosx" in info.filename.lower():
                continue
            if ".." in Path(info.filename).parts:
                raise IngestError(f"unsafe zip path: {info.filename}")
            if name in seen_names:
                raise IngestError(f"duplicate zip entry name: {name}")
            size = info.file_size
            if size > MAX_ENTRY_BYTES:
                raise IngestError(f"zip entry too large: {name} ({size} bytes)")
            total += size
            if total > MAX_TOTAL_BYTES:
                raise IngestError("zip uncompressed size exceeds limit")
            seen_names.add(name)
            target = out / name
            target.write_bytes(zf.read(info))
            extracted.append(target)
    if not extracted:
        raise IngestError("zip contained no usable files")
    return extracted
