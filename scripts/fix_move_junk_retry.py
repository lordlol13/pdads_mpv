"""Retry moving remaining junk: try chmod, copy fallback, then remove originals when possible.

Run after `move_junk_to_trash.py` if some items failed to move due to locks/permissions.
"""
from __future__ import annotations

import os
import shutil
import stat
from datetime import datetime
from pathlib import Path
import sys


def make_writable(path: Path):
    try:
        path.chmod(0o777)
    except Exception:
        pass


def chmod_recursive(path: Path):
    for root_dir, dirs, files in os.walk(path):
        for d in dirs:
            try:
                make_writable(Path(root_dir) / d)
            except Exception:
                pass
        for f in files:
            try:
                make_writable(Path(root_dir) / f)
            except Exception:
                pass


def main():
    root = Path(__file__).resolve().parent.parent
    trash_base = root / "trash"
    # pick the most recent cleanup_* folder if exists
    archives = sorted(trash_base.glob("cleanup_*"))
    if archives:
        dest = archives[-1]
    else:
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = trash_base / f"cleanup_{now}"
        dest.mkdir(parents=True, exist_ok=True)

    # Candidates remaining at repo root
    candidates = list(root.glob("pytest-cache-files*")) + [root / "logs"]

    for p in candidates:
        if not p.exists():
            continue
        print(f"Processing: {p}")
        try:
            shutil.move(str(p), str(dest / p.name))
            print(f"Moved: {p} -> {dest / p.name}")
            continue
        except Exception as exc:
            print(f"Move failed for {p}: {exc}")

        # Try make writable
        try:
            if p.is_dir():
                chmod_recursive(p)
            else:
                make_writable(p)
        except Exception:
            pass

        # Try move again
        try:
            shutil.move(str(p), str(dest / p.name))
            print(f"Moved after chmod: {p}")
            continue
        except Exception as exc:
            print(f"Second move failed for {p}: {exc}")

        # Copy fallback
        try:
            if p.is_dir():
                target = dest / p.name
                shutil.copytree(p, target, dirs_exist_ok=True)
                print(f"Copied dir {p} -> {target}")
                try:
                    shutil.rmtree(p)
                    print(f"Removed original dir {p}")
                except Exception as e_rm:
                    print(f"Could not remove original {p}: {e_rm}")
            else:
                target = dest / p.name
                shutil.copy2(p, target)
                print(f"Copied file {p} -> {target}")
                try:
                    p.unlink()
                    print(f"Removed original file {p}")
                except Exception as e_rm:
                    print(f"Could not remove original file {p}: {e_rm}")
        except Exception as exc2:
            print(f"Copy fallback failed for {p}: {exc2}")

    print("Retry complete. Check the archive:", dest)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("Retry script failed:", e)
        sys.exit(2)
