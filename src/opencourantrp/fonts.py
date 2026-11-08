"""User-chosen fonts of the texts drawn in the 3D view (colour bar, min/max list, probe boxes)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from functools import lru_cache

BUILTIN = ("Arial", "Courier", "Times")  # the families VTK draws without a font file
VTK_FONT_FILE = 4  # vtkTextProperty font family "use SetFontFile"

# (key, label shown in the dialog)
ITEMS = (
    ("ticks", "Colour bar tick labels"),
    ("title", "Colour bar title"),
    ("minmax", "Min/max values"),
    ("probes", "Probes"),
    ("ruler", "Ruler"),
    ("info", "Model information"),
)


@dataclass(frozen=True)
class FontSpec:
    family: str = "Arial"
    bold: bool = False
    italic: bool = False
    size: int = 14
    color: str | None = None  # "#rrggbb"; None follows the theme (black on the light view, white on the dark one)


def default_fonts() -> dict[str, FontSpec]:
    """What the program used before fonts became configurable."""
    return {
        "ticks": FontSpec(size=14),
        "title": FontSpec(size=18),
        "minmax": FontSpec(size=14),
        "probes": FontSpec(size=11),
        "ruler": FontSpec(size=12),
        "info": FontSpec(size=14),
    }


def dumps(fonts: dict[str, FontSpec]) -> str:
    return json.dumps({k: asdict(v) for k, v in fonts.items()})


def loads(text: str) -> dict[str, FontSpec]:
    """Saved fonts; anything missing or malformed falls back to the default for that item."""
    fonts = default_fonts()
    try:
        raw = json.loads(text)
        for key in fonts:
            fonts[key] = FontSpec(**{**asdict(fonts[key]), **raw.get(key, {})})
    except (ValueError, TypeError, AttributeError):
        return default_fonts()
    return fonts


@lru_cache(maxsize=None)
def font_file(family: str, bold: bool, italic: bool) -> str | None:
    """Path of the installed font file for `family` (None when it cannot be found)."""
    try:
        from matplotlib import font_manager

        prop = font_manager.FontProperties(family=family, weight="bold" if bold else "normal",
                                           style="italic" if italic else "normal")
        return font_manager.findfont(prop, fallback_to_default=False)
    except Exception:
        return None


def bracket_font_file(spec: FontSpec) -> str | None:
    """Font file to draw square brackets with, or None when the font itself has them.

    The Arial that comes with VTK has no [ ] (it shows ( ) instead), so for it the installed Arial is used for
    the brackets; the other built-in fonts and every font file are used as they are.
    """
    if spec.family != "Arial":
        return None
    return font_file("Arial", spec.bold, spec.italic) or font_file("DejaVu Sans", spec.bold, spec.italic)


def unicode_font_file(spec: FontSpec) -> str | None:
    """Font file to draw Greek letters with (the fonts that come with VTK have none), or None to keep the font."""
    if spec.family not in BUILTIN:
        return None  # a font file the user chose is used as it is
    return font_file("Arial", spec.bold, spec.italic) or font_file("DejaVu Sans", spec.bold, spec.italic)


def apply_font(text_property, spec: FontSpec, default_color: tuple[float, float, float], scale: int = 1) -> None:
    """Set family, style, size (times `scale`, for large pictures) and colour of a vtkTextProperty."""
    from .theme import rgb

    text_property.SetFontSize(int(spec.size * scale))
    text_property.SetColor(*(rgb(spec.color) if spec.color else default_color))
    path = None if spec.family in BUILTIN else font_file(spec.family, spec.bold, spec.italic)
    if path:
        text_property.SetFontFamily(VTK_FONT_FILE)
        text_property.SetFontFile(path)
        text_property.SetBold(False)  # the file is already the bold / italic variant
        text_property.SetItalic(False)
    else:
        text_property.SetFontFamilyAsString(spec.family if spec.family in BUILTIN else "Arial")
        text_property.SetBold(spec.bold)
        text_property.SetItalic(spec.italic)
