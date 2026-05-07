"""
Verify which of the 14 known cards from our test pack are actually in
the database (by exact name OR DFC name lookup). Cards missing from the
DB will never match no matter how good the hash strategy is.

Run with:
  py phase3_check_db.py
"""

import json


# Ground truth cards from the test screenshot
TRUTH = [
    "Emeritus of Ideation",
    "Sleight of Hand",
    "Archaic's Agony",
    "Social Snub",
    "Stirring Honormancer",
    "Abstract Paintmage",
    "Rapier Wit",
    "Spellbook Seeker",
    "Sneering Shadewriter",
    "Zealous Lorecaster",
    "Wild Hypothesis",
    "Biblioplex Tomekeeper",
    "Terramorphic Expanse",
    "Plains",
]


def main():
    with open("card_db/cards.json", "r", encoding="utf-8") as f:
        db = json.load(f)
    print(f"DB has {len(db)} entries\n")

    # Build index by face_name AND by full card name (for DFCs)
    by_face = {}
    by_full = {}
    for e in db:
        by_face.setdefault(e["face_name"], []).append(e)
        by_full.setdefault(e["name"], []).append(e)

    missing = []
    for name in TRUTH:
        # Exact face_name match
        if name in by_face:
            entries = by_face[name]
            sets = ", ".join(sorted({f"{e['set']}#{e['collector_number']}" for e in entries}))
            print(f"  OK   {name:35} -- {len(entries)} entries: {sets}")
            continue
        # Look for DFC where this is one face
        partial = [e for e in db if name.lower() in e["name"].lower()
                   or name.lower() in e["face_name"].lower()]
        if partial:
            entries = partial[:3]
            sets = ", ".join(f"{e['name']} ({e['set']}#{e['collector_number']})" for e in entries)
            print(f"  ~    {name:35} -- found via partial: {sets}")
            continue
        print(f"  MISS {name:35} -- NOT FOUND in DB")
        missing.append(name)

    print()
    print(f"Summary: {len(TRUTH) - len(missing)}/{len(TRUTH)} cards present, "
          f"{len(missing)} missing")
    if missing:
        print(f"Missing: {missing}")


if __name__ == "__main__":
    main()
