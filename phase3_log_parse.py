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
import shutil
import sys
from datetime import datetime
from pathlib import Path


LOG_PATH = (
    Path.home()
    / "AppData" / "LocalLow" / "Wizards Of The Coast" / "MTGA" / "Player.log"
)
LOG_PATH_PREV = LOG_PATH.with_name("Player-prev.log")

# Persistent draft snapshot — survives Arena restarts and log rotation.
DRAFT_SNAPSHOT_PATH = Path(__file__).parent / "card_db" / "last_draft.json"
DRAFTS_ARCHIVE_DIR = Path(__file__).parent / "card_db" / "drafts"


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


# ---------- Persistent snapshots ----------

def save_draft_snapshot(payload: dict) -> None:
    """Write the current draft state to disk so it survives Arena's log
    rotation. If we detect a new draft starting (different event or a
    significantly smaller pool), archive the previous snapshot first."""
    if not payload:
        return
    new_event = payload.get("EventName")
    new_picked = payload.get("PickedCards", []) or []

    DRAFT_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # If a previous snapshot exists, decide whether to archive it
    if DRAFT_SNAPSHOT_PATH.exists():
        try:
            prev = json.loads(
                DRAFT_SNAPSHOT_PATH.read_text(encoding="utf-8")
            )
            prev_event = prev.get("event_name")
            prev_picked = prev.get("picked_card_ids", []) or []
            # New draft = event name changed, or pool shrank by 5+ cards
            new_draft = (
                prev_event != new_event
                or len(new_picked) < len(prev_picked) - 5
            )
            # Only archive if the previous one had real picks worth saving
            if new_draft and len(prev_picked) >= 10:
                DRAFTS_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
                ts = (prev.get("saved_at") or "unknown").replace(":", "-")
                ev = (prev_event or "unknown").replace("/", "_")
                archive_name = f"{ts}__{ev}__{len(prev_picked)}cards.json"
                try:
                    shutil.copyfile(
                        DRAFT_SNAPSHOT_PATH,
                        DRAFTS_ARCHIVE_DIR / archive_name,
                    )
                except OSError:
                    pass
        except (json.JSONDecodeError, OSError):
            pass

    snapshot = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "event_name": new_event,
        "pack_number": payload.get("PackNumber"),
        "pick_number": payload.get("PickNumber"),
        "picked_card_ids": new_picked,
        "current_pack_ids": payload.get("DraftPack", []),
    }
    DRAFT_SNAPSHOT_PATH.write_text(
        json.dumps(snapshot, indent=2), encoding="utf-8"
    )


def _snapshot_to_payload(snap: dict) -> dict:
    """Convert a saved snapshot back into a Payload-shaped dict so the
    rest of the pipeline can treat it the same as a live log payload."""
    return {
        "EventName": snap.get("event_name"),
        "PackNumber": snap.get("pack_number"),
        "PickNumber": snap.get("pick_number"),
        "DraftPack": snap.get("current_pack_ids", []),
        "PickedCards": snap.get("picked_card_ids", []),
    }


def load_draft_snapshot() -> dict | None:
    """Load the most-recent saved snapshot (if any)."""
    if not DRAFT_SNAPSHOT_PATH.exists():
        return None
    try:
        return json.loads(DRAFT_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def load_most_recent_archived_draft() -> dict | None:
    """Load the freshest file in the drafts/ archive folder."""
    if not DRAFTS_ARCHIVE_DIR.exists():
        return None
    files = sorted(
        DRAFTS_ARCHIVE_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for f in files:
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
    return None


def list_archived_drafts() -> list[dict]:
    """Return summary info for every persisted draft, freshest first.

    Includes the current `last_draft.json` plus everything in the drafts/
    archive folder. Each entry has:
      path        - Path to the source JSON file
      saved_at    - timestamp string (ISO format)
      event_name  - the Arena event name (e.g. QuickDraft_SOS_20260430)
      card_count  - how many cards in the pool
      is_current  - True only for the live snapshot, False for archives
      raw         - the full parsed JSON dict
    """
    drafts: list[dict] = []

    # Live snapshot first
    if DRAFT_SNAPSHOT_PATH.exists():
        try:
            data = json.loads(DRAFT_SNAPSHOT_PATH.read_text(encoding="utf-8"))
            drafts.append({
                "path": DRAFT_SNAPSHOT_PATH,
                "is_current": True,
                "saved_at": data.get("saved_at", ""),
                "event_name": data.get("event_name") or "?",
                "card_count": len(data.get("picked_card_ids") or []),
                "raw": data,
            })
        except (json.JSONDecodeError, OSError):
            pass

    if DRAFTS_ARCHIVE_DIR.exists():
        files = sorted(
            DRAFTS_ARCHIVE_DIR.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                drafts.append({
                    "path": f,
                    "is_current": False,
                    "saved_at": data.get("saved_at", ""),
                    "event_name": data.get("event_name") or "?",
                    "card_count": len(data.get("picked_card_ids") or []),
                    "raw": data,
                })
            except (json.JSONDecodeError, OSError):
                continue

    return drafts


def payload_from_draft(draft: dict) -> dict:
    """Convert a list_archived_drafts() entry's raw dict into a Payload."""
    return _snapshot_to_payload(draft["raw"])


def find_latest_payload_anywhere() -> dict | None:
    """Full fallback chain. Used by the deck builder so it always finds
    something if the user has ever drafted with the helper running."""
    # 1. Live log files
    payload = find_latest_bot_draft_status_in_logs()
    if payload:
        return payload
    # 2. Last-draft snapshot (survives Arena log rotation)
    snap = load_draft_snapshot()
    if snap and snap.get("picked_card_ids"):
        return _snapshot_to_payload(snap)
    # 3. Archive of past drafts
    archived = load_most_recent_archived_draft()
    if archived and archived.get("picked_card_ids"):
        return _snapshot_to_payload(archived)
    return None


def find_latest_bot_draft_status_in_logs() -> dict | None:
    """Look at both Player.log AND Player-prev.log and return whichever
    contains the most recent draft event.

    Arena rotates Player.log to Player-prev.log when it restarts, so a
    draft you just finished may be in the old file by the time you click
    'Build Deck'. We pick the file with the more recent modification time
    that actually has a draft event in it.
    """
    candidates = []
    for path in (LOG_PATH, LOG_PATH_PREV):
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        payload = find_latest_bot_draft_status(text)
        if payload:
            candidates.append((path.stat().st_mtime, path.name, payload))
    if not candidates:
        return None
    # Most recently modified file wins
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][2]


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
