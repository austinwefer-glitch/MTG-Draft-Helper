"""
Diagnostic for two issues in the recommender:
  1. Some cards (Biblioplex Tomekeeper, Social Snub) showing tier "?"
     -> name mismatch between our data and 17Lands.
  2. Pool color signal showing R=0 despite the player having red cards
     -> means lookup_card() is returning empty mana_cost for those.

Run with:
  py phase4_debug.py
"""

import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))
from phase3_log_parse import (
    load_arena_index, load_scryfall_db_by_set_cn,
    find_latest_bot_draft_status,
)
from phase4_recommender import load_tier_index, parse_color_symbols


def main():
    arena_index = load_arena_index()
    scry = load_scryfall_db_by_set_cn()
    tiers = load_tier_index()
    print(f"arena_index: {len(arena_index)}, scry by (set,cn): {len(scry)}, "
          f"17Lands tiers: {len(tiers)}")

    # ---- Issue 1: which names do we have in tiers but with formatting differences ----
    print("\n--- Issue 1: name lookup ---")
    for query in ["Biblioplex Tomekeeper", "Social Snub", "Plains",
                  "Emeritus of Ideation", "Spellbook Seeker"]:
        # Exact
        exact = tiers.get(query)
        # Look for partial / similar
        partial = [n for n in tiers if query.lower() in n.lower()]
        front_face_match = [n for n in tiers
                            if " // " in n and n.split(" // ")[0] == query]
        print(f"  '{query}'")
        print(f"     exact match in tiers: {bool(exact)}")
        if exact:
            qd = exact.get("QuickDraft", {}).get("gih_wr")
            print(f"     QD GIH WR: {qd}")
        if partial:
            print(f"     partial matches: {partial[:5]}")
        if front_face_match:
            print(f"     front-face matches: {front_face_match[:5]}")

    # ---- Issue 2: the pool from the latest pack ----
    print("\n--- Issue 2: pool card lookup ---")
    log_path = (Path.home()
                / "AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log")
    text = log_path.read_text(encoding="utf-8", errors="replace")
    payload = find_latest_bot_draft_status(text)
    if not payload:
        print("  No latest pack in the log.")
        return

    picked = payload.get("PickedCards", [])
    print(f"  Pool has {len(picked)} cards.")
    print(f"  {'arena_id':>8}  {'name':<32}  {'set':<4}  {'cn':>5}  {'cost':>16}  found_in_scry?")
    print(f"  " + "-" * 90)
    for sid in picked:
        try:
            aid = int(sid)
        except (TypeError, ValueError):
            print(f"  {sid:>8}  <bad id>")
            continue
        a = arena_index.get(aid)
        if not a:
            print(f"  {aid:>8}  <not in arena_index>")
            continue
        name = a["name"]
        s = a["set"]
        cn = a["collector_number"]
        scry_entry = scry.get((s, cn))
        cost = scry_entry.get("mana_cost", "") if scry_entry else ""
        found = "yes" if scry_entry else "NO"
        print(f"  {aid:>8}  {name:<32}  {s:<4}  {cn:>5}  {cost:>16}  {found}")

    # Show cumulative color signal for diagnostics
    print()
    sig = {c: 0.0 for c in "WUBRG"}
    for sid in picked:
        a = arena_index.get(int(sid)) if str(sid).isdigit() else None
        if not a:
            continue
        scry_entry = scry.get((a["set"], a["collector_number"]))
        if not scry_entry:
            continue
        for c, n in parse_color_symbols(scry_entry.get("mana_cost", "")).items():
            sig[c] += n
    print(f"  Cumulative color signal: {sig}")


if __name__ == "__main__":
    main()
