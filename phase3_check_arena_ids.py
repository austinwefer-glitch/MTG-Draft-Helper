"""
Diagnostic: are arena_ids actually populated in our cards.json?
And do we cover the cards Arena's log is sending us?
"""

import json
from collections import Counter


def main():
    with open("card_db/cards.json", "r", encoding="utf-8") as f:
        db = json.load(f)
    print(f"Total entries: {len(db)}")
    print()

    # Field presence
    have_arena = sum(1 for e in db if e.get("arena_id") is not None)
    have_mtgo = sum(1 for e in db if e.get("mtgo_id") is not None)
    print(f"Entries with non-null arena_id: {have_arena}")
    print(f"Entries with non-null mtgo_id:  {have_mtgo}")

    # Show sample raw fields from first 3 entries
    print()
    print("Sample of first 3 entries' fields (just the IDs):")
    for e in db[:3]:
        keys = {k: e.get(k) for k in
                ("name", "set", "collector_number",
                 "arena_id", "mtgo_id", "scryfall_id")}
        print(f"  {keys}")

    # Range of arena_ids actually present
    if have_arena:
        ids = sorted(int(e["arena_id"]) for e in db
                     if e.get("arena_id") is not None)
        print()
        print(f"arena_id range: min={ids[0]}, max={ids[-1]}")

    # Specifically check if the IDs from the latest pack are present
    pack_ids = [102724, 102706, 102596, 102487, 102527, 102560, 102626,
                102687, 102693, 102566, 102630, 102774, 102504, 102732]
    print()
    print("Checking the IDs from your latest pack:")
    by_arena = {int(e["arena_id"]): e for e in db
                if e.get("arena_id") is not None}
    for aid in pack_ids:
        entry = by_arena.get(aid)
        if entry:
            print(f"  {aid}: FOUND - {entry.get('face_name')}")
        else:
            print(f"  {aid}: missing")


if __name__ == "__main__":
    main()
