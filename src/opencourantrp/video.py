"""Video / animated-GIF writer for the result animation."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

import numpy as np


class VideoCancelled(Exception):
    pass


def write_video(path: str | Path, frames: Iterable[np.ndarray], fps: float,
                cancelled: Callable[[], bool] = lambda: False) -> int:
    """Write RGB frames (HxWx3 uint8) to ``path`` (.mp4 or .gif); return the number of frames."""
    import imageio.v2 as imageio

    path = Path(path)
    if path.suffix.lower() == ".gif":
        writer = imageio.get_writer(str(path), mode="I", duration=1000.0 / fps, loop=0)
    else:
        writer = imageio.get_writer(str(path), fps=fps, codec="libx264", quality=8,
                                    pixelformat="yuv420p", macro_block_size=2)
    n = 0
    try:
        for frame in frames:
            if cancelled():
                raise VideoCancelled()
            h, w = frame.shape[:2]
            writer.append_data(np.ascontiguousarray(frame[: h - h % 2, : w - w % 2, :3]))  # even size for H.264
            n += 1
    except BaseException:
        writer.close()
        path.unlink(missing_ok=True)
        raise
    writer.close()
    return n
