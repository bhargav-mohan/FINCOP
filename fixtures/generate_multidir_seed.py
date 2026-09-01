from __future__ import annotations

from pathlib import Path

from finance_controller.data.multidir_seed import SEED, write_multidir_seed

OUT_DIR = Path(__file__).resolve().parent / "seed_multidir"


def main() -> None:
    written = write_multidir_seed(OUT_DIR, seed=SEED)
    print(f"wrote {len(written)} paths under {OUT_DIR}")
    for rel in written:
        print(f"  {rel}")


if __name__ == "__main__":
    main()
