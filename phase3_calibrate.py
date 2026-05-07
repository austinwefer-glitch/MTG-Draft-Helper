"""
Phase 3 calibration helper.

Loads a screenshot, draws colored rectangles where we *think* each pack card
sits, and saves an annotated PNG so we can verify alignment by eye.

Usage (from VS Code terminal):
  py phase3_calibrate.py screenshots/pack_20260506_145350_mon3.png

It writes:
  screenshots/<input_basename>_annotated.png  - original with red rectangles
  card_crops/<input_basename>/card_NN.png     - one crop per guessed region

Look at the annotated image and tell me which rectangles are on/off the cards.
We'll tune the constants below until they line up.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw


# ---- Card grid layout for 1920x1080 Arena pack screen ----
# Pack 1 Pick 1 is 14 cards: 8 in top row, 6 in bottom row.
# All slots for a 14-card pack at 1920x1080. We start with 8 top + 6 bottom.

CARD_WIDTH = 165
CARD_HEIGHT = 230

TOP_ROW_Y = 145    # y of top edge of top-row cards
BOT_ROW_Y = 395    # y of top edge of bottom-row cards

# x coordinates of each of the 8 columns (left edge of each card).
# Stride = 175. First column at x=305.
COL_X = [305, 480, 655, 830, 1005, 1180, 1355, 1530]

TOP_ROW_SLOTS = [(x, TOP_ROW_Y) for x in COL_X]            # 8 slots
BOT_ROW_SLOTS = [(x, BOT_ROW_Y) for x in COL_X[:6]]        # up to 6 slots

# How many cards we expect in this pack (1..14). Adjust based on the screenshot.
EXPECTED_CARD_COUNT = 14


def card_slots(n: int) -> list[tuple[int, int]]:
    """Return the (x, y) top-left of the first n card slots."""
    if n <= 8:
        return TOP_ROW_SLOTS[:n]
    return TOP_ROW_SLOTS + BOT_ROW_SLOTS[: n - 8]


def annotate(input_path: Path, expected_count: int) -> None:
    img = Image.open(input_path).convert("RGB")
    print(f"Loaded {input_path.name}: {img.size[0]}x{img.size[1]}")

    annotated = img.copy()
    draw = ImageDraw.Draw(annotated)

    crops_dir = Path("card_crops") / input_path.stem
    crops_dir.mkdir(parents=True, exist_ok=True)

    slots = card_slots(expected_count)
    for i, (x, y) in enumerate(slots, start=1):
        # Draw a red rectangle of 3px border
        for d in range(3):
            draw.rectangle(
                [x - d, y - d, x + CARD_WIDTH + d, y + CARD_HEIGHT + d],
                outline=(255, 0, 0),
            )
        # Number the box in the top-left
        draw.text((x + 6, y + 4), str(i), fill=(255, 255, 0))

        # Also save the crop
        crop = img.crop((x, y, x + CARD_WIDTH, y + CARD_HEIGHT))
        crop.save(crops_dir / f"card_{i:02d}.png")

    annotated_path = input_path.parent / f"{input_path.stem}_annotated.png"
    annotated.save(annotated_path)
    print(f"Saved annotated overlay: {annotated_path}")
    print(f"Saved {len(slots)} card crops in: {crops_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: py phase3_calibrate.py <screenshot_path> [expected_count]")
        sys.exit(1)
    path = Path(sys.argv[1])
    n = int(sys.argv[2]) if len(sys.argv) > 2 else EXPECTED_CARD_COUNT
    annotate(path, n)
