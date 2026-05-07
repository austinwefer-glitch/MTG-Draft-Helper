"""
Cleanup script — deletes legacy / debug files and folders that aren't
used by the working tool.

Files deleted are ones from earlier dev iterations (OCR pipeline, log
explorers, diagnostics) that the current log-reading + 17Lands flow
doesn't need.

Folders are HUGE generated data (card images, screenshots) that aren't
used either. Kept on disk by default but you can clear them.

Run with:
  py cleanup.py
"""

import shutil
import sys
from pathlib import Path


HERE = Path(__file__).parent

# Single-file legacy scripts. Safe to delete; nothing in the working
# pipeline imports them.
LEGACY_FILES = [
    # Phase 1 test
    "hello.py",
    # One-off Scryfall verifier from before we built phase2
    "verify_set.py",
    # Deprecated OCR + screenshot capture pipeline
    "phase3_calibrate.py",
    "phase3_capture.py",
    "phase3_match_test.py",
    "phase3_ocr_match.py",
    # Diagnostics from building Phase 3
    "phase3_check_arena_ids.py",
    "phase3_check_db.py",
    "phase3_diagnose.py",
    "phase3_diagnose_v2.py",
    "phase3_diagnose_v3.py",
    "phase3_inspect_mtga.py",
    "phase3_inspect_sqlite.py",
    "phase3_log_explore.py",
    "phase3_log_explore_v2.py",
    "phase3_log_explore_v3.py",
    "phase3_lookup_card.py",
    # Phase 4 debug helper
    "phase4_debug.py",
]

# Folders of generated data. Sizes can be hundreds of MB.
LEGACY_FOLDERS = [
    "screenshots",
    "card_crops",
    "ocr_debug",
    "card_db/images",  # only used by deprecated pHash matching
]


def folder_size_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1024 / 1024


def main() -> None:
    print(f"Cleaning up: {HERE}\n")

    # ---- Phase 1: legacy files ----
    print("Files to delete:")
    to_delete = [HERE / f for f in LEGACY_FILES if (HERE / f).exists()]
    if not to_delete:
        print("  (none — already cleaned up)")
    else:
        for p in to_delete:
            print(f"  - {p.name}")
        confirm = input(f"\nDelete {len(to_delete)} files? [y/N]: ").strip().lower()
        if confirm == "y":
            ok = 0
            for p in to_delete:
                try:
                    p.unlink()
                    ok += 1
                except Exception as e:
                    print(f"  FAILED: {p.name}: {e}")
            print(f"  -> deleted {ok} files")
        else:
            print("  -> skipped")

    # ---- Phase 2: legacy folders (with confirmation per folder) ----
    print("\nFolders that can be removed (each is generated data):")
    for folder in LEGACY_FOLDERS:
        path = HERE / folder
        if not path.exists():
            continue
        size = folder_size_mb(path)
        print(f"\n  {folder}/  ({size:.1f} MB)")
        confirm = input(f"  Delete? [y/N]: ").strip().lower()
        if confirm == "y":
            try:
                shutil.rmtree(path)
                print(f"    -> deleted")
            except Exception as e:
                print(f"    FAILED: {e}")
        else:
            print(f"    -> kept")

    print("\nDone. If you push to GitHub now, the deleted files will be removed there too.")


if __name__ == "__main__":
    main()
