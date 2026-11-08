"""Window to customize the fonts of the colour bar, the min/max list and the probes."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QDialog, QFontComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QVBoxLayout,
)

from .fonts import ITEMS, FontSpec, default_fonts


class FontDialog(QDialog):
    """One row per item: font style (family, bold, italic), size and colour. Changes apply immediately."""

    changed = Signal(dict)  # {item key: FontSpec}

    def __init__(self, fonts: dict[str, FontSpec], theme_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fonts")
        self._fonts = dict(fonts)
        self._theme_text = theme_text  # "#rrggbb" of the colour used when an item follows the theme
        self._rows = {}

        grid = QGridLayout()
        for col, head in enumerate(("Item", "Font style", "", "", "Size", "Colour")):
            if head:
                grid.addWidget(QLabel(f"<b>{head}</b>"), 0, col)
        for row, (key, label) in enumerate(ITEMS, start=1):
            family = QFontComboBox()
            family.setMinimumWidth(190)
            bold, italic = QCheckBox("Bold"), QCheckBox("Italic")
            size = QSpinBox()
            size.setRange(6, 60)
            size.setSuffix(" px")
            theme = QCheckBox("Theme")
            theme.setToolTip("Follow the theme (black on the light view, white on the dark one)")
            swatch = QPushButton()
            swatch.setFixedWidth(46)
            swatch.setToolTip("Choose the colour")
            for col, w in enumerate((QLabel(label), family, bold, italic, size)):
                grid.addWidget(w, row, col)
            box = QHBoxLayout()
            box.addWidget(theme)
            box.addWidget(swatch)
            grid.addLayout(box, row, 5)
            self._rows[key] = (family, bold, italic, size, theme, swatch)
            for signal in (family.currentFontChanged, bold.toggled, italic.toggled, size.valueChanged, theme.toggled):
                signal.connect(lambda *_, k=key: self._edited(k))
            swatch.clicked.connect(lambda _=False, k=key: self._pick_colour(k))

        reset, close = QPushButton("Reset to defaults"), QPushButton("Close")
        reset.clicked.connect(self._reset)
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(reset)
        buttons.addStretch(1)
        buttons.addWidget(close)
        lay = QVBoxLayout(self)
        lay.addLayout(grid)
        lay.addLayout(buttons)
        self._load(self._fonts)

    # -- state <-> widgets -----------------------------------------------------
    def _load(self, fonts: dict[str, FontSpec]) -> None:
        self._fonts = dict(fonts)
        for key, (family, bold, italic, size, theme, swatch) in self._rows.items():
            spec = self._fonts[key]
            for w in (family, bold, italic, size, theme):
                w.blockSignals(True)
            family.setCurrentFont(QFont(spec.family))
            bold.setChecked(spec.bold)
            italic.setChecked(spec.italic)
            size.setValue(spec.size)
            theme.setChecked(spec.color is None)
            for w in (family, bold, italic, size, theme):
                w.blockSignals(False)
            self._paint_swatch(key)

    def _paint_swatch(self, key: str) -> None:
        *_, theme, swatch = self._rows[key]
        colour = self._fonts[key].color or self._theme_text
        swatch.setStyleSheet(f"background-color: {colour}; border: 1px solid #888;")
        swatch.setEnabled(not theme.isChecked())

    def _edited(self, key: str) -> None:
        family, bold, italic, size, theme, _ = self._rows[key]
        old = self._fonts[key]
        colour = None if theme.isChecked() else (old.color or self._theme_text)
        self._fonts[key] = replace(old, family=family.currentFont().family(), bold=bold.isChecked(),
                                   italic=italic.isChecked(), size=size.value(), color=colour)
        self._paint_swatch(key)
        self.changed.emit(dict(self._fonts))

    def _pick_colour(self, key: str) -> None:
        current = QColor(self._fonts[key].color or self._theme_text)
        colour = QColorDialog.getColor(current, self, "Font colour")
        if colour.isValid():
            self._fonts[key] = replace(self._fonts[key], color=colour.name())
            self._paint_swatch(key)
            self.changed.emit(dict(self._fonts))

    def _reset(self) -> None:
        self._load(default_fonts())
        self.changed.emit(dict(self._fonts))

    def set_theme_text(self, colour: str) -> None:
        """Keep the "follow the theme" swatches in step with the theme."""
        self._theme_text = colour
        for key in self._rows:
            self._paint_swatch(key)
