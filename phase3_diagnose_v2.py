"""
Diagnostic v2: try a range of inner-crop insets and see which gives the
lowest pHash distances. The hypothesis is that Arena's hover-highlight
border / overlay text is bleeding into our crop and inflating distances.

Run with:
  py phase3_diagnose_v2.py screenshots/<file>_mon3.png
"""

import json
import sys
from pathlib import Path

import imagehash
from PIL import Image


CARD_WIDTH = 165
CARD_HEIGHT = 230
TOP_ROW_Y = 145
BOT_ROW_Y = 395
COL_X = [305, 480, 655, 830, 1005, 1180, 1355, 1530]


def card_slots(n):
    top = [(x, TOP_ROW_Y) for x in COL_X]
    bot = [(x, BOT_ROW_Y) for x in COL_X[:6]]
    return (top + bot)[:n]


def best_match(crop, db_hashes):
    h = imagehash.phash(crop)
    best = None
    best_d = 999
    for dh, e in db_hashes:
        d = dh - h
        if d < best_d:
            best_d = d
            best = e
    return best, best_d


def main(screenshot_path: Path, expected_count: int = 14) -> None:
    with open("card_db/cards.json", "r", encoding="utf-8") as f:
        db = json.load(f)
    db_hashes = [(imagehash.hex_to_hash(e["phash"]), e) for e in db]
    print(f"DB: {len(db)} entries")

    img = Image.open(screenshot_path).convert("RGB")
    print(f"Screenshot: {img.size[0]}x{img.size[1]}")
    print()

    # Insets to try: pixels to trim from each side of the original 165x230 box
    INSETS = [0, 4, 8, 12, 16, 20]

    slots = card_slots(expected_count)

    print(f"{'Slot':<5}", end="")
    for inset in INSETS:
        print(f"{'in='+str(inset):<28}", end="")
    print()
    print("-" * (5 + 28 * len(INSETS)))

    for i, (x, y) in enumerate(slots, start=1):
        print(f"{i:<5}", end="")
        for inset in INSETS:
            crop = img.crop((
                x + inset,
                y + inset,
                x + CARD_WIDTH - inset,
                y + CARD_HEIGHT - inset,
            ))
            entry, d = best_match(crop, db_hashes)
            name = entry["face_name"][:20]
            print(f"d={d:>3} {name:<22}", end="")
        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: py phase3_diagnose_v2.py <screenshot> [count]")
        sys.exit(1)
    main(Path(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 14)
