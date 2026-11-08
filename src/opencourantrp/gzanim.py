"""Compressed animation files (/ANIM/GZIP writes ``NAMEA001.gz``, ...): list them and turn one into a ``.vtk`` (no GUI)."""

from __future__ import annotations

import gzip
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_GZ_RE = r"^{}A(\d+)\.gz$"


@dataclass(frozen=True)
class GzFile:
    step: int
    path: Path
    size: int  # bytes, compressed
    converted: bool  # the .vtk of this step already exists next to it


def vtk_path(gz: Path) -> Path:
    """``NAMEA001.gz`` -> ``NAMEA001.vtk`` (the name the rest of the program looks for)."""
    return gz.with_name(gz.stem + ".vtk")


def list_gz(folder: str | os.PathLike, name: str) -> list[GzFile]:
    """The compressed animation files ``NAMEA###.gz`` of the folder, sorted by step."""
    rx = re.compile(_GZ_RE.format(re.escape(name)), re.IGNORECASE)
    found = []
    for p in Path(folder).iterdir():
        m = rx.match(p.name)
        if m:
            found.append(GzFile(int(m.group(1)), p, p.stat().st_size, vtk_path(p).is_file()))
    return sorted(found, key=lambda f: f.step)


def pending(folder: str | os.PathLike, name: str) -> list[GzFile]:
    """The compressed files whose ``.vtk`` does not exist yet."""
    return [f for f in list_gz(folder, name) if not f.converted]


def _converter_env(solver: Path) -> dict[str, str]:
    """Environment with the solver's libraries on the PATH, as run_deck.bat sets it."""
    dirs = [solver / "extlib" / "hm_reader" / "win64", solver / "extlib" / "intelOneAPI_runtime" / "win64"]
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([str(d) for d in dirs] + [env.get("PATH", "")])
    return env


def convert(gz: Path, solver: Path) -> Path:
    """Decompress ``gz`` and convert it to ``NAMEA###.vtk`` next to it with the solver's ``anim_to_vtk``.

    The decompressed animation file is only a temporary and is removed (the point of compressing is the space).
    Raises RuntimeError with the converter's message when it fails; no partial .vtk is left.
    """
    exe = solver / "exec" / "anim_to_vtk_win64.exe"
    if not exe.is_file():
        raise RuntimeError(f"anim_to_vtk not found in {solver}")
    out = vtk_path(gz)
    tmp = gz.with_name(gz.stem + ".anim.tmp")
    try:
        with gzip.open(gz, "rb") as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        with open(out, "wb") as fh:
            done = subprocess.run([str(exe), str(tmp)], stdout=fh, stderr=subprocess.PIPE, env=_converter_env(solver),
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if done.returncode != 0 or out.stat().st_size == 0:
            raise RuntimeError(f"Could not convert {gz.name}: " + done.stderr.decode("oem", errors="replace").strip()[:300])
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        out.unlink(missing_ok=True)
        raise RuntimeError(f"Could not read {gz.name}: {exc}") from exc
    except RuntimeError:
        out.unlink(missing_ok=True)
        raise
    finally:
        tmp.unlink(missing_ok=True)
    return out
