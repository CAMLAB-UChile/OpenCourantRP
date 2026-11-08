"""Deck discovery and batch-file generation (no GUI dependencies)."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from importlib import resources
from pathlib import Path

DECK_SUFFIXES = ("_0000.rad", "_0001.rad")


class DeckError(Exception):
    """The project folder does not hold a valid pair of decks."""


def is_combined_deck(path: str | os.PathLike) -> bool:
    """True for a single deck that holds the engine block first and the starter from ``/BEGIN`` on."""
    try:
        with open(path, encoding="latin-1") as fh:
            lines = [line for line in fh if line.upper().startswith(("/BEGIN", "/RUN/"))]
    except OSError:
        return False
    return any(line.upper().startswith("/RUN/") for line in lines) and any(line.upper().startswith("/BEGIN") for line in lines)


def find_deck_name(folder: str | os.PathLike) -> str:
    """Return the common deck NAME of ``NAME_0000.rad`` / ``NAME_0001.rad``, or the NAME of a single combined deck
    ``NAME_0000.rad`` (engine block, then the starter from ``/BEGIN``) when there is no ``_0001.rad`` at all.

    Raises DeckError unless exactly one NAME has both decks (or is a combined one).
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise DeckError(f"Project folder does not exist: {folder}")
    starters = {p.name[: -len(DECK_SUFFIXES[0])] for p in folder.glob("*_0000.rad")}
    engines = {p.name[: -len(DECK_SUFFIXES[1])] for p in folder.glob("*_0001.rad")}
    if len(starters) == 1 and not engines and is_combined_deck(folder / f"{next(iter(starters))}{DECK_SUFFIXES[0]}"):
        return next(iter(starters))
    if not starters or not engines:
        raise DeckError("Need both a *_0000.rad and a *_0001.rad deck in the project folder "
                        "(or one *_0000.rad with the engine block first and the starter from /BEGIN).")
    common = starters & engines
    if not common:
        raise DeckError(
            "The two decks must share the same name: found "
            f"{', '.join(sorted(s + '_0000.rad' for s in starters))} and "
            f"{', '.join(sorted(e + '_0001.rad' for e in engines))}."
        )
    if len(common) > 1 or starters != engines:
        raise DeckError(
            "Ambiguous decks in the project folder; keep exactly one *_0000.rad/*_0001.rad pair "
            f"(found names: {', '.join(sorted(starters | engines))})."
        )
    return common.pop()


def _deck_lines(path: Path, depth: int = 0) -> Iterator[str]:
    """The lines of a deck without the comments; `#include FILE` lines are replaced by the lines of FILE (looked up
    next to the including file). A file that cannot be read is skipped."""
    try:
        with open(path, encoding="latin-1") as fh:
            for line in fh:
                found = re.match(r"#include\s+(.+?)\s*$", line, re.IGNORECASE)
                if found and depth < 8:
                    yield from _deck_lines(path.parent / found.group(1).strip("\"'"), depth + 1)
                elif not line.startswith("#"):
                    yield line
    except OSError:
        pass


def read_part_info(folder: str | os.PathLike, name: str) -> tuple[dict[int, str], dict[int, int]]:
    """({part id: title}, {part id: integration points through the thickness}) from the starter deck.

    The second dictionary only holds the parts whose property is a shell (/PROP/SHELL, /PROP/TYPE1) with a
    readable N. Both are empty when the deck cannot be read.
    """
    titles: dict[int, str] = {}
    prop_of: dict[int, int] = {}
    points: dict[int, int] = {}  # property id -> N
    lines = _deck_lines(Path(folder) / f"{name}{DECK_SUFFIXES[0]}")
    for line in lines:
        found = re.match(r"/PART/(\d+)", line)
        if found:
            pid = int(found.group(1))
            titles[pid] = next(lines, "").strip()
            try:
                prop_of[pid] = int(next(lines, "")[:10])
            except ValueError:
                pass
            continue
        found = re.match(r"/PROP/(?:SHELL|TYPE1)/(\d+)", line)
        if found:
            next(lines, "")  # title
            next(lines, "")  # Ishell, Ismstr, Ish3n, Idrill
            next(lines, "")  # hm, hf, hr, dm, dn
            try:
                points[int(found.group(1))] = int(next(lines, "")[:10])
            except ValueError:
                pass
    return titles, {pid: points[prop] for pid, prop in prop_of.items() if prop in points}


def read_part_names(folder: str | os.PathLike, name: str) -> dict[int, str]:
    """{part id: title} from the /PART blocks of the starter deck (empty when it cannot be read)."""
    return read_part_info(folder, name)[0]


def check_solver(solver: str | os.PathLike) -> None:
    """Raise DeckError if ``solver`` is not an OpenCourant root folder."""
    starter = Path(solver) / "exec" / "starter_win64.exe"
    if not starter.is_file():
        raise DeckError(f"OpenCourant not found in {solver} (missing exec\\starter_win64.exe).")


def run_first_text(name: str, solver: str | os.PathLike, nproc: int) -> str:
    return (
        "@echo off\n"
        f'call "%~dp0run_deck.bat" {name} "{os.fspath(solver)}" {int(nproc)}\n'
        "pause\n"
    )


def run_deck_text() -> str:
    return resources.files("opencourantrp").joinpath("resources/run_deck.bat").read_text(encoding="ascii")


def _write_crlf(path: Path, text: str) -> None:
    with open(path, "w", encoding="ascii", newline="") as fh:
        fh.write(text.replace("\r\n", "\n").replace("\n", "\r\n"))


def write_batch_files(folder: str | os.PathLike, name: str, solver: str | os.PathLike, nproc: int) -> Path:
    """Write run_first.bat, run_deck.bat and its helper script into ``folder``; return run_first.bat."""
    folder = Path(folder)
    first = folder / "run_first.bat"
    _write_crlf(first, run_first_text(name, solver, nproc))
    _write_crlf(folder / "run_deck.bat", run_deck_text())
    script = resources.files("opencourantrp").joinpath("resources/prepare_engine.ps1").read_text(encoding="ascii")
    _write_crlf(folder / "rp_prepare_engine.ps1", script)
    return first


_ANIM_RE = r"^{}A(\d+)\.vtk$"


def list_vtk(folder: str | os.PathLike, name: str) -> list[Path]:
    """Converted animation files ``NAMEA###.vtk`` sorted by step number."""
    rx = re.compile(_ANIM_RE.format(re.escape(name)), re.IGNORECASE)
    found = []
    for p in Path(folder).iterdir():
        m = rx.match(p.name)
        if m:
            found.append((int(m.group(1)), p))
    return [p for _, p in sorted(found)]
