"""Regenerates the pictures of the manual (dark theme) into preview/doc; with --publish also copies them to docs/img.

Run it with the project venv after changing the look of the program, LOOK AT EVERY PICTURE (`preview/` is git-ignored), then
publish and rebuild the manual (`python tools/build_manual.py`). It uses a throwaway settings file (never the registry) and ends
with os._exit, so a segfault at exit is harmless. The window is 1500 x 950 and the examples are in `reference_examples/`.

Pictures: toolbar (the Tools group), overview (main window), parts_vessel_only and probes_minmax (the 3D view: the vessel with
one part hidden; the notch plate with two probes and min/max in mm and MPa), and the Units, Fonts, Model colors (4 tabs) and
Presets windows. The Run, Parts and Results tab pictures (`tab_*.png`) are not made here.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QGroupBox, QTabWidget

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "preview" / "doc"
DOCS = ROOT / "docs" / "img"
EXAMPLES = ROOT / "reference_examples"

import opencourantrp.app as A  # noqa: E402
from opencourantrp import probe  # noqa: E402
from opencourantrp.presetdialog import PresetDialog  # noqa: E402
from opencourantrp.units import Units  # noqa: E402
from opencourantrp.unitsdialog import UnitsDialog  # noqa: E402

A.QSettings = lambda *a: QSettings(tempfile.mkdtemp() + "/t.ini", QSettings.IniFormat)  # NEVER the registry


def scaled(im: Image.Image, width: int) -> Image.Image:
    return im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)


def main(publish: bool) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    w = A.MainWindow()
    w.resize(1500, 950)
    w.show()

    def pump(seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()

    def window() -> Image.Image:
        w.grab().save(str(OUT / "_tmp.png"))
        return Image.open(OUT / "_tmp.png")

    def view() -> Image.Image:
        """The 3D view only (a widget grab does not hold the OpenGL picture, so it is cut out of the window grab)."""
        r, dpr = w.viewer.rect(), w.devicePixelRatioF()
        tl = w.viewer.mapTo(w, r.topLeft())
        return window().crop((int(tl.x() * dpr), int(tl.y() * dpr), int((tl.x() + r.width()) * dpr),
                              int((tl.y() + r.height()) * dpr)))

    def dialog(d, name: str, width: int, size=None) -> None:
        d.show()
        if size:
            d.resize(*size)
        pump(0.6)
        d.grab().save(str(OUT / "_d.png"))
        scaled(Image.open(OUT / "_d.png"), width).save(OUT / f"{name}.png")

    # vessel: overview, toolbar, parts
    w._set_project(str(EXAMPLES / "vessel_puncture"))
    pump(3)
    w._apply_theme("dark")
    w.tabs.setCurrentIndex(2)
    w.results_panel.select("svm")
    w.results_panel.set_thickness("max")
    pump(2)
    full = window()
    scaled(full, 1300).save(OUT / "overview.png")
    box = w.btn_snapshot.parentWidget()
    while box is not None and not isinstance(box, QGroupBox):
        box = box.parentWidget()
    dpr, tl = w.devicePixelRatioF(), box.mapTo(w, box.rect().topLeft())
    y1 = w.slider.mapTo(w, w.slider.rect().bottomLeft()).y() + 6
    scaled(full.crop((int(tl.x() * dpr), int(tl.y() * dpr), int((tl.x() + box.width()) * dpr), int(y1 * dpr))),
           1300).save(OUT / "toolbar.png")
    w.results_panel.select("U")
    w.tabs.setCurrentIndex(1)
    tree = w.parts_tree
    tree.topLevelItem(tree.topLevelItemCount() - 1).setCheckState(0, Qt.Unchecked)  # hide the wedge
    pump(2)
    scaled(view(), 1000).save(OUT / "parts_vessel_only.png")

    # notch plate: two probes and min/max
    w._set_project(str(EXAMPLES / "notch_sample"))
    pump(3)
    w.tabs.setCurrentIndex(2)
    w.results_panel.select("svm")
    w.results_panel.set_thickness("max")
    w.viewer.reset_view("isometric")  # the camera of the previous project does not fit this one
    pump(1)
    w._units_changed(Units(length="mm", stress="MPa"))
    w.minmax_check.setChecked(True)
    pump(2)
    shown = w.viewer._shown
    centres = np.array([np.asarray(shown.point_data["_oc_pos0"])[list(shown.get_cell(i).point_ids)].mean(axis=0)
                        for i in range(shown.n_cells)])
    for target in ((11.85, -7.562, 0.0), (12.95, 5.156, 0.0)):
        i = int(np.argmin(np.linalg.norm(centres - np.array(target), axis=1)))
        w.viewer._probes.append(probe.make_probe(shown, i, shown.cell_centers().points[i]))
    w.viewer.show_result(*w.viewer._last)
    pump(2)
    scaled(view(), 1000).save(OUT / "probes_minmax.png")
    w.minmax_check.setChecked(False)
    w.viewer.clear_probes()
    w._units_changed(Units())

    # dialogs
    all_units = Units(length="mm", time="ms", displacement="mm", velocity="mm/s", force="N", stress="MPa",
                      temperature="K", mass="t", energy="mJ")
    ud = UnitsDialog(all_units, w)
    dialog(ud, "dialog_units", 420, (525, ud.sizeHint().height()))
    ud.close()
    w._show_fonts()
    dialog(w.font_dialog, "dialog_fonts", 560)
    w._show_colors()
    tabs = w.colors_dialog.findChild(QTabWidget)
    for index, name in enumerate(("background", "entities", "triad", "cube")):
        tabs.setCurrentIndex(index)
        dialog(w.colors_dialog, f"dialog_colors_{name}", 420)
    pd = PresetDialog(["my layout"], w)
    pd.names.setCurrentRow(0)
    pd.name_edit.setText("my layout")
    dialog(pd, "dialog_presets", 420, (525, 480))

    if publish:
        for name in ("toolbar", "overview", "parts_vessel_only", "probes_minmax", "dialog_units", "dialog_fonts",
                     "dialog_colors_background", "dialog_colors_entities", "dialog_colors_triad", "dialog_colors_cube",
                     "dialog_presets"):
            Image.open(OUT / f"{name}.png").save(DOCS / f"{name}.png")
        print("published to", DOCS, flush=True)
    os._exit(0)


if __name__ == "__main__":
    main("--publish" in sys.argv)
