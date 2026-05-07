"""
Phase 3 — Log parser (one-shot).

Reads the MTGA Player.log, finds the most recent BotDraftDraftStatus event,
parses out the pack contents, and prints each card identified.

This is the offline / "test it works" version of the live tailer.
Once this runs cleanly, we'll wrap it in a tail-the-file loop in the
next script.

Run with:
  py phase3_log_parse.py
"""

import json
import re
import sys
from pathlib import Path


LOG_PATH = (
    Path.home()
    / "AppData" / "LocalLow" / "Wizards Of The Coast" / "MTGA" / "Player.log"
)


def load_arena_index() -> dict[int, dict]:
    """Load the arena_id -> card-info index built from MTGA's local DB."""
    with open("card_db/arena_index.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    # JSON serializes integer keys as strings; convert back.
    return {int(k): v for k, v in data.items()}


def load_scryfall_db_by_set_cn() -> dict[tuple[str, str], dict]:
    """Load cards.json keyed by (set_code, collector_number) for join lookups
    that bring in Scryfall metadata (mana cost, type line, colors, etc.)."""
    with open("card_db/cards.json", "r", encoding="utf-8") as f:
        db = json.load(f)
    out: dict[tuple[str, str], dict] = {}
    for e in db:
        s = (e.get("set") or "").lower()
        cn = str(e.get("collector_number") or "")
        if s and cn:
            out[(s, cn)] = e
    return out


# Event names that carry a draft-pack payload. Arena uses Status when you
# enter a pack screen, and Pick when you confirm a pick — the JSON body
# is the same shape.
DRAFT_EVENT_NAMES = ("BotDraftDraftStatus", "BotDraftDraftPick")


def find_latest_bot_draft_status(text: str) -> dict | None:
    """Find the LATEST draft-pack event (status OR pick) in the log text
    and return its parsed Payload. Both events carry the same shape."""
    lines = text.splitlines()
    found_payloads = []
    for i, line in enumerate(lines):
        if "<==" not in line:
            continue
        if not any(ev in line for ev in DRAFT_EVENT_NAMES):
            continue
        if i + 1 >= len(lines):
            continue
        try:
            outer = json.loads(lines[i + 1])
        except json.JSONDecodeError:
            continue
        payload_raw = outer.get("Payload")
        if not payload_raw:
            continue
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            continue
        found_payloads.append(payload)
    if not found_payloads:
        return None
    return found_payloads[-1]


def main() -> None:
    if not LOG_PATH.exists():
        print(f"Log not found at: {LOG_PATH}")
        sys.exit(1)

    text = LOG_PATH.read_text(encoding="utf-8", errors="replace")
    payload = find_latest_bot_draft_status(text)
    if payload is None:
        print("No BotDraftDraftStatus events found in the log.")
        print("Open a draft pack screen in Arena, then re-run this script.")
        sys.exit(0)

    print("=" * 60)
    print(f"Latest pack from log:")
    print(f"  Event:     {payload.get('EventName')}")
    print(f"  Pack #:    {payload.get('PackNumber')}")
    print(f"  Pick #:    {payload.get('PickNumber')}")
    print(f"  Status:    {payload.get('DraftStatus')}")
    print("=" * 60)

    arena_index = load_arena_index()
    scry_by_setcn = load_scryfall_db_by_set_cn()
    print(f"arena_index: {len(arena_index)} cards   "
          f"scryfall index: {len(scry_by_setcn)} (set,cn) entries\n")

    def lookup(sid):
        """Return (name, set, cn, rarity, mana_cost, type_line) for an arena id."""
        try:
            aid = int(sid)
        except (TypeError, ValueError):
            return None
        a = arena_index.get(aid)
        if not a:
            return None
        s = a["set"]
        cn = a["collector_number"]
        scry = scry_by_setcn.get((s, cn), {})
        return {
            "arena_id": aid,
            "name": a["name"],
            "set": s,
            "collector_number": cn,
            "rarity": a["rarity"],
            "mana_cost": scry.get("mana_cost", ""),
            "type_line": scry.get("type_line", ""),
            "cmc": scry.get("cmc"),
            "colors": scry.get("colors", []),
        }

    pack_ids = payload.get("DraftPack", [])
    if not pack_ids:
        print("(No DraftPack in payload.)")
        return

    print(f"Pack contains {len(pack_ids)} cards:")
    for i, sid in enumerate(pack_ids, start=1):
        info = lookup(sid)
        if info is None:
            print(f"  {i:>2}. arena_id={sid}  (NOT in arena_index)")
            continue
        print(f"  {i:>2}. {info['name']:38} {info['mana_cost']:>10}  "
              f"{info['rarity']:>10}  {info['type_line']}")

    picked = payload.get("PickedCards", [])
    if picked:
        print()
        print(f"Already picked ({len(picked)}):")
        for sid in picked:
            info = lookup(sid)
            if info:
                print(f"  - {info['name']}")
            else:
                print(f"  - arena_id={sid} (not in index)")


if __name__ == "__main__":
    main()
