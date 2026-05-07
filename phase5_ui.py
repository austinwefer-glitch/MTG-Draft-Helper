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
from pathlib import Path

# Reuse all the loaders, parsers, and recommendation logic.
sys.path.insert(0, str(Path(__file__).parent))
from phase3_log_parse import (
    load_arena_index,
    load_scryfall_db_by_set_cn,
    find_latest_bot_draft_status,
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
)


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

        # Header info
        pack_num = (payload.get("PackNumber", 0) or 0) + 1
        pick_num = (payload.get("PickNumber", 0) or 0) + 1
        ev = payload.get("EventName", "Draft")
        self.pack_info_var.set(
            f"{ev}    ·    Pack {pack_num} / Pick {pick_num}    ·    "
            f"{len(pack_cards)} left in pack"
        )
        self.colors_var.set(
            f"Pool · {archetype_summary(picked_cards)} · "
            f"{len(picked_cards)} picked"
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
            if top.get('basic_penalty'):
                parts.append(f"basic-land {top['basic_penalty']:g}")
            if top.get('override_adjust'):
                parts.append(f"override {top['override_adjust']:+g}")
            self.rec_breakdown_var.set("  ·  ".join(parts))

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

    def _on_close(self):
        self._stop_event.set()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    DraftHelperUI().run()
