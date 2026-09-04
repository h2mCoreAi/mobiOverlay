"""Color, font and style constants matching the approved design mockup.

Reference: docs/DECISIONS.md, "Visual design approved" entry.
Source mockup: design/Main.dc.html
"""

# Backgrounds — sampled directly from a live MobiGlas (in-game device
# menu) screenshot, 2026-09-04, not guessed. MobiGlas runs a blue-gray
# palette, not the teal-black this started as: BG_VOID matched what we
# already had almost exactly (real deep-space bg sampled at #03080d), but
# BG_PANEL/BG_PANEL_HEADER/BORDER_FLAT were all shifted meaningfully
# bluer and lighter to match (panel body sampled at #202832).
BG_VOID = "#04080d"
BG_PANEL = "#1a212b"
BG_PANEL_HEADER = "#141a22"
BORDER_FLAT = "#2a3540"

# Corner radius applied to every bordered box (cards, buttons, panels,
# combos, rows...) and to the main window's own outer shape (including
# the stowed pill — same constant, same radius everywhere on purpose).
# Sized to roughly match the in-game MobiGlas UI's own panel radius
# (checked against a live screenshot, 2026-09-04) — MobiGlas runs
# noticeably softer/rounder than a typical desktop app.
RADIUS = 10

# Primary accent — MobiGlas's panel borders/chrome are a pale ice-blue
# glow (sampled ~#87bee6), not teal; its "tracked/active" status text runs
# a brighter mint-teal (sampled ~#57f3d0, close to the old value here) but
# that's a secondary status color there, not the dominant chrome color —
# shifting the primary accent to ice-blue is what actually reads as
# "part of MobiGlas" rather than a green HUD sitting next to it.
ACCENT_CYAN = "#6ec8ff"
ACCENT_CYAN_DIM = "#16303f"
BORDER_CYAN = "rgba(110, 200, 255, 0.55)"

# Alert / error accent (amber)
ACCENT_AMBER = "#ffb443"
ACCENT_AMBER_DIM = "#3a2710"
BORDER_AMBER = "rgba(255, 180, 67, 0.6)"

# Text — MobiGlas body text carries a blue-white tint (sampled ~#e4e7f3),
# not the teal-white this started as; muted/dim shifted the same
# direction, into the same blue-gray family as the backgrounds above.
TEXT_PRIMARY = "#e4e9f5"
TEXT_MUTED = "#8194a6"
TEXT_DIM = "#48586a"

# Fonts (bundled, see host/assets/fonts/)
FONT_DISPLAY = "Orbitron"
FONT_MONO = "Share Tech Mono"

CARD_HEADER_HEIGHT = 34

# Drag-to-grid snapping (mimics SC's in-game cargo grid styling)
GRID_SIZE = 20
SNAP_BORDER = "#a855f7"
SNAP_FILL = "rgba(168, 85, 247, 0.18)"

# Text size: a global multiplier applied to every font-size in the app.
# Set once at startup from config (see set_font_scale in main.py) — changing
# it requires a restart, since stylesheets are built once as plain strings
# rather than re-computed live. Options shown in Settings.
FONT_SCALE = 1.15
# Shifted up one tier from the original ladder (was 0.85/1.0/1.15/1.3) —
# 1440p made the old "Normal" hard to read. Old Normal is now Small, old
# Large is now Normal, old Extra Large is now Large, and a genuinely new
# Extra Large was added on top, keeping the same +0.15 step.
FONT_SCALE_OPTIONS = {"Small": 1.0, "Normal": 1.15, "Large": 1.3, "Extra Large": 1.45}


def set_font_scale(scale: float) -> None:
    global FONT_SCALE
    FONT_SCALE = scale


def fpx(base_px: int) -> int:
    """Scale a base pixel font size by the current FONT_SCALE."""
    return max(1, round(base_px * FONT_SCALE))


def hex_to_rgba(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"
