# MTG Arena Draft Helper

A small Windows tool that watches MTG Arena's draft logs in real time and shows pick recommendations in an always-on-top window. It uses [17Lands](https://www.17lands.com) community win-rate data, with adjustments for your draft's color commitment and curve.

It's free to run — no API keys, no subscriptions, no cost per pick.

![screenshot placeholder — replace with your own once running]()

---

## What it does

- Reads which cards are in each pack you see, by parsing MTG Arena's local log file. (No screenshot OCR, no game injection.)
- Identifies cards via Arena's own card database that ships with your install.
- Scores every card in the pack using:
  - **Base power** — 17Lands' game-in-hand win rate (community data, free).
  - **Color penalty** — off-color cards get downgraded as you commit to colors.
  - **Curve bonus** — small bonus for filling underrepresented mana costs.
  - **Bomb-splash detection** — strong off-color rares get a softer penalty.
  - **Manual overrides** — your own preferences override the math.
- Displays the top recommendation and the full ranked list in an always-on-top window that you keep visible while drafting.

---

## Requirements

- **Windows 10 or 11**.
- **MTG Arena** installed, with **Detailed Logs (Plugin Support)** enabled in Settings → Account.
- **Python 3.11 or newer** ([download here](https://www.python.org/downloads/windows/)). When installing, **check the "Add python.exe to PATH" box** at the bottom of the first installer screen.
- An internet connection (just to download tier data once; it runs offline after that).

Mac/Linux are not currently supported (Arena's log paths are Windows-specific).

---

## First-time setup

1. **Download or clone** this repo to a folder on your computer.

2. **Open a terminal** in that folder. The easy way: open the folder in Windows Explorer, click the address bar, type `cmd`, and press Enter.

3. **Run the setup script**:

   ```
   py setup.py
   ```

   This:
   - Installs the two Python packages it needs (`requests`, `Pillow`).
   - Downloads card data from Scryfall.
   - Reads card names from your MTG Arena install.
   - Fetches 17Lands tier data.

   First run takes 5–10 minutes because of the Scryfall card download. Subsequent runs (after Arena updates or new sets release) are faster.

4. **In MTG Arena** — open Settings → Account → check **"Detailed Logs (Plugin Support)"**. Then **fully quit and reopen Arena** so the setting takes effect.

That's it. You're ready to draft.

---

## Using it during a draft

1. **Launch the helper**: double-click `run.bat`, or in your terminal run `py phase5_ui.py`.
2. A small dark window appears in the upper-left of your screen, with a green "live" dot.
3. Open MTG Arena and start a Quick Draft (or Premier Draft).
4. The helper reads the pack and updates within ~1 second. The recommended pick is shown big and bold; alternatives are listed below.
5. Pick a card in Arena and confirm. The helper updates with the next pack.
6. Close the helper window when you're done.

You can drag the window's title bar to move it, and resize from the corners.

---

## Understanding the display

- **Top pick panel** — the card recommended for this pick, with its tier letter and breakdown.
- **Tier letter** (S+, S, A, A+, B, B+, C, C+, D, F) — the card's intrinsic power based on community win rates.
- **Score** — the context-aware recommendation, factoring in your colors, curve, and overrides. **Use this number to compare picks; the tier is a card-quality reference.**
- **GIH** — Game-In-Hand win rate. The percentage of games won when this card was in your hand.
- **n** — number of drafted games tracked. Lower numbers mean less reliable data.
- **ALSA** — Average Last Seen At. The average pick number at which this card is still available in the pack. Higher = community ignores it.
- **ATA** — Average Take At. The average pick when the card is taken. Lower = highly valued.

A card with high tier but low score is a strong card that doesn't fit your current deck.

---

## Customizing

### Drafting a different set

When a new set drops, edit `config.json`:

```json
{
  "set_codes_in_pool": ["aaa", "bbb", "ccc"],
  "tier_set_code": "AAA",
  "tier_formats": ["QuickDraft", "PremierDraft"]
}
```

`set_codes_in_pool` is a list of all sets that appear in draft packs (main set, plus things like Mystical Archives or Special Guests). Use the lowercase set code from Scryfall (e.g., `sos`, `dft`, `tdm`).

`tier_set_code` is the uppercase code 17Lands uses (usually the same letters as the main set).

After editing, re-run `py setup.py` to refresh the data.

### Tuning recommendations

After a few drafts you'll have opinions about cards the math gets wrong. Edit `card_db/overrides.json`:

```json
{
  "Card I Like More Than 17Lands Says": { "score_adjust": 8, "note": "great in my decks" },
  "Card I Don't Vibe With": { "score_adjust": -10, "note": "always a brick for me" }
}
```

Positive numbers boost the card; negative downgrades it. Edits take effect on the next pack rendering — no restart needed. **Note**: positive numbers should NOT have a leading `+` in JSON (use `8`, not `+8`).

### Refreshing tier data

17Lands publishes new card win-rate data daily as more drafts complete. Re-run this every few days during a set's draft season:

```
py phase4_fetch_tiers.py
```

The recommendations will get noticeably better as the set matures.

### Rebuilding the arena index

Whenever Arena updates (which happens often), the local card database changes. If new cards aren't being recognized, rebuild the arena index:

```
py phase3_build_arena_index.py
```

---

## Troubleshooting

**"Could not find MTG Arena's data folder"** when running setup — your Arena install is in a non-standard location. Open `phase3_build_arena_index.py`, find `CANDIDATE_INSTALL_ROOTS`, and add your path.

**The helper window opens but stays empty / "Waiting for a pack…"** — make sure Detailed Logs is enabled in Arena (Settings → Account), and that you've **fully restarted Arena since enabling it**. Then start any draft and view a pack.

**Cards show "?" tier** — those cards don't have enough 17Lands data yet (usually because the set is brand new). They default to score 50. Re-run `py phase4_fetch_tiers.py` after a few days for better data.

**Recommendations seem off** — the math improves with set maturity. For brand-new sets the data is sparse. Use overrides (`card_db/overrides.json`) to encode your own preferences.

**Window is too big / too small / wrong colors** — open `phase5_ui.py` and edit the constants near the top: `BG_BASE`, `ACCENT_GOLD`, the `geometry()` size, etc.

---

## What this tool does NOT do

- **Doesn't modify Arena or inject anything into the game.** It only reads a log file Arena writes itself.
- **Doesn't pick cards for you.** You make every pick manually in Arena. The helper just shows recommendations.
- **Doesn't know your deck strategy.** The "context awareness" only looks at colors and curve — it doesn't recognize archetypes (e.g., it doesn't know "this is a UG fractals deck"). Use overrides to encode archetype knowledge.

Use of this tool is consistent with Wizards of the Coast's policy on log-reading tools (the same approach that 17Lands and other public tools use).

---

## Credits

- [Scryfall](https://scryfall.com) for the card metadata API.
- [17Lands](https://www.17lands.com) for the card win-rate data.
- MTG Arena for shipping the card database locally.

---

## License

MIT. Do whatever you want.
