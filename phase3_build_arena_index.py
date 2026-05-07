"""
Build an arena_id -> card-info index by querying MTG Arena's local
SQLite databases (Raw_CardDatabase_*.mtga).

The .mtga files are SQLite. The Cards table has:
  GrpId           -- this IS the arena_id
  TitleId         -- joins to Localizations_enUS.LocId for the English name
  ExpansionCode   -- the set code (e.g. 'SOS')
  CollectorNumber -- collector number string
  Rarity          -- integer enum (mapped via Enums table)
  IsPrimaryCard   -- 0/1
  IsToken         -- 0/1
  Power, Toughness, ...

Output:
  card_db/arena_index.json   - dict of {arena_id: {name, set, collector_number, ...}}

Run with:
  py phase3_build_arena_index.py
"""

import json
import sqlite3
import sys
from pathlib import Path


# Common MTG Arena install locations to probe. The first one that
# contains an MTGA_Data/Downloads/Raw folder wins.
CANDIDATE_INSTALL_ROOTS = [
    Path(r"C:\Program Files\Wizards of the Coast\MTGA"),
    Path(r"C:\Program Files (x86)\Wizards of the Coast\MTGA"),
    Path(r"D:\Program Files\Wizards of the Coast\MTGA"),
    Path(r"D:\Wizards of the Coast\MTGA"),
    Path(r"E:\Program Files\Wizards of the Coast\MTGA"),
    Path.home() / "AppData" / "Local" / "Wizards of the Coast" / "MTGA",
    # Steam library default
    Path(r"C:\Program Files (x86)\Steam\steamapps\common\MTGA"),
]


def find_data_dir() -> Path | None:
    """Find the Raw subdirectory inside any known MTGA install location."""
    for root in CANDIDATE_INSTALL_ROOTS:
        candidate = root / "MTGA_Data" / "Downloads" / "Raw"
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def find_latest(data_dir: Path, prefix: str) -> Path | None:
    candidates = list(data_dir.glob(f"{prefix}*.mtga"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def open_ro(path: Path) -> sqlite3.Connection:
    """Open SQLite file read-only via URI mode."""
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


# Arena's rarity int -> human label. Verified empirically; may need adjustment.
RARITY_MAP = {
    0: "token",
    1: "basic_land",
    2: "common",
    3: "uncommon",
    4: "rare",
    5: "mythic",
}


def main() -> None:
    data_dir = find_data_dir()
    if not data_dir:
        print("Could not find MTG Arena's data folder. Tried:")
        for root in CANDIDATE_INSTALL_ROOTS:
            print(f"  {root / 'MTGA_Data' / 'Downloads' / 'Raw'}")
        print()
        print("Find your MTGA install location (right-click the Arena shortcut "
              "on your desktop → Open File Location → go up two folders) and "
              "add it to CANDIDATE_INSTALL_ROOTS in this file.")
        sys.exit(1)
    print(f"MTGA data dir: {data_dir}")

    cards_file = find_latest(data_dir, "Raw_CardDatabase_")
    if not cards_file:
        print(f"Could not find Raw_CardDatabase_*.mtga in {data_dir}")
        sys.exit(1)
    print(f"Cards db: {cards_file.name}")

    conn = open_ro(cards_file)
    cur = conn.cursor()

    # Pull every card with its English name.
    # Use LEFT JOIN so we still get rows whose name is missing.
    query = """
        SELECT
            c.GrpId,
            l.Loc           AS Name,
            c.ExpansionCode,
            c.CollectorNumber,
            c.Rarity,
            c.IsPrimaryCard,
            c.IsToken,
            c.IsDigitalOnly,
            c.LinkedFaceGrpIds,
            c.Power,
            c.Toughness,
            c.Colors
        FROM Cards c
        LEFT JOIN Localizations_enUS l ON c.TitleId = l.LocId
        WHERE c.GrpId > 0
    """
    cur.execute(query)
    rows = cur.fetchall()
    print(f"Cards table rows: {len(rows):,}")
    conn.close()

    index: dict[int, dict] = {}
    for (grp, name, exp, cn, rarity, is_primary, is_token,
         is_digital, linked_faces, power, tough, colors) in rows:
        if grp is None:
            continue
        index[int(grp)] = {
            "arena_id": int(grp),
            "name": name or "",
            "set": (exp or "").lower(),
            "collector_number": cn or "",
            "rarity": RARITY_MAP.get(rarity, str(rarity)),
            "is_primary": bool(is_primary),
            "is_token": bool(is_token),
            "is_digital_only": bool(is_digital),
            "linked_face_grpids": linked_faces or "",
            "power": power or "",
            "toughness": tough or "",
            "colors": colors or "",
        }

    out_path = Path("card_db") / "arena_index.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {len(index):,} entries to {out_path}")

    # ---- Spot-check IDs from the latest pack ----
    test_ids = [102724, 102706, 102596, 102487, 102527, 102560, 102626,
                102687, 102693, 102566, 102630, 102774, 102504, 102732]
    print("\nSpot-check IDs from the latest pack:")
    hits = misses = 0
    for tid in test_ids:
        e = index.get(tid)
        if e and e["name"]:
            hits += 1
            print(f"  {tid}: {e['name']:38} ({e['set']} #{e['collector_number']}, {e['rarity']})")
        else:
            misses += 1
            print(f"  {tid}: NOT FOUND")
    print(f"\nResult: {hits}/{len(test_ids)} found, {misses} missing")


if __name__ == "__main__":
    main()
