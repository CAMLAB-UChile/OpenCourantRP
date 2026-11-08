"""Named presets of the colour bar / min-max / probe / model colour layout, kept in the application settings."""

from __future__ import annotations

import json

MAX_NAME = 60

# every key a preset holds (limits and the deformation scale depend on the data, so they are not part of it)
KEYS = ("colormap", "ncolors", "digits", "format", "cap", "minmax", "mark_size", "mark_color", "probe_size", "probe_color", "fonts", "entity_colors", "by_entity",
        "background", "triad")


def clean_name(name: str) -> str:
    return " ".join(name.split())[:MAX_NAME]


def loads(text: str) -> dict[str, dict]:
    """All saved presets {name: values}; unreadable settings give an empty collection."""
    try:
        raw = json.loads(text)
    except (ValueError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {clean_name(k): v for k, v in raw.items() if isinstance(v, dict) and clean_name(k)}


def dumps(presets: dict[str, dict]) -> str:
    return json.dumps(presets)


def sorted_names(presets: dict[str, dict]) -> list[str]:
    return sorted(presets, key=str.casefold)
