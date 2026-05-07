"""
Phase 2 — Step 2: Download all Secrets of Strixhaven cards from Scryfall
and compute perceptual hashes (pHashes) for image matching.

Outputs (created in this folder):
  card_db/images/*.jpg   - the downloaded card images
  card_db/cards.json     - list of card metadata + pHashes (the "card database")

How to run (in the VS Code terminal, from this folder):
  py phase2_build_db.py

What to expect:
  - First run takes roughly 5-10 minutes depending on your internet speed.
    The script is polite to Scryfall's API: it sleeps 100ms between requests.
  - If you re-run, it skips re-downloading any image already saved on disk,
    so iterating is fast.
  - Final summary prints how many cards were processed and how many ended
    up with unique perceptual hashes.
"""

import json
import time
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image
import imagehash


# ---- Configuration ----
# Set codes to include in the database — pulled from config.json so the
# tool can target whatever set is currently in Arena draft.
import json as _json
_cfg_path = Path(__file__).parent / "config.json"
if _cfg_path.exists():
    _cfg = _json.loads(_cfg_path.read_text(encoding="utf-8"))
    SET_CODES = _cfg.get("set_codes_in_pool", ["sos", "soa", "spg"])
else:
    SET_CODES = ["sos", "soa", "spg"]

SCRYFALL_API = "https://api.scryfall.com"
USER_AGENT = "MTGDraftHelper/0.1 (https://github.com/austinwefer-glitch/MTG-Draft-Helper)"

# Scryfall asks for at least 50-100ms between requests. We use 100ms.
REQUEST_DELAY_SEC = 0.1

PROJECT_DIR = Path(__file__).parent
OUTPUT_DIR = PROJECT_DIR / "card_db"
IMAGE_DIR = OUTPUT_DIR / "images"
DB_FILE = OUTPUT_DIR / "cards.json"


def http_get_json(url: str) -> dict:
    """GET a JSON URL from Scryfall with the required headers and a polite delay."""
    time.sleep(REQUEST_DELAY_SEC)
    resp = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def http_get_image(url: str) -> Image.Image:
    """Download an image and return a Pillow Image (converted to RGB)."""
    time.sleep(REQUEST_DELAY_SEC)
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return Image.open(BytesIO(resp.content)).convert("RGB")


def fetch_all_cards(set_code: str) -> list[dict]:
    """Use Scryfall's search endpoint to fetch every card in the given set.

    Scryfall paginates results; we follow `next_page` until done.
    """
    print(f"Fetching all cards in set '{set_code}' from Scryfall...")
    # `q=set:sos`    -> match the set
    # `unique=prints` -> one entry per PRINTING (every art variant counted).
    #                   We need this so showcase / borderless / alt-art versions
    #                   each get their own pHash — Arena renders various
    #                   treatments and we have to match whichever shows up.
    # `order=set`    -> stable order by collector number
    url = f"{SCRYFALL_API}/cards/search?q=set%3A{set_code}&unique=prints&order=set"
    cards: list[dict] = []
    page = 1
    while url:
        print(f"  fetching metadata page {page}...")
        data = http_get_json(url)
        cards.extend(data.get("data", []))
        if data.get("has_more"):
            url = data.get("next_page")
            page += 1
        else:
            url = None
    print(f"  Got metadata for {len(cards)} cards.\n")
    return cards


def card_image_faces(card: dict) -> list[tuple[str, str]]:
    """Return a list of (face_label, image_url) for a card.

    Most cards have one image at the top level. Double-faced / transform
    cards have separate images per face under `card_faces`.
    Adventure/split/flip cards have ONE image even though they have two
    `card_faces` entries — those still have a top-level image_uris.
    """
    if "image_uris" in card:
        return [("front", card["image_uris"]["normal"])]
    if "card_faces" in card:
        faces = []
        for i, face in enumerate(card["card_faces"]):
            if "image_uris" in face:
                label = "front" if i == 0 else "back"
                faces.append((label, face["image_uris"]["normal"]))
        return faces
    return []


def face_metadata(card: dict, face_label: str) -> dict:
    """Pull the right metadata block for the given face.

    For DFCs, name / type_line / mana_cost / colors live on the per-face dict.
    For single-faced cards everything lives at the top level.
    """
    if "card_faces" in card and "image_uris" not in card:
        # True DFC — pick the right face block
        idx = 0 if face_label == "front" else 1
        if idx < len(card["card_faces"]):
            return card["card_faces"][idx]
    return card


def build_database(cards: list[dict]) -> list[dict]:
    """For each card face, ensure the image is on disk, compute pHash,
    and produce a list of database entries."""
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    # First, count total faces so progress numbers are meaningful
    total_faces = sum(len(card_image_faces(c)) for c in cards)
    print(f"Will process {total_faces} card faces "
          f"({len(cards)} cards, including double-faced).\n")

    db: list[dict] = []
    processed = 0

    for card in cards:
        for face_label, image_url in card_image_faces(card):
            processed += 1
            filename = f"{card['set']}_{card['collector_number']}_{face_label}.jpg"
            image_path = IMAGE_DIR / filename

            # Download (or reuse cached image), then compute pHash
            try:
                if image_path.exists():
                    img = Image.open(image_path).convert("RGB")
                else:
                    img = http_get_image(image_url)
                    img.save(image_path, "JPEG", quality=85)
                phash = str(imagehash.phash(img))
            except Exception as e:
                print(f"  ! Failed on {card.get('name')} ({face_label}): {e}")
                continue

            face = face_metadata(card, face_label)

            entry = {
                "name": card.get("name"),
                "face_name": face.get("name", card.get("name")),
                "face": face_label,
                "set": card.get("set"),
                "collector_number": card.get("collector_number"),
                "rarity": card.get("rarity"),
                "type_line": face.get("type_line", card.get("type_line", "")),
                "mana_cost": face.get("mana_cost", card.get("mana_cost", "")),
                "cmc": card.get("cmc", 0),
                "colors": face.get("colors", card.get("colors", [])),
                "color_identity": card.get("color_identity", []),
                "scryfall_id": card.get("id"),
                "scryfall_uri": card.get("scryfall_uri"),
                # arena_id maps Scryfall data to MTG Arena's internal card IDs.
                # We use this to identify cards in the Arena log file.
                "arena_id": card.get("arena_id"),
                "mtgo_id": card.get("mtgo_id"),
                # Synergy detection: keywords are Scryfall's parsed list of
                # ability words (Flying, Magecraft, Adventure, etc.).
                # oracle_text is the full rules text — we substring-search it
                # for archetype themes.
                "keywords": card.get("keywords", []),
                "oracle_text": face.get("oracle_text", card.get("oracle_text", "")),
                "image_path": str(image_path.relative_to(PROJECT_DIR)).replace("\\", "/"),
                "phash": phash,
            }
            db.append(entry)

            # Print progress every 25 entries (and at the very end)
            if processed % 25 == 0 or processed == total_faces:
                print(f"  [{processed}/{total_faces}] {card['name']} "
                      f"({face_label}) -> {phash}")

    return db


def main():
    all_cards: list[dict] = []
    for code in SET_CODES:
        all_cards.extend(fetch_all_cards(code))
    print(f"Total cards across {len(SET_CODES)} sets: {len(all_cards)}\n")
    db = build_database(all_cards)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

    # ---- Summary ----
    rarities: dict[str, int] = {}
    for entry in db:
        r = entry.get("rarity", "?")
        rarities[r] = rarities.get(r, 0) + 1

    print()
    print("=" * 60)
    print(f"Saved {len(db)} entries -> {DB_FILE}")
    print(f"Images saved in {IMAGE_DIR}")
    print()
    print("Breakdown by rarity:")
    for r, count in sorted(rarities.items(), key=lambda x: -x[1]):
        print(f"  {r:15} {count}")

    # Detect any cards that share a perceptual hash (rare for distinct art).
    hash_counts: dict[str, list[str]] = {}
    for entry in db:
        hash_counts.setdefault(entry["phash"], []).append(
            f"{entry['face_name']} (#{entry['collector_number']})"
        )
    collisions = {h: names for h, names in hash_counts.items() if len(names) > 1}
    if collisions:
        print(f"\n{len(collisions)} hash collisions "
              f"(cards sharing a pHash — could indicate identical art):")
        for h, names in list(collisions.items())[:10]:
            print(f"  {h}: {names}")
    else:
        print("\nAll cards have unique pHashes — great for matching.")
    print("=" * 60)


if __name__ == "__main__":
    main()
