"""The kinds of cells a result file holds and the colour each one is drawn in (no GUI dependencies).

Shells and solids carry the result and are coloured by it. Rigid bodies, springs, beams and rigid walls have no result
of their own, so they are drawn in a fixed colour; "Color by entity" paints every kind in its own colour instead.
"""

from __future__ import annotations

import json
import re

import numpy as np

SOLID_TYPES = (10, 12, 13, 14, 24, 25, 26, 27)  # VTK tetra, hexahedron, wedge, pyramid and their quadratic forms
SHELL_TYPES = (5, 9)  # VTK triangle, quad
LINE_TYPES = (3, 4, 21)  # VTK line, polyline, quadratic edge

# (key, label in the window, default colour, drawn in a fixed colour when the result is plotted)
ENTITIES = (
    ("shell", "Shell elements", "#4f81bd", False),
    ("solid", "Solid elements (volumes)", "#9bbb59", False),
    ("rigid", "Rigid bodies (lines, solids and shells)", "#7f7f7f", True),
    ("spring", "Springs and beams (lines)", "#f79646", True),
    ("wall", "Rigid walls (surfaces)", "#c0c0c0", True),
)
RIGID_ELEMENT = "_oc_rigid_element"  # cell array prepare_view adds: 1 for the solids and shells of a rigid body
WALL_PART = -1  # id of the "Rigid walls" pseudo-part in the Parts tab (real PART_IDs are positive)
EDGES = ("edges", "Mesh edges (Mesh button)", "#000000")
GHOST = ("ghost", "Undeformed overlay (Overlay button)", "#9aa5b1")
KEYS = tuple(e[0] for e in ENTITIES)
FIXED = tuple(e[0] for e in ENTITIES if e[3])
DEFAULTS = {**{e[0]: e[2] for e in ENTITIES}, EDGES[0]: EDGES[2], GHOST[0]: GHOST[2]}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def classify(mesh) -> np.ndarray:
    """The kind of every cell: shell, solid, rigid, spring or wall.

    A line cell with ELEMENT_ID 0 is a rigid body (the converter numbers real elements from 1), one with an id is a
    spring or beam; a surface cell with ELEMENT_ID 0 is a rigid wall.
    """
    types = np.asarray(mesh.celltypes)
    kind = np.full(mesh.n_cells, "shell", dtype="<U6")
    unnumbered = (np.asarray(mesh.cell_data["ELEMENT_ID"]) == 0 if "ELEMENT_ID" in mesh.cell_data
                  else np.zeros(mesh.n_cells, dtype=bool))
    line = np.isin(types, LINE_TYPES)
    kind[np.isin(types, SOLID_TYPES)] = "solid"
    kind[line & unnumbered] = "rigid"
    kind[line & ~unnumbered] = "spring"
    kind[~line & ~np.isin(types, SOLID_TYPES) & unnumbered] = "wall"
    if RIGID_ELEMENT in mesh.cell_data:
        kind[np.asarray(mesh.cell_data[RIGID_ELEMENT]) == 1] = "rigid"
    return kind


def _links(mesh) -> np.ndarray:
    """The cells that are the line links of a rigid body (line cells with ELEMENT_ID 0)."""
    return np.isin(np.asarray(mesh.celltypes), LINE_TYPES) & (classify(mesh) == "rigid")


def has_links(mesh) -> bool:
    return bool(_links(mesh).any())


def _connectivity(mesh):
    """(point ids of all cells in a row, the cell each one belongs to)."""
    return np.asarray(mesh.cell_connectivity), np.repeat(np.arange(mesh.n_cells), np.diff(mesh.cell_offsets))


def rigid_elements(mesh) -> np.ndarray:
    """The solids and shells the solver switched off because they belong to a rigid body.

    A rigid body replaces its elements (the starter lists them as "deactivated elements from rigid bodies"), so the file
    flags them dead from the first frame, like eroded ones. They are told apart by having every node on a rigid link:
    an eroded element keeps nodes that move on their own.
    """
    out = np.zeros(mesh.n_cells, dtype=bool)
    if "EROSION_STATUS" not in mesh.cell_data:
        return out
    links = _links(mesh)
    dead = np.isin(np.asarray(mesh.celltypes), SOLID_TYPES + SHELL_TYPES) & (np.asarray(mesh.cell_data["EROSION_STATUS"]) == 0)
    if not links.any() or not dead.any():
        return out
    conn, owner = _connectivity(mesh)
    on_link = np.zeros(mesh.n_points, dtype=bool)
    on_link[conn[links[owner]]] = True
    loose = np.zeros(mesh.n_cells, dtype=int)
    np.add.at(loose, owner[~on_link[conn]], 1)
    return dead & (loose == 0)


def cell_parts(mesh) -> np.ndarray:
    """The part of every cell. A rigid body's lines carry the id of the rigid body, not of its part (laminating:
    RBODY/1 on part 2 came out as 1), so they take the part of the surface/volume elements they touch."""
    parts = np.asarray(mesh.cell_data["PART_ID"]).copy()
    rigid = _links(mesh)
    if not rigid.any():
        return parts
    conn, owner = _connectivity(mesh)
    solid = ~np.isin(np.asarray(mesh.celltypes), LINE_TYPES)[owner]
    at_node = np.zeros(mesh.n_points, dtype=parts.dtype)
    np.maximum.at(at_node, conn[solid], parts[owner[solid]])
    touched = rigid[owner]
    best = np.zeros(mesh.n_cells, dtype=parts.dtype)
    np.maximum.at(best, owner[touched], at_node[conn[touched]])
    parts[rigid & (best > 0)] = best[rigid & (best > 0)]
    return parts


def part_ids(mesh) -> list[int]:
    """The ids of the Parts tab: the PART_ID of every cell except rigid walls, then WALL_PART when there are walls.

    A rigid wall is not a part of the model: the converter gives its cells the PART_ID of the part that defined them
    (checked on rigid_ball_impact: all 217 wall cells carry the id of the shell part), so they get an id of their own.
    """
    if "PART_ID" not in mesh.cell_data:
        return []
    wall = classify(mesh) == "wall"
    ids = sorted(int(i) for i in np.unique(cell_parts(mesh)[~wall]))
    return ids + [WALL_PART] if wall.any() else ids


def loads(text: str) -> dict[str, str]:
    """Colours {key: '#rrggbb'} from the settings; anything missing or invalid gets its default."""
    try:
        raw = json.loads(text)
    except (ValueError, TypeError):
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    return {k: (raw[k] if isinstance(raw.get(k), str) and _HEX.match(raw[k]) else d) for k, d in DEFAULTS.items()}


def dumps(colors: dict[str, str]) -> str:
    return json.dumps(colors)
