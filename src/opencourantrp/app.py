"""OpenCourantRP main window."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib import resources
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QProcess, QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QDoubleValidator, QFont, QIcon, QPainter, QPalette, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressDialog, QPushButton, QSlider,
    QSpinBox, QSplitter, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__, about, entities, fonts, gzanim, icons, modelcolors, presets, project, snapshot, solver, units
from .fontdialog import FontDialog
from .gzdialog import ConvertDialog, ask_mode, choose_files
from .presetdialog import PresetDialog
from .unitsdialog import UnitsDialog
from .resultspanel import KEY_ROLE, ResultsPanel
from .modelcolorsdialog import ModelColorsDialog
from .snapshotdialog import SnapshotDialog
from .theme import THEMES, stylesheet
from .video import VideoCancelled, write_video
from .viewer import (
    COLORMAPS, DEFAULT_COLORMAP, DEFAULT_MARK_COLOR, DEFAULT_PROBE_COLOR, MARK_COLORS, DEFAULT_DIGITS, MAX_COLORS, MAX_DIGITS, MAX_MARK_SIZE, MIN_COLORS, MIN_DIGITS, MIN_MARK_SIZE,
    NUMBER_FORMATS, OLD_FORMAT_NAMES,
    PROBE_SIZE, ZOOM_STEP, ColorOptions, ResultViewer, read_result, undeformed_points,
)


SECTION_STEPS = 1000  # positions of the section-plane slider


def resource(name: str) -> str:
    return str(resources.files("opencourantrp").joinpath("resources", name))


class ChoiceSpin(QSpinBox):
    """A spin box that steps through a few words instead of numbers (value = index of the word, text() = the word)."""

    def __init__(self, words):
        super().__init__()
        self._words = tuple(words)
        self.setRange(0, len(self._words) - 1)
        self.setWrapping(True)
        self.lineEdit().setReadOnly(True)

    def textFromValue(self, value: int) -> str:
        return self._words[value]


class Separator(QWidget):
    """Vertical bar between groups of controls, always the same number of device pixels wide."""

    PIXELS = 2
    color = QColor("#8d96a3")  # set from the theme

    def __init__(self):
        super().__init__()
        self.setFixedSize(6, 22)

    def paintEvent(self, _):
        p = QPainter(self)
        dpr = self.devicePixelRatioF()
        full = round(self.width() * dpr)  # width in device pixels
        bar = QPixmap(self.PIXELS, round(self.height() * dpr))  # a pixmap is drawn pixel for pixel, whatever the scaling
        bar.setDevicePixelRatio(dpr)
        bar.fill(self.color)
        p.drawPixmap(QPointF(((full - self.PIXELS) // 2) / dpr, 0), bar)
        p.end()


class MainWindow(QMainWindow):
    LOG_NAMES = ("starter", "engine", "convert")

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"OpenCourantRP {__version__}")
        self.resize(1500, 900)
        self.settings = QSettings("OpenCourantRP", "OpenCourantRP")
        self.deck_name = None
        self.vtk_files: list[Path] = []
        self._gz_asked = False  # the All / Some / Cancel question was shown for this folder
        self.proc = None
        self._log_offsets: dict[Path, int] = {}
        self._mesh = None
        self._part_ids: list[int] = []
        self._part_nip: dict[int, int] = {}
        self._mesh_cache = {}
        self.font_dialog = None
        self.colors_dialog = None
        self.entity_colors = entities.loads(self.settings.value("entity_colors", ""))
        self.by_entity = self.settings.value("by_entity", False, type=bool)
        self.background = modelcolors.background_loads(self.settings.value("background", ""))
        self.triad = modelcolors.triad_loads(self.settings.value("triad_colors", ""))
        self.cube_style = modelcolors.cube_style_loads(self.settings.value("cube_style", "vivid"))
        self.preset_dialog = None
        self.units_dialog = None
        self.units = units.loads(self.settings.value("units", ""))
        self.fonts = fonts.loads(self.settings.value("fonts", ""))
        self._pic_targets: list[tuple[QLabel, str]] = []  # (picture label, icon name), recoloured on a theme change
        self._icon_targets: list[tuple[QWidget, str]] = []  # (widget, icon name), recoloured on a theme change
        self.theme_name = self.settings.value("theme", "light")
        if self.theme_name not in THEMES:
            self.theme_name = "light"
        self.setWindowIcon(QIcon(resource("icon.png")))

        self._build_ui()
        self.play_timer = QTimer(self)
        self.play_timer.setSingleShot(True)
        self.play_timer.timeout.connect(self._advance)
        self._apply_theme(self.theme_name)
        self.log_timer = QTimer(self)
        self.log_timer.setInterval(300)
        self.log_timer.timeout.connect(self._tail_logs)

        last = self.settings.value("project", "")
        if last and Path(last).is_dir():
            self._set_project(last)
        self._refresh_solver_status()

    # ------------------------------------------------------------------ UI
    def _icon(self, widget, name: str):
        """Give `widget` the line icon `name` (drawn in the colours of the current theme)."""
        self._icon_targets.append((widget, name))
        return widget

    def _icon_label(self, icon_name: str, text: str) -> QWidget:
        """A label with a small line icon in front of its text."""
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        pic = QLabel()
        self._pic_targets.append((pic, icon_name))
        lay.addWidget(pic)
        lay.addWidget(QLabel(text))
        return box

    def _refresh_icons(self):
        t = THEMES[self.theme_name]
        for widget, name in self._icon_targets:
            widget.setIcon(icons.icon(name, t.text, t.muted))
        for pic, name in self._pic_targets:
            pic.setPixmap(icons.icon(name, t.text, t.muted).pixmap(16, 16))
        self._update_play_icon()
        self.btn_theme.setIcon(icons.icon("sun" if self.theme_name == "dark" else "moon", t.text, t.muted))

    def _update_play_icon(self):
        t = THEMES[self.theme_name]
        self.btn_play.setIcon(icons.icon("pause" if self.btn_play.text() == "Pause" else "play", t.text, t.muted))

    def _build_ui(self):
        setup = QGroupBox("1. Setup")
        form = QFormLayout(setup)
        self.project_edit = QLineEdit()
        self.project_edit.setReadOnly(True)
        btn_project = self._icon(QPushButton("Select project folder..."), "folder-open")
        btn_project.clicked.connect(self._choose_project)
        row = QHBoxLayout()
        row.addWidget(self.project_edit)
        row.addWidget(btn_project)
        form.addRow("Project:", row)
        self.deck_label = QLabel("-")
        form.addRow("Deck name:", self.deck_label)

        self.solver_label = QLabel()
        form.addRow("Solver:", self.solver_label)

        self.nproc = QComboBox()
        ncpu = os.cpu_count() or 1
        self.nproc.addItems([str(i) for i in range(1, ncpu + 1)])
        saved = int(self.settings.value("nproc", ncpu))
        self.nproc.setCurrentText(str(min(max(saved, 1), ncpu)))
        form.addRow("Processors:", self.nproc)

        run = QWidget()  # the "Run" tab
        v = QVBoxLayout(run)
        row = QHBoxLayout()
        self.btn_run = self._icon(QPushButton("Run"), "play")
        self.btn_run.clicked.connect(self._run)
        self.btn_stop = self._icon(QPushButton("Stop"), "square")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)
        self.btn_gz = self._icon(QPushButton("Compressed files..."), "archive")
        self.btn_gz.setToolTip("Decompress and convert the animation files written with /ANIM/GZIP (NAMEA###.gz) that are not .vtk yet")
        self.btn_gz.setEnabled(False)
        self.btn_gz.clicked.connect(self._ask_gzip)
        row.addWidget(self.btn_run)
        row.addWidget(self.btn_stop)
        row.addWidget(self.btn_gz)
        v.addLayout(row)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(50000)
        self.log.setFont(QFont("Consolas", 9))
        self.log.setLineWrapMode(QPlainTextEdit.NoWrap)
        v.addWidget(self.log)

        left = QWidget()
        lv = QVBoxLayout(left)
        self.parts_tree = QTreeWidget()  # the "Parts" tab: a check box per part, unchecked = hidden
        self.parts_tree.setHeaderLabel("Parts")
        self.parts_tree.setRootIsDecorated(False)
        self.parts_tree.setToolTip("Uncheck a part to hide it; the colour limits then follow the parts that are shown")
        self.parts_tree.itemChanged.connect(self._parts_changed)
        self.tabs = QTabWidget()
        self.tabs.addTab(run, "Run")
        self.tabs.addTab(self.parts_tree, "Parts")
        self.smooth_check = self._icon(QCheckBox("Smoothed"), "waves")
        self.smooth_check.setToolTip("Extrapolate element results (stresses, strains, plastic strain) to the nodes")
        self.results_panel = ResultsPanel(self.smooth_check)  # the "Results" tab: what is plotted
        self.results_panel.select(self.settings.value("variable", "U"))
        self.results_panel.set_thickness(self.settings.value("thickness", "middle"))
        self.results_panel.set_axes(self.settings.value("axes", "global"))
        self.tabs.addTab(self.results_panel, "Results")
        self.results_panel.gz_button.clicked.connect(self._ask_gzip)
        self.tabs.currentChanged.connect(lambda *_: self._maybe_ask_gzip())
        lv.addWidget(setup)
        lv.addWidget(self.tabs, 1)

        res = QGroupBox("Tools")
        rv = QVBoxLayout(res)
        bar = QHBoxLayout()
        self.file_combo = QComboBox()
        self.file_combo.setMinimumWidth(170)
        self.mesh_check = self._icon(QPushButton("Mesh"), "grid-3x3")
        self.mesh_check.setCheckable(True)
        self.mesh_check.setChecked(True)
        self.mesh_check.setToolTip("Show or hide the element edges")
        btn_refresh = self._icon(QPushButton("Refresh files"), "refresh-cw")
        rv.addLayout(bar)

        view_widgets = [QLabel("View:")]
        for label, kind, icon_name in (("Isometric", "isometric", "box"), ("XY", "xy", "view-xy"),
                                       ("XZ", "xz", "view-xz"), ("YZ", "yz", "view-yz")):
            b = self._icon(QPushButton(label), icon_name)
            b.clicked.connect(lambda _=False, k=kind: self.viewer.reset_view(k))
            view_widgets.append(b)
        self.btn_play = QPushButton("Play")  # icon follows the text, see _update_play_icon
        self.btn_play.clicked.connect(self._toggle_play)
        self.speed = QSpinBox()
        self.speed.setRange(1, 30)
        self.speed.setValue(int(self.settings.value("speed", 10)))
        self.speed.setSuffix(" steps/s")
        self.btn_snapshot = self._icon(QPushButton("Snapshot..."), "camera")
        self.btn_snapshot.setToolTip("Save the model view as png, jpg, tiff or pdf")
        self.btn_probes = self._icon(QPushButton("Clear probes"), "eraser")
        self.btn_probes.setToolTip("Right-click the model to probe a value; right-click on empty space also clears the probes")
        self.probe_size = QSpinBox()
        self.probe_size.setRange(4, 40)
        self.probe_size.setValue(min(max(int(self.settings.value("probe_size", PROBE_SIZE)), 4), 40))
        self.probe_size.setSuffix(" px")
        self.probe_size.setToolTip("Diameter of the probe dot (constant on screen)")
        self.probe_color = QComboBox()
        self.probe_color.addItems(list(MARK_COLORS))
        saved_probe = self.settings.value("probe_color", DEFAULT_PROBE_COLOR)
        self.probe_color.setCurrentText(saved_probe if saved_probe in MARK_COLORS else DEFAULT_PROBE_COLOR)
        self.probe_color.setToolTip("Colour of the probe dot")
        self.btn_zoom_in = self._icon(QPushButton("Zoom +"), "zoom-in")
        self.btn_zoom_in.setToolTip("Zoom in about the centre of the view (the mouse wheel zooms too)")
        self.btn_zoom_out = self._icon(QPushButton("Zoom -"), "zoom-out")
        self.btn_zoom_out.setToolTip("Zoom out about the centre of the view")
        self.btn_box_zoom = self._icon(QPushButton("Box zoom"), "square-dashed")
        self.btn_box_zoom.setCheckable(True)
        self.btn_box_zoom.setToolTip("Drag a rectangle with the left button to zoom to it; the tool then switches off")
        self.btn_fit = self._icon(QPushButton("Fit"), "maximize")
        self.btn_fit.setToolTip("Fit the whole model into the view")
        self.btn_video = self._icon(QPushButton("Save video..."), "film")
        self.btn_video.clicked.connect(self._save_video)

        bar3 = QHBoxLayout()
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setDecimals(3)
        self.scale_spin.setRange(0.0, 1e6)
        self.scale_spin.setSingleStep(1.0)
        self.scale_spin.setValue(float(self.settings.value("deform_scale", 1.0)))
        self.scale_spin.setToolTip("Multiplies the displacement that deforms the mesh (1 = as computed by the solver)")
        self.scale_spin.setMaximumWidth(56)  # sized for 1e6 with 3 decimals by default; row 4 must stay narrower than row 1
        self.entity_button = self._icon(QPushButton("Color by entity"), "palette")
        self.entity_button.setCheckable(True)
        self.entity_button.setChecked(self.by_entity)
        self.entity_button.setToolTip("Paint shells, solids, rigid bodies, springs and rigid walls each in its own color "
                                      "(set under Model colors...) instead of the result")
        self.triad_check = self._icon(QPushButton("Triad"), "axis-3d")
        self.triad_check.setCheckable(True)
        self.triad_check.setChecked(self.settings.value("triad_visible", True, type=bool))
        self.triad_check.setToolTip("Show or hide the axes triad at the bottom left of the view")
        self.info_check = self._icon(QPushButton("Info"), "info")
        self.info_check.setCheckable(True)
        self.info_check.setChecked(self.settings.value("info_visible", True, type=bool))
        self.info_check.setToolTip("Show or hide the model name, the time and the frame at the top right of the view")
        self.cube_check = self._icon(QPushButton("Cube"), "box")
        self.cube_check.setCheckable(True)
        self.cube_check.setChecked(self.settings.value("cube_visible", True, type=bool))
        self.cube_check.setToolTip("Show or hide the view cube at the bottom right: drag it to turn the model, click a face, "
                                   "an edge or a corner to look from there, use its two arrows to turn the model in the screen plane")
        self.links_check = self._icon(QPushButton("Links"), "link")
        self.links_check.setCheckable(True)
        self.links_check.setChecked(self.settings.value("links_visible", True, type=bool))
        self.links_check.setToolTip("Show or hide the line links of the rigid bodies (/RBODY); the solid shape of the body stays. "
                                    "Greyed out when the model has none")
        self.logo_check = self._icon(QPushButton("Logo"), "copyright")
        self.logo_check.setCheckable(True)
        self.logo_check.setChecked(self.settings.value("logo_visible", True, type=bool))
        self.logo_check.setToolTip("Show or hide the OpenCourantRP logo (name and version) at the bottom left of the view; "
                                   "it only appears while a result is shown")
        self.ruler_check = self._icon(QPushButton("Ruler"), "ruler-dimension-line")
        self.ruler_check.setCheckable(True)
        self.ruler_check.setChecked(self.settings.value("ruler", True, type=bool))
        self.ruler_check.setToolTip("Show a ruler at the bottom of the view (a third of its width; the numbers follow the zoom)")
        self.btn_undeformed = self._icon(QPushButton("Undeformed"), "frame")
        self.btn_undeformed.setCheckable(True)
        self.btn_undeformed.setToolTip("Plot the original, undeformed domain")
        self.overlay_check = self._icon(QPushButton("Overlay"), "layers")
        self.overlay_check.setCheckable(True)
        self.overlay_check.setChecked(self.settings.value("overlay_visible", False, type=bool))
        self.overlay_check.setToolTip("Draw the undeformed model, translucent, over the deformed one (eroded elements included); "
                                      "its color is in Model colors")
        self.overlay_opacity = QSpinBox()
        self.overlay_opacity.setRange(10, 90)
        self.overlay_opacity.setSuffix(" %")
        try:
            self.overlay_opacity.setValue(int(self.settings.value("overlay_opacity", 25)))
        except (TypeError, ValueError):
            self.overlay_opacity.setValue(25)
        self.overlay_opacity.setToolTip("How opaque the undeformed overlay is")
        self.cmap_combo = QComboBox()
        self.cmap_combo.addItems(list(COLORMAPS))
        self.cmap_combo.setCurrentText(self.settings.value("colormap", DEFAULT_COLORMAP))
        rv.addLayout(bar3)

        bar_section = QHBoxLayout()
        self.ncolors = QSpinBox()
        self.ncolors.setRange(MIN_COLORS, MAX_COLORS)
        self.ncolors.setValue(min(max(int(self.settings.value("ncolors", 12)), MIN_COLORS), MAX_COLORS))
        self.ncolors.setToolTip(f"Number of colours in the colour bar ({MIN_COLORS} to {MAX_COLORS})")
        self.digits = QSpinBox()
        self.digits.setRange(MIN_DIGITS, MAX_DIGITS)
        self.digits.setValue(min(max(int(self.settings.value("digits", DEFAULT_DIGITS)), MIN_DIGITS), MAX_DIGITS))
        self.digits.setToolTip(f"Digits after the point of the colour bar numbers ({MIN_DIGITS} to {MAX_DIGITS})")
        self.number_fmt = ChoiceSpin(NUMBER_FORMATS)
        fmt = self.settings.value("number_format", NUMBER_FORMATS[0])
        fmt = OLD_FORMAT_NAMES.get(fmt, fmt)
        self.number_fmt.setValue(NUMBER_FORMATS.index(fmt) if fmt in NUMBER_FORMATS else 0)
        self.number_fmt.setToolTip('Colour bar numbers: "sci" = scientific, with an exponent (+3.02e+02), "dec" = decimals (+302.15)')
        self.lim_min = QLineEdit()
        self.lim_max = QLineEdit()
        for edit, tip in ((self.lim_min, "Lower limit of the colour bar"), (self.lim_max, "Upper limit of the colour bar")):
            edit.setPlaceholderText("auto")
            edit.setMaximumWidth(90)
            edit.setToolTip(tip + " (empty = from the data, e.g. 1.5e-3)")
            edit.setValidator(QDoubleValidator(edit))
        self.cap_check = self._icon(QCheckBox("Cap values"), "arrow-up-to-line")
        self.cap_check.setToolTip("Paint values above the upper limit dark grey (#383838) and below the lower limit light grey (#9E9E9E)")
        self.cap_check.setChecked(self.settings.value("cap", False, type=bool))
        self.minmax_check = self._icon(QPushButton("Min/Max"), "locate-fixed")
        self.minmax_check.setCheckable(True)
        self.minmax_check.setToolTip("Mark the maximum (magenta triangle) and the minimum (magenta square) on the model")
        self.minmax_check.setChecked(self.settings.value("minmax", False, type=bool))
        self.mark_size = QSpinBox()
        self.mark_size.setRange(MIN_MARK_SIZE, MAX_MARK_SIZE)
        self.mark_size.setValue(min(max(int(self.settings.value("mark_size", 10)), MIN_MARK_SIZE), MAX_MARK_SIZE))
        self.mark_size.setSuffix(" px")
        self.mark_size.setToolTip("Size of the min/max symbols")
        self.mark_color = QComboBox()
        self.mark_color.addItems(list(MARK_COLORS))
        saved_colour = self.settings.value("mark_color", DEFAULT_MARK_COLOR)
        self.mark_color.setCurrentText(saved_colour if saved_colour in MARK_COLORS else DEFAULT_MARK_COLOR)
        self.mark_color.setToolTip("Colour of the min/max symbols")
        rv.addLayout(bar_section)

        bar_deform = QHBoxLayout()  # deformation, extremes, probes: the row under the section plane

        # section plane controls (placed in bar_section, the row above)
        self.section_combo = QComboBox()
        self.section_combo.addItems(["Off", "Plane normal to X", "Plane normal to Y", "Plane normal to Z"])
        self.section_combo.setToolTip("Hide the part of the model on one side of a plane, to see inside")
        self.section_slider = QSlider(Qt.Horizontal)
        self.section_slider.setRange(0, SECTION_STEPS)
        self.section_slider.setValue(SECTION_STEPS // 2)
        self.section_slider.setMinimumWidth(200)
        self.section_slider.setEnabled(False)
        self.section_slider.setToolTip("Position of the section plane across the model")
        self.section_label = QLabel("")
        self.section_label.setMinimumWidth(95)  # room for the position, so the box does not move while dragging
        self.section_label.setVisible(False)  # nothing to show while the plane is off: the check box then sits next to the slider
        self.section_keep = self._icon(QCheckBox("Keep the other side"), "flip-horizontal-2")
        self.section_keep.setToolTip("Show the side of the plane that is hidden now, and hide the one that is shown")
        self.section_keep.setEnabled(False)
        self._section_timer = QTimer(self)  # one redraw when the slider pauses for a moment: a drag stays smooth
        self._section_timer.setSingleShot(True)
        self._section_timer.setInterval(15)
        self._section_timer.timeout.connect(self._apply_section)
        self.section_combo.currentIndexChanged.connect(self._section_mode_changed)
        self.section_slider.valueChanged.connect(self._section_moved)
        self.section_keep.toggled.connect(self._apply_section)
        rv.addLayout(bar_deform)

        # the controls of each row, in groups (a vertical bar goes between groups)
        self._fill(bar, (QLabel("Result file:"), self.file_combo), (btn_refresh,), view_widgets,
                   (self.btn_snapshot, self.btn_video), (self.entity_button,))
        self._fill(bar3, (QLabel("Colormap:"), self.cmap_combo, QLabel("Colors:"), self.ncolors, QLabel("Digits:"), self.digits, QLabel("Format:"), self.number_fmt,
                          QLabel("Limits:"),
                          self.lim_min, QLabel("to"), self.lim_max, self.cap_check),
                   (self.btn_zoom_in, self.btn_zoom_out, self.btn_box_zoom, self.btn_fit))
        self._fill(bar_section, (self._icon_label("scissors", "Section plane:"), self.section_combo, self.section_slider,
                          self.section_label, self.section_keep),
                   (self.mesh_check, self.ruler_check, self.links_check, self.triad_check, self.info_check,
                    self.cube_check, self.logo_check))
        self._fill(bar_deform, (QLabel("Deformation:"), self.scale_spin, self.btn_undeformed),
                   (self.overlay_check, QLabel("opacity:"), self.overlay_opacity),
                   (self.minmax_check, QLabel("Symbol:"), self.mark_size, QLabel("color:"), self.mark_color),
                   (self.btn_probes, QLabel("Probe:"), self.probe_size, QLabel("color:"), self.probe_color))

        row = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal)
        self.time_label = QLabel("")
        row.addWidget(self.btn_play)  # the animation controls sit with the step slider they drive
        row.addWidget(self.speed)
        row.addWidget(self.slider, 1)
        row.addWidget(self.time_label)
        rv.addLayout(row)
        self.viewer = ResultViewer()
        rv.addWidget(self.viewer, 1)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(res)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([480, 1000])

        header = QHBoxLayout()
        header.addStretch(1)
        self.btn_theme = QPushButton()
        self.btn_theme.clicked.connect(self._toggle_theme)
        btn_units = self._icon(QPushButton("Units..."), "ruler")
        btn_units.setToolTip("Declare the units of the model and of the results (shown next to the values)")
        btn_units.clicked.connect(self._show_units)
        btn_presets = self._icon(QPushButton("Presets..."), "bookmark")
        btn_presets.setToolTip("Save the colour bar / min-max / probe layout under a name, and load it later")
        btn_presets.clicked.connect(self._show_presets)
        btn_fonts = self._icon(QPushButton("Fonts..."), "type")
        btn_fonts.clicked.connect(self._show_fonts)
        btn_entities = self._icon(QPushButton("Model colors..."), "palette")
        btn_entities.setToolTip("Choose the colors of the background, of the kinds of cells (shells, solids, rigid bodies, "
                                "springs, rigid walls, mesh edges) and of the triad")
        btn_entities.clicked.connect(self._show_colors)
        btn_help = self._icon(QPushButton("Help"), "circle-help")
        btn_help.setToolTip("Open the manual in the web browser")
        btn_help.clicked.connect(self._show_help)
        btn_about = self._icon(QPushButton("About"), "info")
        btn_about.clicked.connect(self._show_about)
        header.addWidget(btn_units)
        header.addWidget(btn_presets)
        header.addWidget(btn_fonts)
        header.addWidget(btn_entities)
        header.addWidget(self.btn_theme)
        header.addWidget(btn_help)
        header.addWidget(btn_about)
        central = QWidget()
        cv = QVBoxLayout(central)
        cv.setContentsMargins(6, 6, 6, 6)
        cv.addLayout(header)
        cv.addWidget(split, 1)
        self.setCentralWidget(central)
        for button in self.findChildren(QPushButton):  # a click must not leave the focus (blue) outline on a toggled-off button
            button.setFocusPolicy(Qt.TabFocus)

        self.file_combo.currentIndexChanged.connect(self._file_changed)
        self.slider.valueChanged.connect(self.file_combo.setCurrentIndex)
        self.results_panel.changed.connect(self._redraw)
        self.btn_zoom_in.clicked.connect(lambda: self.viewer.zoom(ZOOM_STEP))
        self.btn_zoom_out.clicked.connect(lambda: self.viewer.zoom(1 / ZOOM_STEP))
        self.btn_fit.clicked.connect(self.viewer.fit_view)
        self.btn_box_zoom.toggled.connect(self.viewer.set_box_zoom)
        self.viewer.box_zoom_finished.connect(lambda: self.btn_box_zoom.setChecked(False))
        self.mesh_check.toggled.connect(self._redraw)
        self.scale_spin.valueChanged.connect(self._redraw)
        self.btn_undeformed.toggled.connect(self._redraw)
        self.overlay_check.toggled.connect(self._overlay_changed)
        self.overlay_opacity.valueChanged.connect(self._overlay_changed)
        self.ruler_check.toggled.connect(self._ruler_toggled)
        self.triad_check.toggled.connect(self._triad_toggled)
        self.info_check.toggled.connect(self._info_toggled)
        self.cube_check.toggled.connect(self._cube_toggled)
        self.links_check.toggled.connect(self._links_toggled)
        self.logo_check.toggled.connect(self._logo_toggled)
        self.entity_button.toggled.connect(self._by_entity_toggled)
        self.results_panel.tree.itemClicked.connect(self._variable_clicked)
        self.cmap_combo.currentTextChanged.connect(self._redraw)
        self.ncolors.valueChanged.connect(self._redraw)
        self.digits.valueChanged.connect(self._redraw)
        self.number_fmt.valueChanged.connect(self._redraw)
        self.lim_min.editingFinished.connect(self._redraw)
        self.lim_max.editingFinished.connect(self._redraw)
        self.cap_check.toggled.connect(self._redraw)
        self.minmax_check.toggled.connect(self._redraw)
        self.mark_size.valueChanged.connect(self._redraw)
        self.mark_color.currentTextChanged.connect(self._redraw)
        self.speed.valueChanged.connect(lambda v: self.settings.setValue("speed", v))
        btn_refresh.clicked.connect(self._refresh_files)
        self.btn_probes.clicked.connect(lambda: self.viewer.clear_probes())
        self.btn_snapshot.clicked.connect(self._save_snapshot)
        self.probe_size.valueChanged.connect(self._probe_size_changed)
        self.probe_color.currentTextChanged.connect(self._probe_color_changed)
        self.viewer.probe_size = self.probe_size.value()
        self.viewer.probe_color = self.probe_color.currentText()
        self.viewer.fonts = dict(self.fonts)
        self.viewer.entity_colors, self.viewer.color_by_entity = dict(self.entity_colors), self.by_entity
        self.viewer.background, self.viewer.triad = self.background, dict(self.triad)
        self.viewer._apply_background()
        self.viewer._style_axes()
        self.viewer.units = self.units
        self.viewer.ruler = self.ruler_check.isChecked()
        self.viewer.set_triad_visible(self.triad_check.isChecked())
        self.viewer.info_visible = self.info_check.isChecked()
        self.viewer.links_visible = self.links_check.isChecked()
        self.viewer.overlay_visible = self.overlay_check.isChecked()
        self.viewer.overlay_opacity = self.overlay_opacity.value() / 100
        self.viewer.logo_visible = self.logo_check.isChecked()
        self.viewer.cube.set_visible(self.cube_check.isChecked())
        self.viewer.cube.style = self.cube_style
        self.viewer.cube.restyle()  # after the background and the style are known

    # --------------------------------------------------------------- theme
    def _apply_theme(self, name: str):
        self.theme_name = name
        self.settings.setValue("theme", name)
        app = QApplication.instance()
        app.setStyleSheet(stylesheet(THEMES[name]))
        pal = app.palette()
        Separator.color = QColor(THEMES[name].muted)
        for bar in self.findChildren(Separator):
            bar.update()
        pal.setColor(QPalette.Link, QColor(THEMES[name].accent))  # links in rich text (About box)
        app.setPalette(pal)
        self.btn_theme.setText("Dark theme" if name == "light" else "Light theme")
        self._refresh_icons()
        self.viewer.set_theme(THEMES[name])
        if self.font_dialog is not None:
            self.font_dialog.set_theme_text(THEMES[name].view_text)
        if self.colors_dialog is not None:
            self.colors_dialog.set_theme(THEMES[name])

    def _toggle_theme(self):
        self._apply_theme("dark" if self.theme_name == "light" else "light")

    # ------------------------------------------------------------- presets
    def _layout_state(self) -> dict:
        """The colour bar / min-max / probe settings as they are now."""
        return {
            "colormap": self.cmap_combo.currentText(), "ncolors": self.ncolors.value(), "digits": self.digits.value(),
            "format": self.number_fmt.text(),
            "cap": self.cap_check.isChecked(), "minmax": self.minmax_check.isChecked(),
            "mark_size": self.mark_size.value(), "mark_color": self.mark_color.currentText(),
            "probe_size": self.probe_size.value(), "probe_color": self.probe_color.currentText(),
            "fonts": json.loads(fonts.dumps(self.fonts)),
            "entity_colors": dict(self.entity_colors), "by_entity": self.entity_button.isChecked(),
            "background": self.background, "triad": dict(self.triad), "cube_style": self.cube_style,
        }

    def _apply_layout(self, state: dict):
        """Set the controls from a saved layout (anything missing or invalid keeps its current value)."""
        widgets = (self.cmap_combo, self.ncolors, self.digits, self.number_fmt, self.cap_check, self.minmax_check, self.mark_size, self.mark_color,
                   self.probe_size, self.probe_color)
        for w in widgets:
            w.blockSignals(True)
        try:
            if state.get("colormap") in COLORMAPS:
                self.cmap_combo.setCurrentText(state["colormap"])
            for spin, key in ((self.ncolors, "ncolors"), (self.digits, "digits"), (self.mark_size, "mark_size"), (self.probe_size, "probe_size")):
                if isinstance(state.get(key), int):
                    spin.setValue(state[key])  # a spin box clamps to its own range
            fmt = OLD_FORMAT_NAMES.get(state.get("format"), state.get("format"))
            if fmt in NUMBER_FORMATS:
                self.number_fmt.setValue(NUMBER_FORMATS.index(fmt))
            for check, key in ((self.cap_check, "cap"), (self.minmax_check, "minmax")):
                if isinstance(state.get(key), bool):
                    check.setChecked(state[key])
            for combo, key in ((self.mark_color, "mark_color"), (self.probe_color, "probe_color")):
                if state.get(key) in MARK_COLORS:
                    combo.setCurrentText(state[key])
            if isinstance(state.get("fonts"), dict):
                self.fonts = fonts.loads(json.dumps(state["fonts"]))
            if isinstance(state.get("entity_colors"), dict):
                self.entity_colors = entities.loads(json.dumps(state["entity_colors"]))
            if "background" in state and (state["background"] is None or modelcolors.background_loads(state["background"])):
                self.background = modelcolors.background_loads(state["background"])
            if state.get("cube_style") in modelcolors.CUBE_STYLES:
                self.cube_style = state["cube_style"]
            if isinstance(state.get("triad"), dict):
                self.triad = modelcolors.triad_loads(state["triad"])
            if isinstance(state.get("by_entity"), bool):
                self.entity_button.blockSignals(True)
                self.entity_button.setChecked(state["by_entity"])
                self.entity_button.blockSignals(False)
                self.by_entity = state["by_entity"]
        finally:
            for w in widgets:
                w.blockSignals(False)
        self.settings.setValue("fonts", fonts.dumps(self.fonts))
        self.viewer.fonts = dict(self.fonts)
        self.viewer.units = self.units
        self.viewer.probe_size = self.probe_size.value()
        self.viewer.probe_color = self.probe_color.currentText()
        self.settings.setValue("probe_size", self.probe_size.value())
        self.settings.setValue("probe_color", self.probe_color.currentText())
        if self.font_dialog is not None:
            self.font_dialog._load(self.fonts)
        self.viewer.entity_colors, self.viewer.color_by_entity = dict(self.entity_colors), self.by_entity
        self.settings.setValue("entity_colors", entities.dumps(self.entity_colors))
        self.settings.setValue("by_entity", self.by_entity)
        self.settings.setValue("background", modelcolors.background_dumps(self.background))
        self.settings.setValue("triad_colors", modelcolors.triad_dumps(self.triad))
        self.settings.setValue("cube_style", self.cube_style)
        self.viewer.background, self.viewer.triad = self.background, dict(self.triad)
        self.viewer.cube.style = self.cube_style
        self.viewer.cube.restyle()
        self.viewer._apply_background()
        self.viewer._style_axes()
        if self.colors_dialog is not None:
            self.colors_dialog.load(self.entity_colors, self.background, self.triad, self.cube_style)
        self._redraw()  # draws once and saves the other settings

    def _presets(self) -> dict:
        return presets.loads(self.settings.value("presets", ""))

    def _show_presets(self):
        if self.preset_dialog is None:
            self.preset_dialog = PresetDialog(presets.sorted_names(self._presets()), self)
            self.preset_dialog.save_requested.connect(self._save_preset)
            self.preset_dialog.load_requested.connect(self._load_preset)
            self.preset_dialog.delete_requested.connect(self._delete_preset)
        self.preset_dialog.show()
        self.preset_dialog.raise_()

    def _save_preset(self, name: str):
        saved = self._presets()
        saved[name] = self._layout_state()
        self.settings.setValue("presets", presets.dumps(saved))
        self.preset_dialog.set_names(presets.sorted_names(saved), select=name)

    def _load_preset(self, name: str):
        state = self._presets().get(name)
        if state is not None:
            self._apply_layout(state)

    def _delete_preset(self, name: str):
        saved = self._presets()
        saved.pop(name, None)
        self.settings.setValue("presets", presets.dumps(saved))
        self.preset_dialog.set_names(presets.sorted_names(saved))

    @staticmethod
    def _fill(bar: QHBoxLayout, *groups):
        """Put the widgets of each group in `bar`, a vertical line (with a space on each side) between groups."""
        for n, group in enumerate(groups):
            if n:
                bar.addSpacing(6)
                line = Separator()
                bar.addWidget(line)
                bar.addSpacing(6)
            for w in group:
                bar.addWidget(w)
        bar.addStretch(1)

    def _show_units(self):
        if self.units_dialog is None:
            self.units_dialog = UnitsDialog(self.units, self)
            self.units_dialog.changed.connect(self._units_changed)
        self.units_dialog.show()
        self.units_dialog.raise_()

    def _units_changed(self, new: units.Units):
        self.units = new
        self._update_section_label()
        self.settings.setValue("units", units.dumps(new))
        self.viewer.set_units(new)

    def _show_fonts(self):
        if self.font_dialog is None:
            self.font_dialog = FontDialog(self.fonts, THEMES[self.theme_name].view_text, self)
            self.font_dialog.changed.connect(self._fonts_changed)
        self.font_dialog.show()
        self.font_dialog.raise_()

    def _show_colors(self):
        if self.colors_dialog is None:
            self.colors_dialog = ModelColorsDialog(self.entity_colors, self.background, self.triad, self.cube_style,
                                                   THEMES[self.theme_name], self)
            self.colors_dialog.entities_changed.connect(self._entities_changed)
            self.colors_dialog.background_changed.connect(self._background_changed)
            self.colors_dialog.triad_changed.connect(self._triad_changed)
            self.colors_dialog.cube_style_changed.connect(self._cube_style_changed)
        self.colors_dialog.show()
        self.colors_dialog.raise_()

    def _background_changed(self, spec):
        self.background = spec
        self.settings.setValue("background", modelcolors.background_dumps(spec))
        self.viewer.set_background(spec)

    def _cube_style_changed(self, style: str):
        self.cube_style = style
        self.settings.setValue("cube_style", style)
        self.viewer.set_cube_style(style)

    def _triad_changed(self, colors: dict):
        self.triad = dict(colors)
        self.settings.setValue("triad_colors", modelcolors.triad_dumps(self.triad))
        self.viewer.set_triad(self.triad)

    def _entities_changed(self, colors: dict):
        self.entity_colors = dict(colors)
        self.settings.setValue("entity_colors", entities.dumps(self.entity_colors))
        self.viewer.set_entities(self.entity_colors, self.by_entity)

    def _variable_clicked(self, item, _column=0):
        """Choosing a variable means wanting its result: leave the color-by-entity view."""
        if item.data(0, KEY_ROLE) is not None and self.entity_button.isChecked():
            self.entity_button.setChecked(False)

    def _by_entity_toggled(self, on: bool):
        self.by_entity = on
        self.settings.setValue("by_entity", on)
        self.viewer.set_entities(self.entity_colors, on)

    def _fonts_changed(self, new: dict):
        self.fonts = dict(new)
        self.settings.setValue("fonts", fonts.dumps(self.fonts))
        self.viewer.set_fonts(self.fonts)

    # ------------------------------------------------------------- section plane
    def _section_mode_changed(self, *_):
        on = self.section_combo.currentIndex() > 0
        self.section_slider.setEnabled(on)
        self.section_keep.setEnabled(on)
        self._apply_section()

    def _section_moved(self, *_):
        self._update_section_label()
        self._section_timer.start()

    def _section_state(self):
        """(axis, position, keep_other) from the controls, or None while the plane is off or there is no result."""
        axis = self.section_combo.currentIndex() - 1
        if axis < 0 or self._mesh is None:
            return None
        original = undeformed_points(self._mesh)  # the model before it deforms: the same at every step
        lo, hi = float(original[:, axis].min()), float(original[:, axis].max())
        return axis, lo + (hi - lo) * self.section_slider.value() / SECTION_STEPS, self.section_keep.isChecked()

    def _update_section_label(self):
        state = self._section_state()
        self.section_label.setVisible(state is not None)
        if state is None:
            self.section_label.setText("")
            return
        original = undeformed_points(self._mesh)[:, state[0]]
        span = float(original.max() - original.min())
        value = 0.0 if abs(state[1]) < 1e-5 * span else state[1]  # no 2.9e-05 where the middle is zero
        self.section_label.setText(f"{'XYZ'[state[0]]} = {value:.4g} {self.units.length}".rstrip())

    def _apply_section(self, *_):
        self._update_section_label()
        try:
            self.viewer.set_section(self._section_state())
        except KeyError as exc:  # the plane hides the whole model
            self.viewer.blank()
            self.time_label.setText(str(exc.args[0]))
            return
        if self._mesh is not None:
            self._show_status()

    def _show_help(self):
        manual = Path(resource("manual.html"))
        if not manual.is_file() or not QDesktopServices.openUrl(QUrl.fromLocalFile(str(manual))):
            QMessageBox.warning(self, "Help", f"The manual could not be opened:{chr(10)}{manual}")

    def _show_about(self):
        box = QMessageBox(self)
        box.setWindowTitle("About OpenCourantRP")
        box.setTextFormat(Qt.RichText)
        box.setText(about.about_html(__version__))
        box.setTextInteractionFlags(Qt.TextBrowserInteraction)
        box.setIconPixmap(QIcon(resource("icon.png")).pixmap(96, 96))
        box.exec()

    # ----------------------------------------------------------- animation
    def _stop_play(self):
        self.play_timer.stop()
        self.btn_play.setText("Play")
        self._update_play_icon()

    def _toggle_play(self):
        if self.btn_play.text() == "Pause":
            self._stop_play()
            return
        if len(self.vtk_files) < 2:
            return
        if self.slider.value() >= len(self.vtk_files) - 1:
            self.slider.setValue(0)  # restart from the first step
        self.btn_play.setText("Pause")
        self._update_play_icon()
        self.play_timer.start(self._interval())

    def _interval(self) -> int:
        return max(1, round(1000 / self.speed.value()))

    def _advance(self):
        nxt = self.slider.value() + 1
        if nxt >= len(self.vtk_files):
            self._stop_play()
            return
        self.slider.setValue(nxt)  # loads and draws synchronously
        self.play_timer.start(self._interval())

    def _save_snapshot(self):
        if self._mesh is None:
            QMessageBox.information(self, "Snapshot", "There is no result on screen to save.")
            return
        folder = self.settings.value("snapshot_dir", "") or self.project_edit.text()
        chosen = self.settings.value("snapshot_filter", "") or snapshot.FILTERS.split(";;")[0]
        qualities = {ext: int(self.settings.value(f"snapshot_quality{ext}", snapshot.default_quality(ext)))
                     for _, ext, _ in snapshot.FORMATS}
        name = f"{self.deck_name}_step{self.slider.value() + 1:03d}{snapshot.extension_for(chosen)}"
        dlg = SnapshotDialog(self, str(Path(folder) / name), tuple(self.viewer.plotter.ren_win.GetSize()), qualities, chosen)
        if dlg.exec() != QDialog.Accepted or not dlg.selectedFiles():
            return
        path = snapshot.with_extension(dlg.selectedFiles()[0], dlg.extension())
        quality = dlg.quality.value()
        try:
            snapshot.save_snapshot(path, self.viewer.capture(quality), quality)
        except Exception as exc:  # unwritable folder, full disk...
            QMessageBox.warning(self, "Snapshot", f"{type(exc).__name__}: {exc}")
            return
        self.settings.setValue("snapshot_dir", str(Path(path).parent))
        self.settings.setValue("snapshot_filter", dlg.selectedNameFilter())
        for ext, value in dlg.qualities().items():
            self.settings.setValue(f"snapshot_quality{ext}", value)

    def _save_video(self):
        n = len(self.vtk_files)
        if n == 0:
            QMessageBox.information(self, "Save video", "There are no result files to animate.")
            return
        self._stop_play()
        default = str(Path(self.project_edit.text()) / f"{self.deck_name}.mp4")
        path, _ = QFileDialog.getSaveFileName(self, "Save video", default, "MP4 video (*.mp4);;GIF animation (*.gif)")
        if not path:
            return
        dlg = QProgressDialog("Rendering frames...", "Cancel", 0, n, self)
        dlg.setWindowTitle("Save video")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        start = self.slider.value()

        def frames():
            for i in range(n):
                dlg.setValue(i)
                self.slider.setValue(i)
                QApplication.processEvents()
                yield self.viewer.plotter.screenshot(return_img=True)

        try:
            count = write_video(path, frames(), self.speed.value(), dlg.wasCanceled)
            QMessageBox.information(self, "Save video", f"Saved {count} frames to\n{path}")
        except VideoCancelled:
            pass
        except Exception as exc:  # codec / disk problems
            QMessageBox.warning(self, "Save video", f"{type(exc).__name__}: {exc}")
        finally:
            dlg.close()
            self.slider.setValue(start)

    # ------------------------------------------------------------- project
    def _choose_project(self):
        d = QFileDialog.getExistingDirectory(self, "Select project folder", self.project_edit.text())
        if not d:
            return
        if self.proc is not None:
            QMessageBox.information(self, "Change project", "A run is in progress. Stop it before changing the project.")
            return
        current = self.project_edit.text()
        if current and os.path.normpath(d) != os.path.normpath(current):
            box = QMessageBox(QMessageBox.Question, "Change project", "The current project will be unloaded.", parent=self)
            box.setInformativeText(f"Current: {current}{chr(10)}New: {os.path.normpath(d)}")
            box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
            box.setDefaultButton(QMessageBox.Cancel)
            if box.exec() != QMessageBox.Ok:
                return
        self._set_project(d)

    def _unload_project(self):
        """Erase everything of the previous project: model view, results, parts and run log."""
        self._stop_play()
        self.viewer.unload()
        self._mesh = None
        self._mesh_cache.clear()
        self.vtk_files = []
        self._gz_asked = False
        self._set_gz_pending(0)
        self._update_sequence_controls()
        self._part_ids = []
        self._part_nip = {}
        self.parts_tree.clear()
        self.results_panel.set_mesh(None)
        self.log.clear()
        self._log_offsets = {}
        self._update_notice()

    def _set_project(self, folder: str):
        folder = os.path.normpath(folder)
        self._unload_project()
        self.project_edit.setText(folder)
        self.settings.setValue("project", folder)
        try:
            self.deck_name = project.find_deck_name(folder)
            self.deck_label.setText(self.deck_name)
        except project.DeckError as exc:
            self.deck_name = None
            self.deck_label.setText("-")
            QMessageBox.warning(self, "Project folder", str(exc))
        self._part_ids = []  # a new model: list its parts again
        self.section_combo.setCurrentIndex(0)  # and its own section plane
        self.viewer.hidden_parts = frozenset()
        self._refresh_files()
        self._update_run_enabled()
        self._maybe_ask_gzip()

    # -------------------------------------------------------------- solver
    def _refresh_solver_status(self):
        root = solver.solver_root()
        self.solver_label.setText("OpenCourant (bundled)" if root else "Bundled solver not found")
        self._update_run_enabled()

    def _update_run_enabled(self):
        busy = self.proc is not None
        ok = self.deck_name is not None and solver.solver_root() is not None
        self.btn_run.setEnabled(ok and not busy)
        self.btn_stop.setEnabled(busy)

    # ----------------------------------------------------------------- run
    def _logs(self) -> list[Path]:
        folder = Path(self.project_edit.text())
        return [folder / f"{self.deck_name}_{n}.log" for n in self.LOG_NAMES]

    def _run(self):
        root = solver.solver_root()
        folder = self.project_edit.text()
        try:
            self.deck_name = project.find_deck_name(folder)  # re-check at run time
            project.check_solver(root)
            first = project.write_batch_files(folder, self.deck_name, root, int(self.nproc.currentText()))
        except (project.DeckError, OSError) as exc:
            QMessageBox.warning(self, "Cannot run", str(exc))
            return
        self.settings.setValue("nproc", self.nproc.currentText())
        self.log.clear()
        for p in self._logs():  # regenerated by the run; avoid tailing stale content
            p.unlink(missing_ok=True)
        self._log_offsets = {p: 0 for p in self._logs()}
        self._gz_asked = False

        self.proc = QProcess(self)
        self.proc.setWorkingDirectory(folder)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read_stdout)
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(lambda e: self._append(f"[process error: {e}]\n"))
        self._append(f"> {first}\n")
        self.proc.start("cmd.exe", ["/c", str(first)])
        self.proc.closeWriteChannel()  # lets the batch file's final `pause` return immediately
        self.log_timer.start()
        self._update_run_enabled()

    def _stop(self):
        if self.proc is not None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.processId())],
                           capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self._append("[stopped by user]\n")

    def _read_stdout(self):
        data = bytes(self.proc.readAllStandardOutput())
        self._append(data.decode("oem", errors="replace").replace("\r\n", "\n"))

    def _tail_logs(self):
        for path in self._logs():
            try:
                size = path.stat().st_size
            except OSError:
                continue
            off = self._log_offsets.get(path, 0)
            if size < off:
                off = 0
            if size > off:
                with open(path, "rb") as fh:
                    fh.seek(off)
                    chunk = fh.read()
                cut = chunk.rfind(b"\n") + 1  # keep only complete lines
                if cut:
                    self._log_offsets[path] = off + cut
                    self._append(chunk[:cut].decode("oem", errors="replace").replace("\r\n", "\n"))

    def _finished(self, code, _status):
        self._read_stdout()
        self._tail_logs()
        self.log_timer.stop()
        self.proc = None
        self._append(f"\n[finished, exit code {code}]\n")
        self._update_run_enabled()
        self._refresh_files()
        self._maybe_ask_gzip()

    def _append(self, text: str):
        if not text:
            return
        bar = self.log.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 4
        self.log.moveCursor(QTextCursor.End)
        self.log.insertPlainText(text)
        if at_end:
            bar.setValue(bar.maximum())

    # ------------------------------------------------------------- results
    def _refresh_files(self, *_):
        self._stop_play()
        self._mesh_cache.clear()  # files may have been regenerated
        folder = self.project_edit.text()
        self.vtk_files = project.list_vtk(folder, self.deck_name) if self.deck_name else []
        self.file_combo.blockSignals(True)
        self.file_combo.clear()
        self.file_combo.addItems([p.name for p in self.vtk_files])
        self.file_combo.blockSignals(False)
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(len(self.vtk_files) - 1, 0))
        self.slider.blockSignals(False)
        if self.vtk_files:
            last = len(self.vtk_files) - 1
            self.file_combo.blockSignals(True)
            self.file_combo.setCurrentIndex(last)
            self.file_combo.blockSignals(False)
            self._file_changed(last)
        else:
            self._mesh = None
            self.viewer.blank()
            self.time_label.setText("no .vtk files")
        self._set_gz_pending(len(self._gz_pending()))
        self._update_sequence_controls()

    def _update_sequence_controls(self) -> None:
        """Play and video need a sequence: with fewer than two result files they are greyed out."""
        many = len(self.vtk_files) > 1
        for widget in (self.btn_play, self.speed, self.btn_video):
            widget.setEnabled(many)

    def _gz_pending(self) -> list:
        folder = self.project_edit.text()
        return gzanim.pending(folder, self.deck_name) if self.deck_name and os.path.isdir(folder) else []

    def _set_gz_pending(self, count: int) -> None:
        self.btn_gz.setEnabled(count > 0)
        self.results_panel.set_gz_pending(count)

    def _maybe_ask_gzip(self) -> None:
        """Ask once per folder, when the Results tab is in front, what to do with compressed steps not yet converted."""
        if self._gz_asked or self.proc is not None or self.tabs.currentWidget() is not self.results_panel:
            return
        if self._gz_pending():
            self._gz_asked = True
            self._ask_gzip()

    def _ask_gzip(self) -> None:
        """All / Some / Cancel: decompress and convert the pending compressed steps (the button and the hint ask again)."""
        pending = self._gz_pending()
        if not pending:
            return
        root = solver.solver_root()
        if root is None:
            QMessageBox.warning(self, "Compressed files", "The bundled solver was not found: it holds the converter.")
            return
        mode = ask_mode(self, pending)
        if mode == "all":
            files = [f.path for f in pending]
        elif mode == "some":
            files = choose_files(self, self.project_edit.text(), self.deck_name)
        else:
            return
        if files:
            ConvertDialog(files, root, self).exec()
            self._refresh_files()

    def _update_parts(self):
        """List the parts of the model in the Parts tab (the ones already unchecked stay unchecked)."""
        ids = entities.part_ids(self._mesh) if self._mesh is not None else []
        if ids == self._part_ids:
            return
        self._part_ids = ids
        names, self._part_nip = project.read_part_info(self.project_edit.text(), self.deck_name) if self.deck_name else ({}, {})
        hidden = self.viewer.hidden_parts
        self.parts_tree.blockSignals(True)
        self.parts_tree.clear()
        for pid in ids:
            label = "Rigid walls" if pid == entities.WALL_PART else f"{pid}  {names[pid]}" if names.get(pid) else f"Part {pid}"
            item = QTreeWidgetItem([label])
            item.setData(0, Qt.UserRole, pid)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Unchecked if pid in hidden else Qt.Checked)
            self.parts_tree.addTopLevelItem(item)
        self.parts_tree.blockSignals(False)
        self.viewer.hidden_parts = frozenset(p for p in hidden if p in ids)
        self._update_notice()

    def _update_notice(self):
        """Warn when a shown part has a number of integration points for which layer 3 is not the middle."""
        names = {self.parts_tree.topLevelItem(i).data(0, Qt.UserRole): self.parts_tree.topLevelItem(i).text(0)
                 for i in range(self.parts_tree.topLevelItemCount())}
        rigid = (set(int(p) for p in entities.cell_parts(self._mesh)[entities.rigid_elements(self._mesh)])
                 if self._mesh is not None and "PART_ID" in self._mesh.cell_data else set())  # not coloured by a result
        bad = [f"{names.get(p, p)} (N = {n})" for p, n in sorted(self._part_nip.items())
               if n not in (1, 5) and p in names and p not in self.viewer.hidden_parts and p not in rigid]
        self.results_panel.set_notice(
            "The middle of the thickness is taken as integration point 3, which is only the middle for N = 5. "
            "Not the case for: " + "; ".join(bad) + ". The membrane tensor (mean through the thickness) does not depend on N." if bad else "")

    def _parts_changed(self, *_):
        root = self.parts_tree.invisibleRootItem()
        hidden = [root.child(i).data(0, Qt.UserRole) for i in range(root.childCount())
                  if root.child(i).checkState(0) != Qt.Checked]
        self.viewer.hidden_parts = frozenset(hidden)
        self._update_notice()
        self._redraw()

    def _file_changed(self, index: int):
        if not 0 <= index < len(self.vtk_files):
            return
        self.slider.blockSignals(True)
        self.slider.setValue(index)
        self.slider.blockSignals(False)
        path = self.vtk_files[index]
        try:
            if path not in self._mesh_cache:
                if len(self._mesh_cache) >= 120:  # bounded: keeps replays fast without unbounded memory
                    self._mesh_cache.pop(next(iter(self._mesh_cache)))
                self._mesh_cache[path] = read_result(path)
            self._mesh = self._mesh_cache[path]
        except Exception as exc:
            self._mesh = None
            self.time_label.setText(f"cannot read file: {exc}")
            return
        self._update_parts()
        self._redraw()

    @staticmethod
    def _limit(edit: QLineEdit):
        """The number typed in a limit box, or None when it is empty / not a number (= automatic)."""
        try:
            return float(edit.text().replace(",", "."))
        except ValueError:
            return None

    def _ruler_toggled(self, on: bool):
        self.settings.setValue("ruler", on)
        self.viewer.set_ruler(on)

    def _overlay_changed(self, *_):
        self.settings.setValue("overlay_visible", self.overlay_check.isChecked())
        self.settings.setValue("overlay_opacity", self.overlay_opacity.value())
        self.viewer.set_overlay(self.overlay_check.isChecked(), self.overlay_opacity.value() / 100)

    def _links_toggled(self, on: bool):
        self.settings.setValue("links_visible", on)
        self.viewer.set_links_visible(on)

    def _logo_toggled(self, on: bool):
        self.settings.setValue("logo_visible", on)
        self.viewer.set_logo_visible(on)

    def _cube_toggled(self, on: bool):
        self.settings.setValue("cube_visible", on)
        self.viewer.set_cube_visible(on)

    def _info_toggled(self, on: bool):
        self.settings.setValue("info_visible", on)
        self.viewer.set_info_visible(on)

    def _triad_toggled(self, on: bool):
        self.settings.setValue("triad_visible", on)
        self.viewer.set_triad_visible(on)

    def _probe_color_changed(self, name: str):
        self.settings.setValue("probe_color", name)
        self.viewer.set_probe_color(name)

    def _probe_size_changed(self, value: int):
        self.settings.setValue("probe_size", value)
        self.viewer.set_probe_size(value)

    def _redraw(self, *_):
        if self._mesh is None:
            return
        self.results_panel.set_mesh(self._mesh)  # first: it may change the selected variable
        self.links_check.setEnabled(entities.has_links(self._mesh))
        var = self.results_panel.variable()
        thickness = self.results_panel.thickness()
        self.settings.setValue("variable", var.key)
        self.settings.setValue("thickness", thickness)
        self.settings.setValue("axes", self.results_panel.axes())
        undeformed = self.btn_undeformed.isChecked()
        self.scale_spin.setEnabled(not undeformed)
        can_overlay = not undeformed and "Displacement" in self._mesh.point_data  # nothing to compare otherwise
        self.overlay_check.setEnabled(can_overlay)
        self.overlay_opacity.setEnabled(can_overlay)
        self.settings.setValue("deform_scale", self.scale_spin.value())
        self.settings.setValue("colormap", self.cmap_combo.currentText())
        scale = None if undeformed else self.scale_spin.value()
        self.settings.setValue("ncolors", self.ncolors.value())
        self.settings.setValue("digits", self.digits.value())
        self.settings.setValue("number_format", self.number_fmt.text())
        self.settings.setValue("cap", self.cap_check.isChecked())
        self.settings.setValue("minmax", self.minmax_check.isChecked())
        opts = ColorOptions(self.ncolors.value(), self._limit(self.lim_min), self._limit(self.lim_max),
                            self.cap_check.isChecked(), self.minmax_check.isChecked(),
                            self.mark_size.value(), self.mark_color.currentText(), self.digits.value(),
                            self.number_fmt.text())
        self.settings.setValue("mark_size", self.mark_size.value())
        self.settings.setValue("mark_color", self.mark_color.currentText())
        m = self._mesh
        self.viewer.info = {"name": self.deck_name or Path(self.project_edit.text()).name,
                            "time": float(m.field_data["TIME"][0]) if "TIME" in m.field_data else None,
                            "frame": self.slider.value() + 1, "total": len(self.vtk_files)}
        try:
            self.viewer.show_result(self._mesh, var, self.mesh_check.isChecked(), self.smooth_check.isChecked(),
                                    scale, self.cmap_combo.currentText(), opts, thickness, self.results_panel.axes())
        except KeyError as exc:
            self.viewer.blank()
            self.time_label.setText(str(exc.args[0]))
            return
        self._show_status()

    def _show_status(self):
        m = self._mesh
        t = m.field_data["TIME"][0] if "TIME" in m.field_data else float("nan")
        self.time_label.setText(f"step {self.slider.value() + 1}/{len(self.vtk_files)}   time = {t:g}   "
                                f"nodes = {m.n_points}   elements = {m.n_cells}")

    def closeEvent(self, event):
        if self.proc is not None:
            if QMessageBox.question(self, "Quit", "A simulation is running. Stop it and quit?") != QMessageBox.Yes:
                event.ignore()
                return
            self._stop()
        self.viewer.close_plotter()
        super().closeEvent(event)


def main() -> int:
    if "--selftest" in sys.argv:  # packaging check: report the bundled solver, write result next to the exe
        root = solver.solver_root()
        out = Path(sys.argv[sys.argv.index("--selftest") + 1])
        ok = bool(root and (root / solver.STARTER).is_file())
        report = [f"solver={root}", f"starter={ok}"]
        try:  # exercise the video encoders that the packaged app must carry (ffmpeg, imageio)
            import numpy as np
            for ext in ("mp4", "gif"):
                target = out.with_suffix("." + ext)
                n = write_video(target, (np.full((33, 47, 3), 40 * i, np.uint8) for i in range(4)), 5)
                report.append(f"{ext}={n} frames, {target.stat().st_size} bytes")
        except Exception as exc:
            report.append(f"video error: {type(exc).__name__}: {exc}")
            ok = False
        try:  # the colour-bar titles are drawn as math text (matplotlib inside VTK)
            import pyvista as pv
            from vtkmodules.vtkRenderingCore import vtkTextActor
            pl = pv.Plotter(off_screen=True, window_size=(160, 80))
            actor = vtkTextActor()
            actor.SetInput(r"$\sigma_{vm}$")
            actor.GetTextProperty().SetColor(0, 0, 0)
            actor.GetTextProperty().SetFontSize(30)
            actor.SetPosition(10, 20)
            pl.add_actor(actor)
            image = pl.screenshot(return_img=True)
            pl.close()
            lit = int((image.sum(axis=2) < 700).sum())
            report.append(f"mathtext pixels={lit}")
            ok = ok and lit > 20
        except Exception as exc:
            report.append(f"mathtext error: {type(exc).__name__}: {exc}")
            ok = False
        out.write_text(chr(10).join(report) + chr(10))
        return 0 if (root and ok) else 1
    if sys.platform == "win32":  # own taskbar identity, so Windows shows our icon rather than the host's
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OpenCourantRP.OpenCourantRP.App")
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(resource("icon.png")))
    win = MainWindow()
    win.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
