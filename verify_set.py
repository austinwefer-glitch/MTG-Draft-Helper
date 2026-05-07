"""
Phase 2 — Step 1: Verify the Scryfall set code before we download anything.

This script asks Scryfall, "what set has the code SOS?" and prints the result.
It also searches by name "Secrets of Strixhaven" as a fallback in case the
code is different.

Uses only Python's built-in urllib — no pip installs yet.
"""

import json
import urllib.request
import urllib.parse


def fetch_json(url: str) -> dict:
    """Fetch a URL and return parsed JSON. Scryfall asks for a User-Agent."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "MTGDraftHelper/0.1 (personal use)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def lookup_set_by_code(code: str) -> None:
    print(f"--- Looking up set code: '{code}' ---")
    try:
        data = fetch_json(f"https://api.scryfall.com/sets/{code}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"  No set found with code '{code}' on Scryfall.")
        else:
            print(f"  HTTP error: {e.code} {e.reason}")
        return
    except Exception as e:
        print(f"  Error: {e}")
        return

    print(f"  Name:         {data.get('name')}")
    print(f"  Code:         {data.get('code')}")
    print(f"  Set type:     {data.get('set_type')}")
    print(f"  Released on:  {data.get('released_at')}")
    print(f"  Card count:   {data.get('card_count')}")
    print(f"  Digital only: {data.get('digital')}")


def search_sets_by_name(needle: str) -> None:
    print(f"\n--- Searching all sets for name containing: '{needle}' ---")
    try:
        data = fetch_json("https://api.scryfall.com/sets")
    except Exception as e:
        print(f"  Error: {e}")
        return

    needle_lower = needle.lower()
    matches = [
        s for s in data.get("data", [])
        if needle_lower in s.get("name", "").lower()
    ]
    if not matches:
        print(f"  No set names contain '{needle}'.")
        return
    for s in matches:
        print(f"  - {s['name']} (code: {s['code']}, "
              f"released: {s.get('released_at')}, "
              f"cards: {s.get('card_count')}, type: {s.get('set_type')})")


if __name__ == "__main__":
    lookup_set_by_code("sos")
    search_sets_by_name("Strixhaven")
    print("\nDone.")
