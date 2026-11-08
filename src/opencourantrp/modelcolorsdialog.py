"""Window to choose the colours of the model view: background, entities (kinds of cells) and triad."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QRadioButton, QTabWidget, QVBoxLayout,
    QWidget,
)

from . import entities, modelcolors


def _swatch(on_click) -> QPushButton:
    swatch = QPushButton()
    swatch.setFixedWidth(60)
    swatch.setToolTip("Choose the color")
    swatch.clicked.connect(on_click)
    return swatch


def _paint(swatch: QPushButton, colour: str) -> None:
    swatch.setStyleSheet(f"background-color: {colour}; border: 1px solid #808080;")


def _pick(parent, colour: str) -> str | None:
    chosen = QColorDialog.getColor(QColor(colour), parent, "Choose the color")
    return chosen.name() if chosen.isValid() else None


def _tab(note: str, grid: QGridLayout, reset: QPushButton) -> QWidget:
    page = QWidget()
    lay = QVBoxLayout(page)
    if note:
        label = QLabel(note)
        label.setWordWrap(True)
        lay.addWidget(label)
    grid.setColumnStretch(2, 1)
    lay.addLayout(grid)
    row = QHBoxLayout()
    row.addWidget(reset)
    row.addStretch(1)
    lay.addLayout(row)
    lay.addStretch(1)
    return page


class ModelColorsDialog(QDialog):
    """Three tabs, one swatch per colour. Changes apply at once; each tab has its own reset button."""

    background_changed = Signal(object)  # {style, top, bottom} or None (the theme's own)
    entities_changed = Signal(dict)  # {key: '#rrggbb'}
    triad_changed = Signal(dict)  # {x, y, z, letters}
    cube_style_changed = Signal(str)  # a key of modelcolors.CUBE_STYLES

    def __init__(self, entity_colors: dict[str, str], background: dict | None, triad: dict[str, str], cube_style: str,
                 theme, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Model colors")
        self.setMinimumWidth(400)
        self._theme = theme
        self._entities = dict(entity_colors)
        self._background = background
        self._triad = dict(triad)
        self._cube_style = cube_style
        tabs = QTabWidget()
        tabs.addTab(self._background_tab(), "Background")
        tabs.addTab(self._entities_tab(), "Entities")
        tabs.addTab(self._triad_tab(), "Triad")
        tabs.addTab(self._cube_tab(), "Cube")
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(close)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addLayout(bottom)
        self._paint_all()

    # ------------------------------------------------------------------ tabs
    def _background_tab(self) -> QWidget:
        self._style = QComboBox()
        self._style.addItem("Gradient", "gradient")
        self._style.addItem("Plain color", "plain")
        self._style.currentIndexChanged.connect(self._style_changed)
        self._top_label = QLabel()
        self._top = _swatch(lambda: self._choose_background("top"))
        self._bottom_label = QLabel("Bottom color:")
        self._bottom = _swatch(lambda: self._choose_background("bottom"))
        grid = QGridLayout()
        grid.addWidget(QLabel("Style:"), 0, 0)
        grid.addWidget(self._style, 0, 1)
        grid.addWidget(self._top_label, 1, 0)
        grid.addWidget(self._top, 1, 1)
        grid.addWidget(self._bottom_label, 2, 0)
        grid.addWidget(self._bottom, 2, 1)
        reset = QPushButton("Reset to the theme color")
        reset.clicked.connect(self._reset_background)
        return _tab("The background of the view: one plain color or a gradient. Reset goes back to the color of the "
                    "current theme (light or dark). The numbers and titles of the view keep the theme text color; "
                    "change them under Fonts if the background hides them.", grid, reset)

    def _entities_tab(self) -> QWidget:
        self._entity_swatches: dict[str, QPushButton] = {}
        grid = QGridLayout()
        rows = [(key, label) for key, label, _, _ in entities.ENTITIES] + [(entities.EDGES[0], entities.EDGES[1]),
                                                                       (entities.GHOST[0], entities.GHOST[1])]
        for row, (key, label) in enumerate(rows):
            self._entity_swatches[key] = _swatch(lambda _=False, k=key: self._choose_entity(k))
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(self._entity_swatches[key], row, 1)
        reset = QPushButton("Reset colors")
        reset.clicked.connect(self._reset_entities)
        return _tab("Rigid bodies, springs and rigid walls have no result, so they are always drawn in their own color. "
                    "Shells and solids are colored by the result; with the <b>Color by entity</b> button of the tools "
                    "they are painted in the colors below as well, to tell every kind apart.", grid, reset)

    def _triad_tab(self) -> QWidget:
        self._triad_swatches: dict[str, QPushButton] = {}
        grid = QGridLayout()
        for row, (key, label) in enumerate((("x", "X arrow:"), ("y", "Y arrow:"), ("z", "Z arrow:"), ("letters", "Letters:"),
                                           ("sphere", "Origin sphere:"))):
            self._triad_swatches[key] = _swatch(lambda _=False, k=key: self._choose_triad(k))
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(self._triad_swatches[key], row, 1)
        reset = QPushButton("Reset colors")
        reset.clicked.connect(self._reset_triad)
        return _tab("The axes triad at the bottom left of the view. The letters and the sphere at its origin follow the theme "
                    "(white on the dark theme, black on the light one) until you choose a color.", grid, reset)

    def _cube_tab(self) -> QWidget:
        self._cube_radios: dict[str, QRadioButton] = {}
        grid = QGridLayout()
        for row, (key, label) in enumerate(modelcolors.CUBE_STYLES.items()):
            radio = QRadioButton(label)
            radio.toggled.connect(lambda on, k=key: self._choose_cube_style(k) if on else None)
            self._cube_radios[key] = radio
            grid.addWidget(radio, row, 0, 1, 2)
        reset = QPushButton("Reset (Vivid)")
        reset.clicked.connect(lambda: self._cube_radios["vivid"].setChecked(True))
        return _tab("The look of the view cube at the bottom right of the view. Both looks have a dark and a light version "
                    "that follow the theme (with a custom background, its brightness decides).", grid, reset)

    # ----------------------------------------------------------------- state
    def set_theme(self, theme) -> None:
        """The theme changed: what is not customised shows the new theme's colours."""
        self._theme = theme
        self._paint_all()

    def load(self, entity_colors: dict[str, str], background: dict | None, triad: dict[str, str], cube_style: str) -> None:
        """Show these colours (a preset was loaded) without announcing a change."""
        self._entities, self._background, self._triad = dict(entity_colors), background, dict(triad)
        self._cube_style = cube_style
        self._paint_all()

    def _background_now(self) -> tuple[str, str, str]:
        """(style, top, bottom) as drawn: the custom background, or the theme's."""
        if self._background is not None:
            return self._background["style"], self._background["top"], self._background["bottom"]
        t = self._theme
        return ("plain" if t.view_top == t.view_bottom else "gradient"), t.view_top, t.view_bottom

    def _paint_all(self) -> None:
        style, top, bottom = self._background_now()
        self._style.blockSignals(True)
        self._style.setCurrentIndex(self._style.findData(style))
        self._style.blockSignals(False)
        plain = style == "plain"
        self._top_label.setText("Color:" if plain else "Top color:")
        self._bottom_label.setVisible(not plain)
        self._bottom.setVisible(not plain)
        _paint(self._top, top)
        _paint(self._bottom, bottom)
        for key, swatch in self._entity_swatches.items():
            _paint(swatch, self._entities[key])
        for key, swatch in self._triad_swatches.items():
            _paint(swatch, self._triad[key] or self._theme.view_text)
        for key, radio in self._cube_radios.items():
            radio.blockSignals(True)
            radio.setChecked(key == self._cube_style)
            radio.blockSignals(False)

    # ------------------------------------------------------------ background
    def _set_background(self, style: str, top: str, bottom: str) -> None:
        self._background = {"style": style, "top": top, "bottom": bottom}
        self._paint_all()
        self.background_changed.emit(self._background)

    def _style_changed(self, *_) -> None:
        _, top, bottom = self._background_now()
        self._set_background(self._style.currentData(), top, bottom)

    def _choose_background(self, which: str) -> None:
        style, top, bottom = self._background_now()
        colour = _pick(self, top if which == "top" else bottom)
        if colour:
            self._set_background(style, colour if which == "top" else top, colour if which == "bottom" else bottom)

    def _reset_background(self) -> None:
        self._background = None
        self._paint_all()
        self.background_changed.emit(None)

    # -------------------------------------------------------------- entities
    def _choose_entity(self, key: str) -> None:
        colour = _pick(self, self._entities[key])
        if colour:
            self._entities[key] = colour
            self._paint_all()
            self.entities_changed.emit(dict(self._entities))

    def _reset_entities(self) -> None:
        self._entities = dict(entities.DEFAULTS)
        self._paint_all()
        self.entities_changed.emit(dict(self._entities))

    # ------------------------------------------------------------------ cube
    def _choose_cube_style(self, key: str) -> None:
        self._cube_style = key
        self.cube_style_changed.emit(key)

    # ----------------------------------------------------------------- triad
    def _choose_triad(self, key: str) -> None:
        colour = _pick(self, self._triad[key] or self._theme.view_text)
        if colour:
            self._triad[key] = colour
            self._paint_all()
            self.triad_changed.emit(dict(self._triad))

    def _reset_triad(self) -> None:
        self._triad = modelcolors.triad_loads({})
        self._paint_all()
        self.triad_changed.emit(dict(self._triad))
