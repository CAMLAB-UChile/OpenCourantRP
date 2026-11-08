"""Light and dark themes (colours sampled from the OpenCourantLab light/dark screenshots)."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources


@dataclass(frozen=True)
class Theme:
    name: str
    window: str        # window / toolbar / menu background
    base: str          # list, text-edit and input background
    text: str
    muted: str         # disabled text
    border: str
    accent: str        # active tab underline, slider handle, focus
    selection: str     # selected row
    button: str
    button_hover: str
    # 3D view
    view_bottom: str   # background (bottom of the gradient)
    view_top: str      # top of the gradient (same as bottom: flat colour)
    view_text: str     # colour-bar numbers, title and axes labels (0..1 rgb is derived)


LIGHT = Theme("light", window="#e1e5ea", base="#f7f8fa", text="#1c2330", muted="#8d96a3", border="#c9d0d9",
              accent="#2f7de1", selection="#b6ceed", button="#e8ebf0", button_hover="#d9dee5",
              view_bottom="#ffffff", view_top="#ffffff", view_text="#000000")
DARK = Theme("dark", window="#14171c", base="#1a1e25", text="#dfe3ea", muted="#6b7482", border="#2a303b",
             accent="#4c9eff", selection="#284262", button="#1f242c", button_hover="#2a303b",
             view_bottom="#101725", view_top="#293954", view_text="#ffffff")
THEMES = {"light": LIGHT, "dark": DARK}


def rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def stylesheet(t: Theme) -> str:
    check = str(resources.files("opencourantrp").joinpath("resources", "check.png")).replace("\\", "/")
    return f"""
QWidget {{ background-color: {t.window}; color: {t.text}; }}
QWidget:disabled {{ color: {t.muted}; }}
QTabWidget::pane {{ border: 1px solid {t.border}; border-radius: 4px; top: -1px; }}
QTabBar::tab {{ background-color: {t.window}; border: 1px solid {t.border}; border-bottom: none; border-top-left-radius: 4px;
    border-top-right-radius: 4px; padding: 4px 14px; margin-right: 2px; color: {t.muted}; }}
QTabBar::tab:selected {{ background-color: {t.base}; color: {t.text}; }}
QTreeWidget {{ background-color: {t.base}; border: 1px solid {t.border}; border-radius: 3px; }}
QGroupBox {{ border: 1px solid {t.border}; border-radius: 4px; margin-top: 10px; padding-top: 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QAbstractItemView {{
    background-color: {t.base}; border: 1px solid {t.border}; border-radius: 3px;
    selection-background-color: {t.selection}; selection-color: {t.text}; }}
QHeaderView::section {{ background-color: {t.button}; color: {t.text}; border: 1px solid {t.border}; padding: 2px 4px; }}
QComboBox {{ padding: 2px 6px; }}
QComboBox QAbstractItemView {{ outline: 0; }}
QPushButton {{ background-color: {t.button}; border: 1px solid {t.border}; border-radius: 4px; padding: 4px 6px; }}
QPushButton:hover {{ background-color: {t.button_hover}; }}
QPushButton:pressed, QPushButton:checked {{ border: 1px solid {t.accent}; }}
QPushButton:focus {{ border: 1px solid {t.accent}; }}
QPushButton:disabled {{ border: 1px solid {t.border}; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {t.border}; border-radius: 3px;
    background-color: {t.base}; }}
QCheckBox::indicator:checked {{ background-color: {t.accent}; border: 1px solid {t.accent}; image: url({check}); }}
QCheckBox::indicator:disabled {{ background-color: {t.window}; }}
QRadioButton::indicator {{ width: 12px; height: 12px; border: 2px solid {t.muted}; border-radius: 8px;
    background-color: {t.base}; }}
QRadioButton::indicator:checked {{ border: 2px solid {t.accent};
    background-color: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 {t.accent}, stop:0.55 {t.accent},
    stop:0.6 {t.base}, stop:1 {t.base}); }}
QRadioButton::indicator:disabled {{ border: 2px solid {t.border}; background-color: {t.window}; }}
QTreeWidget::item:selected {{ background-color: {t.selection}; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QSlider::groove:horizontal {{ height: 4px; background: {t.border}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 12px; margin: -5px 0; background: {t.accent}; border-radius: 6px; }}
QProgressBar {{ border: 1px solid {t.border}; border-radius: 3px; text-align: center; background: {t.base}; }}
QProgressBar::chunk {{ background: {t.accent}; }}
QScrollBar:vertical {{ background: {t.base}; width: 12px; }}
QScrollBar:horizontal {{ background: {t.base}; height: 12px; }}
QScrollBar::handle {{ background: {t.border}; border-radius: 4px; min-height: 24px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QSplitter::handle {{ background: {t.window}; }}
QToolTip {{ background-color: {t.base}; color: {t.text}; border: 1px solid {t.border}; }}
"""
