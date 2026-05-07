"""
Phase 3 — Log explorer.

Reads the MTG Arena Player.log file and finds draft-related events
so we can identify the exact JSON format the current Arena version uses.

Once we know the format, we'll write the live tailer/parser around it.

Run with:
  py phase3_log_explore.py

Outputs:
  - Path of the log file and its size.
  - The most recent ~10 events that look draft-related, each with its
    surrounding context lines.
  - A summary of unique event names seen in the file.
"""

import json
import os
import re
import sys
from pathlib import Path

LOG_PATH = (
    Path.home()
    / "AppData"
    / "LocalLow"
    / "Wizards Of The Coast"
    / "MTGA"
    / "Player.log"
)

# Words that mark a line as potentially draft-related
DRAFT_KEYWORDS = [
    "draft",
    "pack",
    "pickedcards",
    "cardpool",
    "draftpack",
    "humandraftpick",
    "botdraft",
    "draftstatus",
]


def scan_for_event_names(text: str) -> dict[str, int]:
    """Find common event-name patterns and count how often each appears."""
    # Patterns we've seen in MTGA logs across versions:
    #   "Event_GetActiveEventsV2"
    #   "BotDraft_DraftPack"
    #   "Draft.MakeHumanDraftPick"
    #   <== Event_NAME ...
    #   ==> EventName(...)
    pat = re.compile(
        r"(?:<==|==>|\"|\b)"
        r"((?:Draft|Bot|Event|MakeHumanDraftPick|GreToClient|ClientToGRE)"
        r"[A-Za-z._]+)"
    )
    counts: dict[str, int] = {}
    for m in pat.finditer(text):
        name = m.group(1)
        counts[name] = counts.get(name, 0) + 1
    return counts


def find_draft_lines(lines: list[str]) -> list[int]:
    """Return line indices that mention any draft keyword (case-insensitive)."""
    indices = []
    for i, line in enumerate(lines):
        low = line.lower()
        if any(k in low for k in DRAFT_KEYWORDS):
            indices.append(i)
    return indices


def print_context(lines: list[str], idx: int, before: int = 1, after: int = 8) -> None:
    """Print line `idx` with surrounding context."""
    a = max(0, idx - before)
    b = min(len(lines), idx + after + 1)
    for j in range(a, b):
        marker = ">> " if j == idx else "   "
        print(f"{marker}{j:>6}: {lines[j].rstrip()}")
    print()


def main() -> None:
    if not LOG_PATH.exists():
        print(f"Log file not found at: {LOG_PATH}")
        print("Make sure Arena has run at least once with Detailed Logs enabled.")
        sys.exit(1)

    size_mb = LOG_PATH.stat().st_size / 1024 / 1024
    print(f"Log: {LOG_PATH}")
    print(f"Size: {size_mb:.1f} MB")

    text = LOG_PATH.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    print(f"Lines: {len(lines):,}")

    # Event-name frequency
    event_counts = scan_for_event_names(text)
    print(f"\nDraft-related event names found ({len(event_counts)} unique):")
    for name, count in sorted(event_counts.items(), key=lambda kv: -kv[1])[:30]:
        print(f"  {count:>5}  {name}")

    # Find draft-related lines
    indices = find_draft_lines(lines)
    print(f"\n{len(indices):,} lines mention a draft keyword.")
    if not indices:
        print("(No draft activity in the log yet — try opening a draft in Arena.)")
        return

    # Print the LAST 10 occurrences with context
    print(f"\n=== Last 10 draft-related lines (with context): ===\n")
    for idx in indices[-10:]:
        print_context(lines, idx)


if __name__ == "__main__":
    main()
