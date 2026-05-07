"""
Phase 3 — Live log tailer.

Watches the MTG Arena Player.log file continuously. As soon as Arena
writes a new BotDraftDraftStatus event (which happens whenever you view
or navigate to a draft pack), the script prints that pack's contents.

Workflow:
  1. Run this in your VS Code terminal.
  2. Open Arena, get into a draft pack screen.
  3. The pack contents appear here within ~1 second.
  4. Keep it running for the whole draft. Press Ctrl+C to quit.

Run with:
  py phase3_tailer.py
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Pull the shared loaders & helpers from the one-shot parser.
sys.path.insert(0, str(Path(__file__).parent))
from phase3_log_parse import (
    load_arena_index,
    load_scryfall_db_by_set_cn,
    find_latest_bot_draft_status,
)
from phase4_recommender import (
    load_tier_index,
    rank_pack,
    archetype_summary,
)


LOG_PATH = (
    Path.home()
    / "AppData" / "LocalLow" / "Wizards Of The Coast" / "MTGA" / "Player.log"
)
POLL_INTERVAL_SEC = 0.5


def lookup_card(arena_index, scry_by_setcn, sid):
    """Translate an arena_id into a merged Arena+Scryfall card record."""
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


def render_pack(payload, arena_index, scry, tier_data):
    """Print a pack summary with pick recommendations."""
    pack_ids = payload.get("DraftPack", [])
    if not pack_ids:
        return

    pack_cards = []
    for sid in pack_ids:
        info = lookup_card(arena_index, scry, sid)
        if info is None:
            info = {"name": f"<arena_id {sid}>", "mana_cost": "", "rarity": "?",
                    "type_line": "", "cmc": 0}
        pack_cards.append(info)

    picked_ids = payload.get("PickedCards", [])
    picked_cards = []
    for sid in picked_ids:
        info = lookup_card(arena_index, scry, sid)
        if info:
            picked_cards.append(info)

    fmt = ("QuickDraft" if "QuickDraft" in (payload.get("EventName") or "")
           else "PremierDraft")
    ranked = rank_pack(pack_cards, picked_cards, tier_data, fmt=fmt)

    print()
    print("=" * 88)
    # Arena's PackNumber and PickNumber are 0-indexed; display as 1-indexed.
    pack_num = (payload.get("PackNumber", 0) or 0) + 1
    pick_num = (payload.get("PickNumber", 0) or 0) + 1
    print(f"  {payload.get('EventName')}  -  "
          f"Pack {pack_num} / Pick {pick_num}"
          f"  -  Pool colors: {archetype_summary(picked_cards)}")
    print("=" * 88)
    print(f"  {'#':>2}  {'Score':>6}  {'Tier':>4}  "
          f"{'Card':<32}  {'Cost':>16}  {'Rarity':>9}  Type")
    print("-" * 88)
    for rank, r in enumerate(ranked, start=1):
        c = r["card"]
        marker = ">>" if rank == 1 else "  "
        wr = f"{r['gih_wr']*100:.1f}%" if r['gih_wr'] is not None else "  -  "
        print(f"{marker}{rank:>2}  {r['score']:>6}  {r['tier']:>4}  "
              f"{c['name']:<32}  {c['mana_cost']:>16}  {c['rarity']:>9}  "
              f"{c['type_line']}")
        # Show breakdown details for the top recommendation
        if rank == 1:
            details = []
            if r['gih_wr'] is not None:
                details.append(f"GIH WR {r['gih_wr']*100:.1f}%")
            details.append(f"base={r['base']}")
            if r['color_penalty']:
                details.append(f"color {r['color_penalty']:+}")
            if r['curve_bonus']:
                details.append(f"curve +{r['curve_bonus']}")
            print(f"      ^^^ recommended pick ({', '.join(details)})")

    if picked_cards:
        names = [c["name"] for c in picked_cards]
        print(f"\n  Pool ({len(names)}):")
        line = "    "
        for n in names:
            if len(line) + len(n) + 3 > 100:
                print(line)
                line = "    "
            line += n + " | "
        if line.strip():
            print(line.rstrip(" |"))


def pack_signature(payload) -> tuple:
    """A signature tuple identifying a unique pack state. Used to dedupe
    repeated events (Arena writes the same DraftStatus multiple times)."""
    return (
        payload.get("EventName"),
        payload.get("PackNumber"),
        payload.get("PickNumber"),
        tuple(payload.get("DraftPack", [])),
    )


# Both event names carry pack data with identical shape. Status appears
# when entering a pack screen, Pick appears when a pick is confirmed.
DRAFT_EVENT_NAMES = ("BotDraftDraftStatus", "BotDraftDraftPick")


def parse_pack_event(prev_line: str, line: str):
    """If `line` is the JSON payload following one of the draft event
    response lines, return the parsed inner Payload dict. Otherwise None."""
    if "<==" not in prev_line:
        return None
    if not any(ev in prev_line for ev in DRAFT_EVENT_NAMES):
        return None
    s = line.strip()
    if not s.startswith("{"):
        return None
    try:
        outer = json.loads(s)
    except json.JSONDecodeError:
        return None
    payload_raw = outer.get("Payload")
    if not payload_raw:
        return None
    try:
        return json.loads(payload_raw)
    except json.JSONDecodeError:
        return None


def main() -> None:
    print("Loading arena index...", end=" ", flush=True)
    arena_index = load_arena_index()
    print(f"{len(arena_index):,} cards")

    print("Loading Scryfall metadata...", end=" ", flush=True)
    scry = load_scryfall_db_by_set_cn()
    print(f"{len(scry):,} (set, cn) entries")

    print("Loading 17Lands tiers...", end=" ", flush=True)
    tier_data = load_tier_index()
    print(f"{len(tier_data):,} cards")

    print(f"\nWatching: {LOG_PATH}")
    if not LOG_PATH.exists():
        print("Log file does not exist yet. Open Arena and try again.")
        sys.exit(1)

    # Show the LAST already-recorded pack on startup, so if the user is
    # already mid-pack we get something useful right away.
    text = LOG_PATH.read_text(encoding="utf-8", errors="replace")
    initial = find_latest_bot_draft_status(text)
    last_sig = None
    if initial:
        render_pack(initial, arena_index, scry, tier_data)
        last_sig = pack_signature(initial)
    print()
    print("Waiting for new pack events (Ctrl+C to stop)...")

    # Open the log and seek to end so we only handle NEW events.
    f = LOG_PATH.open("r", encoding="utf-8", errors="replace")
    f.seek(0, 2)
    last_size = LOG_PATH.stat().st_size
    prev_line = ""

    try:
        while True:
            time.sleep(POLL_INTERVAL_SEC)

            # Detect log truncation (Arena restart can rewrite the file)
            try:
                current_size = LOG_PATH.stat().st_size
            except OSError:
                continue
            if current_size < last_size:
                print("\n[log truncated; reopening]\n")
                f.close()
                f = LOG_PATH.open("r", encoding="utf-8", errors="replace")
                prev_line = ""
            last_size = current_size

            # Drain whatever new lines are available.
            while True:
                line = f.readline()
                if not line:
                    break
                payload = parse_pack_event(prev_line, line)
                if payload:
                    sig = pack_signature(payload)
                    if sig != last_sig:
                        last_sig = sig
                        render_pack(payload, arena_index, scry, tier_data)
                prev_line = line
    except KeyboardInterrupt:
        print("\n\nStopped.")
    finally:
        f.close()


if __name__ == "__main__":
    main()
