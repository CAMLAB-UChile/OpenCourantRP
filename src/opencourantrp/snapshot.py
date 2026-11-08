"""Saving the 3D view as a picture (png, jpg, tiff) or as a one-page pdf."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

# (label in the file dialog, extension, Pillow format name)
FORMATS = (
    ("PNG image", ".png", "PNG"),
    ("JPEG image", ".jpg", "JPEG"),
    ("TIFF image", ".tiff", "TIFF"),
    ("PDF document", ".pdf", "PDF"),
)
FILTERS = ";;".join(f"{label} (*{ext})" for label, ext, _ in FORMATS)
ALIASES = {".jpeg": ".jpg", ".tif": ".tiff"}  # accepted when the user types them
DPI = 150  # resolution the pdf page size is based on: a picture 1x the screen is 150 dpi
QUALITY_RANGE = (1, 8)  # times larger than the view on screen
DEFAULT_QUALITY = {".pdf": 4}  # the other types default to 1 (as on screen)


def extension_for(filter_text: str) -> str:
    """Extension (with the dot) of the file-dialog filter the user selected."""
    for label, ext, _ in FORMATS:
        if filter_text.startswith(label):
            return ext
    return FORMATS[0][1]


def with_extension(path: str, ext: str) -> str:
    """`path` ending in a supported extension; the chosen filter's one is added when it has none."""
    suffix = Path(path).suffix.lower()
    if suffix in {e for _, e, _ in FORMATS} | set(ALIASES):
        return path
    return path + ext


def default_quality(ext: str) -> int:
    """Default quality (times the on-screen size) for a picture type such as ".pdf"."""
    return DEFAULT_QUALITY.get(ALIASES.get(ext.lower(), ext.lower()), 1)


def save_snapshot(path: str | Path, image: np.ndarray, scale: int = 1) -> Path:
    """Write the RGB(A) array `image` to `path`; the format follows the extension.

    `scale` says how much larger than on screen the picture is; the pdf page keeps the on-screen size.
    """
    path = Path(path)
    ext = ALIASES.get(path.suffix.lower(), path.suffix.lower())
    fmt = {e: f for _, e, f in FORMATS}.get(ext)
    if fmt is None:
        raise ValueError(f"unsupported picture type '{path.suffix}' (use png, jpg, tiff or pdf)")
    picture = Image.fromarray(np.asarray(image)[..., :3].astype(np.uint8))  # drop any alpha: jpg and pdf have none
    options = {"resolution": DPI * scale} if fmt == "PDF" else {"quality": 95} if fmt == "JPEG" else {}
    picture.save(path, format=fmt, **options)
    return path
