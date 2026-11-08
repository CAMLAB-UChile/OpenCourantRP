"""The view cube: a small live cube in a corner of the 3D view that always shows how the model is turned.

 - it follows the main camera (same direction, same "up"), drawn by its own renderer in a corner viewport (the same trick as the axes triad);
 - dragging on it turns the main camera, so the model turns with it;
 - clicking a face turns the view to look at that face (+X ... -Z); clicking near an edge gives the 45 degree view of that edge, near a corner
   the isometric view of that corner (the side of the zone is EDGE of the cube side);
 - the zone under the mouse lights up before the click.

Two curved arrows on top of the cube (in the upper part of its square, at the two upper corners) turn the model in the plane of the screen by
ROLL_DEGREES per click: the left arrow turns it to the left (counterclockwise), the right arrow to the right. It is the stepwise version of
Ctrl + a circular mouse move.

Two looks (modelcolors.CUBE_STYLES): vivid (faces tinted with the axis colors, the default) and calmer (neutral faces). The cube sits in the
bottom right corner; its colors follow the background of the view (light or dark, also a custom one). This module comes from OpenCourantLab.

The geometry (which zone is under the pointer, which view a zone gives, the highlighted patches) is plain numpy at the top of the file; the
VTK actors and the Qt mouse handling come after.
"""
from __future__ import annotations

import math
from importlib import resources
from typing import Callable

import numpy as np
from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
from vtkmodules.vtkRenderingCore import vtkActor, vtkActor2D, vtkPolyDataMapper, vtkPolyDataMapper2D, vtkRenderer

SIZE = 130              # px (logical) of the cube's square viewport
MARGIN = 16             # px between the viewport and the corner of the 3D view
SCALE = 0.9             # parallel scale of the cube's camera: half the viewport's height in cube units
EDGE = 0.2              # width of the edge and corner zones, in cube units (the cube side is 1)
TILE_Z, PATCH_Z = 0.505, 0.509          # the face tiles and the highlight sit a little outside the body (half side 0.5)
DRAG_DEGREES = 1.2      # degrees of camera turn per pixel dragged on the cube
CLICK_PIXELS = 4
ARROW_H = 34            # px (logical) height of the strip with the two curved arrows
ROLL_DEGREES = 45.0     # one click on a curved arrow
STEPS, STEP_MS = 10, 18  # the turn to a clicked view: 10 steps about 0.2 s
LIGHT_LUMINANCE = 0.55  # a background brighter than this (0..1) gets the light cube
AXIS_COLOURS = {"X": "#f0805c", "Y": "#3fbf7f", "Z": "#5b86f0"}  # the colors of the labels of the faces
PALETTES = {  # tiles of the cube on a dark / on a light background
    "dark": {"tile": "#222832", "edge": "#3a4452", "accent": "#4c9eff", "on_accent": "#08101c", "core": "#0c1017", "arrow": "#39455B"},
    "light": {"tile": "#f3f5f8", "edge": "#c9d0dc", "accent": "#2f7de1", "on_accent": "#ffffff", "core": "#c3cbd8", "arrow": "#ABB4C2"},
}

LABELS = {"+X": 0, "-X": 0, "+Y": 1, "-Y": 1, "+Z": 2, "-Z": 2}
# face name: (axis index, sign, u direction, v direction): u to the right and v up when the face is looked at from outside, so that the label reads
# upright. The side faces are read with Z up; the Z faces with the text running along +Y, which reads upright from the isometric view of the
# Isometric button (1, 1, 1).
FACES = {
    "+X": (0, 1, (0, 1, 0), (0, 0, 1)), "-X": (0, -1, (0, -1, 0), (0, 0, 1)),
    "+Y": (1, 1, (-1, 0, 0), (0, 0, 1)), "-Y": (1, -1, (1, 0, 0), (0, 0, 1)),
    "+Z": (2, 1, (0, 1, 0), (-1, 0, 0)), "-Z": (2, -1, (0, 1, 0), (1, 0, 0)),
}


# ------------------------------------------------------------------ geometry (no VTK)
def _unit(v) -> np.ndarray:
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def region_at(direction, up, u: float, v: float, scale: float = SCALE):
    """The zone of the cube under a point of its viewport, or None. `direction`: the camera's direction of projection (from the camera to the
    cube); `up`: its view-up; (u, v): the point in the viewport, each in -1..1 from its centre. The zone is a tuple of three signs (-1, 0, 1):
    one non zero = a face, two = an edge, three = a corner."""
    d = _unit(direction)
    right = _unit(np.cross(d, up))
    true_up = np.cross(right, d)
    origin = right * (u * scale) + true_up * (v * scale) - d * 10.0          # a point on the ray, in front of the cube
    t_near, t_far, axis_in = -math.inf, math.inf, -1
    for i in range(3):
        if abs(d[i]) < 1e-12:
            if abs(origin[i]) > 0.5:
                return None
            continue
        t0, t1 = (-0.5 - origin[i]) / d[i], (0.5 - origin[i]) / d[i]
        if t0 > t1:
            t0, t1 = t1, t0
        if t0 > t_near:
            t_near, axis_in = t0, i
        t_far = min(t_far, t1)
    if axis_in < 0 or t_near > t_far:
        return None
    hit = origin + d * t_near
    s = [0, 0, 0]
    for i in range(3):
        if i == axis_in or abs(hit[i]) >= 0.5 - EDGE:
            s[i] = 1 if hit[i] >= 0 else -1
    return tuple(s)


def view_for_region(region) -> tuple[tuple, tuple]:
    """(vector from the model towards the camera, view-up) for a clicked zone. The ups are the ones of the camera buttons: Y up, except Z up
    when looking at a +Y or -Y face."""
    vec = tuple(float(c) for c in region)
    up = (0.0, 0.0, 1.0) if (region[0] == 0 and region[2] == 0) else (0.0, 1.0, 0.0)
    return vec, up


def patch_quads(region, edge: float = EDGE, z: float = PATCH_Z) -> list[np.ndarray]:
    """The quads that light up for a zone: on every face the zone touches, the part of that face inside the zone."""
    quads = []
    for a in range(3):
        if region[a] == 0:
            continue
        b, c = [i for i in range(3) if i != a]
        ranges = []
        for k in (b, c):
            ranges.append((region[k] * (0.5 - edge), region[k] * 0.5) if region[k] else (-(0.5 - edge), 0.5 - edge))
            ranges[-1] = tuple(sorted(ranges[-1]))
        quad = []
        for rb, rc in ((0, 0), (1, 0), (1, 1), (0, 1)):
            p = np.zeros(3)
            p[a], p[b], p[c] = region[a] * z, ranges[0][rb], ranges[1][rc]
            quad.append(p)
        quads.append(np.array(quad))
    return quads


def arrow_shape(width: float, height: float, scale: float = 1.0, side: str = "left") -> tuple[np.ndarray, np.ndarray]:
    """The curved arrow of the strip (pixels, origin bottom left of the strip): (triangles of the arc as an (n, 3, 2) array, the head as (3, 2)).
    The arc is part of an ellipse over the strip; the head is at its outer, lower end and points along the arc (down and outwards)."""
    rx, ry, cy = 0.475 * width, 0.94 * height, -0.02 * height
    a0, a1 = math.radians(116), math.radians(158)
    th = np.linspace(a0, a1, 14)
    pts = np.stack([width / 2 + rx * np.cos(th), cy + ry * np.sin(th)], axis=1)
    tang = np.stack([-rx * np.sin(th), ry * np.cos(th)], axis=1)
    tang /= np.linalg.norm(tang, axis=1)[:, None]
    nrm = np.stack([-tang[:, 1], tang[:, 0]], axis=1)
    half = 2.6 * scale
    head_len, head_half = 13.0 * scale, 8.0 * scale
    end = pts[-1]
    left, right = pts + nrm * half, pts - nrm * half
    tris = []
    for i in range(len(pts) - 1):
        tris.append([left[i], right[i], left[i + 1]])
        tris.append([right[i], right[i + 1], left[i + 1]])
    tip = end + tang[-1] * head_len
    head = np.array([end + nrm[-1] * head_half, end - nrm[-1] * head_half, tip])
    tris = np.array(tris)
    if side == "right":                                   # the mirror image
        tris[..., 0] = width - tris[..., 0]
        head[:, 0] = width - head[:, 0]
    return tris, head


def slerp(a, b, t: float) -> np.ndarray:
    """The unit vector a fraction t of the way from unit vector a to b along the great circle (a half turn goes round the Z or Y axis)."""
    a, b = _unit(a), _unit(b)
    dot = float(np.clip(a @ b, -1.0, 1.0))
    if dot > 1 - 1e-9:
        return b
    if dot < -1 + 1e-9:                                   # opposite: any perpendicular will do, take one that is not the view-up's axis
        mid = _unit(np.cross(a, (0.0, 0.0, 1.0) if abs(a[2]) < 0.9 else (0.0, 1.0, 0.0)))
        return slerp(a, mid, 2 * t) if t < 0.5 else slerp(mid, b, 2 * t - 1)
    ang = math.acos(dot)
    return (math.sin((1 - t) * ang) * a + math.sin(t * ang) * b) / math.sin(ang)


def is_light(top: str, bottom: str) -> bool:
    """True when a background (the two colors of its gradient, "#rrggbb") is light."""
    lum = sum(0.2126 * int(c[1:3], 16) + 0.7152 * int(c[3:5], 16) + 0.0722 * int(c[5:7], 16) for c in (top, bottom)) / 2 / 255
    return lum > LIGHT_LUMINANCE


def arrow_colour(top: str, bottom: str, frac: float) -> str:
    """Colour of the roll arrows for a cube whose centre is at `frac` of the view's height (0 bottom, 1 top). On a dark background it is the
    background there lightened a little, so the arrows stand out at every height of a gradient; on a light one the palette's colour contrasts everywhere."""
    if is_light(top, bottom):
        return PALETTES["light"]["arrow"]
    f = min(1.0, max(0.0, frac))
    bg = [int(bottom[i:i + 2], 16) * (1 - f) + int(top[i:i + 2], 16) * f for i in (1, 3, 5)]
    return "#" + "".join(f"{round(c + (255 - c) * 0.22):02x}" for c in bg)


# ------------------------------------------------------------------ the pictures on the faces
def _mix(a, b, t):
    return tuple(round(a[i] * (1 - t) + b[i] * t) for i in range(3))


def _rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def tile_image(label: str, style: str, palette: dict, size: int = 256, hover: bool = False) -> np.ndarray:
    """RGBA picture of one face: a rounded tile with the label. `style` is "vivid" (tinted with the axis color) or "calmer" (neutral tile, label in the axis color). `hover`: the tile under the mouse, filled with the accent color."""
    from PIL import Image, ImageDraw, ImageFont
    k = 4                                                    # drawn four times bigger and scaled down: smooth edges
    n = size * k
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    axis = _rgb(AXIS_COLOURS[label[1]])
    tile, edge = _rgb(palette["tile"]), _rgb(palette["edge"])
    dark = sum(tile) < 380
    ink = _mix(axis, (255, 255, 255), 0.35) if dark else axis
    if style == "vivid":
        fill, line = _mix(tile, axis, 0.30 if dark else 0.22), _mix(tile, axis, 0.65)
    else:
        fill, line = tile, edge                              # neutral tile; only the letters carry the axis color
    if hover:
        accent = _rgb(palette["accent"])
        fill, line, ink = accent, accent, _rgb(palette["on_accent"])
    margin, radius = int(0.07 * n), int(0.16 * n)
    draw.rounded_rectangle([margin, margin, n - margin, n - margin], radius, fill=fill + (255,), outline=line + (255,), width=int(0.018 * n))
    font = ImageFont.truetype(str(resources.files("opencourantrp").joinpath("resources", "fonts", "Inter-SemiBold.otf")), int(0.34 * n))
    text_label = label.replace("-", "−")                # a real minus sign
    draw.text((n / 2, n * 0.5), text_label, font=font, fill=ink + (255,), anchor="mm")
    return np.array(img.resize((size, size), Image.LANCZOS))


# ------------------------------------------------------------------ the widget
class ViewCube(QObject):
    """The cube of one 3D view. `plotter`: its plotter; `background`: gives the (top, bottom) colors of the view's background; `interactive`:
    False for a picture drawn without a window (no mouse); `ratio`: the pixel scale of a picture drawn without a window (a window uses its own);
    `on_user_view`: called when the user turned the view with the cube."""

    def __init__(self, plotter, background: Callable[[], tuple[str, str]], parent=None, interactive: bool = True,
                 on_user_view: Callable[[], None] | None = None):
        super().__init__(parent)
        import pyvista as pv
        self.plotter, self.background, self.interactive, self.on_user_view = plotter, background, interactive, on_user_view
        self.visible = True
        self.style = "vivid"
        self.ratio = 1.0
        self.main = plotter.renderer
        self.region = None                                    # the zone under the mouse
        self.rect = (0, 0, 0, 0)                              # the cube's viewport in device pixels (x0, y0, x1, y1), origin bottom left
        self._press = None                                    # (x, y, last x, last y, moved) of a left press on the cube
        self._anim = None
        self._timer = QTimer(self)
        self._timer.setInterval(STEP_MS)
        self._timer.timeout.connect(self._step)
        self.renderer = vtkRenderer()
        self.renderer.InteractiveOff()
        window = plotter.ren_win
        window.SetNumberOfLayers(max(2, window.GetNumberOfLayers()))
        self.renderer.SetLayer(1)
        window.AddRenderer(self.renderer)
        self.arrows = vtkRenderer()                       # the strip with the two curved arrows: its own small viewport next to the cube
        self.arrows.InteractiveOff()
        self.arrows.SetLayer(1)
        window.AddRenderer(self.arrows)
        self.arrow_actors, self.arrow_mappers = {}, {}
        for side in ("left", "right"):
            mapper = vtkPolyDataMapper2D()
            mapper.SetInputData(vtkPolyData())                # empty until the first layout (VTK complains about a mapper with no input)
            actor = vtkActor2D()
            actor.SetMapper(mapper)
            actor.PickableOff()
            self.arrows.AddViewProp(actor)
            self.arrow_actors[side], self.arrow_mappers[side] = actor, mapper
        self.arrow_rect = (0, 0, 0, 0)                        # the strip in device pixels (x0, y0, x1, y1), origin bottom left
        self.arrow_hover = None
        self._arrow_key = None
        self._cube_frac = 0.1                                 # height of the cube's centre in the view, 0 bottom .. 1 top (set at every layout)
        self._press_arrow = None
        self.core = self._actor(pv.Cube(x_length=1.0, y_length=1.0, z_length=1.0))
        self.tiles = {}
        for name, (axis, sign, u, v) in FACES.items():
            centre, u, v = np.zeros(3), np.array(u, float), np.array(v, float)
            centre[axis] = sign * TILE_Z
            pts = np.array([centre - u / 2 - v / 2, centre + u / 2 - v / 2, centre + u / 2 + v / 2, centre - u / 2 + v / 2])
            mesh = pv.PolyData(pts, np.array([4, 0, 1, 2, 3]))
            mesh.active_texture_coordinates = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float)
            self.tiles[name] = self._actor(mesh)
        self.patch = vtkActor()
        self.patch.GetProperty().LightingOff()
        self.patch.GetProperty().SetOpacity(0.55)
        self.patch.PickableOff()
        self.patch.SetVisibility(False)
        self.patch_mapper = vtkPolyDataMapper()
        self.patch.SetMapper(self.patch_mapper)
        self.renderer.AddActor(self.patch)                    # last: drawn after the tiles it lies over
        self._observer = self.renderer.AddObserver("StartEvent", self._update)
        if interactive:
            plotter.interactor.installEventFilter(self)
            plotter.interactor.setMouseTracking(True)
            self.restyle()  # a picture drawn without a window is styled by its owner, once the background is known

    def _actor(self, mesh) -> vtkActor:
        actor = vtkActor()
        mapper = vtkPolyDataMapper()
        mapper.SetInputData(mesh)
        actor.SetMapper(mapper)
        actor.GetProperty().LightingOff()
        actor.PickableOff()
        self.renderer.AddActor(actor)
        return actor

    # ---------------------------------------------------------------- look
    def restyle(self) -> None:
        """Colors and pictures for the look, the background now (light or dark) and the visibility."""
        import pyvista as pv
        palette = self.palette()
        self.core.GetProperty().SetColor(*[c / 255 for c in _rgb(palette["core"])])
        self.textures = {}
        for name, actor in self.tiles.items():
            for hover in (False, True):
                texture = pv.Texture(tile_image(name, self.style, palette, hover=hover))
                texture.SetInterpolate(True)
                texture.MipmapOn()
                self.textures[(name, hover)] = texture
            actor.SetTexture(self.textures[(name, False)])
        self.region = None
        self.patch.GetProperty().SetColor(*[c / 255 for c in _rgb(palette["accent"])])
        self.renderer.SetDraw(self.visible)
        self.arrows.SetDraw(self.visible)
        self._paint_arrows()

    def palette(self) -> dict:
        return PALETTES["light" if is_light(*self.background()) else "dark"]

    def set_visible(self, on: bool) -> None:
        self.visible = bool(on)
        self.renderer.SetDraw(self.visible)
        self.arrows.SetDraw(self.visible)

    def pixel_ratio(self) -> float:
        """Device pixels per logical pixel: the screen's own, or the scale of a picture drawn without a window."""
        return self.plotter.devicePixelRatioF() if self.interactive else self.ratio

    # ---------------------------------------------------------------- placement and camera
    def _update(self, renderer, _event=None) -> None:
        """Before every render: put the viewport in its corner and the cube's camera on the model's camera."""
        dpr = self.pixel_ratio()
        w, h = self.plotter.ren_win.GetSize()
        side, margin = SIZE * dpr, MARGIN * dpr
        if w < 2.5 * side or h < 2.5 * side:                  # a tiny window: no room for it
            renderer.SetViewport(0, 0, 0.0001, 0.0001)
            self.arrows.SetViewport(0, 0, 0.0001, 0.0001)
            self.rect = self.arrow_rect = (0, 0, 0, 0)
            return
        x0, y0 = w - margin - side, margin
        self.rect = (x0, y0, x0 + side, y0 + side)
        renderer.SetViewport(x0 / w, y0 / h, (x0 + side) / w, (y0 + side) / h)
        self._layout_arrows(w, h, x0, y0, side, dpr)
        frac = (y0 + side / 2) / h
        if abs(frac - self._cube_frac) > 0.01:                 # the cube moved to another height of the background gradient: the arrows follow its colour
            self._cube_frac = frac
            self._paint_arrows()
        main = self.main.GetActiveCamera()
        cam = renderer.GetActiveCamera()
        d = np.array(main.GetDirectionOfProjection())
        cam.ParallelProjectionOn()
        cam.SetParallelScale(SCALE)
        cam.SetFocalPoint(0.0, 0.0, 0.0)
        cam.SetPosition(*(-6.0 * d))
        cam.SetViewUp(*main.GetViewUp())
        renderer.ResetCameraClippingRange()

    def _paint_arrows(self) -> None:
        """Colors of the two arrows: the palette's `arrow` color (dark or light with the background), the accent color for the one under the mouse."""
        palette = self.palette()
        for side, actor in self.arrow_actors.items():
            hot = self.arrow_hover == side
            colour = palette["accent"] if hot else arrow_colour(*self.background(), self._cube_frac)
            actor.GetProperty().SetColor(*[c / 255 for c in _rgb(colour)])
            actor.GetProperty().SetOpacity(1.0)

    def _layout_arrows(self, w: float, h: float, x0: float, y0: float, side: float, k: float) -> None:
        """Put the strip with the arrows on top of the cube (the upper part of its square) and draw them for this size."""
        sh = ARROW_H * k
        ya = y0 + side - sh                                   # the strip is the top of the cube's own square: the arrows stand at the two upper corners
        self.arrow_rect = (x0, ya, x0 + side, ya + sh)
        self.arrows.SetViewport(x0 / w, ya / h, (x0 + side) / w, (ya + sh) / h)
        key = (round(side, 2), round(sh, 2), round(k, 3))
        if key == self._arrow_key:
            return
        self._arrow_key = key
        for name in ("left", "right"):
            tris, head = arrow_shape(side, sh, k, name)
            points, cells = vtkPoints(), vtkCellArray()
            for tri in [*tris, head]:
                ids = [points.InsertNextPoint(p[0], p[1], 0.0) for p in tri]
                cells.InsertNextCell(3, ids)
            poly = vtkPolyData()
            poly.SetPoints(points)
            poly.SetPolys(cells)
            self.arrow_mappers[name].SetInputData(poly)

    def arrow_at(self, x: float, y: float):
        """'left' or 'right' when a device pixel is over a curved arrow (the half of the strip it stands in), else None."""
        x0, y0, x1, y1 = self.arrow_rect
        if not (x1 > x0 and x0 <= x <= x1 and y0 <= y <= y1):
            return None
        u = (x - x0) / (x1 - x0)
        return "left" if u < 0.42 else ("right" if u > 0.58 else None)

    def set_arrow_hover(self, side) -> None:
        if side == self.arrow_hover:
            return
        self.arrow_hover = side
        self._paint_arrows()
        self.plotter.render()

    # ---------------------------------------------------------------- zones
    def contains(self, x: float, y: float) -> bool:
        x0, y0, x1, y1 = self.rect
        return x1 > x0 and x0 <= x <= x1 and y0 <= y <= y1

    def zone_at(self, x: float, y: float):
        """The zone under a device pixel (VTK coordinates), or None."""
        if not self.contains(x, y):
            return None
        x0, y0, x1, y1 = self.rect
        u, v = 2 * (x - x0) / (x1 - x0) - 1, 2 * (y - y0) / (y1 - y0) - 1
        cam = self.main.GetActiveCamera()
        return region_at(cam.GetDirectionOfProjection(), cam.GetViewUp(), u, v)

    def set_hover(self, region) -> None:
        """Light up a zone (None: none). Renders only when it changed."""
        if region == self.region:
            return
        for name, (axis, sign, _u, _v) in FACES.items():           # a face lights up by swapping its picture; edges and corners by a patch
            lit = region is not None and sum(map(abs, region)) == 1 and region[axis] == sign
            self.tiles[name].SetTexture(self.textures[(name, lit)])
        self.region = region
        patch = region is not None and sum(map(abs, region)) > 1
        self.patch.SetVisibility(patch)
        if patch:
            quads = patch_quads(region)
            points, cells = vtkPoints(), vtkCellArray()
            for quad in quads:
                ids = [points.InsertNextPoint(*p) for p in quad]
                cells.InsertNextCell(4, ids)
            poly = vtkPolyData()
            poly.SetPoints(points)
            poly.SetPolys(cells)
            self.patch_mapper.SetInputData(poly)
        self.plotter.render()

    # ---------------------------------------------------------------- turning the model
    def rotate(self, dx: float, dy: float) -> None:
        """Turn the main camera as a drag of (dx, dy) pixels (dx to the right, dy down) on the cube would: the model follows the pointer."""
        cam = self.main.GetActiveCamera()
        cam.Azimuth(-dx * DRAG_DEGREES)
        cam.Elevation(dy * DRAG_DEGREES)
        cam.OrthogonalizeViewUp()
        self.main.ResetCameraClippingRange()
        self._turned()

    def snap(self, region) -> None:
        """Turn the main camera to look at a zone, about the point it looks at (zoom and pan are kept)."""
        vec, up = view_for_region(region)
        cam = self.main.GetActiveCamera()
        focal = np.array(cam.GetFocalPoint())
        pos = np.array(cam.GetPosition())
        self._anim = {"focal": focal, "dist": float(np.linalg.norm(pos - focal)), "d0": _unit(pos - focal), "d1": _unit(vec),
                      "up0": _unit(cam.GetViewUp()), "up1": _unit(up), "n": 0}
        self._timer.start()

    def roll(self, degrees: float) -> None:
        """Turn the model in the plane of the screen by `degrees` (positive: to the left, counterclockwise), about the view direction, animated.
        Clicks in a row add up: each one starts from where the running turn is going."""
        cam = self.main.GetActiveCamera()
        a = self._anim
        d = _unit(a["d1"] if a else -np.array(cam.GetDirectionOfProjection()))        # from the focal point to the camera
        up = np.array(a["up1"] if a else cam.GetViewUp(), float)
        up = _unit(up - (up @ d) * d)                                                 # exactly across the view direction (the camera's own up need not be)
        right = _unit(np.cross(-d, up))                                               # the screen's right, in the model's axes
        ang = math.radians(degrees)
        up1 = math.cos(ang) * up + math.sin(ang) * right              # the model direction that comes to the top after the turn
        focal = np.array(cam.GetFocalPoint())
        self._anim = {"focal": focal, "dist": float(np.linalg.norm(np.array(cam.GetPosition()) - focal)), "d0": d, "d1": d,
                      "up0": _unit(cam.GetViewUp()), "up1": _unit(up1), "n": 0}
        self._timer.start()

    def _step(self) -> None:
        a = self._anim
        if a is None:
            self._timer.stop()
            return
        a["n"] += 1
        t = min(1.0, a["n"] / STEPS)
        e = t * t * (3 - 2 * t)                               # ease in and out
        d = slerp(a["d0"], a["d1"], e)
        up = (1 - e) * a["up0"] + e * a["up1"]
        if np.linalg.norm(up) < 1e-6:
            up = a["up1"]
        cam = self.main.GetActiveCamera()
        cam.SetPosition(*(a["focal"] + d * a["dist"]))
        cam.SetViewUp(*_unit(up))
        cam.OrthogonalizeViewUp()
        self.main.ResetCameraClippingRange()
        if t >= 1.0:
            self._timer.stop()
            self._anim = None
        self._turned()

    def _turned(self) -> None:
        if self.on_user_view:
            self.on_user_view()
        self.plotter.render()

    # ---------------------------------------------------------------- mouse
    def _vtk(self, event) -> tuple[float, float]:
        dpr, widget = self.plotter.devicePixelRatioF(), self.plotter.interactor
        pos = event.position()
        return pos.x() * dpr, (widget.height() - 1 - pos.y()) * dpr

    def eventFilter(self, obj, event) -> bool:
        t = event.type()
        if t == QEvent.MouseButtonPress and event.button() == Qt.LeftButton and self.visible:
            x, y = self._vtk(event)
            side = self.arrow_at(x, y)
            if side is not None:
                self._press_arrow = side
                return True
            if self.contains(x, y):
                self._timer.stop()
                self._anim = None
                pos = event.position()
                self._press = [pos.x(), pos.y(), pos.x(), pos.y(), False, self.zone_at(x, y)]
                return True                                   # the model must not start its own rotation
        elif t == QEvent.MouseMove and self._press is not None and event.buttons() & Qt.LeftButton:
            pos = event.position()
            p = self._press
            if not p[4] and (abs(pos.x() - p[0]) > CLICK_PIXELS or abs(pos.y() - p[1]) > CLICK_PIXELS):
                p[4] = True
            if p[4]:
                self.rotate(pos.x() - p[2], pos.y() - p[3])
            p[2], p[3] = pos.x(), pos.y()
            return True
        elif t == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton and self._press_arrow is not None:
            side, self._press_arrow = self._press_arrow, None
            x, y = self._vtk(event)
            if self.arrow_at(x, y) == side:
                self.roll(ROLL_DEGREES if side == "left" else -ROLL_DEGREES)
            return True
        elif t == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton and self._press is not None:
            moved, zone = self._press[4], self._press[5]
            self._press = None
            if not moved and zone is not None:
                self.snap(zone)
            return True
        elif t == QEvent.MouseMove and not (event.buttons() & (Qt.LeftButton | Qt.MiddleButton | Qt.RightButton)) and self.visible:
            x, y = self._vtk(event)
            self.set_arrow_hover(self.arrow_at(x, y))
            self.set_hover(self.zone_at(x, y))
        elif t == QEvent.Leave:
            self.set_hover(None)
            self.set_arrow_hover(None)
        return False

    def close(self) -> None:
        self._timer.stop()
        try:
            self.renderer.RemoveObserver(self._observer)
            if self.interactive:
                self.plotter.interactor.removeEventFilter(self)
            self.plotter.ren_win.RemoveRenderer(self.renderer)
            self.plotter.ren_win.RemoveRenderer(self.arrows)
        except RuntimeError:
            pass
