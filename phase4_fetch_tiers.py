"""
Phase 4 — Step 1: Fetch SOS card ratings from 17Lands.

17Lands is a free, community-run service that aggregates real MTG Arena
draft data. They expose a public endpoint at /card_ratings/data that
returns each card's stats for a given set + format.

Key column we care about: GIH WR (game-in-hand win rate). This is the
percentage of games won, when the card was in the player's hand at any
point. It's the single best predictor of card power in limited.

Output:
  card_db/tier_index.json  -- dict keyed by exact card name, with stats
                              per format (QuickDraft and PremierDraft).

Run with:
  py phase4_fetch_tiers.py
"""

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path


# Read set code and formats from config.json so users can target other sets.
import json as _json
_cfg_path = Path(__file__).parent / "config.json"
if _cfg_path.exists():
    _cfg = _json.loads(_cfg_path.read_text(encoding="utf-8"))
    SET_CODE = _cfg.get("tier_set_code", "SOS")
    FORMATS = _cfg.get("tier_formats", ["QuickDraft", "PremierDraft"])
else:
    SET_CODE = "SOS"
    FORMATS = ["QuickDraft", "PremierDraft"]

USER_AGENT = "MTGDraftHelper/0.1 (https://github.com/your-username/mtg-draft-helper)"
OUTPUT = Path("card_db") / "tier_index.json"


def fetch_format(set_code: str, fmt: str) -> list[dict]:
    """Fetch all card ratings for one (set, format) pair."""
    params = {"expansion": set_code, "format": fmt}
    url = "https://www.17lands.com/card_ratings/data?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    print(f"Fetching {fmt}...  ({url})")
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected response type for {fmt}: {type(data)}")
    print(f"  -> {len(data)} card ratings")
    return data


def main() -> None:
    by_name: dict[str, dict] = {}
    for fmt in FORMATS:
        try:
            data = fetch_format(SET_CODE, fmt)
        except Exception as e:
            print(f"  Failed to fetch {fmt}: {e}")
            continue
        for entry in data:
            name = entry.get("name")
            if not name:
                continue
            slot = by_name.setdefault(name, {})
            slot[fmt] = {
                "alsa": entry.get("avg_seen"),
                "ata": entry.get("avg_pick"),
                "gih_wr": entry.get("ever_drawn_win_rate"),
                "ohwr": entry.get("opening_hand_win_rate"),
                "iwd": entry.get("drawn_improvement_win_rate"),
                "drawn_count": entry.get("drawn_game_count"),
                "color": entry.get("color"),
                "rarity": entry.get("rarity"),
            }
        time.sleep(0.5)  # be polite to 17Lands' servers

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as f:
        json.dump(by_name, f, indent=2, ensure_ascii=False)

    print()
    print(f"Wrote {len(by_name)} cards to {OUTPUT}")

    # Quick sanity check
    print("\nSample entries:")
    for sample_name in [
        "Emeritus of Ideation",
        "Sleight of Hand",
        "Plains",
        "Wild Hypothesis",
    ]:
        e = by_name.get(sample_name)
        if e:
            qd = e.get("QuickDraft", {})
            gih = qd.get("gih_wr")
            print(f"  {sample_name:32}  QuickDraft GIH WR = "
                  f"{gih*100:.1f}%" if gih else "  (no data)")
        else:
            print(f"  {sample_name:32}  NOT FOUND")


if __name__ == "__main__":
    main()
