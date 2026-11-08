"""Makes the pictures of the "Screenshots" section of the manual: one 3D view per reference example (dark theme).

    python tools/gallery_shots.py [--root DIR] [--publish]

``--root`` is the folder that holds the examples with their results (default: ``reference_examples``, where only
``vessel_puncture`` and ``notch_sample`` keep ``.vtk`` files; run the others in a copy and point ``--root`` at it).
The pictures go to ``preview/doc`` (look at every one); ``--publish`` also copies them to ``docs/img`` as ``gallery_*.png``.
A throwaway settings file is used (never the registry) and the script ends with os._exit.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "preview" / "doc"
DOCS = ROOT / "docs" / "img"

import opencourantrp.app as A  # noqa: E402
from opencourantrp import entities  # noqa: E402

A.QSettings = lambda *a: QSettings(tempfile.mkdtemp() + "/t.ini", QSettings.IniFormat)  # NEVER the registry

WIDTH = 1000  # pixels; the pictures are embedded in the manual, so they are kept small

# folder, variable key, through the thickness, file (index, -1 = the last), view, hide the rigid walls, mesh edges, picture name
SHOTS = (
    ("notch_sample", "svm", "max", -1, "isometric", False, True, "notch_sample"),
    ("box_beam_under_impact", "svm", "max", -1, "isometric", True, True, "box_beam"),
    ("tensile_test", "epl", "middle", -1, "xy", False, True, "tensile_test"),
    ("sbeam_crash", "svm", "max", -1, "isometric", False, True, "sbeam_crash"),
    ("rigid_ball_impact", "V", "middle", -1, "isometric", False, True, "rigid_ball_impact"),
    ("airbag", "V", "middle", -1, "isometric", False, True, "airbag"),
    ("pendulum", "V", "middle", -1, "isometric", False, True, "pendulum"),
    ("tank_sloshing", "V", "middle", -1, "xy", False, True, "tank_sloshing"),
)


def main(root: Path, publish: bool) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    w = A.MainWindow()
    w.resize(1500, 950)
    w.show()

    def pump(seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()

    def view() -> Image.Image:
        """The 3D view only (cut out of the window grab: a widget grab does not hold the OpenGL picture)."""
        w.grab().save(str(OUT / "_tmp.png"))
        r, dpr = w.viewer.rect(), w.devicePixelRatioF()
        tl = w.viewer.mapTo(w, r.topLeft())
        return Image.open(OUT / "_tmp.png").crop((int(tl.x() * dpr), int(tl.y() * dpr), int((tl.x() + r.width()) * dpr),
                                                  int((tl.y() + r.height()) * dpr)))

    w._apply_theme("dark")
    made = []
    for folder, key, thickness, frame, camera, hide_walls, edges, name in SHOTS:
        path = root / folder
        if not path.is_dir():
            print("skipped (no folder):", folder, flush=True)
            continue
        w._set_project(str(path))
        pump(3)
        files = w.vtk_files
        w.tabs.setCurrentIndex(2)
        w.mesh_check.setChecked(edges)
        w.results_panel.select(key)
        w.results_panel.set_thickness(thickness)
        count = w.file_combo.count()
        if not count:
            print("skipped (no .vtk):", folder, flush=True)
            continue
        w.file_combo.setCurrentIndex(count - 1 if frame < 0 else min(frame, count - 1))
        for i in range(w.parts_tree.topLevelItemCount()):
            item = w.parts_tree.topLevelItem(i)
            if item.data(0, Qt.UserRole) == entities.WALL_PART:
                item.setCheckState(0, Qt.Unchecked if hide_walls else Qt.Checked)
        pump(2)
        w.viewer.reset_view(camera)
        pump(1.5)
        picture = view()
        picture.resize((WIDTH, round(picture.height * WIDTH / picture.width)), Image.LANCZOS).save(
            OUT / f"gallery_{name}.png", optimize=True)
        made.append(name)
        print("made", name, "(", len(files), "files)", flush=True)
    if publish:
        for name in made:
            Image.open(OUT / f"gallery_{name}.png").save(DOCS / f"gallery_{name}.png")
        print("published", len(made), "pictures to", DOCS, flush=True)
    os._exit(0)


if __name__ == "__main__":
    args = sys.argv[1:]
    given = Path(args[args.index("--root") + 1]) if "--root" in args else ROOT / "reference_examples"
    main(given, "--publish" in args)
