"""
Phase 6 — Deck builder.

Takes a finished draft pool (~45 cards) and produces a recommended
40-card deck plus a categorized cut list. Logic:

  1. Identify primary 2 colors from cumulative mana symbols.
  2. Detect archetype (aggressive / midrange / control) from CMC and
     creature distribution.
  3. Find splash candidates: off-color bombs with single off-color pip.
  4. Score every card using the same engine as live picks (sample-shrunken
     win-rate base; overrides applied; no color penalty since this is
     deck-build context).
  5. Bucket by CMC and greedily fill the curve target for the detected
     archetype.
  6. Compute mana base proportionally to colored pips in the chosen deck.
  7. Categorize everything not in the deck with a reason.
"""

from phase4_recommender import (
    archetype_colors,
    card_colors,
    parse_color_symbols,
    score_card,
)

COLORS = "WUBRG"

# Curve targets keyed by archetype, split into creatures vs noncreatures.
# A typical limited deck wants enough creatures to apply pressure / block,
# and a smaller suite of noncreature spells (removal, tricks, card draw).
# Inner dicts are CMC -> count.
CURVE_TARGETS = {
    "aggressive": {
        # 17 creatures + 7 spells = 24 nonlands
        "creatures":    {1: 4, 2: 6, 3: 4, 4: 2, 5: 1, 6: 0},
        "noncreatures": {1: 0, 2: 2, 3: 2, 4: 2, 5: 1, 6: 0},
    },
    "midrange": {
        # 15 creatures + 8 spells = 23 nonlands
        "creatures":    {1: 1, 2: 4, 3: 4, 4: 3, 5: 2, 6: 1},
        "noncreatures": {1: 1, 2: 1, 3: 2, 4: 2, 5: 1, 6: 1},
    },
    "control": {
        # 10 creatures + 12 spells = 22 nonlands
        "creatures":    {1: 0, 2: 2, 3: 2, 4: 2, 5: 2, 6: 2},
        "noncreatures": {1: 0, 2: 2, 3: 3, 4: 3, 5: 2, 6: 2},
    },
}
LANDS_BY_ARCHETYPE = {
    "aggressive": 16,
    "midrange":   17,
    "control":    18,
}

# A card is a "bomb" worth splashing if its WR clears this threshold AND
# it has a single off-color pip (so it's actually castable).
SPLASH_WR_THRESHOLD = 0.60
MAX_SPLASH_CARDS = 2

# How much to "flatten" the mana base toward an even split between primary
# colors. 0 = strictly proportional to pip count (extreme splits possible).
# 1 = always 50/50 regardless of pip count.
# Reference behavior at different flatten values for a 64/36 pip-count deck
# (17 lands, 2 colors):
#   0.0  -> 11 / 6   (raw proportional — most lopsided)
#   0.25 -> 10 / 7
#   0.5  -> 10 / 7   (mild change; rounding hides the shift)
#   0.7  -> 9 / 8    (meaningfully balanced)
#   1.0  -> 9 / 8    (always balanced regardless of pip count)
MANA_BASE_FLATTEN = 0.7

# Splash colors get a flat number of lands rather than proportional
# (you don't want 1 splash land for a splashed bomb you must cast).
SPLASH_LANDS_PER_COLOR = 2


def cmc_of(card: dict) -> int:
    try:
        return min(6, int(float(card.get("cmc") or 0)))
    except (TypeError, ValueError):
        return 0


def is_land(card: dict) -> bool:
    return "Land" in (card.get("type_line") or "")


def is_creature(card: dict) -> bool:
    return "Creature" in (card.get("type_line") or "")


def detect_archetype(nonland_cards: list[dict]) -> str:
    """Classify a deck shape by its CMC distribution."""
    cmcs = []
    creatures_at_low = 0
    spells_at_high = 0
    for c in nonland_cards:
        cmc = float(c.get("cmc") or 0)
        cmcs.append(cmc)
        if is_creature(c) and cmc <= 2:
            creatures_at_low += 1
        if not is_creature(c) and cmc >= 4:
            spells_at_high += 1
    if not cmcs:
        return "midrange"
    avg = sum(cmcs) / len(cmcs)
    if avg < 2.7 and creatures_at_low >= 7:
        return "aggressive"
    if avg > 3.6 and spells_at_high >= 4:
        return "control"
    return "midrange"


def find_splash_candidates(pool, primary_colors, tier_data, overrides, fmt):
    """Off-color cards strong enough to splash. Sorted best-first, capped."""
    out = []
    for card in pool:
        if is_land(card):
            continue
        cs = card_colors(card.get("mana_cost", ""))
        if not cs or cs.issubset(primary_colors):
            continue
        off = cs - primary_colors
        if len(off) != 1:
            continue
        # Count pips: for splash we want exactly 1 strict off-color pip max
        pips = parse_color_symbols(card.get("mana_cost", ""))
        off_pip_count = sum(n for c, n in pips.items() if c not in primary_colors)
        if off_pip_count > 1.5:
            continue
        s = score_card(card, [], tier_data, fmt=fmt, overrides=overrides)
        wr = s.get("gih_wr")
        if wr is None or wr < SPLASH_WR_THRESHOLD:
            continue
        out.append({"card": card, "scored": s,
                    "splash_color": next(iter(off))})
    out.sort(key=lambda x: -(x["scored"]["gih_wr"] or 0))
    return out[:MAX_SPLASH_CARDS]


def build_deck(pool: list[dict], tier_data: dict,
               overrides: dict | None = None,
               fmt: str = "QuickDraft") -> dict:
    """Produce a recommended 40-card deck from a draft pool.

    Returns a dict with:
      archetype, primary_colors, splash_colors,
      deck_nonlands (list of cards), deck_scored (list of score dicts),
      lands (dict of color -> count), lands_total (int),
      cuts (list of {card, reason, score}), deck_total (int).
    """
    primary = archetype_colors(pool, top_n=2)

    splash_candidates = find_splash_candidates(
        pool, primary, tier_data, overrides, fmt
    )
    splash_colors = {sc["splash_color"] for sc in splash_candidates}
    deck_colors = primary | splash_colors

    # Score every card. We pass an empty `picked_cards` so the color
    # penalty doesn't apply (we want the card's intrinsic deck value).
    scored_all = []
    for card in pool:
        s = score_card(card, [], tier_data, fmt=fmt, overrides=overrides)
        scored_all.append(s)

    # Split into playable / cuts based on color fit
    playable: list[dict] = []
    cuts: list[dict] = []
    for s in scored_all:
        card = s["card"]
        if is_land(card):
            cuts.append({"card": card, "scored": s, "score": s["base"],
                         "reason": "Land — handled in mana base"})
            continue
        cs = card_colors(card.get("mana_cost", ""))
        if cs and not cs.issubset(deck_colors):
            cuts.append({"card": card, "scored": s, "score": s["base"],
                         "reason": "Off-color (no splash room)"})
            continue
        playable.append(s)

    archetype = detect_archetype([s["card"] for s in playable])
    curve_target = CURVE_TARGETS[archetype]
    lands_total = LANDS_BY_ARCHETYPE[archetype]
    creature_target = curve_target["creatures"]
    noncreature_target = curve_target["noncreatures"]
    nonland_target = (sum(creature_target.values())
                      + sum(noncreature_target.values()))

    # Two-axis bucketing: (is_creature, cmc).
    cre_buckets: dict[int, list[dict]] = {b: [] for b in range(7)}
    nc_buckets:  dict[int, list[dict]] = {b: [] for b in range(7)}
    for s in playable:
        b = cmc_of(s["card"])
        if is_creature(s["card"]):
            cre_buckets[b].append(s)
        else:
            nc_buckets[b].append(s)
    for b in range(7):
        cre_buckets[b].sort(key=lambda s: -s["base"])
        nc_buckets[b].sort(key=lambda s: -s["base"])

    deck: list[dict] = []
    seen = set()

    # First pass: fill creature targets.
    for cmc in sorted(creature_target):
        want = creature_target[cmc]
        for s in cre_buckets[cmc][:want]:
            deck.append(s)
            seen.add(id(s))

    # Second pass: fill noncreature targets.
    for cmc in sorted(noncreature_target):
        want = noncreature_target[cmc]
        for s in nc_buckets[cmc][:want]:
            deck.append(s)
            seen.add(id(s))

    # Pad if total still short: fill from highest-scored remaining of any type
    leftover = [s for s in playable if id(s) not in seen]
    leftover.sort(key=lambda s: -s["base"])
    while len(deck) < nonland_target and leftover:
        s = leftover.pop(0)
        deck.append(s)
        seen.add(id(s))

    # Trim if over target: cut weakest, with reason
    if len(deck) > nonland_target:
        deck.sort(key=lambda s: -s["base"])
        spilled = deck[nonland_target:]
        deck = deck[:nonland_target]
        for s in spilled:
            kind = "creature" if is_creature(s["card"]) else "spell"
            cuts.append({
                "card": s["card"], "scored": s, "score": s["base"],
                "reason": f"{kind.capitalize()} slot filled at CMC {cmc_of(s['card'])}",
            })

    # Anything in playable that didn't make the deck → cuts
    deck_ids = {id(s) for s in deck}
    for s in playable:
        if id(s) in deck_ids:
            continue
        if any(c.get("scored") is s for c in cuts):
            continue
        cmc = cmc_of(s["card"])
        cuts.append({"card": s["card"], "scored": s, "score": s["base"],
                     "reason": f"Lower-scored alternative at CMC {cmc}"})

    # Mana base: distribute basics across primary + splash colors.
    # Primary colors get a "flattened" proportional split (so a 64/36 pip
    # ratio doesn't produce a 11/6 land split — see MANA_BASE_FLATTEN).
    # Splash colors get a flat small number, enough to cast their card.
    pip_count = {c: 0.0 for c in COLORS}
    for s in deck:
        for c, n in parse_color_symbols(
                s["card"].get("mana_cost", "")).items():
            pip_count[c] += n

    # Reserve splash lands first
    splash_total = SPLASH_LANDS_PER_COLOR * len(splash_colors)
    primary_lands_budget = max(0, lands_total - splash_total)
    primary_with_pips = [c for c in primary if pip_count[c] > 0]
    if not primary_with_pips:
        # Edge case: no primary-color cards, just use whatever has pips
        primary_with_pips = [c for c in COLORS if pip_count[c] > 0]

    primary_pip_total = sum(pip_count[c] for c in primary_with_pips) or 1
    even_share = (primary_lands_budget / len(primary_with_pips)
                  if primary_with_pips else 0)

    lands: dict[str, int] = {}
    for c in primary_with_pips:
        prop_share = primary_lands_budget * pip_count[c] / primary_pip_total
        flat = prop_share * (1 - MANA_BASE_FLATTEN) + even_share * MANA_BASE_FLATTEN
        lands[c] = max(1, round(flat))
    for c in splash_colors:
        lands[c] = SPLASH_LANDS_PER_COLOR

    # Trim to hit lands_total exactly
    while sum(lands.values()) > lands_total:
        # Take from the primary color we have most of
        primaries_in_lands = {c: lands[c] for c in lands if c in primary}
        if primaries_in_lands:
            target = max(primaries_in_lands, key=lambda c: primaries_in_lands[c])
        else:
            target = max(lands, key=lambda c: lands[c])
        lands[target] -= 1
        if lands[target] <= 0:
            del lands[target]
    while sum(lands.values()) < lands_total:
        # Add to color with most pips (skewed toward primaries)
        if primary_with_pips:
            target = max(primary_with_pips, key=lambda c: pip_count[c])
        else:
            target = max(pip_count, key=lambda c: pip_count[c])
        lands[target] = lands.get(target, 0) + 1

    creature_count = sum(1 for s in deck if is_creature(s["card"]))
    noncreature_count = len(deck) - creature_count
    return {
        "archetype": archetype,
        "primary_colors": primary,
        "splash_colors": splash_colors,
        "splash_cards": [sc["card"] for sc in splash_candidates],
        "deck_nonlands": [s["card"] for s in deck],
        "deck_scored": deck,
        "lands": lands,
        "lands_total": lands_total,
        "cuts": cuts,
        "deck_total": len(deck) + lands_total,
        "creature_count": creature_count,
        "noncreature_count": noncreature_count,
        "creature_target": sum(creature_target.values()),
        "noncreature_target": sum(noncreature_target.values()),
    }


def render_text(build: dict) -> str:
    """Pretty-print a deck build for terminal output. Returns the string."""
    out = []
    cols = "".join(sorted(build["primary_colors"]))
    splash = (f" (splashing {''.join(sorted(build['splash_colors']))})"
              if build["splash_colors"] else "")
    out.append("=" * 70)
    out.append(
        f"  Archetype: {build['archetype']}    Colors: {cols}{splash}"
    )
    out.append(
        f"  Deck size: {build['deck_total']} "
        f"({len(build['deck_nonlands'])} nonlands + "
        f"{build['lands_total']} lands)"
    )
    out.append("=" * 70)

    # Group nonlands by CMC
    by_cmc: dict[int, list[dict]] = {}
    for s in build["deck_scored"]:
        c = cmc_of(s["card"])
        by_cmc.setdefault(c, []).append(s)
    for cmc in sorted(by_cmc):
        label = f"CMC {cmc}+" if cmc == 6 else f"CMC {cmc}"
        out.append(f"\n  {label}  ({len(by_cmc[cmc])}):")
        for s in sorted(by_cmc[cmc], key=lambda x: -x["base"]):
            cost = s["card"].get("mana_cost") or ""
            out.append(f"    {s['base']:>5.1f}  "
                       f"{s['name']:<32} {cost}")

    out.append(f"\n  LANDS  ({build['lands_total']}):")
    basic_names = {"W": "Plains", "U": "Island", "B": "Swamp",
                   "R": "Mountain", "G": "Forest"}
    for c, n in sorted(build["lands"].items(), key=lambda x: -x[1]):
        out.append(f"    {n}x {basic_names[c]}")

    if build["cuts"]:
        out.append(f"\n  CUTS  ({len(build['cuts'])}):")
        for c in sorted(build["cuts"], key=lambda x: x["score"]):
            name = c["card"].get("name", "?")
            out.append(f"    {c['score']:>5.1f}  {name:<32} — {c['reason']}")

    return "\n".join(out)
