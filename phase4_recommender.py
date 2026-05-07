"""
Phase 4 — Pick recommendation engine (v2, polished).

Scoring layers, in order of application:
  1. BASE: GIH WR from 17Lands, shrunken toward set average using a
     Bayesian estimator so cards with low sample size don't dominate.
  2. COLOR PENALTY: off-color cards lose value, scaling with draft depth.
     Splashable bombs get a reduced penalty.
  3. CURVE BONUS: small uplift for cards filling underrepresented mana
     slots in your current pool.
  4. BASIC-LAND PENALTY: flat -45 (Arena gives basics free).
  5. MANUAL OVERRIDE: user-defined +/- adjustment from card_db/overrides.json.

Tunable parameters are exposed as constants near the top.
"""

import json
import re
from pathlib import Path

from phase7_synergy import (
    load_archetype_config,
    synergy_score,
)


# ---------- Tunable constants ----------

# 17Lands data is averaged across the entire set; this is roughly the
# mean GIH WR across all cards in a typical limited set.
SET_AVERAGE_WR = 0.535

# Effective prior sample size for Bayesian shrinkage. Higher = more
# aggressive shrinkage of low-sample cards toward the average.
SHRINKAGE_K = 250

# Color-penalty schedule keyed by # of cards already picked.
# Penalty is applied to cards whose mana cost requires an off-color pip.
COLOR_PENALTY_BY_PICKS = [
    (4, -2),
    (7, -6),
    (10, -12),
    (45, -22),
]

# A card with GIH WR ≥ this is considered a "bomb" — splashing might
# be justified, so off-color penalty is reduced.
BOMB_WR_THRESHOLD = 0.62

# Reduction multiplier for the off-color penalty when a card is both a
# bomb AND splashable (≤1.5 off-color pips).
BOMB_SPLASH_REDUCTION = 0.4

# Reduction multiplier for the off-color penalty when a card has only
# one strict off-color pip and decent WR (light splash candidate).
LIGHT_SPLASH_REDUCTION = 0.7

# Basic-land flat penalty (these should never be drafted in Arena).
BASIC_LAND_PENALTY = -45.0

# Curve bonus for filling an underrepresented CMC bucket.
CURVE_BONUS = 1.5

# Composition targets per archetype. Cards that fill an underrepresented
# slot get a small bonus.
ARCHETYPE_COMP_TARGETS = {
    "aggressive": {"creatures": 17, "spells": 7},   # 24 nonlands + 16 lands
    "midrange":   {"creatures": 15, "spells": 8},   # 23 + 17
    "control":    {"creatures": 10, "spells": 12},  # 22 + 18
}
COMP_BONUS_LARGE = 1.5    # deficit >= 1.5 cards behind ideal
COMP_BONUS_SMALL = 0.75   # deficit >= 0.5 cards behind ideal

# "Wheel risk" adjustment: cards with low ALSA (Average Last Seen At) get
# sniped if passed, so we boost them to encourage taking now. Cards with
# high ALSA tend to come back to you, so a small deprioritization saves
# the pick for stronger contested cards.
# These thresholds work across pack/pick numbers; tweak if needed.
WHEEL_BONUS_VERY_CONTESTED = 2.0   # ALSA <= 2.0
WHEEL_BONUS_CONTESTED = 1.5        # ALSA <= 3.5
WHEEL_BONUS_MEDIUM = 0.75          # ALSA <= 5.0
WHEEL_PENALTY_LIKELY_WHEEL = -0.75 # ALSA >= 9.0
WHEEL_PENALTY_USUALLY_WHEELS = -1.5  # ALSA >= 11.0


COLORS = "WUBRG"


# ---------- Loaders ----------

def load_tier_index() -> dict:
    """Load 17Lands win-rate data keyed by card name."""
    with (Path("card_db") / "tier_index.json").open("r", encoding="utf-8") as f:
        return json.load(f)


def load_overrides() -> dict:
    """Load manual score overrides. Returns {} if the file doesn't exist.

    Schema:
      { "Card Name": { "score_adjust": +/-N, "note": "..." }, ... }
    """
    path = Path("card_db") / "overrides.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"WARNING: {path} could not be parsed as JSON; ignoring.")
        return {}


# ---------- Color analysis ----------

def parse_color_symbols(mana_cost: str) -> dict:
    """Return color -> symbol count for a mana cost string.
    Hybrid {W/B} counts half toward each side."""
    counts = {c: 0.0 for c in COLORS}
    if not mana_cost:
        return counts
    for sym in re.findall(r"\{([^}]+)\}", mana_cost):
        s = sym.upper()
        if s in COLORS:
            counts[s] += 1
        elif "/" in s:
            parts = [p for p in s.split("/") if p]
            colored = [p for p in parts if p in COLORS]
            if not colored:
                continue
            share = 1.0 / len(colored)
            for p in colored:
                counts[p] += share
    return counts


def card_colors(mana_cost: str) -> set:
    return {c for c, n in parse_color_symbols(mana_cost).items() if n > 0}


def archetype_colors(picked_cards: list, top_n: int = 2) -> set:
    cum = {c: 0.0 for c in COLORS}
    for card in picked_cards:
        for c, n in parse_color_symbols(card.get("mana_cost", "")).items():
            cum[c] += n
    if not any(cum.values()):
        return set()
    sorted_colors = sorted(cum.items(), key=lambda x: -x[1])
    return {c for c, n in sorted_colors[:top_n] if n > 0}


# ---------- Sample-size shrinkage ----------

def shrunken_wr(gih_wr, sample_size,
                set_avg: float = SET_AVERAGE_WR,
                k: float = SHRINKAGE_K) -> float | None:
    """Bayesian-style shrinkage toward set average.

    For a card with n drawn games, the posterior WR is
        (n * observed + k * prior) / (n + k)

    This makes low-sample cards' scores conservative.
    """
    if gih_wr is None:
        return None
    n = sample_size or 0
    if n <= 0:
        return set_avg
    return (n * gih_wr + k * set_avg) / (n + k)


# ---------- Scoring layers ----------

def base_grade(adjusted_wr) -> float:
    """Convert (shrunken) GIH WR to a 0..100 grade.
    40% -> 0, 55% -> 50, 70% -> 100, clamped."""
    if adjusted_wr is None:
        return 50.0
    return max(0.0, min(100.0, (adjusted_wr - 0.40) / 0.30 * 100))


def tier_letter(gih_wr) -> str:
    """Tier letter is based on the RAW (unshrunken) GIH WR — it's a
    descriptor of the card's intrinsic ceiling, not its risk-adjusted score."""
    if gih_wr is None:
        return "?"
    bands = [
        (0.65, "S+"), (0.60, "S"),
        (0.575, "A+"), (0.555, "A"),
        (0.535, "B+"), (0.515, "B"),
        (0.495, "C+"), (0.475, "C"),
        (0.455, "D"),
    ]
    for thr, letter in bands:
        if gih_wr >= thr:
            return letter
    return "F"


def is_basic_land(card: dict) -> bool:
    return "basic land" in (card.get("type_line") or "").lower()


def color_penalty(card_mana: str, my_colors: set, picks_made: int,
                   gih_wr) -> float:
    """Penalty for cards outside my deck's colors. Splashable bombs get
    a reduced penalty (you might splash them anyway)."""
    if not my_colors:
        return 0
    card_cols = card_colors(card_mana)
    if not card_cols or card_cols.issubset(my_colors):
        return 0

    # Pick the schedule entry whose threshold the picks-made just crossed.
    base_pen = -22
    for limit, pen in COLOR_PENALTY_BY_PICKS:
        if picks_made <= limit:
            base_pen = pen
            break

    # How many off-color pips? Single off-color pips are splashable;
    # multiple off-color pips are not.
    pips = parse_color_symbols(card_mana)
    off_pips = sum(n for c, n in pips.items() if c not in my_colors)

    is_bomb = gih_wr is not None and gih_wr >= BOMB_WR_THRESHOLD
    if is_bomb and off_pips <= 1.5:
        return base_pen * BOMB_SPLASH_REDUCTION
    # Light splash: single pip + decent card
    if off_pips <= 1.0 and gih_wr is not None and gih_wr >= 0.55:
        return base_pen * LIGHT_SPLASH_REDUCTION
    return base_pen


def detect_archetype(picked_cards: list) -> str:
    """Classify a pool as aggressive / midrange / control based on its
    CMC distribution and creature density.

    Thresholds scale with pool size — early picks where almost no signal
    exists default to midrange; clear signals at 10+ nonlands flip the
    classification.
    """
    nonlands = [c for c in picked_cards
                if "Land" not in (c.get("type_line") or "")]
    if not nonlands:
        return "midrange"

    cmcs = []
    creatures_at_low = 0
    spells_at_high = 0
    for c in nonlands:
        try:
            cmc = float(c.get("cmc") or 0)
        except (TypeError, ValueError):
            cmc = 0
        cmcs.append(cmc)
        is_cre = "Creature" in (c.get("type_line") or "")
        if is_cre and cmc <= 2:
            creatures_at_low += 1
        if not is_cre and cmc >= 4:
            spells_at_high += 1
    avg = sum(cmcs) / len(cmcs)

    # Scale threshold counts with pool size — 23 nonlands is a "full" deck
    scale = max(0.3, len(nonlands) / 23)
    if avg < 2.7 and creatures_at_low >= 7 * scale:
        return "aggressive"
    if avg > 3.6 and spells_at_high >= 4 * scale:
        return "control"
    return "midrange"


def composition_bonus(card: dict, picked_cards: list) -> tuple[float, str]:
    """Boost cards that move the pool toward a balanced creature/spell
    mix for the detected archetype. Returns (bonus, archetype_label) so
    callers can surface which archetype the targets came from.
    """
    if not picked_cards:
        return 0, "midrange"
    type_line = card.get("type_line") or ""
    if "Land" in type_line:
        return 0, "midrange"
    nonlands = [c for c in picked_cards
                if "Land" not in (c.get("type_line") or "")]
    if not nonlands:
        return 0, "midrange"

    archetype = detect_archetype(nonlands)
    targets = ARCHETYPE_COMP_TARGETS[archetype]
    target_cre = targets["creatures"]
    target_spell = targets["spells"]

    cre_count = sum(1 for c in nonlands
                    if "Creature" in (c.get("type_line") or ""))
    spell_count = len(nonlands) - cre_count

    target_total = target_cre + target_spell
    progress = min(1.0, len(nonlands) / target_total)
    ideal_cre = target_cre * progress
    ideal_spell = target_spell * progress

    is_card_creature = "Creature" in type_line
    deficit = (ideal_cre - cre_count) if is_card_creature else (ideal_spell - spell_count)

    if deficit >= 1.5:
        return COMP_BONUS_LARGE, archetype
    if deficit >= 0.5:
        return COMP_BONUS_SMALL, archetype
    return 0, archetype


def wheel_adjustment(alsa) -> float:
    """Adjust score by how likely the card is to wheel back to you.

    ALSA = Average Last Seen At. Low values mean the card is taken
    early (won't wheel) — boost it so we don't miss the snipe. High
    values mean the card often comes back — small penalty so we
    prioritize cards that won't.
    """
    if alsa is None:
        return 0
    if alsa <= 2.0:
        return WHEEL_BONUS_VERY_CONTESTED
    if alsa <= 3.5:
        return WHEEL_BONUS_CONTESTED
    if alsa <= 5.0:
        return WHEEL_BONUS_MEDIUM
    if alsa >= 11.0:
        return WHEEL_PENALTY_USUALLY_WHEELS
    if alsa >= 9.0:
        return WHEEL_PENALTY_LIKELY_WHEEL
    return 0


def curve_bonus(card_cmc, picked_cards: list) -> float:
    if card_cmc is None:
        return 0
    buckets = {b: 0 for b in range(7)}
    for c in picked_cards:
        if "Land" in (c.get("type_line") or ""):
            continue
        try:
            cmc = float(c.get("cmc") or 0)
        except (TypeError, ValueError):
            cmc = 0
        b = min(6, int(cmc))
        buckets[b] += 1
    ideal_full = {0: 0, 1: 3, 2: 6, 3: 6, 4: 4, 5: 2, 6: 1}
    total_picked = sum(buckets.values())
    progress = min(1.0, total_picked / 23)
    try:
        cv = float(card_cmc)
    except (TypeError, ValueError):
        cv = 0
    b = min(6, int(cv))
    if buckets[b] < ideal_full[b] * progress + 0.5:
        return CURVE_BONUS
    return 0.0


# ---------- Public API ----------

def score_card(card: dict, picked_cards: list, tier_data: dict,
               fmt: str = "QuickDraft", overrides: dict | None = None) -> dict:
    """Score a single card. Returns a dict with score + breakdown."""
    name = card.get("name") or ""

    # Look up tier data, with format and DFC fallbacks.
    def _lookup(name_key, fmt_key):
        return (tier_data.get(name_key) or {}).get(fmt_key) or {}

    fallback_fmt = "PremierDraft" if fmt == "QuickDraft" else "QuickDraft"
    front = name.split(" // ")[0] if " // " in name else None

    fmt_data = _lookup(name, fmt)
    if not fmt_data.get("gih_wr") and front:
        fmt_data = _lookup(front, fmt)
    if not fmt_data.get("gih_wr"):
        fmt_data = _lookup(name, fallback_fmt) or fmt_data
    if not fmt_data.get("gih_wr") and front:
        fmt_data = _lookup(front, fallback_fmt) or fmt_data

    gih = fmt_data.get("gih_wr")
    sample = fmt_data.get("drawn_count")
    alsa = fmt_data.get("alsa")
    ata = fmt_data.get("ata")

    adj_wr = shrunken_wr(gih, sample)
    base = base_grade(adj_wr)

    my_colors = archetype_colors(picked_cards)
    cpen = color_penalty(card.get("mana_cost", ""), my_colors,
                          len(picked_cards), gih)
    cbonus = curve_bonus(card.get("cmc"), picked_cards)
    wheel_adj = wheel_adjustment(alsa)
    comp_bonus, comp_archetype = composition_bonus(card, picked_cards)
    basic_pen = BASIC_LAND_PENALTY if is_basic_land(card) else 0.0
    override_adj = ((overrides or {}).get(name, {}) or {}).get("score_adjust", 0)
    override_note = ((overrides or {}).get(name, {}) or {}).get("note", "")

    # Synergy: tribal + keyword + archetype theme match against the pool.
    # archetype_config is loaded fresh each call for hot-reload.
    syn_bonus, syn_reasons = synergy_score(
        card, picked_cards, my_colors, load_archetype_config()
    )

    final = (base + cpen + cbonus + wheel_adj + comp_bonus + syn_bonus
             + basic_pen + override_adj)
    return {
        "name": name,
        "score": round(final, 1),
        "base": round(base, 1),
        "color_penalty": cpen,
        "curve_bonus": cbonus,
        "wheel_adjust": wheel_adj,
        "composition_bonus": comp_bonus,
        "composition_archetype": comp_archetype,
        "synergy_bonus": syn_bonus,
        "synergy_reasons": syn_reasons,
        "basic_penalty": basic_pen,
        "override_adjust": override_adj,
        "override_note": override_note,
        "gih_wr": gih,
        "adjusted_wr": adj_wr,
        "sample_size": sample,
        "alsa": alsa,
        "ata": ata,
        "tier": tier_letter(gih),
        "card": card,
    }


def rank_pack(pack: list, picked: list, tier_data: dict,
              fmt: str = "QuickDraft", overrides: dict | None = None) -> list:
    """Return all pack cards sorted by score (best first)."""
    scored = [score_card(c, picked, tier_data, fmt, overrides) for c in pack]
    scored.sort(key=lambda x: -x["score"])
    return scored


def archetype_summary(picked_cards: list) -> str:
    cum = {c: 0.0 for c in COLORS}
    for card in picked_cards:
        for c, n in parse_color_symbols(card.get("mana_cost", "")).items():
            cum[c] += n
    if not any(cum.values()):
        return "(no colors yet)"
    sorted_colors = sorted(cum.items(), key=lambda x: -x[1])
    primary = [(c, n) for c, n in sorted_colors if n > 0]
    parts = [f"{c}({n:.1f})" for c, n in primary[:3]]
    return " ".join(parts)
