"""
Diagnostic v3: try several hash algorithms / sizes / crop strategies and
score each against ground truth (the hand-typed list of cards we know are
in the test pack).

Run with:
  py phase3_diagnose_v3.py screenshots/<file>_mon3.png
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


# Hand-typed ground truth from the user
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


def card_slots(n):
    top = [(x, TOP_ROW_Y) for x in COL_X]
    bot = [(x, BOT_ROW_Y) for x in COL_X[:6]]
    return (top + bot)[:n]


def hash_image(img, algo: str, size: int):
    """Compute a hash of the given Pillow image with the specified algorithm."""
    if algo == "phash":
        return imagehash.phash(img, hash_size=size)
    if algo == "dhash":
        return imagehash.dhash(img, hash_size=size)
    if algo == "whash":
        return imagehash.whash(img, hash_size=size)
    if algo == "ahash":
        return imagehash.average_hash(img, hash_size=size)
    raise ValueError(algo)


def db_hashes_for(db, algo: str, size: int):
    """Compute every DB image's hash with the given algorithm/size.

    Re-hashing from disk each run is ~563 images and takes a minute. That's
    acceptable for diagnosis.
    """
    out = []
    for e in db:
        path = e.get("image_path")
        if path and Path(path).exists():
            try:
                im = Image.open(path).convert("RGB")
                h = hash_image(im, algo, size)
                out.append((h, e))
            except Exception:
                pass
    return out


def best(crop_h, db_h):
    bd = 9999
    be = None
    for dh, e in db_h:
        d = dh - crop_h
        if d < bd:
            bd = d
            be = e
    return be, bd


def name_matches(predicted_name: str, expected_name: str) -> bool:
    """A predicted card name matches expected if either name is contained
    in the other (case-insensitive). Handles DFC '//' joining."""
    if not predicted_name or not expected_name:
        return False
    pl = predicted_name.lower()
    el = expected_name.lower()
    return el in pl or pl in el


def evaluate_strategy(img, db_h, *, name: str, inset: int):
    correct = 0
    rows = []
    for i, (x, y) in enumerate(card_slots(len(TRUTH)), start=1):
        crop = img.crop((
            x + inset, y + inset,
            x + CARD_WIDTH - inset, y + CARD_HEIGHT - inset,
        ))
        # We need to know the algo/size from the strategy name
        # Format: "<algo>_h<size>_inset<n>"  (already encoded in name)
        # Actually we already created the db_h with this algo/size,
        # so we just need to hash the crop with the same.
        # Pass via globals to keep this readable:
        h = STRATEGY_HASH(crop)
        e, d = best(h, db_h)
        ok = name_matches(e["face_name"], TRUTH[i-1]) or name_matches(e["name"], TRUTH[i-1])
        if ok:
            correct += 1
        rows.append((i, TRUTH[i-1], e["face_name"], d, ok))
    return correct, rows


# Global hash function for strategy currently being tested.
STRATEGY_HASH = None


def main(screenshot_path: Path) -> None:
    with open("card_db/cards.json", "r", encoding="utf-8") as f:
        db = json.load(f)
    print(f"DB: {len(db)} entries")

    img = Image.open(screenshot_path).convert("RGB")
    print(f"Screenshot: {img.size[0]}x{img.size[1]}")
    print(f"Ground truth: {len(TRUTH)} cards")
    print()

    strategies = [
        ("phash", 8),
        ("phash", 16),
        ("dhash", 8),
        ("dhash", 16),
        ("whash", 8),
        ("ahash", 8),
    ]
    insets = [0, 8, 12, 16]

    best_strategy = None
    best_correct = -1
    summary = []

    for algo, size in strategies:
        print(f"--- Building DB hashes with {algo} size={size} (re-hashing all images)... ---")
        db_h = db_hashes_for(db, algo, size)
        print(f"    {len(db_h)} entries hashed.")

        global STRATEGY_HASH
        STRATEGY_HASH = lambda im, a=algo, s=size: hash_image(im, a, s)

        for inset in insets:
            correct, rows = evaluate_strategy(img, db_h, name=f"{algo}_h{size}_in{inset}", inset=inset)
            label = f"{algo} hsize={size} inset={inset}"
            summary.append((correct, label, rows))
            print(f"  {label:<32} -> {correct}/{len(TRUTH)} correct")
            if correct > best_correct:
                best_correct = correct
                best_strategy = (label, rows)

    print()
    print("=" * 70)
    print(f"BEST: {best_strategy[0]}  ({best_correct}/{len(TRUTH)} correct)")
    print("=" * 70)
    print(f"{'#':>3}  {'Truth':<30}  {'Predicted':<32}  d   ok")
    print("-" * 80)
    for i, truth, pred, d, ok in best_strategy[1]:
        marker = "OK" if ok else " "
        print(f"{i:>3}  {truth:<30}  {pred:<32}  {d:>2}  {marker}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: py phase3_diagnose_v3.py <screenshot>")
        sys.exit(1)
    main(Path(sys.argv[1]))
