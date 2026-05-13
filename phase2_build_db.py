"""
Phase 2 — Step 2: Download all cards in the configured sets from Scryfall
and compute perceptual hashes (pHashes) for image matching.

Outputs (created in this folder):
  card_db/images/*.jpg           - downloaded card images
  card_db/cards.json             - list of card metadata + pHashes
  card_db/_metadata_cache/*.json - per-page Scryfall responses, used for
                                    resume on failure (delete to refetch)

How to run (in the VS Code terminal, from this folder):
  py phase2_build_db.py

Resilience:
  - HTTP requests retry up to 5 times with exponential backoff on
    transient network errors (ConnectionError, Timeout, etc.).
  - Each Scryfall metadata page is cached to disk after a successful
    fetch. A re-run picks up where the previous one died.
  - Image downloads are skipped if the file already exists.

Progress:
  - Every page and every (downloaded) image prints a line so you can
    watch it work and see where it stopped if it errors out.
"""

import json
import time
from io import BytesIO
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
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

# Retry policy for transient network failures.
APP_RETRIES = 5
APP_RETRY_BACKOFF_BASE_SEC = 2  # 2s, 4s, 8s, 16s, 32s

PROJECT_DIR = Path(__file__).parent
OUTPUT_DIR = PROJECT_DIR / "card_db"
IMAGE_DIR = OUTPUT_DIR / "images"
METADATA_CACHE_DIR = OUTPUT_DIR / "_metadata_cache"
DB_FILE = OUTPUT_DIR / "cards.json"


# ---- HTTP session with built-in retry policy ----

def _make_session() -> requests.Session:
    """Create a requests.Session with urllib3 Retry mounted on both
    http:// and https://. This handles 429/5xx and connection-level
    retries at the transport layer."""
    s = requests.Session()
    retry = Retry(
        total=APP_RETRIES,
        connect=APP_RETRIES,
        read=APP_RETRIES,
        backoff_factor=APP_RETRY_BACKOFF_BASE_SEC,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.headers.update({"User-Agent": USER_AGENT})
    return s


SESSION = _make_session()


# Connection-reset errors raised at the socket level sometimes escape
# urllib3.Retry (e.g. WinError 10054 mid-stream). Wrap requests in an
# additional app-level retry loop with exponential backoff to catch those.
def _request_with_app_retries(method: str, url: str, **kwargs) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(APP_RETRIES + 1):
        try:
            return SESSION.request(method, url, **kwargs)
        except (
            requests.ConnectionError,
            requests.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ) as e:
            last_exc = e
            if attempt >= APP_RETRIES:
                break
            delay = APP_RETRY_BACKOFF_BASE_SEC * (2 ** attempt)
            print(f"    ! {type(e).__name__}: {e}")
            print(f"      retrying in {delay}s (attempt {attempt + 2}/{APP_RETRIES + 1})...")
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def http_get_json(url: str) -> dict:
    """GET a JSON URL from Scryfall with retries and a polite delay."""
    time.sleep(REQUEST_DELAY_SEC)
    resp = _request_with_app_retries(
        "GET", url,
        headers={"Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def http_get_image(url: str) -> Image.Image:
    """Download an image with retries; return a Pillow Image in RGB."""
    time.sleep(REQUEST_DELAY_SEC)
    resp = _request_with_app_retries("GET", url, timeout=30)
    resp.raise_for_status()
    return Image.open(BytesIO(resp.content)).convert("RGB")


# ---- Scryfall metadata fetch (with per-page cache) ----

def fetch_all_cards(set_code: str) -> list[dict]:
    """Fetch every card in a set from Scryfall, following pagination.
    Each page is cached to disk so a re-run can resume from where the
    previous run died."""
    METADATA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\nFetching set '{set_code}' from Scryfall...")
    url = (f"{SCRYFALL_API}/cards/search?"
           f"q=set%3A{set_code}&unique=prints&order=set")
    cards: list[dict] = []
    page = 1
    while url:
        cache_file = METADATA_CACHE_DIR / f"{set_code}_page_{page}.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                n = len(data.get("data", []))
                print(f"  Page {page} (cached, {n} cards)")
            except json.JSONDecodeError:
                print(f"  Page {page} cache corrupt; re-fetching")
                data = http_get_json(url)
                cache_file.write_text(json.dumps(data), encoding="utf-8")
                n = len(data.get("data", []))
                print(f"  Page {page} fetched ({n} cards)")
        else:
            data = http_get_json(url)
            cache_file.write_text(json.dumps(data), encoding="utf-8")
            n = len(data.get("data", []))
            print(f"  Page {page} fetched ({n} cards)")
        cards.extend(data.get("data", []))
        if data.get("has_more"):
            url = data.get("next_page")
            page += 1
        else:
            url = None
    print(f"  Done — {len(cards)} cards in '{set_code}'")
    return cards


# ---- Per-card image / hash handling ----

def card_image_faces(card: dict) -> list[tuple[str, str]]:
    """Return a list of (face_label, image_url) for a card."""
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
    """Pull the right metadata block for the given face."""
    if "card_faces" in card and "image_uris" not in card:
        idx = 0 if face_label == "front" else 1
        if idx < len(card["card_faces"]):
            return card["card_faces"][idx]
    return card


def build_database(cards: list[dict]) -> list[dict]:
    """For each card face, ensure the image is on disk, compute pHash,
    and produce a list of database entries.

    Images already on disk are reused — re-running after a failure
    skips the download. The pHash is recomputed each time from the
    on-disk image, which is fast (sub-100ms each)."""
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    total_faces = sum(len(card_image_faces(c)) for c in cards)
    print(f"\nProcessing {total_faces} card faces "
          f"({len(cards)} cards, includes double-faced).")

    db: list[dict] = []
    processed = 0
    downloaded = 0
    cached = 0
    failed = 0

    for card in cards:
        for face_label, image_url in card_image_faces(card):
            processed += 1
            filename = f"{card['set']}_{card['collector_number']}_{face_label}.jpg"
            image_path = IMAGE_DIR / filename

            try:
                if image_path.exists():
                    img = Image.open(image_path).convert("RGB")
                    cached += 1
                else:
                    img = http_get_image(image_url)
                    img.save(image_path, "JPEG", quality=85)
                    downloaded += 1
                    # Print every new download so the user sees progress
                    print(f"  Image {processed}/{total_faces} downloaded "
                          f"({downloaded} new, {cached} cached): "
                          f"{card['name']} ({face_label})")
                phash = str(imagehash.phash(img))
            except Exception as e:
                failed += 1
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
                "arena_id": card.get("arena_id"),
                "mtgo_id": card.get("mtgo_id"),
                "keywords": card.get("keywords", []),
                "oracle_text": face.get("oracle_text", card.get("oracle_text", "")),
                "image_path": str(image_path.relative_to(PROJECT_DIR)).replace("\\", "/"),
                "phash": phash,
            }
            db.append(entry)

    print(f"\nImage stage complete: "
          f"{downloaded} downloaded, {cached} cached, {failed} failed.")
    return db


# ---- Entry point ----

def main():
    all_cards: list[dict] = []
    for code in SET_CODES:
        all_cards.extend(fetch_all_cards(code))
    print(f"\nTotal cards across {len(SET_CODES)} sets: {len(all_cards)}")

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
        print(f"\n{len(collisions)} hash collisions:")
        for h, names in list(collisions.items())[:10]:
            print(f"  {h}: {names}")
    else:
        print("\nAll cards have unique pHashes — great for matching.")
    print("=" * 60)


if __name__ == "__main__":
    main()
