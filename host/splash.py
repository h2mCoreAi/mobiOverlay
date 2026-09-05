"""Startup splash screen shown while mobiOverlay loads.

Some module top-level imports are genuinely slow (Logistics Hub's
`import easyocr` pulls in PyTorch — measured ~2.8s on its own, see the
startup-delay investigation in docs/DECISIONS.md) and that happens before
any window exists to show progress in. This gives the user something to
look at instead of a frozen/absent window during that window, styled like
the rest of the HUD (void background, cyan border, mobiOverlay wordmark).
"""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSplashScreen

from host import theme

WIDTH = 320
HEIGHT = 150


def _draw_two_tone(painter: QPainter, font: QFont, left_text: str, right_text: str, y: float, h: float):
    """Draws `left_text` in TEXT_PRIMARY (white) immediately followed by
    `right_text` in ACCENT_CYAN (blue), as one horizontally centered line —
    shared by the wordmark and the byline below it."""
    metrics = QFontMetrics(font)
    left_width = metrics.horizontalAdvance(left_text)
    right_width = metrics.horizontalAdvance(right_text)
    start_x = (WIDTH - (left_width + right_width)) / 2

    painter.setFont(font)
    painter.setPen(QColor(theme.TEXT_PRIMARY))
    painter.drawText(
        QRectF(start_x, y, left_width + 2, h),
        Qt.AlignLeft | Qt.AlignVCenter, left_text,
    )
    painter.setPen(QColor(theme.ACCENT_CYAN))
    painter.drawText(
        QRectF(start_x + left_width, y, right_width + 4, h),
        Qt.AlignLeft | Qt.AlignVCenter, right_text,
    )


def _build_pixmap() -> QPixmap:
    pixmap = QPixmap(WIDTH, HEIGHT)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    rect = QRectF(0.5, 0.5, WIDTH - 1, HEIGHT - 1)
    path = QPainterPath()
    path.addRoundedRect(rect, theme.RADIUS, theme.RADIUS)
    painter.fillPath(path, QColor(theme.BG_VOID))
    painter.setPen(QPen(QColor(theme.ACCENT_CYAN), 1))
    painter.drawPath(path)

    # Two-tone "mobiOverlay" wordmark: mobi in white/TEXT_PRIMARY, Overlay
    # in the blue accent — same split used everywhere else (see
    # host/main_window.py's _TitleBar and every module's display_name).
    _draw_two_tone(
        painter, QFont(theme.FONT_DISPLAY, 18, QFont.Weight.Bold),
        "mobi", "Overlay", y=34, h=34,
    )
    # "by Kestryl" byline, centered below the wordmark: "by " in white,
    # "Kestryl" in the same blue accent — mirrors _TitleBar's byline but
    # centered on its own line rather than trailing inline.
    _draw_two_tone(
        painter, QFont(theme.FONT_DISPLAY, 10, QFont.Weight.DemiBold),
        "by ", "Kestryl", y=70, h=22,
    )

    painter.end()
    return pixmap


def show_splash() -> QSplashScreen:
    splash = QSplashScreen(_build_pixmap())
    splash.setAttribute(Qt.WA_TranslucentBackground)
    splash.show()
    set_status(splash, "Starting up...")
    return splash


def set_status(splash: QSplashScreen, text: str):
    splash.showMessage(
        text, int(Qt.AlignHCenter | Qt.AlignBottom), QColor(theme.TEXT_MUTED)
    )
    # Force an immediate repaint — the caller is about to block the event
    # loop with a slow synchronous call (module import, API fetch), so
    # there won't be a natural repaint opportunity otherwise.
    splash.repaint()
