"""
Look up specific cards on Scryfall to figure out which set they belong to.

Helps us discover whether the cards in Arena packs are coming from sets we
haven't downloaded yet (e.g., a Special Guests / Bonus slot).

Run with:
  py phase3_lookup_card.py
"""

import json
import urllib.request
import urllib.parse


CARDS_TO_LOOK_UP = [
    "Emeritus of Ideation",   # slot 1 in our test screenshot
    "Sleight of Hand",        # slot 2 (in DB but hash distance 34 from Arena render)
]


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "MTGDraftHelper/0.1 (personal use)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def named_search(name: str):
    """Use Scryfall's named/exact endpoint to find one specific card."""
    enc = urllib.parse.quote(name)
    try:
        return fetch_json(f"https://api.scryfall.com/cards/named?exact={enc}")
    except urllib.error.HTTPError:
        return None


def all_prints(name: str):
    """Find all printings of a card by name."""
    enc = urllib.parse.quote(f'!"{name}"')
    try:
        url = (f"https://api.scryfall.com/cards/search?"
               f"q={enc}&unique=prints&order=released")
        all_data = []
        next_url = url
        while next_url:
            d = fetch_json(next_url)
            all_data.extend(d.get("data", []))
            next_url = d.get("next_page") if d.get("has_more") else None
        return all_data
    except urllib.error.HTTPError:
        return []


def main():
    for name in CARDS_TO_LOOK_UP:
        print("=" * 70)
        print(f"Looking up: {name}")
        print("=" * 70)

        prints = all_prints(name)
        if not prints:
            print(f"  No results found at all.")
            continue

        print(f"  Found {len(prints)} printings across various sets:")
        # Group by set
        sets_seen = {}
        for p in prints:
            sc = p.get("set", "?")
            sn = p.get("set_name", "?")
            sets_seen.setdefault((sc, sn), []).append(p.get("collector_number"))
        for (sc, sn), cns in sorted(sets_seen.items()):
            print(f"    set='{sc}' ({sn}) -- "
                  f"{len(cns)} printing(s), e.g. cn={cns[0]}")

        # Highlight any that match our 2026 sos family
        print()
        for p in prints:
            sc = p.get("set", "")
            if sc.startswith("sos") or sc.startswith("soa") or sc.startswith("psos") or sc == "spg" or sc.startswith("special"):
                print(f"  *** {sc} {p.get('collector_number')} - "
                      f"{p.get('frame_effects', [])} - "
                      f"released {p.get('released_at')}")
        print()


if __name__ == "__main__":
    main()
