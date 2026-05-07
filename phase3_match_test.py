"""
Phase 3 — match test.

Loads each of the 14 card crops produced by phase3_calibrate.py, computes the
perceptual hash, and finds the closest match in the card database (by Hamming
distance — number of bits that differ).

Hamming distance interpretation:
   0..10  - almost certainly the right card
  11..20  - probably the right card
  21..30  - same rough family but suspicious
  31+     - probably misaligned crop or card not in DB

Run with:
  py phase3_match_test.py screenshots/<your_screenshot>_mon3.png
"""

import json
import sys
from pathlib import Path

import imagehash
from PIL import Image


# Same constants as phase3_calibrate.py
CARD_WIDTH = 165
CARD_HEIGHT = 230
TOP_ROW_Y = 145
BOT_ROW_Y = 395
COL_X = [305, 480, 655, 830, 1005, 1180, 1355, 1530]


def card_slots(n: int) -> list[tuple[int, int]]:
    top = [(x, TOP_ROW_Y) for x in COL_X]
    bot = [(x, BOT_ROW_Y) for x in COL_X[:6]]
    return (top + bot)[:n]


def load_db(path: str = "card_db/cards.json") -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_best_match(query_hash, db: list[dict]) -> tuple[dict, int]:
    best = None
    best_dist = 999
    for entry in db:
        d = imagehash.hex_to_hash(entry["phash"]) - query_hash
        if d < best_dist:
            best_dist = d
            best = entry
    return best, best_dist


def run(screenshot_path: Path, expected_count: int = 14) -> None:
    db = load_db()
    print(f"Loaded {len(db)} cards from card_db/cards.json")
    print(f"Loading {screenshot_path}...")
    img = Image.open(screenshot_path).convert("RGB")
    print(f"  ({img.size[0]} x {img.size[1]})")
    print()
    print(f"Trying to identify {expected_count} cards...")
    print(f"{'#':>3}  {'Hamming':>7}  {'Verdict':>7}  Card")
    print("-" * 72)

    slots = card_slots(expected_count)
    for i, (x, y) in enumerate(slots, start=1):
        crop = img.crop((x, y, x + CARD_WIDTH, y + CARD_HEIGHT))
        h = imagehash.phash(crop)
        match, dist = find_best_match(h, db)
        if dist <= 10:
            verdict = "OK"
        elif dist <= 20:
            verdict = "maybe"
        else:
            verdict = "FAIL"
        name = f"{match['face_name']:34}  ({match['set']} {match['rarity']})"
        print(f"{i:>3}  {dist:>7}  {verdict:>7}  {name}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: py phase3_match_test.py <screenshot_path> [expected_count]")
        sys.exit(1)
    path = Path(sys.argv[1])
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 14
    run(path, n)
