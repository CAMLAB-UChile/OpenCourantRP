"""Populate ./solver with the OpenCourant files the app needs (the folder is git-ignored).

    python tools/fetch_solver.py --from C:/path/to/OpenCourant   # copy from a local solver folder
    python tools/fetch_solver.py                                   # download the pinned official release
    python tools/fetch_solver.py --tag latest-YYYYMMDD             # another release (or "latest")

Only the double-precision SMP executables, converters and runtime libraries are kept; the
single-precision, Intel MPI, GUI and H3D (Siemens) parts are skipped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# The release the app is built and tested against (its executables are byte-identical to the ones used for 1.0.0).
PINNED_TAG = "latest-20261011"
API = "https://api.github.com/repos/OpenCourant/OpenCourant/releases/"
ASSET = "OpenCourant_win64.zip"
DEST = Path(__file__).resolve().parents[1] / "solver"

KEEP_EXEC = ["starter_win64.exe", "engine_win64.exe", "anim_to_vtk_win64.exe", "th_to_csv_win64.exe"]
KEEP_DIRS = [
    "extlib/hm_reader/win64",
    "extlib/intelOneAPI_runtime/win64",
    "hm_cfg_files",
    "licenses",
]
KEEP_FILES = ["COPYRIGHT.md"]
# Siemens H3D library: RP ignores /H3D cards, and its licence limits use to OpenRadioss, so it is not redistributed.


def find_root(folder: Path) -> Path:
    for c in [folder, *folder.iterdir()]:
        if (c / "exec" / "starter_win64.exe").is_file():
            return c
    raise SystemExit(f"No exec/starter_win64.exe found in {folder}")


def trim_copy(src: Path, dest: Path) -> None:
    shutil.rmtree(dest, ignore_errors=True)
    (dest / "exec").mkdir(parents=True)
    for name in KEEP_EXEC:
        shutil.copy2(src / "exec" / name, dest / "exec" / name)
    for d in KEEP_DIRS:
        if (src / d).is_dir():
            shutil.copytree(src / d, dest / d)
    for f in KEEP_FILES:
        if (src / f).is_file():
            shutil.copy2(src / f, dest / f)
    (dest / "licenses" / "h3d_license.txt").unlink(missing_ok=True)


def download(tmp: Path, tag: str = PINNED_TAG) -> tuple[Path, str]:
    hdr = {"User-Agent": "OpenCourantRP", "Accept": "application/vnd.github+json"}
    with urllib.request.urlopen(urllib.request.Request(API + ("latest" if tag == "latest" else "tags/" + tag), headers=hdr), timeout=30) as r:
        rel = json.load(r)
    asset = next(a for a in rel["assets"] if a["name"] == ASSET)
    want = (asset.get("digest") or "").removeprefix("sha256:").lower()
    zpath, sha = tmp / ASSET, hashlib.sha256()
    print(f"Downloading {rel['tag_name']} ({asset['size'] / 2**20:.0f} MiB)...")
    with urllib.request.urlopen(urllib.request.Request(asset["browser_download_url"], headers=hdr)) as r, open(zpath, "wb") as out:
        while chunk := r.read(1 << 20):
            out.write(chunk)
            sha.update(chunk)
    if want and sha.hexdigest() != want:
        raise SystemExit("Checksum mismatch: download is corrupt.")
    print("Checksum OK. Extracting...")
    with zipfile.ZipFile(zpath) as z:
        z.extractall(tmp / "x")
    return tmp / "x", rel["tag_name"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", type=Path, help="local OpenCourant folder (default: download)")
    ap.add_argument("--tag", default=PINNED_TAG, help=f"release to download (default {PINNED_TAG})")
    args = ap.parse_args()
    if args.src:
        trim_copy(find_root(args.src), DEST)
        version = f"local copy of {args.src}"
    else:
        with tempfile.TemporaryDirectory() as t:
            extracted, version = download(Path(t), args.tag)
            trim_copy(find_root(extracted), DEST)
    (DEST / "VERSION").write_text(version)
    size = sum(f.stat().st_size for f in DEST.rglob("*") if f.is_file())
    print(f"Solver ready in {DEST} ({size / 2**20:.0f} MiB)")


if __name__ == "__main__":
    main()
