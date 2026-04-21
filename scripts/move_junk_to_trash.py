"""Move common junk files/directories into a timestamped `trash/cleanup_*` folder.

Usage: run from repo root or via Python: `python scripts/move_junk_to_trash.py`
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parent.parent
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = root / "trash" / f"cleanup_{now}"
    dest.mkdir(parents=True, exist_ok=True)

    # Candidate patterns (top-level paths)
    candidates = []
    # move entire logs dir if present
    candidates.append(root / "logs")
    # any pytest-cache-files* dirs
    candidates.extend(list(root.glob("pytest-cache-files*")))
    # top-level __pycache__
    candidates.append(root / "__pycache__")

    moved = []
    failed = []

    for p in candidates:
        if not p.exists():
            continue
        try:
            target = dest / p.name
            shutil.move(str(p), str(target))
            moved.append(str(p))
            print(f"Moved: {p} -> {target}")
        except Exception as exc:
            failed.append((str(p), str(exc)))
            print(f"Failed to move {p}: {exc}")

    # also move repository-level caches if any inside trash/cleanup candidates
    # write README with summary
    readme = dest / "README.md"
    with readme.open("w", encoding="utf8") as fh:
        fh.write("# Cleanup archive\n\n")
        fh.write(f"Created: {now}\n\n")
        if moved:
            fh.write("Moved items:\n")
            for m in moved:
                fh.write(f"- {m}\n")
        else:
            fh.write("No items were moved.\n")
        if failed:
            fh.write("\nFailed to move:\n")
            for p, e in failed:
                fh.write(f"- {p}: {e}\n")

    print("\nSummary:")
    print(f"  Archive: {dest}")
    print(f"  Moved: {len(moved)}")
    print(f"  Failed: {len(failed)}")

    if failed:
        print("Some items failed to move. Check permissions or processes holding files.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("Error during cleanup:", e)
        sys.exit(2)
