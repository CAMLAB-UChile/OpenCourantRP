"""Exports the public part of this repository into a clone of the public repo (one clean commit per release).

    python tools/publish_public.py                 # dry run: lists what would be published
    python tools/publish_public.py --apply         # copy it into ../OpenCourantRP-public and `git add -A`
    python tools/publish_public.py --apply --commit "OpenCourantRP 1.0.0" [--push]

The tree of HEAD is exported (commit first: uncommitted changes are not published). Public: src, tests, tools,
installer, docs, README.md, LICENSE, pyproject.toml, .gitignore and, of reference_examples, only the `.rad` decks (and the `#include` file of sbeam_crash).
Never public: doc/ (Altair PDFs), preview/, CLAUDE.md, .claude/, results and run files of the examples.
"""
from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOP = {"src", "tests", "tools", "installer", "docs", "reference_examples", "README.md", "LICENSE", "pyproject.toml",
       ".gitignore"}
BIG = 10 * 2**20  # warn about files above this size


def public(path: str) -> bool:
    parts = path.split("/")
    if parts[0] not in TOP:
        return False
    return parts[0] != "reference_examples" or path.endswith((".rad", "QEPH_prop_shell.txt"))  # decks + the #include of S_BEAM


def export(dest: Path) -> list[str]:
    data = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=ROOT, check=True, capture_output=True).stdout
    kept = []
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for m in tar.getmembers():
            if m.isfile() and public(m.name):
                tar.extract(m, dest, filter="data")
                kept.append(m.name)
    return sorted(kept)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--public", type=Path, default=ROOT.parent / "OpenCourantRP-public", help="clone of the public repo")
    ap.add_argument("--apply", action="store_true", help="copy into the public clone (default: only list)")
    ap.add_argument("--commit", metavar="MESSAGE", help="commit the public clone with this message (needs --apply)")
    ap.add_argument("--push", action="store_true", help="push the commit (needs --commit)")
    a = ap.parse_args()
    if subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip():
        print("WARNING: uncommitted changes in the private repo are NOT part of the export.")
    with tempfile.TemporaryDirectory() as t:
        stage = Path(t)
        files = export(stage)
        total = sum((stage / f).stat().st_size for f in files)
        print(f"{len(files)} files, {total / 2**20:.1f} MiB")
        for f in files:
            size = (stage / f).stat().st_size
            print(f"  BIG {f}  ({size / 2**20:.1f} MiB)" if size > BIG else f"      {f}")
        if not a.apply:
            print("Dry run: nothing copied. Use --apply.")
            return
        if not (a.public / ".git").is_dir():
            sys.exit(f"{a.public} is not a git clone (git clone https://github.com/CAMLAB-UChile/OpenCourantRP.git {a.public})")
        for item in a.public.iterdir():  # empty the clone but keep .git, so deletions propagate
            if item.name != ".git":
                shutil.rmtree(item) if item.is_dir() else item.unlink()
        for f in files:
            (a.public / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stage / f, a.public / f)
    subprocess.run(["git", "add", "-A"], cwd=a.public, check=True)
    subprocess.run(["git", "status", "--short"], cwd=a.public, check=True)
    if a.commit:
        subprocess.run(["git", "commit", "-m", a.commit], cwd=a.public, check=True)
        if a.push:
            subprocess.run(["git", "push", "origin", "main"], cwd=a.public, check=True)


if __name__ == "__main__":
    main()
