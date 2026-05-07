"""
Phase 3 — Log explorer v2.

Stricter than v1: only looks for BotDraft_DraftPack and similar live-pack
events, filtering out the precon decklists and other noise.

Run with:
  py phase3_log_explore_v2.py

Need to be on a draft pack screen in Arena (or have been recently) for the
events to be in the log.
"""

import re
import sys
from pathlib import Path

LOG_PATH = (
    Path.home()
    / "AppData" / "LocalLow" / "Wizards Of The Coast" / "MTGA" / "Player.log"
)


# Specific draft event names we care about
TARGET_EVENTS = [
    "BotDraft_DraftPack",
    "BotDraft_DraftPick",
    "Draft.MakeHumanDraftPick",
    "Draft.Notify",
    "Event.PlayerDraftStatus",
    "Event_PlayerDraftMakePick",
    "DraftStatus",
    "MakeHumanDraftPick",
]


def main() -> None:
    if not LOG_PATH.exists():
        print(f"Log not found at: {LOG_PATH}")
        sys.exit(1)

    text = LOG_PATH.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    print(f"Log: {LOG_PATH}")
    print(f"Lines: {len(lines):,}")
    print()

    # Find lines mentioning any target event
    pattern = re.compile("|".join(re.escape(e) for e in TARGET_EVENTS))

    matches = []
    for i, line in enumerate(lines):
        if pattern.search(line):
            matches.append(i)

    print(f"Found {len(matches)} lines matching draft events.")
    if not matches:
        print()
        print("No live-draft events in the log yet.")
        print("Try this in Arena:")
        print("  1. Open the Quick Draft you're in (the one called QuickDraft_SOS_20260430).")
        print("  2. Make sure you're viewing the PACK screen with the 14 cards.")
        print("  3. Wait 2-3 seconds.")
        print("  4. Run this script again.")
        return

    # Show the LAST 5 matches with surrounding context
    print()
    print("=" * 70)
    print("Last 5 draft events (with context):")
    print("=" * 70)
    for idx in matches[-5:]:
        a = max(0, idx - 1)
        b = min(len(lines), idx + 12)
        for j in range(a, b):
            marker = ">> " if j == idx else "   "
            line = lines[j].rstrip()
            # Truncate ultra-long lines so output stays scannable
            if len(line) > 400:
                line = line[:400] + " [...truncated]"
            print(f"{marker}{j:>6}: {line}")
        print()


if __name__ == "__main__":
    main()
