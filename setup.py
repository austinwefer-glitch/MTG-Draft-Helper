"""
One-shot setup script for new users.

Runs everything needed to get the draft helper working from a fresh clone:
  1. Install Python dependencies (requests, Pillow).
  2. Build the card metadata database from Scryfall.
  3. Build the arena_id -> name index from your local MTGA install.
  4. Fetch 17Lands tier data.

Run with:
  py setup.py
"""

import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).parent


def step(label: str, cmd: list[str]) -> None:
    print()
    print("=" * 70)
    print(f"  {label}")
    print("=" * 70)
    result = subprocess.run(cmd, cwd=HERE)
    if result.returncode != 0:
        print(f"\n!!! {label} failed (exit code {result.returncode}). "
              f"Stopping setup.")
        sys.exit(1)


def main() -> None:
    py = sys.executable
    step("[1/4]  Installing Python dependencies",
         [py, "-m", "pip", "install", "-r", "requirements.txt"])

    step("[2/4]  Building card metadata database from Scryfall  "
         "(this can take a few minutes)",
         [py, "phase2_build_db.py"])

    step("[3/4]  Building arena_id -> name index from your MTGA install",
         [py, "phase3_build_arena_index.py"])

    step("[4/4]  Fetching 17Lands tier data",
         [py, "phase4_fetch_tiers.py"])

    print()
    print("=" * 70)
    print("  Setup complete!")
    print("=" * 70)
    print()
    print("Before drafting:")
    print("  1. In MTG Arena: Settings -> Account -> enable 'Detailed Logs")
    print("     (Plugin Support)'.")
    print("  2. Fully quit and restart Arena so the setting takes effect.")
    print()
    print("To launch the helper, run:  py phase5_ui.py")
    print("(or double-click run.bat)")
    print()


if __name__ == "__main__":
    main()
