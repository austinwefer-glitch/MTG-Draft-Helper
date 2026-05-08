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

USER_AGENT = "MTGDraftHelper/0.1 (https://github.com/austinwefer-glitch/MTG-Draft-Helper)"
OUTPUT = Path("card_db") / "tier_index.json"


USER_GROUPS = ["all", "top"]


def fetch_format(set_code: str, fmt: str, user_group: str) -> list[dict]:
    """Fetch all card ratings for one (set, format, user_group) tuple.

    17Lands treats "all users" as the unfiltered default — passing
    user_group=all returns empty data. Only the "top" filter is a real
    parameter value.
    """
    params = {
        "expansion": set_code,
        "format": fmt,
    }
    if user_group != "all":
        params["user_group"] = user_group
    url = ("https://www.17lands.com/card_ratings/data?"
           + urllib.parse.urlencode(params))
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    print(f"Fetching {fmt} ({user_group})...")
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected response type for {fmt}/{user_group}")
    print(f"  -> {len(data)} card ratings")
    return data


def main() -> None:
    by_name: dict[str, dict] = {}
    for fmt in FORMATS:
        for ug in USER_GROUPS:
            try:
                data = fetch_format(SET_CODE, fmt, ug)
            except Exception as e:
                print(f"  Failed to fetch {fmt} ({ug}): {e}")
                continue
            for entry in data:
                name = entry.get("name")
                if not name:
                    continue
                slot = by_name.setdefault(name, {}).setdefault(fmt, {})
                # ALSA / ATA / color / rarity only stored from the 'all' group
                # (those are about community pick order — broader sample is better).
                if ug == "all":
                    slot["alsa"] = entry.get("avg_seen")
                    slot["ata"] = entry.get("avg_pick")
                    slot["color"] = entry.get("color")
                    slot["rarity"] = entry.get("rarity")
                    slot["gih_wr_all"] = entry.get("ever_drawn_win_rate")
                    slot["drawn_count_all"] = entry.get("drawn_game_count")
                    # Legacy fields kept for backward compatibility
                    slot["gih_wr"] = entry.get("ever_drawn_win_rate")
                    slot["drawn_count"] = entry.get("drawn_game_count")
                else:  # "top"
                    slot["gih_wr_top"] = entry.get("ever_drawn_win_rate")
                    slot["drawn_count_top"] = entry.get("drawn_game_count")
            time.sleep(0.5)  # be polite to 17Lands' servers

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as f:
        json.dump(by_name, f, indent=2, ensure_ascii=False)

    print()
    print(f"Wrote {len(by_name)} cards to {OUTPUT}")

    # Quick sanity check showing both player groups side by side
    print("\nSample entries (all-player WR / top-player WR):")
    for sample_name in [
        "Emeritus of Ideation",
        "Sleight of Hand",
        "Wild Hypothesis",
    ]:
        e = by_name.get(sample_name)
        if not e:
            print(f"  {sample_name:32}  NOT FOUND")
            continue
        qd = e.get("QuickDraft", {})
        all_wr = qd.get("gih_wr_all")
        top_wr = qd.get("gih_wr_top")
        all_str = f"{all_wr*100:.1f}%" if all_wr is not None else "  -  "
        top_str = f"{top_wr*100:.1f}%" if top_wr is not None else "  -  "
        print(f"  {sample_name:32}  all={all_str:>7}   top={top_str:>7}")


if __name__ == "__main__":
    main()
