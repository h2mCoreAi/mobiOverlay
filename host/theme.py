"""Color, font and style constants matching the approved design mockup.

Reference: docs/DECISIONS.md, "Visual design approved" entry.
Source mockup: design/Main.dc.html
"""

# Backgrounds
BG_VOID = "#06090b"
BG_PANEL = "#0d1417"
BG_PANEL_HEADER = "#101a1e"
BORDER_FLAT = "#1c2b2d"

# Primary accent (cyan)
ACCENT_CYAN = "#2de1d0"
ACCENT_CYAN_DIM = "#123632"
BORDER_CYAN = "rgba(45, 225, 208, 0.5)"

# Alert / error accent (amber)
ACCENT_AMBER = "#ffb443"
ACCENT_AMBER_DIM = "#3a2710"
BORDER_AMBER = "rgba(255, 180, 67, 0.6)"

# Text
TEXT_PRIMARY = "#dff5f2"
TEXT_MUTED = "#7fa3a1"
TEXT_DIM = "#3f5c5a"

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
