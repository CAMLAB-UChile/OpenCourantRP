"""The results that can be plotted, and how each one is read from a .vtk result file (no GUI dependencies).

Displacements, velocities and accelerations are stored at the nodes. Stresses, strains and the plastic strain of a shell are
stored per element at three places through the thickness (top = upper, middle = layer 3, bottom = lower);
``thickness`` picks one of them, or the largest ("max") / smallest ("min") of the three, or the "membrane" tensor
(the mean through the thickness) when the run wrote it. A run that wrote only the membrane tensor uses it as "middle".

A solid (hexahedron, tetrahedron, ...) has one value per element (``3DELEM_*`` arrays, tensors in the global axes), so the
choice through the thickness and the axes do not apply to it. In a file with both, each kind of element reads its own arrays.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import frames as shell_frames
from .entities import LINE_TYPES, SHELL_TYPES as _SHELL_TYPES, SOLID_TYPES as _SOLID_TYPES

AXES = ("global", "local")
DEFAULT_AXES = "global"
THICKNESS = ("top", "middle", "bottom", "max", "min", "membrane")
DEFAULT_THICKNESS = "middle"
_PLACE = {"top": "(upper)", "middle": "(layer__3)_", "bottom": "(lower)", "membrane": "(membrane)_"}
_PLASTIC = {"top": "2DELEM_Plastic_Strain_Upper", "middle": "2DELEM_Plastic_Strain",
            "bottom": "2DELEM_Plastic_Strain_Lower",
            "membrane": "2DELEM_Plastic_Strain_(membrane)_"}  # the solver does not write one: never there, so not available
_VON_MISES = "2DELEM_Von_Mises"  # the solver's own value: von Mises of the membrane (through-thickness mean) tensor
_DAMAGE = "2DELEM_MAX_DAMAGE_ELEMENT"
_NODAL_STEP = "Time_Step"
_NODAL_MAX = 1e5  # the solver writes 1e6 (and sometimes far more) where a node has no time step, 0 on rigid nodes
_SOLID_PLASTIC = "3DELEM_Plastic_Strain"
_SOLID_VON_MISES = "3DELEM_Von_Mises"
POS0 = "_oc_pos0"  # node coordinates before the deformation (added by viewer.prepare)
_TENSOR_INDEX = {"xx": 0, "xy": 1, "xz": 2, "yy": 4, "yz": 5, "zz": 8}  # the 9 numbers are the 3x3 tensor by rows


@dataclass(frozen=True)
class Variable:
    key: str  # short unique name, stored in the settings
    group: str  # heading it is listed under
    html: str  # its name in the list (rich text)
    math: str  # its name as the colour-bar title (matplotlib math text)
    title: str  # its name in plain text (probe boxes)
    kind: str  # "vector", "tensor", "plastic", "damage", "element" (one element array, `array`) or "node" (one node array)
    nodal: bool  # True: stored at the nodes; False: per element (can be smoothed to the nodes)
    quantity: str | None = None  # which declared unit it uses: "displacement", "stress", "temperature", ...; None: unitless
    array: str = ""  # vector kinds: the array in the file; tensor kinds: "Stress" or "Strain"
    part: str = ""  # a component ("x", "xy"), "mag" (magnitude), "1", "2", "3" (principal), "vm" or "tmax"
    optional: bool = False  # listed only when the result file holds it

    @property
    def name(self) -> str:
        """Name of the scalar array that is plotted."""
        return "oc_" + self.key

    @property
    def local(self) -> bool:
        """True for the tensor components, which the solver writes in the local axes of each element."""
        return self.kind == "tensor" and self.part in _TENSOR_INDEX

    @property
    def layered(self) -> bool:
        """True when the choice through the thickness matters."""
        return self.kind in ("tensor", "plastic")

    @property
    def raw(self) -> str:
        """Vector array a probe also reports the three components of (the total displacement / velocity)."""
        return self.array if self.kind == "vector" and self.part == "mag" else ""


def _build() -> list[Variable]:
    out: list[Variable] = []
    for group, letter, array, quantity, optional in (("Displacements", "U", "Displacement", "displacement", False),
                                                     ("Velocities", "V", "Velocity", "velocity", False),
                                                     ("Accelerations", "A", "Acceleration", "acceleration", True)):
        for axis in "xyz":  # accelerations: only when the engine deck asked for /ANIM/VECT/ACC
            out.append(Variable(f"{letter}{axis}", group, f"<i>{letter}</i><sub>{axis}</sub>", f"${letter}_{axis}$",
                                f"{letter}_{axis}", "vector", True, quantity, array, axis, optional=optional))
        out.append(Variable(letter, group, f"<i>{letter}</i>", f"${letter}$", letter, "vector", True, quantity, array, "mag",
                            optional=optional))
    for axis in "xyz":  # /ANIM/VECT/CONT: only when the engine deck asked for it
        out.append(Variable(f"F{axis}", "Contact forces", f"<i>F</i><sub>{axis}</sub>", f"$F_{axis}$", f"F_{axis}",
                            "vector", True, "force", "Contact_Forces", axis, optional=True))
    out.append(Variable("F", "Contact forces", "<i>F</i>", "$F$", "F", "vector", True, "force", "Contact_Forces", "mag",
                        optional=True))
    for group, symbol, key, base, quantity in (("Strains", "varepsilon", "e", "Strain", None),
                                               ("Stresses", "sigma", "s", "Stress", "stress")):
        glyph = "ε" if symbol == "varepsilon" else "σ"
        for comp in ("xx", "yy", "zz", "xy", "xz", "yz"):
            out.append(Variable(f"{key}{comp}", group, f"<i>{glyph}</i><sub>{comp}</sub>", f"$\\{symbol}_{{{comp}}}$",
                                f"{glyph}_{comp}", "tensor", False, quantity, base, comp))
        for n in "123":
            out.append(Variable(f"{key}{n}", group, f"<i>{glyph}</i><sub>{n}</sub>", f"$\\{symbol}_{{{n}}}$",
                                f"{glyph}_{n}", "tensor", False, quantity, base, n))
        if base == "Strain":
            out.append(Variable("epl", group, "<i>ε</i><sub>pl</sub>", "$\\varepsilon_{pl}$", "ε_pl", "plastic", False))
        else:
            out.append(Variable("svm", group, "<i>σ</i><sub>vm</sub>", "$\\sigma_{vm}$", "σ_vm", "tensor", False,
                                quantity, base, "vm"))
            out.append(Variable("tmax", group, "<i>τ</i><sub>max</sub>", "$\\tau_{max}$", "τ_max", "tensor", False,
                                quantity, base, "tmax"))
    out.append(Variable("damage", "Damage", "Damage", "Damage", "Damage", "damage", False, optional=True))
    out.append(Variable("ndt", "Nodal data", "Nodal time step", "Nodal time step", "Nodal time step", "node", True, None,
                        "Time_Step", optional=True))  # /ANIM/NODA/DT
    out.append(Variable("temp", "Nodal data", "Temperature", "Temperature", "Temperature", "node", True, "temperature",
                        "Nodal_Temperature", optional=True))  # /ANIM/NODA/TEMP
    out.append(Variable("dmas", "Nodal data", "Added mass", "Added mass", "Added mass", "node", True, "mass",
                        "Mass_Change", optional=True))  # /ANIM/NODA/DMAS
    out.append(Variable("ener", "Element data", "Specific energy", "Specific energy", "Specific energy", "element",
                        False, "energy/mass", "2DELEM_Specific_Energy", optional=True))  # /ANIM/ELEM/ENER
    out.append(Variable("dt", "Element data", "Time step", "Time step", "Time step", "element", False, None,
                        "2DELEM_Element_Time_Step", optional=True))  # /ANIM/ELEM/DT
    out.append(Variable("hourg", "Element data", "Hourglass energy", "Hourglass energy", "Hourglass energy", "element", False,
                        "energy/mass", "2DELEM_Hourglass_Energy_per_unit_mass", optional=True))  # /ANIM/ELEM/HOURG
    out.append(Variable("pres", "Element data", "Pressure", "Pressure", "Pressure", "element", False, "stress",
                        "2DELEM_Pressure", optional=True))  # /ANIM/ELEM/P
    out.append(Variable("dens", "Element data", "Density", "Density", "Density", "element", False, "mass/volume",
                        "2DELEM_Density", optional=True))  # /ANIM/ELEM/DENS
    return out


VARIABLES = _build()
DEFAULT_KEY = "U"
FALLBACK_KEYS = ("U", "V", "svm", "epl")  # tried in this order when the file lacks the selected variable
GROUPS = list(dict.fromkeys(v.group for v in VARIABLES))


def variable(key: str) -> Variable:
    """The variable called `key` (the default one when unknown)."""
    return next((v for v in VARIABLES if v.key == key), next(v for v in VARIABLES if v.key == DEFAULT_KEY))


def _places(thickness: str) -> tuple[str, ...]:
    return ("top", "middle", "bottom") if thickness in ("max", "min") else (thickness if thickness in _PLACE else "middle",)


def _centre_layer(prefix: str, suffix: str, mesh) -> int:
    """Number of the layer at the centre of the thickness among the ``prefix<n>suffix`` arrays of the file (3 when it
    holds none, the centre for N = 5). A shell with one integration point writes only layer 1, which is its middle."""
    if mesh is not None:
        found = sorted(int(k[len(prefix):-len(suffix)]) for k in mesh.cell_data.keys()
                       if k.startswith(prefix) and k.endswith(suffix) and k[len(prefix):-len(suffix)].isdigit())
        if found:
            return found[len(found) // 2]
    return 3


def _tensor_key(var: Variable, place: str, mesh=None) -> str:
    if place == "middle":
        return f"2DELEM_{var.array}_(layer__{_centre_layer(f'2DELEM_{var.array}_(layer__', ')_', mesh)})_"
    key = f"2DELEM_{var.array}_{_PLACE[place]}"
    alt = f"2DELEM_{var.array}_(membrane)"  # the stock engine writes the membrane tensor without the final underscore
    if place == "membrane" and mesh is not None and key not in mesh.cell_data and alt in mesh.cell_data:
        return alt
    return key


def _plastic_key(place: str, mesh=None) -> str:
    """Array the plastic strain reads at `place`; the middle falls back to the centre layer of /ANIM/SHELL/EPSP/ALL."""
    key = _PLASTIC[place]
    if place == "middle" and mesh is not None and key not in mesh.cell_data:
        prefix = "2DELEM_Plast_Strn_Layer___"
        layer = f"{prefix}{_centre_layer(prefix, '_', mesh)}_"
        if layer in mesh.cell_data:
            return layer
    return key


def _source(var: Variable, place: str, mesh) -> str:
    """Array a tensor variable reads at `place`. The middle is the centre-layer tensor; a run that wrote only the
    membrane tensor gets that one instead. The von Mises of the middle comes from the same tensor as the other
    components; the solver's own value (the von Mises of the membrane tensor, different where the shell bends)
    only stands in when the run wrote no tensor at all, and for "membrane" when its tensor is missing."""
    key = _tensor_key(var, place, mesh)
    if mesh is None or key in mesh.cell_data:
        return key
    if place == "middle" and _tensor_key(var, "membrane", mesh) in mesh.cell_data:
        return _tensor_key(var, "membrane", mesh)
    if var.part == "vm" and place in ("middle", "membrane"):
        return _VON_MISES
    return key


def required(var: Variable, thickness: str = DEFAULT_THICKNESS, mesh=None) -> list[tuple[str, bool]]:
    """[(array name, is a node array)] a variable needs for the given choice through the thickness."""
    if var.kind in ("vector", "node"):
        return [(var.array, True)]
    if var.kind == "damage":
        return [(_DAMAGE, False)]
    if var.kind == "element":
        return [(var.array, False)]
    names = []
    for place in _places(thickness):
        if var.kind == "plastic":
            names.append((_plastic_key(place, mesh), False))
        else:
            names.append((_source(var, place, mesh), False))
    return names


def _solid_cells(mesh) -> np.ndarray:
    return np.isin(np.asarray(mesh.celltypes), _SOLID_TYPES)


def has_solids(mesh) -> bool:
    return bool(_solid_cells(mesh).any())


def has_shells(mesh) -> bool:
    return bool(np.isin(np.asarray(mesh.celltypes), _SHELL_TYPES).any())


def _solid_key(var: Variable, mesh=None) -> str:
    """Array a solid element reads for `var` ("" when solids have none); the von Mises falls back to the solver's own."""
    if var.kind == "element":
        return var.array.replace("2DELEM_", "3DELEM_")
    if var.kind == "plastic":
        return _SOLID_PLASTIC
    if var.kind == "tensor":
        key = f"3DELEM_{var.array}"
        if var.part == "vm" and mesh is not None and key not in mesh.cell_data:
            return _SOLID_VON_MISES
        return key
    return ""


def _nodal_values(mesh, name: str) -> np.ndarray:
    """A nodal array with what is not a result turned into NaN, which is not coloured: the placeholders of the nodal time
    step (0, or huge), and the nodes that belong only to line cells (rigid bodies, springs), which hold 0."""
    values = np.asarray(mesh.point_data[name], dtype=float).copy()
    if name == _NODAL_STEP:
        values[(values <= 0) | (values >= _NODAL_MAX)] = np.nan
    offsets = np.asarray(mesh.cell_offsets)
    cell = np.repeat(np.arange(mesh.n_cells), np.diff(offsets))
    used = np.zeros(mesh.n_points, dtype=bool)
    used[np.asarray(mesh.cell_connectivity)[~np.isin(np.asarray(mesh.celltypes)[cell], LINE_TYPES)]] = True
    values[~used] = np.nan
    return values


def shell_available(var: Variable, mesh, thickness: str = DEFAULT_THICKNESS) -> bool:
    """Does the file hold what the shells need for `var` at this place through the thickness?"""
    return all(name in (mesh.point_data if node else mesh.cell_data) for name, node in required(var, thickness, mesh))


def solid_available(var: Variable, mesh) -> bool:
    key = _solid_key(var, mesh)
    return bool(key) and key in mesh.cell_data and has_solids(mesh)


def available(var: Variable, mesh, thickness: str = DEFAULT_THICKNESS) -> bool:
    if var.kind == "node":  # a run without /DT/NODA writes only placeholders: nothing to plot
        return shell_available(var, mesh) and bool(np.isfinite(_nodal_values(mesh, var.array)).any())
    if var.kind == "vector":
        return shell_available(var, mesh, thickness)
    return shell_available(var, mesh, thickness) or solid_available(var, mesh)


def _tensor_scalar(var: Variable, data: np.ndarray, frames: np.ndarray | None = None) -> np.ndarray:
    comp = var.part
    if comp in _TENSOR_INDEX:
        if frames is not None:  # turn the local components into global ones
            data = shell_frames.to_global(data, frames)
        return data[:, _TENSOR_INDEX[comp]]
    if comp == "vm":
        s = {c: data[:, i] for c, i in _TENSOR_INDEX.items()}
        return np.sqrt(0.5 * ((s["xx"] - s["yy"]) ** 2 + (s["yy"] - s["zz"]) ** 2 + (s["zz"] - s["xx"]) ** 2)
                       + 3 * (s["xy"] ** 2 + s["yz"] ** 2 + s["xz"] ** 2))
    full = data.reshape(-1, 3, 3)
    principal = np.linalg.eigvalsh(0.5 * (full + full.transpose(0, 2, 1)))  # ascending
    if comp == "tmax":
        return 0.5 * (principal[:, 2] - principal[:, 0])
    return principal[:, 3 - int(comp)]  # sigma_1 is the largest


def _file_points(mesh) -> np.ndarray:
    """Node positions as the result file stores them (original + displacement). The solver's element axes follow the
    current shape of each element, so the frames are built from these, whatever deformation scale is being drawn."""
    if POS0 in mesh.point_data and "Displacement" in mesh.point_data:
        return np.asarray(mesh.point_data[POS0]) + np.asarray(mesh.point_data["Displacement"])
    return np.asarray(mesh.points)


def evaluate(var: Variable, mesh, thickness: str = DEFAULT_THICKNESS, axes: str = "local") -> np.ndarray:
    """The scalar of `var`: one value per node (vector kinds) or per element (the others).

    With ``axes="global"`` the stress / strain components are rotated from the local axes of each element (the
    solver's) to the global ones, using the element geometry stored in the file; the other results do not depend on the axes.

    Solids read their own arrays (one value per element, global axes); where a file has both kinds the solid cells get
    the solid value and every other cell the shell value.

    Raises KeyError when the file does not hold what is needed.
    """
    if var.kind not in ("vector", "node") and solid_available(var, mesh):
        solid = _solid_values(var, mesh)
        if not shell_available(var, mesh, thickness):
            return solid
        values = _shell_values(var, mesh, thickness, axes)
        mask = _solid_cells(mesh)
        values[mask] = solid[mask]
        return values
    return _shell_values(var, mesh, thickness, axes)


def _solid_values(var: Variable, mesh) -> np.ndarray:
    data = np.asarray(mesh.cell_data[_solid_key(var, mesh)], dtype=float)
    return data if data.ndim == 1 else _tensor_scalar(var, data)


def _shell_values(var: Variable, mesh, thickness: str, axes: str) -> np.ndarray:
    for name, node in required(var, thickness, mesh):
        if name not in (mesh.point_data if node else mesh.cell_data):
            raise KeyError(f"'{name}' not found in the result file")
    if var.kind == "node":
        return _nodal_values(mesh, var.array)
    if var.kind == "vector":
        data = np.asarray(mesh.point_data[var.array], dtype=float)
        return np.linalg.norm(data, axis=1) if var.part == "mag" else data[:, "xyz".index(var.part)]
    if var.kind == "damage":
        return np.asarray(mesh.cell_data[_DAMAGE], dtype=float)
    if var.kind == "element":
        return np.asarray(mesh.cell_data[var.array], dtype=float).copy()
    frames = None
    if axes == "global" and var.local:
        frames = shell_frames.element_frames(mesh, _file_points(mesh))
    layers = []
    for place in _places(thickness):
        if var.kind == "plastic":
            layers.append(np.asarray(mesh.cell_data[_plastic_key(place, mesh)], dtype=float))
        else:
            key = _source(var, place, mesh)
            data = np.asarray(mesh.cell_data[key], dtype=float)
            layers.append(data if key == _VON_MISES else _tensor_scalar(var, data, frames))
    if len(layers) == 1:
        return layers[0].copy()
    return np.max(layers, axis=0) if thickness == "max" else np.min(layers, axis=0)
