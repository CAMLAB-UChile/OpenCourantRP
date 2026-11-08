"""Probes: a point picked on the model whose value is read out, and followed from step to step.

A probe remembers the *original* ids of the element it was picked in and of the nearest node (the
mesh shown has eroded elements removed, so its own ids change from step to step). A variable stored
at the nodes (displacement, velocity, smoothed results) is read at that node; an element variable
(plastic strain, von Mises) is read at the interior of that element, at the picked place.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyvista as pv

CELL_ID = "_oc_cell_id"  # original id arrays that prepare() adds to the mesh it returns
POINT_ID = "_oc_point_id"
POS0 = "_oc_pos0"  # node coordinates before the deformation (what the model dimensions refer to)
VALUE_FMT = "{:+.3e}"


@dataclass(frozen=True)
class Probe:
    cell: int  # original element id
    node: int  # original id of the element's node closest to the picked place
    offset: tuple[float, float, float]  # picked place minus the element centre, kept to follow the element


def make_probe(shown: pv.DataSet, cell: int, position) -> Probe:
    """Probe for the element `cell` of `shown` picked at the world `position`."""
    position = np.asarray(position, dtype=float)
    ids = list(shown.get_cell(cell).point_ids)
    pts = np.asarray(shown.points)[ids]
    node = ids[int(np.argmin(np.linalg.norm(pts - position, axis=1)))]
    centre = np.asarray(shown.cell_centers().points[cell])
    return Probe(int(shown.cell_data[CELL_ID][cell]), int(shown.point_data[POINT_ID][node]),
                 tuple(float(v) for v in position - centre))


def _index(ids, original: int):
    found = np.nonzero(np.asarray(ids) == original)[0]
    return int(found[0]) if len(found) else None


def read_probe(shown: pv.DataSet, name: str, raw: str, title: str, probe: Probe, unit: str = "", length_unit: str = ""):
    """(world position, text lines) of `probe` on the mesh being shown.

    `name` is the plotted scalar, `raw` the array it comes from (a vector gives extra component lines).
    `unit` follows the values; with a `length_unit` a line gives the place of the probe in the model
    (undeformed coordinates). Returns (None, None) when the element has been deleted.
    """
    if name in shown.point_data:  # nodal quantity: read at the node
        i = _index(shown.point_data[POINT_ID], probe.node)
        if i is None:
            return None, None
        data = shown.point_data
        pos = np.asarray(shown.points[i], dtype=float)
        where = np.asarray(shown.point_data[POS0][i], dtype=float)
        head = "Node value"
    else:  # element quantity: read inside the element
        i = _index(shown.cell_data[CELL_ID], probe.cell)
        if i is None:
            return None, None
        data = shown.cell_data
        pos = np.asarray(shown.cell_centers().points[i], dtype=float) + np.asarray(probe.offset)
        where = np.asarray(shown.point_data[POS0])[list(shown.get_cell(i).point_ids)].mean(axis=0)  # element centre
        head = "Element value (interior)"
    suffix = f" {unit}" if unit else ""
    lines = [head, f"{title} = {VALUE_FMT.format(float(data[name][i]))}{suffix}"]
    vec = np.asarray(data[raw][i]) if raw in data else None
    if vec is not None and vec.ndim == 1 and len(vec) == 3:
        lines += [f"{axis} = {VALUE_FMT.format(float(v))}{suffix}" for axis, v in zip("xyz", vec)]
    if length_unit:
        tiny = 1e-9 * max(float(np.abs(where).max()), float(shown.length))  # rounding noise such as 4.8e-19
        lines.append("at (" + ", ".join(f"{(0.0 if abs(v) < tiny else v):.4g}" for v in where) + f") {length_unit}")
    return pos, lines
