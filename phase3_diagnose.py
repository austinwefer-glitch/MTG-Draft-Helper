"""
Diagnostic: for each cropped card region, show the top 5 closest matches
in the database (by pHash Hamming distance), so we can see whether the
right card is even close.

Run with:
  py phase3_diagnose.py screenshots/<file>_mon3.png

Also computes the distance between the database's stored image of a card
and the crop, for cards we name explicitly below (KNOWN_CARDS) so we can
see how big the mismatch is on the actual right card.
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

# Cards we visually confirmed in the screenshot (slot index -> name)
KNOWN_CARDS = {
    1: "Emeritus of Ideation",
    2: "Sleight of Hand",
}


def card_slots(n: int):
    top = [(x, TOP_ROW_Y) for x in COL_X]
    bot = [(x, BOT_ROW_Y) for x in COL_X[:6]]
    return (top + bot)[:n]


def main(screenshot_path: Path, expected_count: int = 14) -> None:
    with open("card_db/cards.json", "r", encoding="utf-8") as f:
        db = json.load(f)
    print(f"DB has {len(db)} cards")

    # Pre-decode all DB hashes
    db_hashes = [(imagehash.hex_to_hash(e["phash"]), e) for e in db]
    by_name = {e["face_name"]: e for e in db}

    img = Image.open(screenshot_path).convert("RGB")
    print(f"Screenshot: {img.size[0]}x{img.size[1]}")
    print()

    slots = card_slots(expected_count)
    for i, (x, y) in enumerate(slots, start=1):
        crop = img.crop((x, y, x + CARD_WIDTH, y + CARD_HEIGHT))
        h = imagehash.phash(crop)

        # Find top 5
        scored = [(dh - h, e) for dh, e in db_hashes]
        scored.sort(key=lambda x: x[0])

        print(f"--- Slot {i} (x={x}, y={y}) ---")
        for dist, entry in scored[:5]:
            print(f"   d={dist:>3}  {entry['face_name']:38} ({entry['set']} "
                  f"{entry['collector_number']} {entry['rarity']})")

        # If we know the expected card, also report its distance
        if i in KNOWN_CARDS:
            expected = KNOWN_CARDS[i]
            entry = by_name.get(expected)
            if entry:
                stored_h = imagehash.hex_to_hash(entry["phash"])
                d = stored_h - h
                # Also re-hash the on-disk DB image to verify pHash is reproducible
                if Path(entry["image_path"]).exists():
                    db_img = Image.open(entry["image_path"]).convert("RGB")
                    rehash = imagehash.phash(db_img)
                    rehash_d = rehash - h
                    print(f"   EXPECTED '{expected}': stored-hash distance "
                          f"= {d}  (rehashed-from-disk dist = {rehash_d})")
                else:
                    print(f"   EXPECTED '{expected}': stored-hash distance = {d}  "
                          f"[image not on disk]")
            else:
                print(f"   EXPECTED '{expected}': NOT IN DATABASE")
        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: py phase3_diagnose.py <screenshot_path> [expected_count]")
        sys.exit(1)
    main(Path(sys.argv[1]),
         int(sys.argv[2]) if len(sys.argv) > 2 else 14)
