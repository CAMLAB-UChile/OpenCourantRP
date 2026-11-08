"""Local axes of shell elements, to turn the stress / strain components the solver writes into global ones.

The solver writes the tensors in the local frame of each element, which follows the current shape of the element.
Found for OpenCourantLab (the sibling program that writes these files) by comparing the written tensors with the known
stress of a pressurised tube (triangles and skewed quads), and consistent with the Radioss Theory Manual:
  z (normal) = right-hand rule on the node order, from the diagonals: (P3 - P1) x (P4 - P2); a triangle repeats its 3rd node.
  3-node shell: x along side 1 -> 2.
  4-node shell: x along the bisector of the diagonals 1-3 and 4-2, taken in the plane of the element.
  y = z x x.
"""

from __future__ import annotations

import numpy as np

VTK_TRIANGLE, VTK_QUAD = 5, 9


def _unit(v: np.ndarray) -> np.ndarray:
    length = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(length > 0, length, 1.0)


def _triangle_frames(p: np.ndarray) -> np.ndarray:
    g1, g2 = p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]
    n = _unit(np.cross(g1, g2))
    x = _unit(g1)
    return np.stack([x, np.cross(n, x), n], axis=1)


def _quad_frames(p: np.ndarray) -> np.ndarray:
    d13, d42 = p[:, 2] - p[:, 0], p[:, 1] - p[:, 3]
    n = _unit(np.cross(d13, p[:, 3] - p[:, 1]))
    x = _unit(_unit(d13) + _unit(d42))
    x = _unit(x - np.einsum("mi,mi->m", x, n)[:, None] * n)  # in the plane of the element
    return np.stack([x, np.cross(n, x), n], axis=1)


def element_frames(mesh, points: np.ndarray | None = None) -> np.ndarray:
    """(n_cells, 3, 3) array whose rows are the local x, y and z axes of each element, in global coordinates.

    Cells that are not 3- or 4-node shells get the identity (their components stay as they are).
    """
    pts = np.asarray(mesh.points if points is None else points, dtype=float)
    frames = np.tile(np.eye(3), (mesh.n_cells, 1, 1))
    types = np.asarray(mesh.celltypes)
    conn, start = np.asarray(mesh.cell_connectivity), np.asarray(mesh.cell_offsets)[:-1]
    for vtk_type, count, build in ((VTK_TRIANGLE, 3, _triangle_frames), (VTK_QUAD, 4, _quad_frames)):
        sel = np.nonzero(types == vtk_type)[0]
        if len(sel):
            ids = conn[start[sel][:, None] + np.arange(count)]
            frames[sel] = build(pts[ids])
    return frames


def to_global(tensor: np.ndarray, frames: np.ndarray) -> np.ndarray:
    """Rotate (n, 9) tensors given in the local frames into the global axes; rows of `frames` are the local axes."""
    full = tensor.reshape(-1, 3, 3)
    return np.einsum("nia,nij,njb->nab", frames, full, frames).reshape(-1, 9)
