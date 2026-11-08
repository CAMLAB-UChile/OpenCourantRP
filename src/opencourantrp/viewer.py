"""Embedded PyVista view of the converted .vtk results.

The look (coolwarm, 12 segmented colour blocks, custom colour bar, deleted elements hidden,
deformed shape) follows the reference view_*.py scripts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6.QtCore import QEvent, QRect, Qt, Signal
from PySide6.QtWidgets import QRubberBand, QVBoxLayout, QWidget
from vtkmodules.vtkCommonCore import vtkPoints, vtkUnsignedCharArray
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
from vtkmodules.vtkFiltersSources import vtkSphereSource
from vtkmodules.vtkRenderingCore import (
    vtkActor, vtkActor2D, vtkCellPicker, vtkCoordinate, vtkPolyDataMapper, vtkPolyDataMapper2D, vtkTextActor,
)

from . import __version__, entities, modelcolors
from . import probe as probes
from .fonts import VTK_FONT_FILE, FontSpec, apply_font, bracket_font_file, default_fonts, unicode_font_file
from .fastmap import FAST
from .theme import LIGHT, Theme, rgb
from .units import Units, with_unit
from .variables import DEFAULT_AXES, DEFAULT_THICKNESS, VARIABLES, Variable, evaluate  # noqa: F401  (VARIABLES: re-exported)
from .viewcube import ViewCube


def _colormaps() -> dict:
    from cmcrameri import cm as crameri
    from matplotlib.colors import LinearSegmentedColormap

    maps = {"coolwarm": "coolwarm", "vik": crameri.vik, "RdYlBu": "RdYlBu", "RdBu": "RdBu",
            "jet": "jet", "turbo": "turbo", "inferno": "inferno"}
    maps["fast (ParaView)"] = LinearSegmentedColormap.from_list("paraview_fast", FAST, N=256)
    return maps


COLORMAPS = _colormaps()
DEFAULT_COLORMAP = "coolwarm"

DEFAULT_DIGITS, MIN_DIGITS, MAX_DIGITS = 2, 0, 6  # digits after the point of the numbers of the colour bar
NUMBER_FORMATS = ("sci", "dec")  # scientific form (+3.02e+02) or plain decimals (+302.15)
OLD_FORMAT_NAMES = {"eng": "sci"}  # what settings and presets saved before the rename say


def number_format(digits: int, fmt: str = "sci") -> str:
    """The format string of the colour bar numbers: `digits` after the point, in scientific form ("sci") or as decimals ("dec")."""
    return f"{{:+.{min(max(digits, MIN_DIGITS), MAX_DIGITS)}{'f' if fmt == 'dec' else 'e'}}}"

@dataclass(frozen=True)
class ColorOptions:
    """Colour-bar settings chosen by the user."""
    ncolors: int = 12  # number of colour blocks, MIN_COLORS..MAX_COLORS
    lower: float | None = None  # fixed lower / upper limit of the colour range; None = from the data
    upper: float | None = None
    cap: bool = False  # paint values outside the limits with CAP_ABOVE / CAP_BELOW instead of the end colours
    show_minmax: bool = False  # mark the extreme values on the model and list them under the colour bar
    mark_size: int = 10  # diameter of the min/max symbols on the model, pixels (the legend ones are 80 % of it)
    mark_color: str = "Magenta"  # a key of MARK_COLORS
    digits: int = DEFAULT_DIGITS  # digits after the point of the colour bar numbers and of the min/max values
    fmt: str = "sci"  # NUMBER_FORMATS: how those numbers are written


MIN_COLORS, MAX_COLORS = 2, 24
CAP_ABOVE = "#383838"  # values above the upper limit
CAP_BELOW = "#9E9E9E"  # values below the lower limit
MARK_COLORS = {"Magenta": (1.0, 0.0, 1.0), "Cyan": (0.0, 1.0, 1.0), "White": (1.0, 1.0, 1.0)}
DEFAULT_MARK_COLOR = "Magenta"
DEFAULT_PROBE_COLOR = "White"
PROBE_HALO = (0.06, 0.06, 0.06)  # thin dark ring around the probe dot, so it shows on any colour
MIN_MARK_SIZE, MAX_MARK_SIZE = 4, 40
RULER_DIVISIONS = 20  # small intervals along the ruler
RULER_MINOR_PER_MAJOR = 5  # a number every this many intervals
RULER_MAJOR, RULER_MINOR = 14, 8  # tick lengths, pixels
RULER_PAD = 9  # space between the ruler and its box, pixels
RULER_RADIUS = 6  # rounded corners of the ruler panel, pixels
RADIUS_STEPS = 6  # segments per rounded corner
WATERMARK_MARGIN = 8  # distance of the watermark from the bottom and left edges of the view, pixels
WATERMARK_SIZE = 13
WATERMARK_OPACITY = 0.4
INFO_MARGIN = 20  # distance of the model information from the top and right edges of the view, pixels
RULER_BOTTOM = 10  # distance of the box from the bottom of the view, pixels
PART_ID = "PART_ID"  # cell array of the part each element belongs to
RIGID_ELEMENT_OPACITY = 0.35  # elements of a rigid body while their links are shown, so that the links can be seen
PROBE_BOX_PAD = 6  # space between the text and the border of a probe box, pixels
PROBE_SIZE = 10  # default probe dot diameter, pixels (constant on screen, whatever the zoom or the mesh)
PROBE_BOX_OFFSET = 14  # info box distance from the sphere, pixels
CLICK_TOLERANCE = 4  # a right-button press/release closer than this (pixels) is a click, not a zoom drag
ZOOM_STEP = 1.25  # factor of one click of Zoom + (Zoom - divides by it)
LEGEND_ROW = 26  # vertical spacing of the two legend lines, pixels

# --- Colour bar layout (pixels, except the two fractions) --------------------
BAR_HEIGHT_FRAC = 0.47  # the colour blocks take 47 % of the view height, in the top left corner
BAR_W = 32
GAP = 2
LABEL_PAD = 10
LEFT_MARGIN = 45
TOP_MARGIN = 20  # between the top of the view and the top of the title
TITLE_GAP = 30
TITLE_DX = -4
AXES_SIZE = 167  # triad viewport, pixels
AXES_ARROW_SCALE = 1.25  # the triad's camera sees this much closer than its widget's own: arrows 1/4 longer
AXES_TIP = 0.24 * AXES_ARROW_SCALE  # arrow tip distance from the triad centre, fraction of AXES_SIZE (tuned by eye)
AXES_LABEL_GAP = 20  # pixels between the arrow tip and the centre of the letter
AXES_SPHERE_RADIUS = 0.14  # of the length of the triad arrows
AXES_PARKED_REACH = 15  # pixels between the origin and the letter of an axis that points into the screen
AXES_FONT_SIZE = 13


def read_result(path: str | Path) -> pv.DataSet:
    return pv.read(str(path))


def undeformed_points(mesh: pv.DataSet) -> np.ndarray:
    """Node coordinates of the model before it deforms.

    The points stored in a result file are where the nodes are at that step (original position plus the
    displacement written next to them), so the original ones are the stored points minus the displacement.
    """
    points = np.asarray(mesh.points, dtype=float)
    if "Displacement" in mesh.point_data:
        points = points - np.asarray(mesh.point_data["Displacement"], dtype=float)
    return points


def section_keep(centres: np.ndarray, section) -> np.ndarray:
    """Which cells the section plane keeps: those below it, or above it with ``keep_other`` (by their centre)."""
    axis, position, keep_other = section
    above = centres[:, axis] >= position
    return ~above if keep_other else above


def ghost_view(mesh: pv.DataSet, hidden=(), scale: float | None = 1.0, section=None):
    """The outer skin of the undeformed model, or None when there is nothing to compare with.

    Every shell and solid of the parts that are shown is in, eroded and rigid-body ones too (that is where the
    material was); the section plane keeps the cells it keeps in the deformed view. Only the skin is returned, so that
    a translucent solid does not show its inner faces.
    """
    if scale is None or "Displacement" not in mesh.point_data:
        return None
    keep = np.isin(entities.classify(mesh), ("shell", "solid"))
    if len(hidden) and PART_ID in mesh.cell_data:
        keep &= ~np.isin(entities.cell_parts(mesh), list(hidden))
    if not keep.any():
        return None
    ghost = mesh.extract_cells(np.where(keep)[0]).copy(deep=True)
    original = undeformed_points(ghost)
    if section is not None:
        ghost.points = original + float(scale) * np.asarray(ghost.point_data["Displacement"])
        keep = section_keep(ghost.cell_centers().points, section)
        if not keep.any():
            return None
        ghost = ghost.extract_cells(np.where(keep)[0]).copy(deep=True)
        original = undeformed_points(ghost)
    ghost.points = original
    return ghost.extract_surface(algorithm="dataset_surface")


def prepare(mesh: pv.DataSet, var: Variable, smooth: bool = False, scale: float | None = 1.0, hidden=(),
            thickness: str = DEFAULT_THICKNESS, axes: str = "local", section=None):
    """prepare_view() with every cell coloured by the result: (mesh to show, scalar name, vmin, vmax)."""
    shown, _, name, vmin, vmax = prepare_view(mesh, var, smooth, scale, hidden, thickness, axes, section)
    return shown, name, vmin, vmax


def prepare_view(mesh: pv.DataSet, var: Variable, smooth: bool = False, scale: float | None = 1.0, hidden=(),
                 thickness: str = DEFAULT_THICKNESS, axes: str = "local", section=None, fixed=(), links: bool = True):
    """Hide eroded elements, apply the displacement and add a scalar to colour by.

    With ``smooth`` an element variable is extrapolated to the nodes (average of the surviving
    elements around each node); nodal variables are unaffected.

    ``scale`` multiplies the displacement that deforms the mesh (1 = the shape stored in the file);
    ``None`` shows the undeformed domain. The elements of the parts (PART_ID) in ``hidden`` are left out;
    ``entities.WALL_PART`` stands for the rigid walls.

    ``thickness`` (top, middle, bottom, max, min) picks the place through the shell thickness of a stress or strain;
    ``axes`` ("global" or "local") the axes of its components.

    ``section`` = (axis 0/1/2, position, keep_other) hides the elements whose centre is on one side of the plane
    (axis coordinate = position) of the deformed model: those below it, or those above it with ``keep_other``.

    ``fixed`` lists the entity kinds (entities.KEYS) that are not coloured by the result: they are split off, and the
    colour range and the smoothing only see the other cells.

    The solids and shells of a rigid body (dead in the file from the start) are drawn as rigid cells when "rigid" is in ``fixed``;
    ``links`` False hides the line links of the rigid bodies.

    Returns (mesh to show or None when every cell is fixed, the fixed cells or None, scalar name, vmin, vmax).
    """
    mesh = mesh.copy(deep=False)  # own array containers: the ids below must not leak into the cached mesh
    mesh.cell_data[probes.CELL_ID] = np.arange(mesh.n_cells)
    mesh.point_data[probes.POINT_ID] = np.arange(mesh.n_points)
    keep = np.ones(mesh.n_cells, dtype=bool)
    if "EROSION_STATUS" in mesh.cell_data:
        keep &= np.asarray(mesh.cell_data["EROSION_STATUS"]) == 1  # 1 = alive
        if "rigid" in fixed:
            rigid_element = entities.rigid_elements(mesh)
            mesh.cell_data[entities.RIGID_ELEMENT] = rigid_element.astype(np.uint8)
            keep |= rigid_element
    if not links:
        keep &= ~entities._links(mesh)
    if len(hidden) and PART_ID in mesh.cell_data:
        wall = entities.classify(mesh) == "wall"  # their PART_ID is not theirs: the pseudo-part WALL_PART hides them
        keep &= ~(np.isin(entities.cell_parts(mesh), list(hidden)) & ~wall)
        keep &= ~(wall & (entities.WALL_PART in hidden))
    if not keep.all():
        shown = mesh.extract_cells(np.where(keep)[0]).copy(deep=True)  # never share points with the cached mesh
    else:
        shown = mesh.copy()
    if shown.n_cells == 0:
        raise KeyError("nothing to show: every part is hidden")
    original = undeformed_points(shown)
    shown.point_data[probes.POS0] = original  # where the nodes are in the model, before any deformation
    if "Displacement" in shown.point_data:
        shown.points = original if scale is None else original + float(scale) * np.asarray(shown.point_data["Displacement"])
    if section is not None:
        keep = section_keep(shown.cell_centers().points, section)
        if not keep.all():
            if not keep.any():
                raise KeyError("nothing to show: the section plane hides everything")
            shown = shown.extract_cells(np.where(keep)[0]).copy(deep=True)

    name = var.name
    rest = None
    if len(fixed):
        isfixed = np.isin(entities.classify(shown), list(fixed))
        if isfixed.any():
            rest = shown.extract_cells(np.where(isfixed)[0]).copy(deep=True)
            if isfixed.all():
                return None, rest, name, 0.0, 1.0
            shown = shown.extract_cells(np.where(~isfixed)[0]).copy(deep=True)
    values = evaluate(var, shown, thickness, axes)  # raises KeyError when the file lacks the data
    if var.nodal:
        shown.point_data[name] = values
    else:
        shown.cell_data[name] = values
        if smooth:  # average the element values at the nodes; only the plotted one is carried over
            light = shown.copy(deep=False)
            for key in list(light.cell_data.keys()):
                if key not in (name, probes.CELL_ID, PART_ID):
                    del light.cell_data[key]
            shown = light.cell_data_to_point_data(pass_cell_data=True)
            del shown.cell_data[name]

    values = np.asarray(shown[name])
    vmin, vmax = float(np.nanmin(values)), float(np.nanmax(values))
    if vmax == vmin:  # guard against a constant field
        vmax = vmin + 1e-12
    return shown, rest, name, vmin, vmax


def info_lines(info: dict | None, time_unit: str = "") -> list[str]:
    """The model information: name, time (with its unit when one is declared) and frame."""
    if not info:
        return []
    time = info.get("time")
    time_text = "Time = " + ("-" if time is None or time != time else with_unit(f"{time:g}", time_unit))
    return [str(info.get("name", "")), time_text, f"Frame {info.get('frame', 0)} / {info.get('total', 0)}"]


def ruler_number(value: float) -> str:
    """A number for the ruler: three significant figures, without an exponent while it stays readable."""
    text = f"{value:.3g}"
    if "e" in text and 1 <= abs(value) < 1e7:
        text = f"{value:.0f}"
    return text


class ResultViewer(QWidget):
    """A QtInteractor that can be redrawn with a new mesh / variable / edge setting."""

    box_zoom_finished = Signal()  # the box zoom tool did its zoom (the tool switches itself off)

    def __init__(self, parent=None, offscreen_size=None):
        super().__init__(parent)
        if offscreen_size is None:
            self.plotter = QtInteractor(self)
            lay = QVBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(self.plotter.interactor)
        else:  # a picture drawn without a window: used for the large snapshots
            self.plotter = pv.Plotter(off_screen=True, window_size=list(offscreen_size))
        self.plotter.enable_parallel_projection()  # orthographic: no perspective, so panning and rotating keep the shape
        self._observer = None
        self._first_draw = True
        self._theme = LIGHT
        self._last = None  # arguments of the last draw, to redraw on a theme change
        self.plotter.add_axes(viewport=(0.0, 0.0, 0.1, 0.1), line_width=3)
        source = vtkSphereSource()  # the origin of the triad, in the triad's own small viewport so it follows its camera
        source.SetRadius(AXES_SPHERE_RADIUS * max(self.plotter.renderer.axes_actor.GetTotalLength()) / AXES_ARROW_SCALE)  # the zoom below would enlarge it
        source.SetThetaResolution(32)
        source.SetPhiResolution(32)
        mapper = vtkPolyDataMapper()
        mapper.SetInputConnection(source.GetOutputPort())
        self._triad_sphere = vtkActor()
        self._triad_sphere.SetMapper(mapper)
        self._triad_sphere.GetProperty().SetSpecular(0.5)
        self._triad_sphere.GetProperty().SetSpecularPower(30)
        self._triad_sphere.PickableOff()
        axes_renderer = self.plotter.renderer.axes_widget.GetRenderer()
        axes_renderer.AddViewProp(self._triad_sphere)
        self._axes_base_scale = None
        axes_renderer.AddObserver("StartEvent", self._zoom_axes)
        self._axis_labels = []
        for text in "XYZ":
            t = vtkTextActor()
            t.SetInput(text)
            prop = t.GetTextProperty()
            prop.SetFontSize(AXES_FONT_SIZE)
            prop.SetBold(False)
            prop.SetItalic(False)
            prop.SetShadow(False)
            prop.SetJustificationToCentered()
            prop.SetVerticalJustificationToCentered()
            self.plotter.add_actor(t, reset_camera=False, pickable=False)
            self._axis_labels.append(t)
        self.entity_colors = dict(entities.DEFAULTS)  # colour of each kind of cell (entities.KEYS) and of the mesh edges
        self.color_by_entity = False  # paint every kind in its own colour instead of the result
        self.background = None  # custom background (modelcolors.background_loads), None = the theme's
        self.triad = modelcolors.triad_loads({})  # colours of the triad arrows and letters
        self._shown = None  # mesh, scalar and variable of the last draw: what a probe click is picked from
        self._actor = None
        self._name = None
        self._var = None
        self._probes: list[probes.Probe] = []
        self._probe_observer = None
        self._ruler_observer = None
        self.ruler = True  # the on-screen ruler
        self.triad_visible = True  # the axes triad at the bottom left
        self.info_visible = True  # the model information at the top right
        self.links_visible = True  # the line links of the rigid bodies
        self.overlay_visible = False  # the undeformed model, translucent, over the deformed one
        self.overlay_opacity = 0.25
        self.logo_visible = True  # the watermark at the bottom left (drawn only while a result is shown)
        self.info = None  # {name, time, frame, total}, set by the window before each draw
        self._info_observer = None
        self.probe_size = PROBE_SIZE
        self.probe_color = DEFAULT_PROBE_COLOR
        self.units = Units()
        self.hidden_parts: frozenset = frozenset()  # PART_IDs that are not drawn
        self.section = None  # (axis, position, keep_other) of the section plane, None = no plane
        self._k = 1  # pixel scale of the overlays: >1 only while a scaled capture runs
        self.fonts = default_fonts()
        self._press = None
        self._box = False  # the box zoom tool is on: the left button drags a rectangle instead of rotating
        self._box_start = None
        self._band = None
        if offscreen_size is None:
            self.plotter.interactor.installEventFilter(self)  # right clicks pick probes; VTK still gets every event
        self.plotter.ren_win.AddObserver("EndEvent", self._place_axis_labels)
        self.plotter.iren.add_observer("InteractionEvent", self._place_axis_labels)
        self._apply_background()
        self._style_axes()
        self._apply_triad_visibility()
        self.cube = ViewCube(self.plotter, self.view_background, self, interactive=offscreen_size is None)

    def view_background(self) -> tuple[str, str]:
        """(top, bottom) colors of the background now: the custom one or the theme's."""
        return modelcolors.background_colors(self.background, self._theme)

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._apply_background()
        self._style_axes()
        self.cube.restyle()
        if self._last is not None:
            self.show_result(*self._last)
        else:
            self.plotter.render()

    def _apply_background(self) -> None:
        top, bottom = modelcolors.background_colors(self.background, self._theme)
        if top == bottom:
            self.plotter.set_background(bottom)
        else:
            self.plotter.set_background(bottom, top=top)

    def _style_axes(self) -> None:
        """Triad with coloured arrows and plain labels in front of the arrow tips."""
        axes = self.plotter.renderer.axes_actor
        axes.AxisLabelsOff()  # labels are drawn by _place_axis_labels, where the tips really are
        for part, key in ((axes.GetXAxisShaftProperty(), "x"), (axes.GetXAxisTipProperty(), "x"),
                          (axes.GetYAxisShaftProperty(), "y"), (axes.GetYAxisTipProperty(), "y"),
                          (axes.GetZAxisShaftProperty(), "z"), (axes.GetZAxisTipProperty(), "z")):
            part.SetColor(*rgb(self.triad[key]))
        for t in self._axis_labels:
            t.GetTextProperty().SetColor(*rgb(self.triad["letters"] or self._theme.view_text))
        self._triad_sphere.GetProperty().SetColor(*rgb(self.triad["sphere"] or self._theme.view_text))

    def _zoom_axes(self, renderer, _event=None) -> None:
        """Longer arrows: the triad's camera sees AXES_ARROW_SCALE times closer (the view is orthographic, so its parallel scale
        shrinks). It is set from the widget's own scale, so it is idempotent and survives the widget resetting its camera."""
        cam = renderer.GetActiveCamera()
        if self._axes_base_scale is None:
            self._axes_base_scale = cam.GetParallelScale()
        cam.SetParallelScale(self._axes_base_scale / AXES_ARROW_SCALE)

    def _apply_triad_visibility(self) -> None:
        self.plotter.renderer.axes_widget.SetEnabled(int(self.triad_visible))
        for t in self._axis_labels:
            t.SetVisibility(int(self.triad_visible))

    def set_triad_visible(self, on: bool) -> None:
        self.triad_visible = bool(on)
        self._apply_triad_visibility()
        self.plotter.render()

    def _place_axis_labels(self, *_) -> None:
        pl = self.plotter
        if pl._closed:
            return
        W, H = self._size()
        if W <= 0 or H <= 0:
            return
        pl.renderer.axes_widget.SetViewport(0.0, 0.0, min(AXES_SIZE * self._k / W, 0.5), min(AXES_SIZE * self._k / H, 0.5))
        cam = pl.camera
        d = np.array(cam.focal_point) - np.array(cam.position)
        d /= np.linalg.norm(d)
        up = np.array(cam.up)
        right = np.cross(d, up)
        right /= np.linalg.norm(right)
        up = np.cross(right, d)
        c = AXES_SIZE * self._k / 2
        for t, e in zip(self._axis_labels, np.eye(3)):
            vx, vy = float(e @ right), float(e @ up)
            norm = max(np.hypot(vx, vy), 1e-9)
            if np.hypot(vx, vy) < 0.2:  # axis points into the screen: park its letter close to the origin
                vx, vy, reach = -1.0, -1.0, AXES_PARKED_REACH * self._k
                norm = np.hypot(vx, vy)
            else:
                reach = (AXES_TIP * AXES_SIZE * min(np.hypot(vx, vy), 1.0) + AXES_LABEL_GAP) * self._k  # beyond the tip, outward
            t.SetPosition(c + vx / norm * reach, c + vy / norm * reach)

    def show_result(self, mesh: pv.DataSet, var: Variable, show_edges: bool, smooth: bool = False,
                    scale: float | None = 1.0, cmap: str = DEFAULT_COLORMAP,
                    opts: ColorOptions = ColorOptions(), thickness: str = DEFAULT_THICKNESS,
                    axes: str = DEFAULT_AXES) -> tuple[float, float]:
        """Draw the result; returns the (min, max) of the plotted data (before any user limits)."""
        pl = self.plotter
        self._last = (mesh, var, show_edges, smooth, scale, cmap, opts, thickness, axes)
        fixed = entities.KEYS if self.color_by_entity else entities.FIXED
        shown, rest, name, dmin, dmax = prepare_view(mesh, var, smooth, scale, self.hidden_parts, thickness, axes,
                                                     self.section, fixed, self.links_visible)
        camera = None if self._first_draw else pl.camera_position

        lo = dmin if opts.lower is None else opts.lower
        hi = dmax if opts.upper is None else opts.upper
        if not hi > lo:  # inconsistent user limits: fall back to the data range
            lo, hi = dmin, dmax

        self._clear()
        edge = self.entity_colors.get("edges", entities.DEFAULTS["edges"])
        actor = None
        if shown is not None:
            extra = {"above_color": CAP_ABOVE, "below_color": CAP_BELOW} if opts.cap else {}
            actor = pl.add_mesh(
                shown,
                scalars=name,
                cmap=COLORMAPS[cmap],
                show_edges=show_edges,
                edge_color=edge,
                n_colors=opts.ncolors,
                clim=[lo, hi],
                show_scalar_bar=False,  # custom colour bar below
                reset_camera=self._first_draw,
                line_width=self._k,  # edges of the mesh
                **extra,
            )
            marks = self._extremes(shown, name) if opts.show_minmax else None
            self._build_colorbar(actor, lo, hi, var.math, opts, marks, self.units.of(var.quantity))
        if rest is not None:
            self._draw_entities(rest, show_edges, edge, reset=self._first_draw and shown is None)
        ghost = ghost_view(mesh, self.hidden_parts, scale, self.section) if self.overlay_visible else None
        if ghost is not None:
            pl.add_mesh(ghost, color=self.entity_colors.get("ghost", entities.DEFAULTS["ghost"]), opacity=self.overlay_opacity,
                        lighting=False, show_scalar_bar=False, pickable=False, reset_camera=False)
        self._shown, self._actor, self._name, self._var = shown, actor, name, var
        self._draw_probes()
        if self.ruler:
            self._build_ruler()
        if self.info_visible and self.info:
            self._build_info()
        if self.logo_visible:
            self._build_watermark()
        if camera is not None:
            pl.camera_position = camera
        self._first_draw = False
        pl.render()
        return dmin, dmax

    def _draw_entities(self, mesh: pv.DataSet, show_edges: bool, edge: str, reset: bool) -> None:
        """Draw the cells that are not coloured by the result, each kind in its own colour (not pickable)."""
        kind = entities.classify(mesh)
        is_line = np.isin(np.asarray(mesh.celltypes), entities.LINE_TYPES)  # a rigid body is lines and/or its solids
        see_links = bool(is_line[kind == "rigid"].any())  # the links lie inside the solid: let them show through
        for key in entities.KEYS:
            for line in (False, True):
                sel = np.where((kind == key) & (is_line == line))[0]
                if not len(sel):
                    continue
                self.plotter.add_mesh(
                    mesh.extract_cells(sel), color=self.entity_colors.get(key, entities.DEFAULTS[key]),
                    show_edges=show_edges and not line, edge_color=edge, lighting=not line, show_scalar_bar=False,
                    line_width=(2 if line else 1) * self._k, pickable=False, reset_camera=reset,
                    opacity=RIGID_ELEMENT_OPACITY if see_links and key == "rigid" and not line else 1.0,
                )
                reset = False

    @staticmethod
    def _extremes(shown: pv.DataSet, name: str):
        """((x, y, z), value, "Node 12" / "Element 34") of the maximum and of the minimum of the plotted scalar.

        The label carries the number the deck gives to the node or element (empty when the file has no such array).
        """
        values = np.asarray(shown[name])
        if name in shown.point_data:
            where, kind, ids = np.asarray(shown.points), "Node", shown.point_data.get("NODE_ID")
        else:
            where, kind, ids = np.asarray(shown.cell_centers().points), "Element", shown.cell_data.get("ELEMENT_ID")

        def mark(i: int):
            return where[i], float(values[i]), (f"{kind} {int(ids[i])}" if ids is not None else "")
        return mark(int(np.nanargmax(values))), mark(int(np.nanargmin(values)))

    def reset_view(self, kind: str = "isometric") -> None:
        pl = self.plotter
        {"xy": pl.view_xy, "xz": pl.view_xz, "yz": pl.view_yz, "isometric": pl.view_isometric}[kind]()
        pl.reset_camera()
        pl.render()

    def zoom(self, factor: float) -> None:
        """Zoom in (factor > 1) or out (< 1) about the centre of the view."""
        self.plotter.camera.parallel_scale /= factor
        self.plotter.render()

    def fit_view(self) -> None:
        """Fit the whole model into the view, keeping the viewing direction."""
        self.plotter.reset_camera()
        self.plotter.render()

    def set_box_zoom(self, on: bool) -> None:
        self._box = on
        self._box_start = None
        if self._band is not None:
            self._band.hide()
        self.plotter.interactor.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)

    def _zoom_to(self, rect: QRect) -> None:
        """Zoom so that `rect` (widget pixels) fills the view."""
        wid = self.plotter.interactor
        w, h = wid.width(), wid.height()
        cam = self.plotter.camera
        per_px = 2 * cam.parallel_scale / h  # model length of one pixel (the scale is half the view height)
        cam.OrthogonalizeViewUp()
        up = np.asarray(cam.up, dtype=float)
        right = np.cross(np.asarray(cam.direction, dtype=float), up)
        shift = right * (rect.center().x() - w / 2) * per_px + up * (h / 2 - rect.center().y()) * per_px
        cam.position = np.asarray(cam.position) + shift
        cam.focal_point = np.asarray(cam.focal_point) + shift
        cam.parallel_scale *= max(rect.width() / w, rect.height() / h)
        self.plotter.render()

    def _box_event(self, event) -> bool:
        """Draw the rectangle of the box zoom tool; True when the event was used."""
        kind = event.type()
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._box_start = event.position().toPoint()
            if self._band is None:
                self._band = QRubberBand(QRubberBand.Rectangle, self.plotter.interactor)
            self._band.setGeometry(QRect(self._box_start, self._box_start))
            self._band.show()
            return True
        if self._box_start is None:
            return False
        rect = QRect(self._box_start, event.position().toPoint()).normalized()
        if kind == QEvent.MouseMove:
            self._band.setGeometry(rect)
            return True
        if kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            self._band.hide()
            self._box_start = None
            if rect.width() >= 4 and rect.height() >= 4:  # a click without a drag does nothing
                self._zoom_to(rect)
                self.set_box_zoom(False)
                self.box_zoom_finished.emit()
            return True
        return False

    def close_plotter(self) -> None:
        self.cube.close()
        self._clear()
        self.plotter.close()

    # -- internals ----------------------------------------------------------
    # -- probes ---------------------------------------------------------------
    def clear_probes(self) -> None:
        self._probes.clear()
        if self._last is not None:
            self.show_result(*self._last)

    def eventFilter(self, obj, event):
        if self._box and obj is self.plotter.interactor and hasattr(event, "button")                 and event.type() in (QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.MouseButtonRelease):
            if self._box_event(event):
                return True
        if obj is self.plotter.interactor and hasattr(event, "button") and event.button() == Qt.RightButton:
            if event.type() == QEvent.MouseButtonPress:
                self._press = event.position()
            elif event.type() == QEvent.MouseButtonRelease and self._press is not None:
                press, self._press = self._press, None
                pos = event.position()
                if (pos - press).manhattanLength() <= CLICK_TOLERANCE:  # a click, not a zoom drag
                    self._probe_click(pos)
        return False

    def _probe_click(self, pos) -> None:
        if self._shown is None:
            return
        wid = self.plotter.interactor
        ratio = wid.devicePixelRatioF()
        x, y = pos.x() * ratio, (wid.height() - pos.y()) * ratio  # VTK counts pixels from the bottom
        picker = vtkCellPicker()
        picker.SetTolerance(0.0005)
        picker.PickFromListOn()
        picker.AddPickList(self._actor)
        if picker.Pick(x, y, 0, self.plotter.renderer) and picker.GetCellId() >= 0:
            self._probes.append(probes.make_probe(self._shown, picker.GetCellId(), picker.GetPickPosition()))
        else:
            self._probes.clear()  # a right click on empty space removes the probes
        self.show_result(*self._last)

    def _size(self) -> tuple[int, int]:
        return tuple(self.plotter.ren_win.GetSize())

    def capture(self, scale: int = 1):
        """The view as an RGB array, `scale` times larger than on screen.

        A larger picture is drawn again in an off-screen window of that size, with the pixel sizes of the
        overlays (fonts, colour bar, symbols, probes, lines) multiplied, so text and lines stay sharp
        instead of being enlarged.
        """
        pl = self.plotter
        if scale <= 1 or self._last is None:
            return pl.screenshot(return_img=True)
        width, height = pl.ren_win.GetSize()
        big = ResultViewer(offscreen_size=(width * scale, height * scale))
        try:
            big.plotter.ren_win.SetSize(width * scale, height * scale)
            big.plotter.ren_win.Render()  # creates the window at its real size before anything is laid out
            big.plotter._first_time = False  # the plotter is used without show(): draw and grab directly
            big._k, big._theme, big.fonts = scale, self._theme, dict(self.fonts)
            big.probe_size, big.probe_color, big._probes = self.probe_size, self.probe_color, list(self._probes)
            big.units = self.units
            big.ruler = self.ruler
            big.triad_visible = self.triad_visible
            big.links_visible = self.links_visible
            big.overlay_visible, big.overlay_opacity = self.overlay_visible, self.overlay_opacity
            big.info, big.info_visible, big.logo_visible = self.info, self.info_visible, self.logo_visible
            big.cube.visible, big.cube.style = self.cube.visible, self.cube.style
            big.cube.ratio = scale * self.cube.pixel_ratio()
            big._apply_triad_visibility()
            big.hidden_parts = self.hidden_parts
            big.section = self.section
            big.entity_colors, big.color_by_entity = dict(self.entity_colors), self.color_by_entity
            big.background, big.triad = self.background, dict(self.triad)
            big._apply_background()
            big._style_axes()
            big.cube.restyle()
            axes = big.plotter.renderer.axes_actor
            for t in big._axis_labels:
                t.GetTextProperty().SetFontSize(AXES_FONT_SIZE * scale)
            for part in (axes.GetXAxisShaftProperty(), axes.GetYAxisShaftProperty(), axes.GetZAxisShaftProperty()):
                part.SetLineWidth(3 * scale)
            big.show_result(*self._last)
            big.plotter.camera_position = pl.camera_position
            big.plotter.camera.parallel_scale = pl.camera.parallel_scale  # the zoom of an orthographic camera
            big.plotter.ren_win.Render()  # overlays are laid out at the end of a frame, so draw twice:
            big.plotter.ren_win.Render()  # the second frame uses the final camera
            return big.plotter.screenshot(return_img=True)
        finally:
            big.close_plotter()
            big.deleteLater()

    def set_fonts(self, fonts: dict[str, FontSpec]) -> None:
        self.fonts = dict(fonts)
        if self._last is not None:
            self.show_result(*self._last)

    def set_entities(self, colors: dict[str, str], by_entity: bool) -> None:
        """Colours of the kinds of cells and whether they replace the result colours."""
        self.entity_colors, self.color_by_entity = dict(colors), bool(by_entity)
        if self._last is not None:
            self.show_result(*self._last)

    def set_background(self, spec: dict | None) -> None:
        """Custom background (modelcolors.background_loads), or None for the theme's own."""
        self.background = spec
        self._apply_background()
        self.cube.restyle()
        self.plotter.render()

    def set_triad(self, colors: dict[str, str]) -> None:
        """Colours of the triad arrows (x, y, z) and letters (empty = the theme's text colour)."""
        self.triad = dict(colors)
        self._style_axes()
        self.plotter.render()

    def set_section(self, section) -> None:
        """Hide one side of a plane: `section` = (axis, position, keep_other), or None for no plane."""
        self.section = section
        if self._last is not None:
            self.show_result(*self._last)

    def set_hidden_parts(self, parts) -> None:
        self.hidden_parts = frozenset(parts)
        if self._last is not None:
            self.show_result(*self._last)

    def blank(self) -> None:
        """Remove the result from the view (used when there is nothing to show)."""
        self._clear()
        self.plotter.render()

    def unload(self) -> None:
        """Forget the model: empty view, no probes, nothing to redraw (a new project is being loaded)."""
        self.blank()
        self._last = None
        self.clear_probes()

    def set_cube_style(self, style: str) -> None:
        """Look of the view cube: "vivid" or "calmer" (modelcolors.CUBE_STYLES)."""
        self.cube.style = modelcolors.cube_style_loads(style)
        self.cube.restyle()
        self.plotter.render()

    def set_cube_visible(self, on: bool) -> None:
        self.cube.set_visible(on)
        self.plotter.render()

    def set_overlay(self, on: bool, opacity: float) -> None:
        self.overlay_visible, self.overlay_opacity = bool(on), float(opacity)
        if self._last is not None:
            self.show_result(*self._last)

    def set_links_visible(self, on: bool) -> None:
        self.links_visible = bool(on)
        if self._last is not None:
            self.show_result(*self._last)

    def set_logo_visible(self, on: bool) -> None:
        self.logo_visible = bool(on)
        if self._last is not None:
            self.show_result(*self._last)

    def set_info_visible(self, on: bool) -> None:
        self.info_visible = bool(on)
        if self._last is not None:
            self.show_result(*self._last)

    def set_ruler(self, on: bool) -> None:
        self.ruler = on
        if self._last is not None:
            self.show_result(*self._last)

    def set_units(self, units: Units) -> None:
        self.units = units
        if self._last is not None:
            self.show_result(*self._last)

    def set_probe_color(self, name: str) -> None:
        self.probe_color = name
        if self._last is not None:
            self.show_result(*self._last)

    def set_probe_size(self, diameter: int) -> None:
        self.probe_size = diameter
        if self._last is not None:
            self.show_result(*self._last)

    def _make_disc(self, colour: tuple[float, float, float]):
        """A filled circle drawn in screen pixels; returns place(x, y, radius)."""
        count = 24
        pts = vtkPoints()
        pts.SetNumberOfPoints(count)
        cells = vtkCellArray()
        cells.InsertNextCell(count)
        for k in range(count):
            cells.InsertCellPoint(k)
        pd = vtkPolyData()
        pd.SetPoints(pts)
        pd.SetPolys(cells)
        mp = vtkPolyDataMapper2D()
        mp.SetInputData(pd)
        ac = vtkActor2D()
        ac.SetMapper(mp)
        ac.GetProperty().SetColor(*colour)
        self.plotter.add_actor(ac, reset_camera=False, pickable=False)
        angles = np.linspace(0, 2 * np.pi, count, endpoint=False)

        def place(x, y, r):
            for k, a in enumerate(angles):
                pts.SetPoint(k, x + r * np.cos(a), y + r * np.sin(a), 0)
            pts.Modified()
            pd.Modified()
        return place

    def _world_per_pixel(self, height: float) -> float:
        """Model length covered by one screen pixel at the point the camera looks at."""
        cam = self.plotter.camera
        if cam.parallel_projection:
            return 2 * cam.parallel_scale / height
        distance = float(np.linalg.norm(np.array(cam.focal_point) - np.array(cam.position)))
        return 2 * distance * np.tan(np.radians(cam.view_angle) / 2) / height

    def _build_watermark(self) -> None:
        """"OpenCourantRP <version>", slanted and faint, in the bottom left corner."""
        text = vtkTextActor()
        text.SetInput(f"OpenCourantRP {__version__}")
        prop = text.GetTextProperty()
        prop.SetFontFamilyAsString("Arial")
        prop.SetFontSize(int(WATERMARK_SIZE * self._k))
        prop.SetItalic(True)
        prop.SetBold(False)
        prop.SetShadow(False)
        prop.SetColor(*rgb(self._theme.view_text))
        prop.SetOpacity(WATERMARK_OPACITY)
        prop.SetJustificationToLeft()
        prop.SetVerticalJustificationToBottom()
        text.SetPosition(WATERMARK_MARGIN * self._k, WATERMARK_MARGIN * self._k)
        self.plotter.add_actor(text, reset_camera=False, pickable=False)

    def _build_info(self) -> None:
        """Model name, time and frame in the top right corner, every line aligned to the right edge."""
        pl = self.plotter
        text = vtkTextActor()
        text.SetInput("\n".join(info_lines(self.info, self.units.time)))
        prop = text.GetTextProperty()
        apply_font(prop, self.fonts["info"], rgb(self._theme.view_text), self._k)
        prop.SetJustificationToRight()
        prop.SetVerticalJustificationToTop()
        prop.SetLineSpacing(1.2)
        pl.add_actor(text, reset_camera=False, pickable=False)

        def update(*_):
            if pl._closed:
                return
            W, H = self._size()
            if W > 0 and H > 0:
                text.SetPosition(W - INFO_MARGIN * self._k, H - INFO_MARGIN * self._k)

        self._info_observer = pl.ren_win.AddObserver("EndEvent", update)
        update()

    def _build_ruler(self) -> None:
        """Ruler at the bottom middle of the view: a fixed third of the width, with numbers that follow the zoom."""
        pl, t = self.plotter, self._theme
        frame = self._make_frame(t.base, None)  # a plain panel, no border; drawn first so the rest is on top of it
        n_ticks = RULER_DIVISIONS + 1
        pts = vtkPoints()
        pts.SetNumberOfPoints(2 * n_ticks + 2)
        cells = vtkCellArray()
        cells.InsertNextCell(2)  # baseline
        cells.InsertCellPoint(2 * n_ticks)
        cells.InsertCellPoint(2 * n_ticks + 1)
        for i in range(n_ticks):
            cells.InsertNextCell(2)
            cells.InsertCellPoint(2 * i)
            cells.InsertCellPoint(2 * i + 1)
        pd = vtkPolyData()
        pd.SetPoints(pts)
        pd.SetLines(cells)
        mp = vtkPolyDataMapper2D()
        mp.SetInputData(pd)
        ticks = vtkActor2D()
        ticks.SetMapper(mp)
        ticks.GetProperty().SetColor(*rgb(t.view_text))
        ticks.GetProperty().SetLineWidth(1.5 * self._k)
        pl.add_actor(ticks, reset_camera=False, pickable=False)

        def make_text(text, centered):
            tx = vtkTextActor()
            tx.SetInput(text)
            prop = tx.GetTextProperty()
            apply_font(prop, self.fonts["ruler"], rgb(t.view_text), self._k)
            prop.SetVerticalJustificationToCentered()
            prop.SetJustificationToCentered() if centered else prop.SetJustificationToLeft()
            pl.add_actor(tx, reset_camera=False, pickable=False)
            return tx

        n_major = RULER_DIVISIONS // RULER_MINOR_PER_MAJOR + 1
        labels = [make_text("0", True) for _ in range(n_major)]
        unit = self.units.length
        unit_text = make_text(unit, False) if unit else None

        def update(*_):
            if pl._closed:
                return
            W, H = self._size()
            if W <= 0 or H <= 0:
                return
            sc = self._k
            length = W / 3  # the ruler always spans a third of the view
            x0 = (W - length) / 2
            total = self._world_per_pixel(H) * length
            for i, lab in enumerate(labels):
                text = ruler_number(total * i / (n_major - 1))
                if lab.GetInput() != text:
                    lab.SetInput(text)
            lb = [0, 0, 0, 0]
            labels[-1].GetBoundingBox(pl.renderer, lb)
            label_h = lb[3] - lb[2]
            pad, gap, major, minor = RULER_PAD * sc, 3 * sc, RULER_MAJOR * sc, RULER_MINOR * sc
            unit_w = 0.0
            if unit_text is not None:
                ub = [0, 0, 0, 0]
                unit_text.GetBoundingBox(pl.renderer, ub)
                unit_w = ub[1] - ub[0] + 8 * sc
            box_h = pad + major + gap + label_h + pad
            bottom = RULER_BOTTOM * sc
            top = bottom + box_h
            y_base = bottom + pad
            edge = max(lb[1] - lb[0], 0) / 2  # half the widest number sticks out of the ends of the ruler
            frame(x0 - pad - edge, bottom, x0 + length + max(edge, 0) + unit_w + pad, top, sc, RULER_RADIUS * sc)
            pts.SetPoint(2 * n_ticks, x0, y_base, 0)
            pts.SetPoint(2 * n_ticks + 1, x0 + length, y_base, 0)
            for i in range(n_ticks):
                x = x0 + length * i / RULER_DIVISIONS
                size = major if i % RULER_MINOR_PER_MAJOR == 0 else minor
                pts.SetPoint(2 * i, x, y_base, 0)
                pts.SetPoint(2 * i + 1, x, y_base + size, 0)
            pts.Modified()
            pd.Modified()
            for i, lab in enumerate(labels):
                lab.SetPosition(x0 + length * i / (n_major - 1), y_base + major + gap + label_h / 2)
            if unit_text is not None:
                unit_text.SetPosition(x0 + length + 8 * sc, y_base + major / 2)

        self._ruler_observer = pl.ren_win.AddObserver("EndEvent", update)
        update()

    def _make_frame(self, fill: str, line: str | None):
        """A filled rectangle with optionally rounded corners, outlined unless `line` is None, in screen pixels.

        Returns place(x0, y0, x1, y1, line_width, radius=0).
        """
        pl = self.plotter
        steps = RADIUS_STEPS
        count = 4 * (steps + 1)  # every corner is an arc of steps + 1 points (all equal when the radius is 0)
        pts = vtkPoints()
        pts.SetNumberOfPoints(count)
        fill_cells = vtkCellArray()
        fill_cells.InsertNextCell(count)
        line_cells = vtkCellArray()
        line_cells.InsertNextCell(count + 1)
        for k in range(count):
            fill_cells.InsertCellPoint(k)
            line_cells.InsertCellPoint(k)
        line_cells.InsertCellPoint(0)
        actors = []
        for cells, colour, opacity in ((fill_cells, fill, 0.92), (line_cells, line, 1.0)):
            if colour is None:  # no border
                actors.append(None)
                continue
            pd = vtkPolyData()
            pd.SetPoints(pts)
            if cells is fill_cells:
                pd.SetPolys(cells)
            else:
                pd.SetLines(cells)
            mp = vtkPolyDataMapper2D()
            mp.SetInputData(pd)
            ac = vtkActor2D()
            ac.SetMapper(mp)
            ac.GetProperty().SetColor(*rgb(colour))
            ac.GetProperty().SetOpacity(opacity)
            pl.add_actor(ac, reset_camera=False, pickable=False)
            actors.append(ac)
        angles = np.linspace(0.0, np.pi / 2, steps + 1)

        def place(x0, y0, x1, y1, line_width, radius=0.0):
            r = max(0.0, min(radius, (x1 - x0) / 2, (y1 - y0) / 2))
            # counter-clockwise from the bottom-left corner; each arc turns by 90 degrees
            corners = ((x0 + r, y0 + r, np.pi), (x1 - r, y0 + r, 1.5 * np.pi), (x1 - r, y1 - r, 0.0), (x0 + r, y1 - r, 0.5 * np.pi))
            k = 0
            for cx, cy, start in corners:
                for a in angles:
                    pts.SetPoint(k, cx + r * np.cos(start + a), cy + r * np.sin(start + a), 0)
                    k += 1
            pts.Modified()
            if actors[1] is not None:
                actors[1].GetProperty().SetLineWidth(line_width)
        return place

    def _draw_probes(self) -> None:
        """A dot and an info box for every probe; both follow the probed point on screen."""
        pl, t = self.plotter, self._theme
        if self._probe_observer is not None:
            pl.ren_win.RemoveObserver(self._probe_observer)
            self._probe_observer = None
        items = []  # (dot centre, outline, dot, text actor)
        for pr in (self._probes if self._shown is not None else []):  # nothing to read in the color-by-entity view
            pos, lines = probes.read_probe(self._shown, self._name, self._var.raw, self._var.title, pr,
                                           self.units.of(self._var.quantity), self.units.length)
            if pos is None:
                continue
            outline = self._make_disc(PROBE_HALO)  # dot with a halo: visible on any colour
            dot = self._make_disc(MARK_COLORS.get(self.probe_color, MARK_COLORS[DEFAULT_PROBE_COLOR]))
            frame = self._make_frame(t.base, t.view_text)  # drawn first, so the text is on top of it
            box = vtkTextActor()
            box.SetInput("\n".join(lines))
            prop = box.GetTextProperty()
            apply_font(prop, self.fonts["probes"], rgb(t.view_text), self._k)
            greek = unicode_font_file(self.fonts["probes"]) if any(ord(ch) > 127 for ch in box.GetInput()) else None
            if greek:  # σ, ε, τ: not in the fonts VTK carries
                prop.SetFontFamily(VTK_FONT_FILE)
                prop.SetFontFile(greek)
                prop.SetBold(False)
                prop.SetItalic(False)
            prop.SetJustificationToLeft()
            prop.SetVerticalJustificationToBottom()
            pl.add_actor(box, reset_camera=False, pickable=False)
            items.append((pos, outline, dot, box, frame))
        if not items:
            return
        coord = vtkCoordinate()
        coord.SetCoordinateSystemToWorld()

        def place(*_):
            if pl._closed:
                return
            W, H = self._size()
            sc = self._k
            r = self.probe_size * sc / 2
            for pos, outline, dot, box, frame in items:
                coord.SetValue(*[float(c) for c in pos])
                x, y = coord.GetComputedDoubleDisplayValue(pl.renderer)
                outline(x, y, r + 1.5 * sc)
                dot(x, y, r)
                bbox = [0, 0, 0, 0]
                box.GetBoundingBox(pl.renderer, bbox)
                pad = PROBE_BOX_PAD * sc
                w, h = bbox[1] - bbox[0] + 2 * pad, bbox[3] - bbox[2] + 2 * pad
                bx = min(max(x + PROBE_BOX_OFFSET * sc, 2), max(W - w - 8 * sc, 2))  # keep the box inside the view
                by = min(max(y + PROBE_BOX_OFFSET * sc, 2), max(H - h - 8 * sc, 2))
                frame(bx, by, bx + w, by + h, sc)
                box.SetPosition(bx + pad, by + pad)

        self._probe_observer = pl.ren_win.AddObserver("EndEvent", place)
        place()

    def _clear(self) -> None:
        pl = self.plotter
        if self._ruler_observer is not None:
            pl.ren_win.RemoveObserver(self._ruler_observer)
            self._ruler_observer = None
        if self._info_observer is not None:
            pl.ren_win.RemoveObserver(self._info_observer)
            self._info_observer = None
        if self._probe_observer is not None:
            pl.ren_win.RemoveObserver(self._probe_observer)
            self._probe_observer = None
        if self._observer is not None:
            pl.ren_win.RemoveObserver(self._observer)
            self._observer = None
        pl.clear_actors()
        for t in self._axis_labels:  # clear_actors drops the triad letters too
            pl.add_actor(t, reset_camera=False, pickable=False)

    def _build_colorbar(self, actor, vmin: float, vmax: float, title_text: str, opts: ColorOptions, marks,
                        unit: str = "") -> None:
        pl = self.plotter
        n = opts.ncolors
        number = number_format(opts.digits, opts.fmt)
        o = 1 if opts.cap else 0  # a cap block sits below and above the n colour blocks
        m = n + 2 * o

        def to_rgb255(c):
            return [int(round(v * 255)) for v in c]

        # Block colours come from the mesh's own lookup table so they match exactly
        lut = actor.mapper.lookup_table
        colors = vtkUnsignedCharArray()
        colors.SetNumberOfComponents(3)
        if o:
            colors.InsertNextTuple3(*to_rgb255(pv.Color(CAP_BELOW).float_rgb))
        for i in range(n):
            colors.InsertNextTuple3(*to_rgb255(lut.GetTableValue(i)[:3]))
        if o:
            colors.InsertNextTuple3(*to_rgb255(pv.Color(CAP_ABOVE).float_rgb))

        block_pts = vtkPoints()
        block_pts.SetNumberOfPoints(4 * m)
        quads = vtkCellArray()
        for i in range(m):
            quads.InsertNextCell(4)
            for k in range(4):
                quads.InsertCellPoint(4 * i + k)
        poly = vtkPolyData()
        poly.SetPoints(block_pts)
        poly.SetPolys(quads)
        poly.GetCellData().SetScalars(colors)

        mapper = vtkPolyDataMapper2D()
        mapper.SetInputData(poly)
        mapper.SetScalarModeToUseCellData()
        mapper.SetColorModeToDirectScalars()
        block_actor = vtkActor2D()
        block_actor.SetMapper(mapper)
        pl.add_actor(block_actor, reset_camera=False, pickable=False)

        def make_text(text, item, centered=False):
            t = vtkTextActor()
            t.SetInput(text)
            prop = t.GetTextProperty()
            apply_font(prop, self.fonts[item], rgb(self._theme.view_text), self._k)
            prop.SetVerticalJustificationToCentered()
            if centered:
                prop.SetJustificationToCentered()
            else:
                prop.SetJustificationToLeft()
            pl.add_actor(t, reset_camera=False, pickable=False)
            return t

        def make_symbol(shape):
            """A small magenta triangle / square drawn in screen pixels; returns place(x, y, half_size)."""
            count = 3 if shape == "triangle" else 4
            pts = vtkPoints()
            pts.SetNumberOfPoints(count)
            cells = vtkCellArray()
            cells.InsertNextCell(count)
            for k in range(count):
                cells.InsertCellPoint(k)
            pd = vtkPolyData()
            pd.SetPoints(pts)
            pd.SetPolys(cells)
            mp = vtkPolyDataMapper2D()
            mp.SetInputData(pd)
            ac = vtkActor2D()
            ac.SetMapper(mp)
            ac.GetProperty().SetColor(*MARK_COLORS.get(opts.mark_color, MARK_COLORS[DEFAULT_MARK_COLOR]))
            pl.add_actor(ac, reset_camera=False, pickable=False)

            def place(x, y, r):
                if shape == "triangle":
                    corners = ((x, y + r), (x - r, y - r), (x + r, y - r))
                else:
                    corners = ((x - r, y - r), (x + r, y - r), (x + r, y + r), (x - r, y + r))
                for k, (px, py) in enumerate(corners):
                    pts.SetPoint(k, px, py, 0)
                pts.Modified()
                pd.Modified()
            return place

        labels = []
        for k, v in enumerate(np.linspace(vmin, vmax, n + 1)):
            prefix = "<" if (o and k == 0) else ">" if (o and k == n) else ""
            labels.append(make_text(prefix + number.format(v), "ticks"))
        title = make_text(title_text, "title", centered=True)
        unit_line = None
        if unit:  # second line, [unit]: its own text so that the brackets can come from a font that has them
            unit_line = make_text(f"[{unit}]", "title", centered=True)
            bracket_font = bracket_font_file(self.fonts["title"])
            if bracket_font:
                unit_line.GetTextProperty().SetFontFamily(VTK_FONT_FILE)
                unit_line.GetTextProperty().SetFontFile(bracket_font)

        if marks is not None:
            (max_xyz, max_val, max_id), (min_xyz, min_val, min_id) = marks
            max_on_model, min_on_model = make_symbol("triangle"), make_symbol("square")
            max_in_legend, min_in_legend = make_symbol("triangle"), make_symbol("square")
            max_text = make_text(with_unit("Max " + number.format(max_val), unit), "minmax")
            min_text = make_text(with_unit("Min " + number.format(min_val), unit), "minmax")
            max_where, min_where = make_text(max_id, "minmax"), make_text(min_id, "minmax")  # node / element of the extreme
            coord = vtkCoordinate()
            coord.SetCoordinateSystemToWorld()

        def update_colorbar(*_):
            if pl._closed:
                return
            W, H = self._size()
            if W <= 0 or H <= 0:
                return
            bar_h = BAR_HEIGHT_FRAC * H
            sc = self._k
            tb = [0, 0, 0, 0]
            title.GetBoundingBox(pl.renderer, tb)
            title_h = tb[3] - tb[2]
            if unit_line is not None:  # the unit sits right above the bar, the title above the unit
                ub = [0, 0, 0, 0]
                unit_line.GetBoundingBox(pl.renderer, ub)
                above = TITLE_GAP * sc + (ub[3] - ub[2]) / 2 + title_h + 2 * sc
            else:
                above = TITLE_GAP * sc + title_h / 2
            y0 = H - TOP_MARGIN * sc - above - bar_h  # the title block ends TOP_MARGIN below the top of the view
            gap, bar_w, pad = GAP * sc, BAR_W * sc, LABEL_PAD * sc
            block_h = (bar_h - gap * (m - 1)) / m
            text_w = 0
            for t in labels:
                bbox = [0, 0, 0, 0]
                t.GetBoundingBox(pl.renderer, bbox)  # xmin, xmax, ymin, ymax
                text_w = max(text_w, bbox[1] - bbox[0])
            x_left = LEFT_MARGIN * sc
            x_right = x_left + bar_w
            for i in range(m):
                yb = y0 + i * (block_h + gap)
                yt = yb + block_h
                block_pts.SetPoint(4 * i + 0, x_left, yb, 0)
                block_pts.SetPoint(4 * i + 1, x_right, yb, 0)
                block_pts.SetPoint(4 * i + 2, x_right, yt, 0)
                block_pts.SetPoint(4 * i + 3, x_left, yt, 0)
            block_pts.Modified()
            poly.Modified()

            for k, t in enumerate(labels):  # numbers sit on the boundaries between colour blocks
                if not o and k == 0:
                    y = y0
                elif not o and k == n:
                    y = y0 + bar_h
                else:
                    y = y0 + (k + o) * block_h + (k + o - 1) * gap + gap / 2
                t.SetPosition(x_right + pad, y)

            x_title = x_left + (bar_w + pad + text_w) / 2  # centred over blocks + numbers
            x_title = max(x_title, (tb[1] - tb[0]) / 2 + 4 * sc)  # a wide title must not leave the view on the left
            y_title = y0 + bar_h + TITLE_GAP * sc
            if unit_line is not None:  # the unit takes the title's place and the title moves up above it
                unit_line.SetPosition(x_title + TITLE_DX * sc, y_title)
                y_title += (ub[3] - ub[2]) / 2 + (tb[3] - tb[2]) / 2 + 2 * sc
            title.SetPosition(x_title + TITLE_DX * sc, y_title)

            if marks is not None:
                for xyz, place in ((max_xyz, max_on_model), (min_xyz, min_on_model)):
                    coord.SetValue(*[float(c) for c in xyz])
                    px, py = coord.GetComputedDoubleDisplayValue(pl.renderer)
                    place(px, py, opts.mark_size * sc / 2)
                y_max = y0 - LEGEND_ROW * 1.2 * sc
                y_max_where = y_max - LEGEND_ROW * sc
                y_min = y_max_where - LEGEND_ROW * 1.2 * sc
                y_min_where = y_min - LEGEND_ROW * sc
                r = opts.mark_size * sc * 0.4  # legend symbols: 80 % of the on-model ones
                widest = 0
                for tx in (max_text, min_text, max_where, min_where):
                    lb = [0, 0, 0, 0]
                    tx.GetBoundingBox(pl.renderer, lb)
                    widest = max(widest, lb[1] - lb[0])
                x_sym = x_left + r + 2 * sc
                x_sym -= max(0.0, x_sym + r + 8 * sc + widest - (W - 6 * sc))  # long units must not leave the view
                max_in_legend(x_sym, y_max, r)
                min_in_legend(x_sym, y_min, r)
                max_text.SetPosition(x_sym + r + 8 * sc, y_max)
                min_text.SetPosition(x_sym + r + 8 * sc, y_min)
                max_where.SetPosition(x_sym + r + 8 * sc, y_max_where)
                min_where.SetPosition(x_sym + r + 8 * sc, y_min_where)

        self._observer = pl.ren_win.AddObserver("EndEvent", update_colorbar)
        update_colorbar()
