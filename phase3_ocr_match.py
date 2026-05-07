"""
Phase 3 — OCR-based card identifier.

Crops the title-bar region of each card slot, runs Tesseract OCR on it,
then fuzzy-matches the extracted text against the 563 card names in our
database.

Run with:
  py phase3_ocr_match.py screenshots/<file>_mon3.png
"""

import difflib
import json
import sys
from pathlib import Path

import pytesseract
from PIL import Image, ImageOps, ImageFilter
import numpy as np


# Tell pytesseract where Tesseract is installed (Windows default location)
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)


# Card slot grid (same as before)
CARD_WIDTH = 165
CARD_HEIGHT = 185
TOP_ROW_Y = 200
BOT_ROW_Y = 395
# x coordinates of each of the 8 columns. Stride is ~175 for slots 1-6,
# but compresses to ~145/170 for slots 7-8 (Arena's pack layout isn't
# perfectly uniform — visually verified from screenshot).
COL_X = [305, 480, 655, 830, 1005, 1180, 1320, 1495]

# Title bar within a card (offsets relative to the card's top-left).
# X inset starts past the leading icon/rarity gem so we get pure text.
# Width trims off the mana-cost icons on the right.
TITLE_X_INSET = 12
TITLE_Y_INSET = 5
TITLE_WIDTH = 115
TITLE_HEIGHT = 24

# Upscale factor for OCR — higher gives more pixel detail per character.
# 6x converts a 24-pixel-tall title into 144 pixels of text height,
# which is well within Tesseract's sweet spot.
OCR_UPSCALE = 6

# Tesseract config: --oem 3 = default LSTM engine, --psm 7 = single text line.
# (No char whitelist — apostrophes break shlex parsing on Windows, and Tesseract
# does fine on English card titles without one.)
TESS_CONFIG = "--oem 3 --psm 7"


def card_slots(n):
    top = [(x, TOP_ROW_Y) for x in COL_X]
    bot = [(x, BOT_ROW_Y) for x in COL_X[:6]]
    return (top + bot)[:n]


def _upscale(crop: Image.Image) -> Image.Image:
    """Grayscale + Lanczos upscale + sharpening (the rendering tricks that
    matter most for clean OCR on small text)."""
    g = crop.convert("L")
    w, h = g.size
    g = g.resize((w * OCR_UPSCALE, h * OCR_UPSCALE), Image.LANCZOS)
    # Unsharp mask sharpens letter edges noticeably without over-amplifying noise
    g = g.filter(ImageFilter.UnsharpMask(radius=2, percent=180, threshold=3))
    return g


def preprocess_simple(crop: Image.Image) -> Image.Image:
    """Upscale + grayscale + sharpen + autocontrast."""
    return ImageOps.autocontrast(_upscale(crop), cutoff=2)


def preprocess_threshold(crop: Image.Image, want_dark_text: bool = True) -> Image.Image:
    """Upscale + sharpen + binarize (handles colored title bars best)."""
    g = _upscale(crop)
    arr = np.array(g, dtype=np.uint8)
    mean = arr.mean()
    if want_dark_text and mean < 128:
        arr = 255 - arr
    threshold = int(np.percentile(arr, 60))
    binarized = np.where(arr < threshold, 0, 255).astype(np.uint8)
    return Image.fromarray(binarized, mode="L")


def preprocess_variants(crop: Image.Image) -> list[Image.Image]:
    """Return several preprocessed versions to try OCR on."""
    return [
        preprocess_simple(crop),
        preprocess_threshold(crop, want_dark_text=True),
        preprocess_threshold(crop, want_dark_text=False),
    ]


def ocr_title_candidates(img: Image.Image, x: int, y: int, slot_index: int = 0) -> list[str]:
    """Crop the title bar of a card at (x, y) and OCR it multiple ways.
    Returns all candidate text strings — the caller picks the best by
    fuzzy-matching each against the card name list.
    """
    title_box = (
        x + TITLE_X_INSET,
        y + TITLE_Y_INSET,
        x + TITLE_X_INSET + TITLE_WIDTH,
        y + TITLE_Y_INSET + TITLE_HEIGHT,
    )
    crop = img.crop(title_box)

    debug_dir = Path("ocr_debug")
    debug_dir.mkdir(exist_ok=True)
    crop.save(debug_dir / f"slot_{slot_index:02d}_raw.png")

    candidates = []
    for variant_idx, pre in enumerate(preprocess_variants(crop)):
        if variant_idx == 0:
            pre.save(debug_dir / f"slot_{slot_index:02d}_preprocessed.png")
        for psm in (7, 6, 8):  # 7=line, 6=block, 8=word
            cfg = f"--oem 3 --psm {psm}"
            try:
                text = pytesseract.image_to_string(pre, config=cfg).strip()
            except Exception:
                text = ""
            if text:
                candidates.append(text)
    return candidates


def best_name_match(query: str, all_names: list[str]) -> tuple[str, float]:
    """Find the card name most similar to the OCR query."""
    if not query:
        return "(no text)", 0.0
    matches = difflib.get_close_matches(query, all_names, n=1, cutoff=0.0)
    if not matches:
        return "(no match)", 0.0
    best = matches[0]
    score = difflib.SequenceMatcher(None, query.lower(), best.lower()).ratio()
    return best, score


def main(screenshot_path: Path, expected_count: int = 14) -> None:
    with open("card_db/cards.json", "r", encoding="utf-8") as f:
        db = json.load(f)
    print(f"DB: {len(db)} entries")

    # Build a flat list of unique card names for matching.
    # Include both the full name (DFCs joined with //) and per-face names.
    all_names = set()
    for e in db:
        if e.get("name"):
            all_names.add(e["name"])
        if e.get("face_name"):
            all_names.add(e["face_name"])
    all_names = sorted(all_names)
    print(f"Unique card names to match against: {len(all_names)}")

    img = Image.open(screenshot_path).convert("RGB")
    print(f"Screenshot: {img.size[0]}x{img.size[1]}")
    print()
    print(f"{'#':>3}  {'OCR text':<28}  {'Best match':<28}  conf")
    print("-" * 70)

    for i, (x, y) in enumerate(card_slots(expected_count), start=1):
        texts = ocr_title_candidates(img, x, y, slot_index=i)
        # For each OCR candidate, find best DB match + confidence.
        # Pick the (text, match, confidence) with the highest confidence.
        best_text = ""
        best_match = "(no match)"
        best_conf = 0.0
        for t in texts:
            m, c = best_name_match(t, all_names)
            if c > best_conf:
                best_conf = c
                best_match = m
                best_text = t
        ocr_disp = best_text if best_text else "(empty)"
        print(f"{i:>3}  {ocr_disp[:28]:<28}  {best_match[:28]:<28}  {best_conf:.2f}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: py phase3_ocr_match.py <screenshot_path> [expected_count]")
        sys.exit(1)
    main(Path(sys.argv[1]),
         int(sys.argv[2]) if len(sys.argv) > 2 else 14)
