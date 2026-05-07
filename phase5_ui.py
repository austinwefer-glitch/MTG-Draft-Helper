"""
Phase 5 — Always-on-top UI overlay (polished v3).

Visual features:
  - Mana costs rendered as colored pips, MTG-style.
  - Subtle gold pulse animation when a new pack arrives.
  - Custom row layout for alternatives (tier badges, score, name, pips).
  - Draggable from the title bar (default OS behavior).
  - Tier-coded text colors for at-a-glance scanning.

Run with:
  py phase5_ui.py
"""

import re
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

# Reuse all the loaders, parsers, and recommendation logic.
sys.path.insert(0, str(Path(__file__).parent))
from phase3_log_parse import (
    load_arena_index,
    load_scryfall_db_by_set_cn,
    find_latest_bot_draft_status,
    find_latest_bot_draft_status_in_logs,
    find_latest_payload_anywhere,
    save_draft_snapshot,
    list_archived_drafts,
    payload_from_draft,
)
from phase3_tailer import (
    parse_pack_event,
    pack_signature,
    lookup_card,
)
from phase4_recommender import (
    load_tier_index,
    load_overrides,
    rank_pack,
    archetype_summary,
    detect_archetype,
)
from phase6_deckbuilder import build_deck, cmc_of, is_creature


LOG_PATH = (
    Path.home()
    / "AppData" / "LocalLow" / "Wizards Of The Coast" / "MTGA" / "Player.log"
)
POLL_INTERVAL_SEC = 0.5


# ---------- Color theme ----------

BG_BASE = "#1a1d23"
BG_PANEL = "#22262e"
BG_TOP_PICK = "#2c2a1e"     # subtle gold tint on dark base
BG_DIVIDER = "#3a3f48"
BG_ROW_ALT = "#1f2229"

FG_TEXT = "#e1e4e8"
FG_DIM = "#9ba0a6"
FG_MUTED = "#6b7079"

ACCENT_GOLD = "#f5c265"
ACCENT_GREEN = "#7adb87"
ACCENT_BLUE = "#79b8ff"
ACCENT_GRAY = "#9ba0a6"
ACCENT_RED = "#f47174"

STATUS_LIVE = "#7adb87"


# ---------- Mana symbol color palette ----------
# Slightly desaturated to look good on the dark theme.
MANA_BG = {
    "W": "#f5efd3",   # warm cream
    "U": "#a4c5ea",   # soft blue
    "B": "#9d8fc2",   # muted purple
    "R": "#ea8278",   # warm red
    "G": "#7fc987",   # soft green
    "C": "#bdc1c8",   # neutral gray
}
MANA_FG = "#1a1d23"   # always dark text on bright pip


def tier_bg(tier: str) -> str:
    if tier in ("S+", "S"):
        return ACCENT_GOLD
    if tier in ("A+", "A"):
        return ACCENT_GREEN
    if tier in ("B+", "B"):
        return ACCENT_BLUE
    if tier in ("C+", "C"):
        return ACCENT_GRAY
    if tier in ("D", "F"):
        return ACCENT_RED
    return FG_MUTED


def tier_fg(tier: str) -> str:
    return BG_BASE  # dark text on bright badge


def tier_color(tier: str) -> str:
    if tier in ("S+", "S"):
        return ACCENT_GOLD
    if tier in ("A+", "A"):
        return ACCENT_GREEN
    if tier in ("B+", "B"):
        return ACCENT_BLUE
    if tier in ("C+", "C"):
        return FG_DIM
    if tier in ("D", "F"):
        return ACCENT_RED
    return FG_MUTED


# ---------- Mana cost renderer ----------

def mana_pips_frame(parent, cost_string: str, bg: str, size: int = 8) -> tk.Frame:
    """Build a horizontal Frame of colored mana-pip Labels.

    For example {1}{U}{U} renders as three pills: gray '1', blue 'U', blue 'U'.
    Hybrid {W/B} shows the slash, colored by the first colored side.
    """
    frame = tk.Frame(parent, bg=bg)
    if not cost_string:
        return frame
    symbols = re.findall(r"\{([^}]+)\}", cost_string)
    for sym in symbols:
        s = sym.upper()
        if s in MANA_BG:
            pip_bg = MANA_BG[s]
            text = s
        elif "/" in s:
            parts = [p for p in s.split("/") if p]
            colored = [p for p in parts if p in MANA_BG]
            pip_bg = MANA_BG[colored[0]] if colored else MANA_BG["C"]
            text = s
        elif s.isdigit() or s == "X":
            pip_bg = MANA_BG["C"]
            text = s
        else:
            pip_bg = MANA_BG["C"]
            text = s
        pip = tk.Label(
            frame, text=f" {text} ",
            bg=pip_bg, fg=MANA_FG,
            font=("Segoe UI Semibold", size),
            padx=0, pady=0, borderwidth=0,
        )
        pip.pack(side=tk.LEFT, padx=1)
    return frame


# ---------- App ----------

class DraftHelperUI:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("MTG Draft Helper")
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG_BASE)
        self.root.geometry("520x780+50+50")
        self.root.minsize(440, 520)

        # Load data
        self.arena_index = load_arena_index()
        self.scry = load_scryfall_db_by_set_cn()
        self.tier_data = load_tier_index()
        self.overrides = load_overrides()

        # Track top-pick widgets so we can pulse them
        self._top_panel_widgets: list[tk.Widget] = []

        self._build_layout()

        self.last_sig = None
        self._show_initial()

        self._stop_event = threading.Event()
        self._watcher_thread = threading.Thread(
            target=self._watch_log, daemon=True
        )
        self._watcher_thread.start()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- UI construction ----------

    def _build_layout(self):
        # --- Title bar ---
        header = tk.Frame(self.root, bg=BG_PANEL, height=44)
        header.pack(fill=tk.X, side=tk.TOP)
        header.pack_propagate(False)

        tk.Label(
            header, text="MTG  Draft  Helper",
            font=("Segoe UI Semibold", 12),
            bg=BG_PANEL, fg=FG_TEXT,
        ).pack(side=tk.LEFT, padx=14)

        status_frame = tk.Frame(header, bg=BG_PANEL)
        status_frame.pack(side=tk.RIGHT, padx=14)

        # "Drafts" button — browse past drafts.
        drafts_btn = tk.Button(
            status_frame, text="Drafts",
            font=("Segoe UI", 9),
            bg=BG_BASE, fg=FG_TEXT,
            activebackground=BG_DIVIDER, activeforeground=FG_TEXT,
            borderwidth=1, relief="flat", padx=10, pady=2,
            cursor="hand2",
            command=self._open_drafts_history,
        )
        drafts_btn.pack(side=tk.LEFT, padx=(0, 6))

        # "Build Deck" button — opens deck-builder window using the current pool.
        build_btn = tk.Button(
            status_frame, text="Build Deck",
            font=("Segoe UI Semibold", 9),
            bg=BG_BASE, fg=ACCENT_GOLD,
            activebackground=BG_DIVIDER, activeforeground=ACCENT_GOLD,
            borderwidth=1, relief="flat", padx=10, pady=2,
            cursor="hand2",
            command=self._open_deck_builder,
        )
        build_btn.pack(side=tk.LEFT, padx=(0, 12))

        self.status_dot = tk.Label(
            status_frame, text="●",
            font=("Segoe UI", 11),
            bg=BG_PANEL, fg=STATUS_LIVE,
        )
        self.status_dot.pack(side=tk.LEFT)
        tk.Label(
            status_frame, text=" live",
            font=("Segoe UI", 9),
            bg=BG_PANEL, fg=FG_DIM,
        ).pack(side=tk.LEFT)

        # State: keep the most recent picked-cards pool for deck building
        self._current_pool: list[dict] = []
        self._current_fmt: str = "QuickDraft"

        # --- Pack info ---
        self.pack_info_var = tk.StringVar(value="Waiting for a pack…")
        tk.Label(
            self.root, textvariable=self.pack_info_var,
            font=("Segoe UI", 10),
            bg=BG_BASE, fg=FG_TEXT, anchor="w",
        ).pack(fill=tk.X, padx=14, pady=(10, 2))

        self.colors_var = tk.StringVar(value="")
        tk.Label(
            self.root, textvariable=self.colors_var,
            font=("Segoe UI", 9),
            bg=BG_BASE, fg=FG_DIM, anchor="w",
        ).pack(fill=tk.X, padx=14, pady=(0, 10))

        # --- Top recommendation panel ---
        self.rec_panel = tk.Frame(
            self.root, bg=BG_TOP_PICK,
            highlightthickness=1, highlightbackground=BG_DIVIDER,
        )
        self.rec_panel.pack(fill=tk.X, padx=10, pady=(0, 12))
        self._top_panel_widgets.append(self.rec_panel)

        rec_inner = tk.Frame(self.rec_panel, bg=BG_TOP_PICK)
        rec_inner.pack(fill=tk.X, padx=14, pady=10)
        self._top_panel_widgets.append(rec_inner)

        # Top row inside the panel: label + tier badge + score
        top_row = tk.Frame(rec_inner, bg=BG_TOP_PICK)
        top_row.pack(fill=tk.X)
        self._top_panel_widgets.append(top_row)

        self.top_pick_label = tk.Label(
            top_row, text="TOP PICK",
            font=("Segoe UI Semibold", 8),
            bg=BG_TOP_PICK, fg=ACCENT_GOLD,
        )
        self.top_pick_label.pack(side=tk.LEFT)
        self._top_panel_widgets.append(self.top_pick_label)

        self.tier_badge = tk.Label(
            top_row, text=" — ",
            font=("Segoe UI Semibold", 9),
            bg=FG_MUTED, fg=tier_fg("?"),
            padx=8, pady=1,
        )
        self.tier_badge.pack(side=tk.RIGHT)

        self.score_lbl = tk.Label(
            top_row, text="",
            font=("Segoe UI Semibold", 10),
            bg=BG_TOP_PICK, fg=FG_DIM,
        )
        self.score_lbl.pack(side=tk.RIGHT, padx=(0, 8))
        self._top_panel_widgets.append(self.score_lbl)

        # Card name
        self.rec_name_var = tk.StringVar(value="—")
        rec_name = tk.Label(
            rec_inner, textvariable=self.rec_name_var,
            font=("Segoe UI Semibold", 16),
            bg=BG_TOP_PICK, fg=FG_TEXT,
            anchor="w", justify="left",
        )
        rec_name.pack(fill=tk.X, pady=(4, 4))
        self._top_panel_widgets.append(rec_name)

        # Cost (mana pips) + rarity / type
        cost_row = tk.Frame(rec_inner, bg=BG_TOP_PICK)
        cost_row.pack(fill=tk.X, pady=(0, 2))
        self._top_panel_widgets.append(cost_row)

        self._cost_pip_container = tk.Frame(cost_row, bg=BG_TOP_PICK)
        self._cost_pip_container.pack(side=tk.LEFT)
        self._top_panel_widgets.append(self._cost_pip_container)

        self.rec_meta_var = tk.StringVar(value="")
        rec_meta = tk.Label(
            cost_row, textvariable=self.rec_meta_var,
            font=("Segoe UI", 9),
            bg=BG_TOP_PICK, fg=FG_DIM,
        )
        rec_meta.pack(side=tk.LEFT, padx=(8, 0))
        self._top_panel_widgets.append(rec_meta)

        # Divider
        div = tk.Frame(rec_inner, bg=BG_DIVIDER, height=1)
        div.pack(fill=tk.X, pady=(8, 6))

        # Stats line
        self.rec_stats_var = tk.StringVar(value="")
        rec_stats = tk.Label(
            rec_inner, textvariable=self.rec_stats_var,
            font=("Consolas", 9),
            bg=BG_TOP_PICK, fg=FG_TEXT, anchor="w",
        )
        rec_stats.pack(fill=tk.X)
        self._top_panel_widgets.append(rec_stats)

        # Breakdown line
        self.rec_breakdown_var = tk.StringVar(value="")
        rec_breakdown = tk.Label(
            rec_inner, textvariable=self.rec_breakdown_var,
            font=("Consolas", 8),
            bg=BG_TOP_PICK, fg=FG_MUTED, anchor="w",
        )
        rec_breakdown.pack(fill=tk.X, pady=(2, 0))
        self._top_panel_widgets.append(rec_breakdown)

        # --- Alternatives heading ---
        tk.Label(
            self.root, text="ALTERNATIVES",
            font=("Segoe UI Semibold", 8),
            bg=BG_BASE, fg=FG_DIM, anchor="w",
        ).pack(fill=tk.X, padx=14, pady=(0, 4))

        # Container for the row Frames (one per alternative card)
        alt_outer = tk.Frame(
            self.root, bg=BG_PANEL,
            highlightthickness=1, highlightbackground=BG_DIVIDER,
        )
        alt_outer.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.alt_container = tk.Frame(alt_outer, bg=BG_PANEL)
        self.alt_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

        # --- Pool footer ---
        tk.Label(
            self.root, text="POOL",
            font=("Segoe UI Semibold", 8),
            bg=BG_BASE, fg=FG_DIM, anchor="w",
        ).pack(fill=tk.X, padx=14, pady=(0, 4))

        self.pool_text = tk.Text(
            self.root,
            font=("Segoe UI", 8),
            bg=BG_BASE, fg=FG_MUTED, wrap=tk.WORD,
            height=4, borderwidth=0, highlightthickness=0,
            padx=10, pady=4,
        )
        self.pool_text.pack(fill=tk.X, padx=10, pady=(0, 10))
        self.pool_text.config(state=tk.DISABLED)

    # ---------- Animations ----------

    def _pulse_top_panel(self):
        """Brief subtle gold flash on the top pick panel when a new pack arrives."""
        # 6-step transition: dim → bright → settle
        steps = [
            "#3a3525", "#4a4326", "#5a4d24",
            "#4a4326", "#3a3525", BG_TOP_PICK,
        ]
        for i, color in enumerate(steps):
            self.root.after(i * 70, lambda c=color: self._set_top_panel_bg(c))

    def _set_top_panel_bg(self, color: str):
        for w in self._top_panel_widgets:
            try:
                w.configure(bg=color)
            except tk.TclError:
                pass

    # ---------- Data flow ----------

    def _show_initial(self):
        try:
            text = LOG_PATH.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return
        payload = find_latest_bot_draft_status(text)
        if payload:
            self.last_sig = pack_signature(payload)
            self._update_display(payload)

    def _watch_log(self):
        try:
            f = LOG_PATH.open("r", encoding="utf-8", errors="replace")
            f.seek(0, 2)
        except OSError:
            return
        last_size = LOG_PATH.stat().st_size
        prev_line = ""
        while not self._stop_event.is_set():
            time.sleep(POLL_INTERVAL_SEC)
            try:
                current_size = LOG_PATH.stat().st_size
            except OSError:
                continue
            if current_size < last_size:
                try:
                    f.close()
                    f = LOG_PATH.open("r", encoding="utf-8", errors="replace")
                except OSError:
                    continue
                prev_line = ""
            last_size = current_size
            while True:
                line = f.readline()
                if not line:
                    break
                payload = parse_pack_event(prev_line, line)
                if payload:
                    sig = pack_signature(payload)
                    if sig != self.last_sig:
                        self.last_sig = sig
                        self.root.after(0, self._update_display, payload, True)
                prev_line = line
        f.close()

    def _build_alt_row(self, parent, rank: int, r: dict, row_bg: str) -> tk.Frame:
        c = r["card"]
        tier = r["tier"]

        row = tk.Frame(parent, bg=row_bg, height=24)
        row.pack(fill=tk.X, pady=1)
        row.pack_propagate(False)

        # Rank
        tk.Label(
            row, text=f"{rank:>2}",
            font=("Consolas", 9),
            bg=row_bg, fg=FG_DIM, width=3, anchor="e",
        ).pack(side=tk.LEFT, padx=(4, 6))

        # Tier badge
        tk.Label(
            row, text=f" {tier} ",
            font=("Segoe UI Semibold", 8),
            bg=tier_bg(tier), fg=tier_fg(tier), padx=2,
        ).pack(side=tk.LEFT)

        # Score
        tk.Label(
            row, text=f"{r['score']:>5.1f}",
            font=("Consolas", 9),
            bg=row_bg, fg=tier_color(tier), width=6, anchor="e",
        ).pack(side=tk.LEFT, padx=(8, 4))

        # Card name (truncated to fit)
        name = r["name"]
        if len(name) > 26:
            name = name[:25] + "…"
        tk.Label(
            row, text=name, font=("Segoe UI", 9),
            bg=row_bg, fg=FG_TEXT, width=26, anchor="w",
        ).pack(side=tk.LEFT)

        # Mana pips
        mana_pips_frame(
            row, c.get("mana_cost", "") or "", bg=row_bg, size=7
        ).pack(side=tk.LEFT, padx=4)

        # ALSA / ATA on the right
        meta_parts = []
        if r.get("alsa") is not None:
            meta_parts.append(f"L{r['alsa']:.1f}")
        if r.get("ata") is not None:
            meta_parts.append(f"T{r['ata']:.1f}")
        meta_text = "  ".join(meta_parts) if meta_parts else ""
        tk.Label(
            row, text=meta_text, font=("Consolas", 8),
            bg=row_bg, fg=FG_MUTED, anchor="e",
        ).pack(side=tk.RIGHT, padx=(0, 6))

        return row

    def _update_display(self, payload, animate: bool = False):
        pack_ids = payload.get("DraftPack", [])
        if not pack_ids:
            return

        pack_cards = []
        for sid in pack_ids:
            info = lookup_card(self.arena_index, self.scry, sid)
            if info is None:
                info = {"name": f"<arena_id {sid}>", "mana_cost": "",
                        "rarity": "?", "type_line": "", "cmc": 0}
            pack_cards.append(info)

        picked_ids = payload.get("PickedCards", [])
        picked_cards = []
        for sid in picked_ids:
            info = lookup_card(self.arena_index, self.scry, sid)
            if info:
                picked_cards.append(info)

        fmt = ("QuickDraft" if "QuickDraft" in (payload.get("EventName") or "")
               else "PremierDraft")
        self.overrides = load_overrides()
        ranked = rank_pack(pack_cards, picked_cards, self.tier_data,
                           fmt=fmt, overrides=self.overrides)

        # Stash the pool for the deck builder
        self._current_pool = list(picked_cards)
        self._current_fmt = fmt

        # Persist the latest draft state so the deck builder can recover it
        # later, even after Arena rotates its log files.
        save_draft_snapshot(payload)

        # Header info
        pack_num = (payload.get("PackNumber", 0) or 0) + 1
        pick_num = (payload.get("PickNumber", 0) or 0) + 1
        ev = payload.get("EventName", "Draft")
        self.pack_info_var.set(
            f"{ev}    ·    Pack {pack_num} / Pick {pick_num}    ·    "
            f"{len(pack_cards)} left in pack"
        )
        # Detect what shape the pool is heading toward (aggressive / midrange / control).
        # Once we have enough picks for the detection to be meaningful (10+),
        # surface it so the user knows which targets the recommender is using.
        shape = detect_archetype(picked_cards) if len(picked_cards) >= 10 else None
        shape_str = f" · shape: {shape}" if shape else ""
        self.colors_var.set(
            f"Pool · {archetype_summary(picked_cards)} · "
            f"{len(picked_cards)} picked{shape_str}"
        )

        # Top recommendation
        if ranked:
            top = ranked[0]
            tcard = top["card"]
            self.rec_name_var.set(top["name"])

            rar = (tcard.get("rarity") or "").replace("_", " ").title()
            tline = tcard.get("type_line") or ""
            self.rec_meta_var.set(f"{rar}  ·  {tline}")

            # Re-build the cost pip row
            for child in self._cost_pip_container.winfo_children():
                child.destroy()
            new_pips = mana_pips_frame(
                self._cost_pip_container, tcard.get("mana_cost", "") or "",
                bg=BG_TOP_PICK, size=10,
            )
            new_pips.pack()

            tier = top["tier"]
            self.tier_badge.config(
                text=f" {tier} ", bg=tier_bg(tier), fg=tier_fg(tier)
            )
            self.score_lbl.config(text=f"score {top['score']:>5.1f}")

            wr = (f"{top['gih_wr']*100:.1f}% GIH"
                  if top.get('gih_wr') is not None else "no WR data")
            n = (f"  n={top['sample_size']:,}"
                 if top.get('sample_size') else "")
            alsa = (f"  ALSA {top['alsa']:.1f}"
                    if top.get('alsa') is not None else "")
            ata = (f"  ATA {top['ata']:.1f}"
                   if top.get('ata') is not None else "")
            self.rec_stats_var.set(f"{wr}{n}{alsa}{ata}")

            parts = [f"base {top['base']}"]
            if top['color_penalty']:
                parts.append(f"color {top['color_penalty']:+g}")
            if top['curve_bonus']:
                parts.append(f"curve +{top['curve_bonus']:g}")
            if top.get('wheel_adjust'):
                parts.append(f"wheel {top['wheel_adjust']:+g}")
            if top.get('composition_bonus'):
                arch_short = (top.get('composition_archetype') or "")[:3]
                parts.append(f"comp +{top['composition_bonus']:g} ({arch_short})")
            if top.get('synergy_bonus'):
                parts.append(f"synergy +{top['synergy_bonus']:g}")
            if top.get('basic_penalty'):
                parts.append(f"basic-land {top['basic_penalty']:g}")
            if top.get('override_adjust'):
                parts.append(f"override {top['override_adjust']:+g}")
            breakdown_text = "  ·  ".join(parts)
            # Append synergy reasons on a second line if any fired
            reasons = top.get('synergy_reasons') or []
            if reasons:
                breakdown_text += "\n  synergy: " + " · ".join(reasons[:3])
            self.rec_breakdown_var.set(breakdown_text)

        # Alternatives — clear and rebuild
        for child in self.alt_container.winfo_children():
            child.destroy()
        for i, r in enumerate(ranked[1:], start=2):
            row_bg = BG_PANEL if i % 2 == 0 else BG_ROW_ALT
            self._build_alt_row(self.alt_container, i, r, row_bg)

        # Pool
        self.pool_text.config(state=tk.NORMAL)
        self.pool_text.delete("1.0", tk.END)
        names = [c["name"] for c in picked_cards]
        self.pool_text.insert(tk.END, "  ·  ".join(names) if names else "—")
        self.pool_text.config(state=tk.DISABLED)

        # Pulse the top pick panel (only on live updates, not initial render)
        if animate:
            self._pulse_top_panel()

    # ---------- Deck builder window ----------

    def _latest_pool_from_log(self) -> tuple[list, str]:
        """Find the most recent pool from any source, falling back through:
        live Player.log -> Player-prev.log -> last_draft.json -> drafts/ archive.
        Always returns the freshest available even if Arena's been closed."""
        payload = find_latest_payload_anywhere()
        if not payload:
            return [], "QuickDraft"
        fmt = ("QuickDraft" if "QuickDraft" in (payload.get("EventName") or "")
               else "PremierDraft")
        pool = []
        for sid in payload.get("PickedCards", []):
            info = lookup_card(self.arena_index, self.scry, sid)
            if info:
                pool.append(info)
        return pool, fmt

    def _open_deck_builder(self):
        """Launch a separate Toplevel window with the deck-build view.
        Always re-reads the latest pool from the log so this works
        whether a pack is currently visible or the draft has ended."""
        pool, fmt = self._latest_pool_from_log()
        if not pool:
            messagebox.showinfo(
                "Build Deck",
                "Couldn't find a draft pool in the log.\n\n"
                "Make sure you've completed at least a few picks with "
                "Detailed Logs enabled, then try again."
            )
            return
        # Reload overrides so the build uses the latest tweaks
        self.overrides = load_overrides()
        DeckBuilderWindow(
            self.root, pool, self.tier_data, self.overrides, fmt,
        )

    def _open_drafts_history(self):
        """Open the past-drafts browser window."""
        DraftHistoryWindow(
            self.root,
            arena_index=self.arena_index,
            scry=self.scry,
            tier_data=self.tier_data,
            on_open_draft=self._open_deck_for_draft,
        )

    def _open_deck_for_draft(self, draft: dict):
        """Build a deck from an arbitrary archived draft entry."""
        payload = payload_from_draft(draft)
        pool = []
        for sid in payload.get("PickedCards", []):
            info = lookup_card(self.arena_index, self.scry, sid)
            if info:
                pool.append(info)
        if not pool:
            messagebox.showinfo(
                "Open Draft",
                "Couldn't resolve any cards in this draft. The arena index "
                "may have rotated since the draft was saved."
            )
            return
        fmt = ("QuickDraft" if "QuickDraft" in (payload.get("EventName") or "")
               else "PremierDraft")
        self.overrides = load_overrides()
        DeckBuilderWindow(
            self.root, pool, self.tier_data, self.overrides, fmt,
        )

    def _on_close(self):
        self._stop_event.set()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


class DeckBuilderWindow:
    """Separate Toplevel window that shows a deck-build recommendation
    based on the current pool. Independent of the main always-on-top
    helper window."""

    def __init__(self, parent, pool, tier_data, overrides, fmt):
        self.win = tk.Toplevel(parent)
        self.win.title("Deck Builder")
        self.win.configure(bg=BG_BASE)
        self.win.geometry("680x780+200+80")
        self.win.minsize(560, 600)

        self.pool = pool
        self.tier_data = tier_data
        self.overrides = overrides
        self.fmt = fmt
        self.build = None

        self._build_layout()
        self._render()

    def _build_layout(self):
        # Header bar
        header = tk.Frame(self.win, bg=BG_PANEL, height=44)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(
            header, text="Deck Builder",
            font=("Segoe UI Semibold", 12),
            bg=BG_PANEL, fg=FG_TEXT,
        ).pack(side=tk.LEFT, padx=14)

        rebuild_btn = tk.Button(
            header, text="Rebuild",
            font=("Segoe UI", 9),
            bg=BG_BASE, fg=ACCENT_GOLD,
            activebackground=BG_DIVIDER, activeforeground=ACCENT_GOLD,
            borderwidth=1, relief="flat", padx=10, pady=2,
            cursor="hand2",
            command=self._render,
        )
        rebuild_btn.pack(side=tk.RIGHT, padx=14)

        # Top summary
        self.summary_var = tk.StringVar()
        tk.Label(
            self.win, textvariable=self.summary_var,
            font=("Segoe UI Semibold", 11),
            bg=BG_BASE, fg=ACCENT_GOLD, anchor="w",
        ).pack(fill=tk.X, padx=14, pady=(10, 2))

        self.detail_var = tk.StringVar()
        tk.Label(
            self.win, textvariable=self.detail_var,
            font=("Segoe UI", 9),
            bg=BG_BASE, fg=FG_DIM, anchor="w",
        ).pack(fill=tk.X, padx=14, pady=(0, 10))

        # Curve graph (textual ASCII bars)
        curve_panel = tk.Frame(
            self.win, bg=BG_PANEL,
            highlightthickness=1, highlightbackground=BG_DIVIDER,
        )
        curve_panel.pack(fill=tk.X, padx=10, pady=(0, 10))
        tk.Label(
            curve_panel, text="MANA CURVE",
            font=("Segoe UI Semibold", 8),
            bg=BG_PANEL, fg=FG_DIM, anchor="w", padx=10,
        ).pack(fill=tk.X, pady=(8, 2))
        self.curve_text = tk.Text(
            curve_panel, font=("Consolas", 9),
            bg=BG_PANEL, fg=FG_TEXT, wrap=tk.NONE,
            height=8, borderwidth=0, highlightthickness=0,
            padx=12, pady=4,
        )
        self.curve_text.pack(fill=tk.X, pady=(0, 8))
        self.curve_text.config(state=tk.DISABLED)

        # Two-column body: deck on the left, cuts on the right
        body = tk.Frame(self.win, bg=BG_BASE)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # DECK column
        deck_col = tk.Frame(body, bg=BG_BASE)
        deck_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                      padx=(0, 5))
        tk.Label(
            deck_col, text="DECK (KEEP)",
            font=("Segoe UI Semibold", 8),
            bg=BG_BASE, fg=ACCENT_GREEN, anchor="w",
        ).pack(fill=tk.X, padx=4, pady=(0, 4))
        deck_frame = tk.Frame(
            deck_col, bg=BG_PANEL,
            highlightthickness=1, highlightbackground=BG_DIVIDER,
        )
        deck_frame.pack(fill=tk.BOTH, expand=True)
        self.deck_text = tk.Text(
            deck_frame, font=("Consolas", 9),
            bg=BG_PANEL, fg=FG_TEXT, wrap=tk.NONE,
            borderwidth=0, highlightthickness=0,
            padx=10, pady=8, spacing1=1,
        )
        self.deck_text.pack(fill=tk.BOTH, expand=True)
        self.deck_text.config(state=tk.DISABLED)

        # CUTS column
        cuts_col = tk.Frame(body, bg=BG_BASE)
        cuts_col.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True,
                      padx=(5, 0))
        tk.Label(
            cuts_col, text="CUTS",
            font=("Segoe UI Semibold", 8),
            bg=BG_BASE, fg=ACCENT_RED, anchor="w",
        ).pack(fill=tk.X, padx=4, pady=(0, 4))
        cuts_frame = tk.Frame(
            cuts_col, bg=BG_PANEL,
            highlightthickness=1, highlightbackground=BG_DIVIDER,
        )
        cuts_frame.pack(fill=tk.BOTH, expand=True)
        self.cuts_text = tk.Text(
            cuts_frame, font=("Consolas", 8),
            bg=BG_PANEL, fg=FG_DIM, wrap=tk.NONE,
            borderwidth=0, highlightthickness=0,
            padx=10, pady=8, spacing1=1,
        )
        self.cuts_text.pack(fill=tk.BOTH, expand=True)
        self.cuts_text.config(state=tk.DISABLED)

    def _render(self):
        self.build = build_deck(
            self.pool, self.tier_data,
            overrides=self.overrides, fmt=self.fmt,
        )

        # ---- Summary ----
        b = self.build
        cols = "".join(sorted(b["primary_colors"]))
        splash = (f"  +  splash {''.join(sorted(b['splash_colors']))}"
                  if b["splash_colors"] else "")
        self.summary_var.set(
            f"{b['archetype'].upper()}    ·    {cols}{splash}"
        )
        # Vs target — flag if we're short on creatures or spells
        cre_n, cre_t = b["creature_count"], b["creature_target"]
        nc_n, nc_t = b["noncreature_count"], b["noncreature_target"]
        cre_warn = " ⚠" if cre_n < cre_t - 1 else ""
        nc_warn = " ⚠" if nc_n < nc_t - 1 else ""
        self.detail_var.set(
            f"Pool: {len(self.pool)} cards   ·   "
            f"Deck: {b['deck_total']} ({len(b['deck_nonlands'])}+"
            f"{b['lands_total']} lands)   ·   "
            f"{cre_n} creatures{cre_warn}  /  "
            f"{nc_n} spells{nc_warn}"
        )

        # ---- Curve graph (split by creatures vs noncreatures) ----
        cre_count = {b_: 0 for b_ in range(7)}
        nc_count = {b_: 0 for b_ in range(7)}
        for s in b["deck_scored"]:
            c = cmc_of(s["card"])
            if is_creature(s["card"]):
                cre_count[c] += 1
            else:
                nc_count[c] += 1
        max_count = max(
            (cre_count[c] + nc_count[c] for c in range(7)),
            default=1,
        ) or 1
        self.curve_text.config(state=tk.NORMAL)
        self.curve_text.delete("1.0", tk.END)
        # Clear old tags first
        for tag in self.curve_text.tag_names():
            if tag.startswith("curve_"):
                self.curve_text.tag_delete(tag)
        for c in sorted(cre_count):
            label = f"{c}+" if c == 6 else str(c)
            cre_n_b = cre_count[c]
            nc_n_b = nc_count[c]
            total = cre_n_b + nc_n_b
            cre_bar = "█" * int(28 * cre_n_b / max_count) if cre_n_b else ""
            nc_bar = "▒" * int(28 * nc_n_b / max_count) if nc_n_b else ""
            self.curve_text.insert(
                tk.END,
                f"  CMC {label:<2}  {cre_n_b:>2}c {nc_n_b:>2}s  ",
                "curve_label",
            )
            self.curve_text.insert(tk.END, cre_bar, f"curve_creature_{c}")
            self.curve_text.insert(tk.END, nc_bar, f"curve_spell_{c}")
            self.curve_text.insert(tk.END, "\n")
        self.curve_text.tag_config("curve_label", foreground=FG_TEXT)
        for c in range(7):
            self.curve_text.tag_config(f"curve_creature_{c}",
                                       foreground=ACCENT_GREEN)
            self.curve_text.tag_config(f"curve_spell_{c}",
                                       foreground=ACCENT_BLUE)
        self.curve_text.config(state=tk.DISABLED)

        # ---- Deck list ----
        self.deck_text.config(state=tk.NORMAL)
        self.deck_text.delete("1.0", tk.END)
        for tag in self.deck_text.tag_names():
            self.deck_text.tag_delete(tag)

        # Header
        self.deck_text.insert(tk.END, "Lands\n", "section")
        basic_names = {"W": "Plains", "U": "Island", "B": "Swamp",
                       "R": "Mountain", "G": "Forest"}
        for c, n in sorted(b["lands"].items(), key=lambda x: -x[1]):
            self.deck_text.insert(tk.END,
                f"  {n:>2}x  {basic_names[c]}\n", "land"
            )

        # Group nonlands by CMC, sorted with creatures first inside each bucket
        by_cmc: dict = {}
        for s in b["deck_scored"]:
            c = cmc_of(s["card"])
            by_cmc.setdefault(c, []).append(s)
        for c in sorted(by_cmc):
            label = f"CMC {c}+" if c == 6 else f"CMC {c}"
            self.deck_text.insert(tk.END, f"\n{label}\n", "section")
            # Creatures first, then noncreatures, each by score
            sorted_bucket = sorted(
                by_cmc[c],
                key=lambda x: (not is_creature(x["card"]), -x["base"]),
            )
            for s in sorted_bucket:
                cost = s["card"].get("mana_cost") or ""
                kind_marker = "•" if is_creature(s["card"]) else "◇"
                tag = "creature" if is_creature(s["card"]) else "spell"
                line = (f"  {kind_marker} {s['base']:>5.1f}  "
                        f"{s['name'][:24]:<24} {cost}\n")
                self.deck_text.insert(tk.END, line, tag)

        self.deck_text.tag_config(
            "section", foreground=ACCENT_GOLD,
            font=("Segoe UI Semibold", 9), spacing1=4, spacing3=2,
        )
        self.deck_text.tag_config("land", foreground=FG_TEXT)
        self.deck_text.tag_config("creature", foreground=ACCENT_GREEN)
        self.deck_text.tag_config("spell", foreground=ACCENT_BLUE)
        self.deck_text.config(state=tk.DISABLED)

        # ---- Cuts ----
        self.cuts_text.config(state=tk.NORMAL)
        self.cuts_text.delete("1.0", tk.END)
        for tag in self.cuts_text.tag_names():
            self.cuts_text.tag_delete(tag)

        # Group cuts by reason
        cuts_by_reason: dict = {}
        for c in b["cuts"]:
            cuts_by_reason.setdefault(c["reason"], []).append(c)

        for reason, items in cuts_by_reason.items():
            self.cuts_text.insert(tk.END, f"{reason}\n", "section")
            for c in sorted(items, key=lambda x: x["score"]):
                name = c["card"].get("name", "?")[:26]
                line = f"  {c['score']:>5.1f}  {name}\n"
                self.cuts_text.insert(tk.END, line, "cut")

        self.cuts_text.tag_config(
            "section", foreground=ACCENT_RED,
            font=("Segoe UI Semibold", 8), spacing1=6, spacing3=2,
        )
        self.cuts_text.tag_config("cut", foreground=FG_DIM)
        self.cuts_text.config(state=tk.DISABLED)


class DraftHistoryWindow:
    """A scrollable list of all persisted drafts. Click a row to open
    the deck builder for that draft."""

    def __init__(self, parent, arena_index, scry, tier_data, on_open_draft):
        self.win = tk.Toplevel(parent)
        self.win.title("Past Drafts")
        self.win.configure(bg=BG_BASE)
        self.win.geometry("620x520+150+100")
        self.win.minsize(480, 320)

        self.arena_index = arena_index
        self.scry = scry
        self.tier_data = tier_data
        self.on_open_draft = on_open_draft

        self._build_layout()
        self._populate()

    def _build_layout(self):
        header = tk.Frame(self.win, bg=BG_PANEL, height=44)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(
            header, text="Past Drafts",
            font=("Segoe UI Semibold", 12),
            bg=BG_PANEL, fg=FG_TEXT,
        ).pack(side=tk.LEFT, padx=14)

        refresh_btn = tk.Button(
            header, text="Refresh",
            font=("Segoe UI", 9),
            bg=BG_BASE, fg=FG_TEXT,
            activebackground=BG_DIVIDER, activeforeground=FG_TEXT,
            borderwidth=1, relief="flat", padx=10, pady=2,
            cursor="hand2",
            command=self._populate,
        )
        refresh_btn.pack(side=tk.RIGHT, padx=14)

        # Subtitle / count
        self.count_var = tk.StringVar(value="")
        tk.Label(
            self.win, textvariable=self.count_var,
            font=("Segoe UI", 9),
            bg=BG_BASE, fg=FG_DIM, anchor="w",
        ).pack(fill=tk.X, padx=14, pady=(8, 8))

        # Scrollable list area
        list_frame = tk.Frame(
            self.win, bg=BG_PANEL,
            highlightthickness=1, highlightbackground=BG_DIVIDER,
        )
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.canvas = tk.Canvas(
            list_frame, bg=BG_PANEL, highlightthickness=0,
        )
        scrollbar = tk.Scrollbar(
            list_frame, orient=tk.VERTICAL, command=self.canvas.yview,
        )
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.rows_frame = tk.Frame(self.canvas, bg=BG_PANEL)
        self.canvas.create_window(
            (0, 0), window=self.rows_frame, anchor="nw"
        )
        self.rows_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        # Mouse-wheel scroll
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        # Only scroll if our window has focus
        try:
            if self.win.focus_displayof() and self.win == self.win.focus_displayof().winfo_toplevel():
                self.canvas.yview_scroll(-1 * (event.delta // 120), "units")
        except (tk.TclError, AttributeError):
            pass

    def _format_when(self, saved_at: str) -> str:
        """Pretty-format the saved_at timestamp."""
        if not saved_at:
            return "(unknown)"
        # ISO format like "2026-05-07T14:32:11"
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(saved_at)
            return dt.strftime("%Y-%m-%d  %H:%M")
        except (ValueError, TypeError):
            return saved_at

    def _build_row(self, parent, draft: dict, idx: int) -> tk.Frame:
        is_current = draft.get("is_current", False)
        row_bg = BG_TOP_PICK if is_current else (
            BG_PANEL if idx % 2 == 0 else BG_ROW_ALT
        )
        row = tk.Frame(parent, bg=row_bg, cursor="hand2")
        row.pack(fill=tk.X)

        inner = tk.Frame(row, bg=row_bg)
        inner.pack(fill=tk.X, padx=12, pady=8)

        when = self._format_when(draft.get("saved_at", ""))
        event = draft.get("event_name", "?")
        n = draft.get("card_count", 0)
        tag = "  • current" if is_current else ""

        # When + tag
        when_lbl = tk.Label(
            inner, text=when + tag,
            font=("Consolas", 9),
            bg=row_bg, fg=ACCENT_GOLD if is_current else FG_DIM,
            anchor="w",
        )
        when_lbl.pack(side=tk.LEFT, padx=(0, 16))

        # Event name + cards
        event_lbl = tk.Label(
            inner, text=f"{event}",
            font=("Segoe UI", 9),
            bg=row_bg, fg=FG_TEXT, anchor="w",
        )
        event_lbl.pack(side=tk.LEFT, padx=(0, 16))

        cards_lbl = tk.Label(
            inner, text=f"{n} cards",
            font=("Segoe UI", 9),
            bg=row_bg, fg=FG_DIM, anchor="w",
        )
        cards_lbl.pack(side=tk.LEFT)

        open_lbl = tk.Label(
            inner, text="Open  ➜",
            font=("Segoe UI", 9),
            bg=row_bg, fg=ACCENT_GOLD,
        )
        open_lbl.pack(side=tk.RIGHT)

        # Click anywhere on the row opens the deck builder
        def _on_click(e, d=draft):
            self.on_open_draft(d)
        for w in (row, inner, when_lbl, event_lbl, cards_lbl, open_lbl):
            w.bind("<Button-1>", _on_click)

        # Hover effect
        def _enter(e, w=row, ws=[row, inner, when_lbl, event_lbl, cards_lbl, open_lbl]):
            for x in ws:
                x.config(bg=BG_DIVIDER)
        def _leave(e, w=row, ws=[row, inner, when_lbl, event_lbl, cards_lbl, open_lbl], orig=row_bg):
            for x in ws:
                x.config(bg=orig)
        for w in (row, inner, when_lbl, event_lbl, cards_lbl, open_lbl):
            w.bind("<Enter>", _enter)
            w.bind("<Leave>", _leave)

        return row

    def _populate(self):
        # Clear existing rows
        for child in self.rows_frame.winfo_children():
            child.destroy()

        drafts = list_archived_drafts()
        if not drafts:
            self.count_var.set("No drafts saved yet.")
            tk.Label(
                self.rows_frame,
                text=("Drafts will appear here automatically once you've "
                      "drafted with the helper running."),
                font=("Segoe UI", 9),
                bg=BG_PANEL, fg=FG_DIM,
                wraplength=520, justify="left",
                padx=20, pady=20,
            ).pack(fill=tk.X)
            return

        n = len(drafts)
        self.count_var.set(
            f"{n} draft{'s' if n != 1 else ''} saved · "
            f"click any row to view its deck recommendation"
        )
        for idx, draft in enumerate(drafts):
            self._build_row(self.rows_frame, draft, idx)


if __name__ == "__main__":
    DraftHelperUI().run()
