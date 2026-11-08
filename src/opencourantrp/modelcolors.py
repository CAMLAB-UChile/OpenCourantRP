"""Colours of the view that are not the result: the background and the triad (no GUI dependencies)."""

from __future__ import annotations

import json
import re

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

TRIAD_KEYS = ("x", "y", "z", "letters", "sphere")
# letters and sphere "" = follow the theme text color (white on the dark view, black on the light one)
TRIAD_DEFAULTS = {"x": "#f77347", "y": "#26b359", "z": "#1a1af2", "letters": "", "sphere": ""}
STYLES = ("gradient", "plain")
CUBE_STYLES = {"vivid": "Vivid (faces tinted with the axis colors)", "calmer": "Calmer (neutral faces)"}  # the view cube's looks


def _hex(value, default=None):
    return value if isinstance(value, str) and _HEX.match(value) else default


def background_loads(text) -> dict | None:
    """The custom background {style, top, bottom} from the settings (JSON text or a dict); None = the theme's own.

    A plain background uses ``top``. Anything unreadable gives None.
    """
    try:
        raw = json.loads(text) if isinstance(text, str) else text
    except (ValueError, TypeError):
        return None
    if not isinstance(raw, dict) or raw.get("style") not in STYLES:
        return None
    top, bottom = _hex(raw.get("top")), _hex(raw.get("bottom"))
    if top is None or bottom is None:
        return None
    return {"style": raw["style"], "top": top, "bottom": bottom}


def background_dumps(spec: dict | None) -> str:
    return json.dumps(spec)


def background_colors(spec: dict | None, theme) -> tuple[str, str]:
    """(top, bottom) colours to draw: the custom ones, or the theme's; equal when flat."""
    if spec is None:
        return theme.view_top, theme.view_bottom
    return (spec["top"], spec["top"]) if spec["style"] == "plain" else (spec["top"], spec["bottom"])


def cube_style_loads(value) -> str:
    """The saved look of the view cube; anything unknown gives the default, vivid."""
    return value if isinstance(value, str) and value in CUBE_STYLES else "vivid"


def triad_loads(text) -> dict[str, str]:
    """Triad colours {x, y, z, letters}; anything missing or invalid gets its default."""
    try:
        raw = json.loads(text) if isinstance(text, str) else text
    except (ValueError, TypeError):
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    return {k: _hex(raw.get(k), d) for k, d in TRIAD_DEFAULTS.items()}


def triad_dumps(colors: dict[str, str]) -> str:
    return json.dumps(colors)
