"""Build dist/OpenCourantRP-Setup-<version>.exe (Inno Setup installer). Builds the app folder first."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from opencourantrp import __version__  # noqa: E402

CANDIDATES = [
    os.environ.get("ISCC", ""),
    str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"),
    str(Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe"),
    str(Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe"),
]
iscc = next((c for c in CANDIDATES if c and Path(c).is_file()), None)
if iscc is None:
    raise SystemExit("Inno Setup 6 not found. Install it (winget install JRSoftware.InnoSetup) or set ISCC.")

if "--skip-app" not in sys.argv:
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_exe.py")], check=True)

subprocess.run([iscc, f"/DAppVersion={__version__}", str(ROOT / "installer" / "OpenCourantRP.iss")], check=True)
print("Built", ROOT / "dist" / f"OpenCourantRP-Setup-{__version__}.exe")
