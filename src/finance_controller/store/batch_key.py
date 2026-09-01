from __future__ import annotations

import hashlib
from pathlib import Path

from finance_controller.config import ReconConfig


def generated_batch_key(config: ReconConfig) -> str:
    return (
        f"generated:{config.seed}:{config.num_records}:"
        f"{config.inject_exceptions}:{config.inject_resolvable}:{config.inject_edges}"
    )


def file_batch_key(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return f"file:{digest.hexdigest()}"


def dir_batch_key(path: str | Path) -> str:
    root = Path(path)
    digest = hashlib.sha256()
    files = [
        p
        for p in root.rglob("*")
        if p.is_file() and "_expanded" not in p.parts
    ]
    for file in sorted(files, key=lambda p: str(p.relative_to(root))):
        digest.update(str(file.relative_to(root)).encode())
        digest.update(file.read_bytes())
    return f"dir:{digest.hexdigest()}"
