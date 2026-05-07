"""
Show ALL recent draft-related event types in the Player.log so we can see
what Arena writes after a pick is confirmed.

We previously matched on 'BotDraftDraftStatus' but a 'pick' may use a
different event name (e.g. 'BotDraftMakePick' or 'Event_PlayerDraftPick').
"""

import re
from collections import Counter
from pathlib import Path

LOG_PATH = (
    Path.home()
    / "AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log"
)


def main() -> None:
    text = LOG_PATH.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    print(f"Log: {LOG_PATH}")
    print(f"Lines: {len(lines):,}")

    # Find every '<==' response indicator and capture the event name.
    # Format is: <== EventName(uuid)
    pat = re.compile(r"<==\s+([A-Za-z_]+)\b")
    counts: Counter[str] = Counter()
    last_seen: dict[str, int] = {}
    for i, line in enumerate(lines):
        m = pat.search(line)
        if m:
            counts[m.group(1)] += 1
            last_seen[m.group(1)] = i

    # Filter to draft-ish events
    draft_events = {n: c for n, c in counts.items()
                    if any(k in n.lower() for k in
                           ["draft", "event", "pick", "course"])}
    print(f"\nDraft-ish event types found ({len(draft_events)}):")
    for name, n in sorted(draft_events.items(), key=lambda kv: -last_seen[kv[0]])[:20]:
        idx = last_seen[name]
        print(f"  {n:>4}x  {name}  (last at line {idx})")

    # Show the LAST few draft-related events with their bodies
    print("\nLast 5 draft-related event responses (with body):")
    candidates = [(i, m.group(1)) for i, line in enumerate(lines)
                  for m in [pat.search(line)] if m
                  and m.group(1).lower().find("draft") >= 0]
    for idx, name in candidates[-5:]:
        print(f"\n  >> line {idx}: <== {name}")
        # Print the next line which should be the JSON body, truncated
        if idx + 1 < len(lines):
            body = lines[idx + 1]
            if len(body) > 600:
                body = body[:600] + " [...truncated]"
            print(f"      body: {body}")


if __name__ == "__main__":
    main()
