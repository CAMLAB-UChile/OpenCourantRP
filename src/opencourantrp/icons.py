"""Line icons (Lucide, ISC licence; see resources/icons/LICENSE-lucide.txt) recoloured for the theme."""

from __future__ import annotations

from importlib import resources

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

SIZE = 18  # logical pixels


def _svg_text(name: str) -> str:
    return resources.files("opencourantrp").joinpath("resources", "icons", f"{name}.svg").read_text(encoding="utf-8")


def _pixmap(svg: str, colour: str, size: int, ratio: float) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg.replace("currentColor", colour).encode("utf-8")))
    px = int(round(size * ratio))
    img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    renderer.render(painter)
    painter.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(ratio)
    return pm


def icon(name: str, colour: str, disabled_colour: str, ratio: float = 2.0) -> QIcon:
    """An icon drawn in `colour` (and `disabled_colour` when the control is disabled)."""
    svg = _svg_text(name)
    out = QIcon()
    out.addPixmap(_pixmap(svg, colour, SIZE, ratio), QIcon.Normal)
    out.addPixmap(_pixmap(svg, disabled_colour, SIZE, ratio), QIcon.Disabled)
    return out
