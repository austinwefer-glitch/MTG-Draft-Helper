"""
Phase 7 — Synergy scoring.

Three layers, all surfaced as a single bonus number plus a list of
human-readable reasons:

  L1 TRIBAL  -- Card shares creature subtypes with 3+ pool cards.
  L2 KEYWORD -- Card shares ability keywords (Adventure, Magecraft, etc.)
                with 3+ pool cards.
  L3 ARCHETYPE -- Card matches a theme defined in archetype_config.json
                  for the player's current color pair.

Each match adds a small bonus, capped at SYNERGY_MAX_BONUS so synergy
never single-handedly flips a pick decision but consistently breaks ties
toward cohesive cards.
"""

import json
from pathlib import Path


# ---- Tunable constants ----

SYNERGY_TRIBAL_THRESHOLD = 3   # need this many of a creature subtype in pool
SYNERGY_TRIBAL_BONUS = 1.5     # bonus per matching subtype
SYNERGY_KEYWORD_THRESHOLD = 3  # need this many of a keyword in pool
SYNERGY_KEYWORD_BONUS = 1.0    # bonus per matching keyword
SYNERGY_ARCHETYPE_BONUS = 2.0  # bonus per archetype-theme match
SYNERGY_MAX_BONUS = 6.0        # cap so synergy can't overpower base


# ---- Loaders ----

def load_archetype_config() -> dict:
    """Load color-pair archetype config. Returns {} if missing."""
    path = Path(__file__).parent / "archetype_config.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except json.JSONDecodeError:
        print(f"WARNING: {path} could not be parsed as JSON; ignoring.")
        return {}


# ---- Helpers ----

def extract_subtypes(type_line: str) -> list[str]:
    """Pull creature/artifact/etc. subtypes out of a type line.

    'Creature — Human Wizard' -> ['Human', 'Wizard']
    'Sorcery' -> []
    """
    if not type_line or "—" not in type_line:
        return []
    _, subtypes_part = type_line.split("—", 1)
    return [t for t in subtypes_part.strip().split() if t]


def collect_pool_signals(picked_cards: list) -> tuple[dict, dict]:
    """Aggregate pool-wide counts of creature subtypes and ability keywords.

    Returns (subtype_counts, keyword_counts).
    """
    subtype_counts: dict[str, int] = {}
    keyword_counts: dict[str, int] = {}
    for c in picked_cards:
        for st in extract_subtypes(c.get("type_line") or ""):
            subtype_counts[st] = subtype_counts.get(st, 0) + 1
        for kw in (c.get("keywords") or []):
            keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
    return subtype_counts, keyword_counts


def archetype_for_colors(my_colors: set, archetype_config: dict) -> dict | None:
    """Look up the archetype entry for a player's color pair.

    Color-pair keys in the config are sorted alphabetically (BG, GU, RW, etc.).
    For 3+ color pools we use the top 2 colors (as detected by archetype_colors).
    """
    if not my_colors or not archetype_config:
        return None
    if len(my_colors) < 2:
        return None
    key = "".join(sorted(c for c in my_colors)[:2])
    return archetype_config.get(key)


# ---- Scoring ----

def synergy_score(card: dict, picked_cards: list, my_colors: set,
                  archetype_config: dict | None = None) -> tuple[float, list[str]]:
    """Compute synergy bonus + list of human-readable reasons."""
    if archetype_config is None:
        archetype_config = {}

    subtype_counts, keyword_counts = collect_pool_signals(picked_cards)
    bonus = 0.0
    reasons = []

    # ---- L1: Tribal ----
    card_subtypes = set(extract_subtypes(card.get("type_line") or ""))
    for st in card_subtypes:
        n = subtype_counts.get(st, 0)
        if n >= SYNERGY_TRIBAL_THRESHOLD:
            bonus += SYNERGY_TRIBAL_BONUS
            reasons.append(f"{n} {st}s in pool")

    # ---- L2: Keyword ----
    card_keywords = card.get("keywords") or []
    for kw in card_keywords:
        n = keyword_counts.get(kw, 0)
        if n >= SYNERGY_KEYWORD_THRESHOLD:
            bonus += SYNERGY_KEYWORD_BONUS
            reasons.append(f"{n} {kw} cards in pool")

    # ---- L3: Archetype ----
    arch = archetype_for_colors(my_colors, archetype_config)
    if arch:
        oracle = (card.get("oracle_text") or "").lower()
        kw_lower = [k.lower() for k in card_keywords]
        arch_name = arch.get("name", "archetype")
        # First check: does the card share a creature type with the archetype?
        for ct in arch.get("creature_types", []):
            if ct in card_subtypes:
                bonus += SYNERGY_ARCHETYPE_BONUS
                reasons.append(f"{arch_name} type: {ct}")
                break
        # Then check: do any of the archetype's themes appear in the card's
        # oracle text or keyword list?
        for theme in arch.get("themes", []):
            tl = theme.lower()
            if tl in oracle or tl in kw_lower:
                bonus += SYNERGY_ARCHETYPE_BONUS
                reasons.append(f"{arch_name} theme: {theme}")
                break  # one archetype-theme bonus per card max

    bonus = min(bonus, SYNERGY_MAX_BONUS)
    return round(bonus, 2), reasons
