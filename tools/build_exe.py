"""Build dist/OpenCourantRP.exe with the solver embedded.

If solver/ is missing it is downloaded from the official OpenCourant release first.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "solver" / "exec" / "starter_win64.exe").is_file():
    print("solver/ not found: downloading the official OpenCourant release...")
    subprocess.run([sys.executable, str(ROOT / "tools" / "fetch_solver.py")], check=True)

subprocess.run(
    [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", "OpenCourantRP",
        "--icon", str(ROOT / "src" / "opencourantrp" / "resources" / "icon.ico"),
        "--paths", str(ROOT / "src"),
        "--add-data", f"{ROOT / 'solver'};solver",
        "--add-data", f"{ROOT / 'src' / 'opencourantrp' / 'resources'};opencourantrp/resources",
        "--collect-all", "pyvista", "--collect-all", "pyvistaqt", "--collect-submodules", "vtkmodules",
        "--collect-all", "imageio", "--collect-all", "imageio_ffmpeg", "--collect-all", "cmcrameri",
        "--hidden-import", "vtkmodules.all",
        "--exclude-module", "tkinter",
        str(ROOT / "tools" / "launcher.py"),
    ],
    cwd=ROOT,
    check=True,
)
print("Built", ROOT / "dist" / "OpenCourantRP" / "OpenCourantRP.exe")
