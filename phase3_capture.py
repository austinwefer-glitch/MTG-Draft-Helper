"""
Phase 3 — Step A: Hotkey-triggered screenshot capture.

Run this in your VS Code terminal, then alt-tab to MTG Arena.
When a draft pack appears on screen, press Ctrl+Shift+M and the screenshot
is saved to disk. Repeat as many times as you want.

Hotkeys:
  Ctrl+Shift+M  - capture the current screen
  Ctrl+Shift+Q  - quit the listener

Output:
  screenshots/pack_YYYYMMDD_HHMMSS.png  (one PNG per capture)

Run with:
  py phase3_capture.py
"""

from datetime import datetime
from pathlib import Path
import time

import keyboard
import mss


PROJECT_DIR = Path(__file__).parent
SCREENSHOTS_DIR = PROJECT_DIR / "screenshots"
HOTKEY_CAPTURE = "ctrl+shift+m"
HOTKEY_DELAYED = "ctrl+shift+n"   # delayed-capture hotkey (4 sec delay)
HOTKEY_QUIT = "ctrl+shift+q"
DELAY_SEC = 4

# Which mss monitor index to capture (1-based; 0 is the all-monitors view).
# Austin runs Arena on monitor 3 (leftmost 1920x1080).
ARENA_MONITOR_INDEX = 3

# Counter so the terminal output is easy to follow
_capture_count = 0


def capture_screenshot():
    """Capture only the Arena monitor (locked to ARENA_MONITOR_INDEX)."""
    global _capture_count
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"pack_{timestamp}.png"
    filepath = SCREENSHOTS_DIR / filename

    with mss.mss() as sct:
        monitor = sct.monitors[ARENA_MONITOR_INDEX]
        sct.shot(mon=ARENA_MONITOR_INDEX, output=str(filepath))

    _capture_count += 1
    print(f"  [{_capture_count}] Saved: {filename}  "
          f"({monitor['width']}x{monitor['height']})")


def capture_delayed():
    """Wait DELAY_SEC seconds, then capture. Gives time to alt-tab to Arena."""
    print(f"  ... delayed capture: switch to Arena now, "
          f"capturing in {DELAY_SEC}s ...")
    time.sleep(DELAY_SEC)
    capture_screenshot()


def list_monitors():
    """Print the monitors mss can see, so we know what we're working with."""
    with mss.mss() as sct:
        print("Detected monitors:")
        for i, m in enumerate(sct.monitors):
            label = "(virtual / all monitors)" if i == 0 else f"(monitor {i})"
            print(f"  index {i} {label}: "
                  f"{m['width']}x{m['height']} at offset "
                  f"({m['left']}, {m['top']})")
        print()


def main():
    print("=" * 60)
    print("MTG Draft Helper — Phase 3: screenshot capture")
    print()
    list_monitors()
    print(f"  Instant capture:  {HOTKEY_CAPTURE.upper()}")
    print(f"  Delayed capture:  {HOTKEY_DELAYED.upper()}  "
          f"(waits {DELAY_SEC}s — gives time to switch to Arena)")
    print(f"  Quit:             {HOTKEY_QUIT.upper()}  "
          f"(or Ctrl+C in terminal)")
    print()
    print(f"  Screenshots saved to:")
    print(f"    {SCREENSHOTS_DIR}")
    print("=" * 60)
    print()
    print("Listening... go to Arena and press the hotkey when you see a pack.")

    keyboard.add_hotkey(HOTKEY_CAPTURE, capture_screenshot)
    keyboard.add_hotkey(HOTKEY_DELAYED, capture_delayed)
    # Block here until the quit hotkey is pressed (or Ctrl+C)
    keyboard.wait(HOTKEY_QUIT)
    print("\nQuit hotkey received. Goodbye.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted (Ctrl+C). Exiting.")
