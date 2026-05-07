"""
Phase 6 — Deck builder, standalone command-line wrapper.

Reads the most recent draft state from your Player.log, calls the deck
builder, and prints the recommended deck + cuts to your terminal.

Run with:
  py phase6_deckbuild.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from phase3_log_parse import (
    find_latest_bot_draft_status,
    load_arena_index,
    load_scryfall_db_by_set_cn,
)
from phase3_tailer import lookup_card
from phase4_recommender import load_tier_index, load_overrides
from phase6_deckbuilder import build_deck, render_text


LOG_PATH = (
    Path.home()
    / "AppData" / "LocalLow" / "Wizards Of The Coast" / "MTGA" / "Player.log"
)


def main() -> None:
    if not LOG_PATH.exists():
        print(f"Log file not found: {LOG_PATH}")
        sys.exit(1)

    text = LOG_PATH.read_text(encoding="utf-8", errors="replace")
    payload = find_latest_bot_draft_status(text)
    if not payload:
        print("No draft state found in the log.")
        print("Make sure you've drafted at least once with Detailed Logs on.")
        sys.exit(1)

    print("Loading arena index...", end=" ", flush=True)
    arena_index = load_arena_index()
    print(f"{len(arena_index):,} cards")

    print("Loading Scryfall metadata...", end=" ", flush=True)
    scry = load_scryfall_db_by_set_cn()
    print(f"{len(scry):,} entries")

    print("Loading 17Lands tiers...", end=" ", flush=True)
    tier_data = load_tier_index()
    print(f"{len(tier_data):,} cards")
    overrides = load_overrides()

    # Pull the pool. We include both PickedCards AND any card we already
    # took as the most recent pick (since BotDraftDraftPick events list
    # the picked card in the next event's PickedCards array).
    picked_ids = payload.get("PickedCards", [])
    pool: list[dict] = []
    for sid in picked_ids:
        info = lookup_card(arena_index, scry, sid)
        if info:
            pool.append(info)

    print(f"\nDraft pool: {len(pool)} cards")
    if len(pool) < 30:
        print("  (Pool is small — deck recommendation may be unreliable.)")

    fmt = ("QuickDraft" if "QuickDraft" in (payload.get("EventName") or "")
           else "PremierDraft")
    build = build_deck(pool, tier_data, overrides=overrides, fmt=fmt)
    print()
    print(render_text(build))


if __name__ == "__main__":
    main()
