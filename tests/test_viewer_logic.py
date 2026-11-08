import numpy as np
import pyvista as pv
import pytest

from opencourantrp import about, entities, theme
from opencourantrp.video import write_video
from opencourantrp.variables import VARIABLES, available, evaluate, has_shells, has_solids, shell_available, variable
from opencourantrp.viewer import ghost_view, prepare, prepare_view


def make_mesh():
    grid = pv.Plane(i_resolution=3, j_resolution=3).cast_to_unstructured_grid()
    grid.cell_data["EROSION_STATUS"] = np.ones(grid.n_cells, dtype=int)
    grid.cell_data["2DELEM_Von_Mises"] = np.arange(grid.n_cells, dtype=float)
    grid.cell_data["2DELEM_Plastic_Strain"] = np.arange(grid.n_cells, dtype=float)
    grid.point_data["Displacement"] = np.zeros((grid.n_points, 3))
    grid.point_data["Velocity"] = np.tile([3.0, 4.0, 0.0], (grid.n_points, 1))
    return grid


def test_smoothing_moves_element_data_to_nodes():
    var = variable("svm")
    flat, name, _, _ = prepare(make_mesh(), var, smooth=False)
    smooth, name2, vmin, vmax = prepare(make_mesh(), var, smooth=True)
    assert len(flat[name]) == flat.n_cells
    assert len(smooth[name2]) == smooth.n_points
    assert vmin >= 0 and vmax <= 8  # averages stay inside the element range


def test_smoothing_ignores_nodal_variables():
    var = variable("V")
    a = prepare(make_mesh(), var, smooth=False)
    b = prepare(make_mesh(), var, smooth=True)
    assert np.allclose(a[0][a[1]], 5.0) and np.allclose(b[0][b[1]], 5.0)  # |(3,4,0)| = 5


def test_eroded_elements_hidden():
    mesh = make_mesh()
    mesh.cell_data["EROSION_STATUS"][0] = 0
    var = variable("svm")
    shown, *_ = prepare(mesh, var)
    assert shown.n_cells == mesh.n_cells - 1


def test_themes_complete():
    assert set(theme.THEMES) == {"light", "dark"}
    for t in theme.THEMES.values():
        assert "QPushButton" in theme.stylesheet(t)
        assert all(0 <= c <= 1 for c in theme.rgb(t.view_text))


def test_about_text():
    html = about.about_html("1.2.3")
    for needle in ("AGPL-3.0 or later", "Copyright 2026 Alejandro Ortiz-Bernardin",
                   "https://camlab.cl/software/OpenCourantRP/", "1.2.3"):
        assert needle in html


@pytest.mark.parametrize("ext", ["mp4", "gif"])
def test_write_video(tmp_path, ext):
    frames = (np.full((33, 47, 3), i * 20, dtype=np.uint8) for i in range(5))  # odd size is cropped
    out = tmp_path / f"v.{ext}"
    assert write_video(out, frames, fps=5) == 5
    assert out.stat().st_size > 0


def test_deformation_scale():
    mesh = make_mesh()
    mesh.point_data["Displacement"] = np.tile([0.0, 0.0, 2.0], (mesh.n_points, 1))
    z0 = np.array(mesh.points[:, 2])  # the original height
    mesh.points = mesh.points + mesh.point_data["Displacement"]  # a result file stores the deformed positions
    var = variable("U")
    for scale, expect in ((1.0, 2.0), (5.0, 10.0), (None, 0.0)):
        shown, *_ = prepare(mesh, var, scale=scale)
        assert np.allclose(shown.points[:, 2] - z0[: shown.n_points], expect)
        assert np.allclose(shown.point_data["_oc_pos0"][:, 2], z0[: shown.n_points])  # probes report original positions


def test_colormaps_available():
    from opencourantrp.viewer import COLORMAPS
    assert list(COLORMAPS) == ["coolwarm", "vik", "RdYlBu", "RdBu", "jet", "turbo", "inferno", "fast (ParaView)"]


def test_probe_follows_original_ids_through_erosion():
    from opencourantrp import probe
    mesh = make_mesh()
    var = variable("svm")
    shown, name, *_ = prepare(mesh, var)
    cell = 4
    pr = probe.make_probe(shown, cell, shown.cell_centers().points[cell])
    pos, lines = probe.read_probe(shown, name, var.array, var.title, pr)
    assert "interior" in lines[0] and f"{float(cell):+.3e}" in lines[1]
    mesh.cell_data["EROSION_STATUS"][0] = 0  # ids shift by one in the mesh shown; the probe must still find its element
    shown2, name2, *_ = prepare(mesh, var)
    pos2, lines2 = probe.read_probe(shown2, name2, var.array, var.title, pr)
    assert np.allclose(pos, pos2) and lines == lines2
    mesh.cell_data["EROSION_STATUS"][cell] = 0
    shown3, name3, *_ = prepare(mesh, var)
    assert probe.read_probe(shown3, name3, var.array, var.title, pr) == (None, None)


def test_probe_reads_node_value_and_components():
    from opencourantrp import probe
    mesh = make_mesh()
    var = variable("V")
    shown, name, *_ = prepare(mesh, var)
    pr = probe.make_probe(shown, 0, shown.cell_centers().points[0])
    _, lines = probe.read_probe(shown, name, var.array, var.title, pr)
    assert lines[0] == "Node value" and "+5.000e+00" in lines[1] and len(lines) == 5


def test_fonts_defaults_and_roundtrip():
    from opencourantrp import fonts
    d = fonts.default_fonts()
    assert [d[k].size for k in ("ticks", "title", "minmax", "probes")] == [14, 18, 14, 11]
    assert all(s.family == "Arial" and s.color is None and not s.bold and not s.italic for s in d.values())
    custom = dict(d, title=fonts.FontSpec("Times", True, True, 22, "#ff0000"))
    assert fonts.loads(fonts.dumps(custom)) == custom
    assert fonts.loads("not json") == d and fonts.loads("") == d  # corrupt / empty settings fall back to the defaults


@pytest.mark.parametrize("ext, magic", [(".png", b"\x89PNG"), (".jpg", b"\xff\xd8"), (".tiff", b"II"), (".pdf", b"%PDF")])
def test_snapshot_formats(tmp_path, ext, magic):
    from opencourantrp import snapshot
    image = np.random.default_rng(0).integers(0, 255, (40, 60, 3), dtype=np.uint8)
    out = snapshot.save_snapshot(tmp_path / f"view{ext}", image)
    assert out.read_bytes()[:4].startswith(magic) or out.read_bytes()[:2] == magic[:2]


def test_snapshot_extension_handling(tmp_path):
    from opencourantrp import snapshot
    assert snapshot.extension_for("TIFF image (*.tiff)") == ".tiff"
    assert snapshot.with_extension("a/b/view", ".pdf") == "a/b/view.pdf"
    assert snapshot.with_extension("a/b/view.JPEG", ".png") == "a/b/view.JPEG"
    snapshot.save_snapshot(tmp_path / "v.tif", np.zeros((8, 8, 4), np.uint8))  # alias and alpha channel accepted
    with pytest.raises(ValueError):
        snapshot.save_snapshot(tmp_path / "v.bmp", np.zeros((8, 8, 3), np.uint8))


def test_snapshot_quality_defaults_and_pdf_page_size(tmp_path):
    from opencourantrp import snapshot
    assert snapshot.default_quality(".pdf") == 4 and snapshot.default_quality(".png") == 1
    assert snapshot.default_quality(".TIF") == 1 and snapshot.QUALITY_RANGE == (1, 8)
    k = 3  # whatever the user chose: the pdf page keeps the on-screen size
    out = snapshot.save_snapshot(tmp_path / "v.pdf", np.zeros((12 * k, 20 * k, 3), np.uint8), k)
    page = [float(x) for x in out.read_bytes().split(b"/MediaBox [")[1].split(b"]")[0].split()]
    assert abs(page[2] - 20 * 72 / snapshot.DPI) < 0.1 and abs(page[3] - 12 * 72 / snapshot.DPI) < 0.1  # points


def test_presets_roundtrip_and_bad_data():
    from opencourantrp import presets
    saved = {"Paper": {"ncolors": 8}, "article  figure": {"cap": True}}
    assert presets.loads(presets.dumps(saved)) == {"Paper": {"ncolors": 8}, "article figure": {"cap": True}}
    assert presets.sorted_names({"b": {}, "A": {}, "c": {}}) == ["A", "b", "c"]
    assert presets.loads("garbage") == {} and presets.loads("[1, 2]") == {} and presets.loads("") == {}
    assert presets.loads('{"": {"x": 1}, "ok": 5}') == {}  # no name / not a settings dict
    assert presets.clean_name("  a   b ") == "a b"


def test_units_in_probe_and_text():
    from opencourantrp import probe, units
    mesh = make_mesh()
    var = variable("V")
    shown, name, *_ = prepare(mesh, var)
    pr = probe.make_probe(shown, 0, shown.cell_centers().points[0])
    _, plain = probe.read_probe(shown, name, var.array, var.title, pr)
    _, with_units = probe.read_probe(shown, name, var.array, var.title, pr, "mm/s", "mm")
    assert not any("mm" in ln for ln in plain) and len(plain) == 5  # no unit declared: nothing shown, as before
    assert with_units[1].endswith(" mm/s") and with_units[2].endswith(" mm/s") and with_units[-1].startswith("at (")
    assert with_units[-1].endswith(") mm")
    u = units.Units(stress=" MPa ")
    assert units.loads(units.dumps(units.loads('{"stress": " MPa "}'))).stress == "MPa" and u.of("stress") == " MPa "
    assert units.Units().of("stress") == "" and units.Units().of(None) == "" and units.loads("junk") == units.Units()
    u = units.Units(temperature="K", mass="t", energy="mJ")
    assert [u.of(variable(k).quantity) for k in ("temp", "dmas", "ener", "hourg")] == ["K", "t", "mJ/t", "mJ/t"]
    assert units.Units(energy="mJ").of("energy/mass") == "" and units.loads(units.dumps(u)) == u
    assert units.with_unit("max 3", "") == "max 3" and units.with_unit("max 3", "MPa") == "max 3 MPa"
    assert {v.key: v.quantity for v in VARIABLES if v.key in ("Ux", "V", "epl", "svm", "exx", "damage")} == {
        "Ux": "displacement", "V": "velocity", "epl": None, "svm": "stress", "exx": None, "damage": None}


def test_ruler_numbers_and_scale():
    from opencourantrp.viewer import ruler_number
    assert [ruler_number(v) for v in (0, 110.25, 220.5, 441)] == ["0", "110", "220", "441"]
    assert ruler_number(1234.5) == "1234" or ruler_number(1234.5) == "1235"  # no exponent while readable
    assert ruler_number(0.01234) == "0.0123" and ruler_number(2.5e-9) == "2.5e-09"


def test_hidden_parts_are_left_out_and_limits_follow_the_rest():
    mesh = make_mesh()
    mesh.cell_data["PART_ID"] = np.where(np.arange(mesh.n_cells) < 4, 1, 2)
    var = variable("svm")
    shown, name, vmin, vmax = prepare(mesh, var)
    assert shown.n_cells == mesh.n_cells
    shown, name, vmin, vmax = prepare(mesh, var, hidden={1})
    assert shown.n_cells == mesh.n_cells - 4 and vmin == 4.0
    with pytest.raises(KeyError):
        prepare(mesh, var, hidden={1, 2})


def tensor_mesh():
    mesh = make_mesh()
    n = mesh.n_cells
    for place, value in (("upper", 3.0), ("layer__3", 1.0), ("lower", -2.0)):
        stress = np.zeros((n, 9))
        stress[:, 0] = value * 100  # xx
        stress[:, 4] = 40.0  # yy
        stress[:, 1] = stress[:, 3] = 30.0  # xy = yx
        mesh.cell_data[f"2DELEM_Stress_({place})" if place != "layer__3" else "2DELEM_Stress_(layer__3)_"] = stress
    mesh.cell_data["2DELEM_Plastic_Strain"] = np.full(n, 0.2)
    mesh.cell_data["2DELEM_Plastic_Strain_Upper"] = np.full(n, 0.3)
    mesh.cell_data["2DELEM_Plastic_Strain_Lower"] = np.full(n, 0.1)
    return mesh


def test_stress_components_principal_and_through_the_thickness():
    mesh = tensor_mesh()
    assert np.allclose(evaluate(variable("sxx"), mesh, "top"), 300)
    assert np.allclose(evaluate(variable("sxx"), mesh, "middle"), 100)
    assert np.allclose(evaluate(variable("sxx"), mesh, "bottom"), -200)
    assert np.allclose(evaluate(variable("sxx"), mesh, "max"), 300) and np.allclose(evaluate(variable("sxx"), mesh, "min"), -200)
    assert np.allclose(evaluate(variable("sxy"), mesh, "top"), 30)
    s1, s2, s3 = (evaluate(variable(k), mesh, "middle") for k in ("s1", "s2", "s3"))
    assert np.all(s1 >= s2) and np.all(s2 >= s3)
    assert np.allclose(s1 + s2 + s3, 140)  # trace: 100 + 40 + 0
    assert np.allclose(evaluate(variable("tmax"), mesh, "middle"), (s1 - s3) / 2)
    assert np.allclose(evaluate(variable("svm"), mesh, "top"), np.sqrt(300**2 - 300 * 40 + 40**2 + 3 * 30**2))
    assert np.allclose(evaluate(variable("epl"), mesh, "max"), 0.3) and np.allclose(evaluate(variable("epl"), mesh, "min"), 0.1)


def test_availability_follows_the_arrays_in_the_file():
    mesh = make_mesh()  # only the element von Mises and plastic strain (middle), displacement and velocity
    assert available(variable("U"), mesh) and available(variable("svm"), mesh) and available(variable("epl"), mesh)
    assert not available(variable("sxx"), mesh) and not available(variable("epl"), mesh, "top")
    with pytest.raises(KeyError):
        evaluate(variable("sxx"), mesh)
    assert available(variable("sxx"), tensor_mesh(), "max") and not available(variable("damage"), mesh)


def test_part_names_and_integration_points_from_the_starter_deck(tmp_path):
    from opencourantrp import project
    (tmp_path / "A_0000.rad").write_text(
        "#RADIOSS STARTER\n/PART/1\nvessel\n         1         1         0\n/PART/2\nwedge\n         7         2         0\n"
        "/PROP/SHELL/1\nprop_1\n        24         0         2         0         0\n"
        "                   0                   0                   0                   0                   0\n"
        "         3                           9.5                   0                   1         1         0\n"
        "/PROP/SHELL/2\nprop_2\n        24         0         2         0         0\n# a comment\n"
        "                   0                   0                   0                   0                   0\n"
        "         1                             1\n")
    names, nip = project.read_part_info(tmp_path, "A")
    assert names == {1: "vessel", 2: "wedge"} and nip == {1: 3}  # part 2 points at property 7, which is not there
    assert project.read_part_info(tmp_path / "missing", "A") == ({}, {})
    assert variable("sxx").local and variable("exy").local and not variable("s1").local and not variable("svm").local
    assert not variable("U").local


def test_element_frames_and_rotation_to_global():
    from opencourantrp.frames import element_frames, to_global
    # one triangle in a plane rotated 90 degrees about Z: edge 1-2 along global +Y, normal +Z
    tri = pv.UnstructuredGrid(np.array([3, 0, 1, 2]), np.array([5]), np.array([[0, 0, 0], [0, 2, 0], [-1, 0, 0]], float))
    f = element_frames(tri)
    assert np.allclose(f[0], [[0, 1, 0], [-1, 0, 0], [0, 0, 1]])
    local = np.zeros((1, 9)); local[0, 0] = 5.0  # sigma_xx(local) = 5, the rest zero
    assert np.allclose(to_global(local, f)[0].reshape(3, 3), np.diag([0, 5, 0]))  # it points along global Y
    shear = np.zeros((1, 9)); shear[0, 1] = shear[0, 3] = 2.0
    g = to_global(shear, f)[0].reshape(3, 3)
    assert np.allclose(g, [[0, -2, 0], [-2, 0, 0], [0, 0, 0]])  # local x = global Y, local y = global -X
    # a square quad on the XY plane: x along the bisector turned back by 45 degrees = global X
    quad = pv.UnstructuredGrid(np.array([4, 0, 1, 2, 3]), np.array([9]), np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float))
    assert np.allclose(element_frames(quad)[0], np.eye(3))
    # evaluate: global components of a mesh whose element axes differ from the global ones
    mesh = tri.copy()
    for place, v in (("upper", 5.0), ("layer__3", 5.0), ("lower", 5.0)):
        s = np.zeros((1, 9)); s[0, 0] = v
        mesh.cell_data[f"2DELEM_Stress_({place})" if place != "layer__3" else "2DELEM_Stress_(layer__3)_"] = s
    assert np.allclose(evaluate(variable("sxx"), mesh, "middle", "local"), 5.0)
    assert np.allclose(evaluate(variable("sxx"), mesh, "middle", "global"), 0.0)
    assert np.allclose(evaluate(variable("syy"), mesh, "middle", "global"), 5.0)
    assert np.allclose(evaluate(variable("s1"), mesh, "middle", "global"), 5.0)  # principal values: no change


def test_damage_is_listed_only_when_the_file_has_it():
    from opencourantrp.variables import VARIABLES
    optional = [v.key for v in VARIABLES if v.optional]
    assert optional == ["Ax", "Ay", "Az", "A", "Fx", "Fy", "Fz", "F", "damage", "ndt", "temp", "dmas", "ener", "dt", "hourg", "pres", "dens"]
    mesh = make_mesh()
    assert not available(variable("damage"), mesh)
    mesh.cell_data["2DELEM_MAX_DAMAGE_ELEMENT"] = np.linspace(0, 1, mesh.n_cells)
    assert available(variable("damage"), mesh) and np.allclose(evaluate(variable("damage"), mesh).max(), 1.0)


def test_contact_forces_are_listed_only_when_the_file_has_them():
    mesh = make_mesh()
    assert not available(variable("F"), mesh)
    mesh.point_data["Contact_Forces"] = np.tile([3.0, 4.0, 0.0], (mesh.n_points, 1))
    assert available(variable("F"), mesh)
    assert np.allclose(evaluate(variable("Fx"), mesh), 3.0) and np.allclose(evaluate(variable("F"), mesh), 5.0)
    from opencourantrp import units
    assert units.Units(force="N").of(variable("F").quantity) == "N"


def test_section_plane_hides_one_side_of_the_model():
    mesh = make_mesh()  # a unit-ish plane in XY, 9 elements
    var = variable("svm")
    x = mesh.cell_centers().points[:, 0]
    full, *_ = prepare(mesh, var)
    kept, *_ = prepare(mesh, var, section=(0, 0.0, False))  # the side with x >= 0 stays
    other, *_ = prepare(mesh, var, section=(0, 0.0, True))
    assert kept.n_cells == int((x >= 0).sum()) and other.n_cells == int((x < 0).sum())
    assert kept.n_cells + other.n_cells == full.n_cells
    assert kept.cell_centers().points[:, 0].min() >= 0 and other.cell_centers().points[:, 0].max() < 0
    assert probes_ids_survive(kept)
    with pytest.raises(KeyError):
        prepare(mesh, var, section=(0, 100.0, False))  # a plane beyond the model hides everything


def probes_ids_survive(shown):
    from opencourantrp import probe
    return probe.CELL_ID in shown.cell_data and probe.POINT_ID in shown.point_data and probe.POS0 in shown.point_data


def test_quad_frame_is_the_bisector_of_the_diagonals_and_follows_the_given_positions():
    from opencourantrp.frames import element_frames
    quad = pv.UnstructuredGrid(np.array([4, 0, 1, 2, 3]), np.array([9]),
                               np.array([[0, 0, 0], [2, 0, 0], [3, 1, 0], [1, 1, 0]], float))  # a parallelogram
    f = element_frames(quad)[0]
    d13, d42 = np.array([3.0, 1.0, 0.0]), np.array([1.0, -1.0, 0.0])
    x = d13 / np.linalg.norm(d13) + d42 / np.linalg.norm(d42)
    assert np.allclose(f[0], x / np.linalg.norm(x)) and np.allclose(f[2], [0, 0, 1]) and np.allclose(np.cross(f[2], f[0]), f[1])
    moved = np.array(quad.points) + [5.0, 0.0, 0.0]
    assert np.allclose(element_frames(quad, moved)[0], f)  # a translation does not turn the axes


def test_von_mises_of_the_middle_comes_from_the_centre_layer_tensor_when_there_is_one():
    mesh = tensor_mesh()  # centre layer: xx = 100, yy = 40, xy = 30
    expected = np.sqrt(100**2 - 100 * 40 + 40**2 + 3 * 30**2)
    assert np.allclose(evaluate(variable("svm"), mesh, "middle"), expected)  # not the file's own 2DELEM_Von_Mises
    plain = make_mesh()  # no tensors: the solver's value stands in
    assert np.allclose(evaluate(variable("svm"), plain, "middle"), plain.cell_data["2DELEM_Von_Mises"])


def membrane_mesh():
    mesh = tensor_mesh()
    n = mesh.n_cells
    for kind in ("Stress", "Strain"):
        mem = np.zeros((n, 9))
        mem[:, 0] = 70.0
        mem[:, 4] = 20.0
        mesh.cell_data[f"2DELEM_{kind}_(membrane)_"] = mem
    return mesh


def test_membrane_tensor_name_without_the_final_underscore():
    """The stock engine writes 2DELEM_Stress_(membrane), OpenCourantLab 2DELEM_Stress_(membrane)_: both are read."""
    mesh = membrane_mesh()
    for kind in ("Stress", "Strain"):
        mesh.cell_data[f"2DELEM_{kind}_(membrane)"] = mesh.cell_data.pop(f"2DELEM_{kind}_(membrane)_")
    assert available(variable("sxx"), mesh, "membrane")
    assert np.allclose(evaluate(variable("sxx"), mesh, "membrane"), 70.0)


def test_membrane_tensor_is_a_separate_choice_and_the_middle_when_alone():
    mesh = membrane_mesh()  # layers and membrane: both available
    assert np.allclose(evaluate(variable("sxx"), mesh, "membrane"), 70.0)
    assert np.allclose(evaluate(variable("sxx"), mesh, "middle"), 100.0)  # the centre layer is still the middle
    assert np.allclose(evaluate(variable("svm"), mesh, "membrane"), np.sqrt(70**2 - 70 * 20 + 20**2))
    assert np.allclose(evaluate(variable("sxx"), mesh, "max"), 300.0)  # max/min keep to top, middle and bottom
    only = make_mesh()  # a run that wrote the membrane tensor only: it stands for the middle
    only.cell_data["2DELEM_Stress_(membrane)_"] = membrane_mesh().cell_data["2DELEM_Stress_(membrane)_"]
    assert np.allclose(evaluate(variable("sxx"), only, "middle"), 70.0) and available(variable("sxx"), only, "middle")
    assert np.allclose(evaluate(variable("svm"), only, "middle"), np.sqrt(70**2 - 70 * 20 + 20**2))
    assert not available(variable("sxx"), tensor_mesh(), "membrane")  # no membrane tensor in this run
    assert available(variable("svm"), make_mesh(), "membrane")  # the solver's own von Mises is the membrane one
    assert not available(variable("epl"), mesh, "membrane")  # no membrane plastic strain exists


def test_plastic_strain_middle_falls_back_to_layer_3():
    """/ANIM/SHELL/EPSP/ALL writes the layers, not 2DELEM_Plastic_Strain."""
    mesh = tensor_mesh()
    mesh.cell_data["2DELEM_Plast_Strn_Layer___3_"] = np.full(mesh.n_cells, 0.5)
    assert np.allclose(evaluate(variable("epl"), mesh, "middle"), 0.2)  # the element value wins when present
    del mesh.cell_data["2DELEM_Plastic_Strain"]
    assert available(variable("epl"), mesh, "middle")
    assert np.allclose(evaluate(variable("epl"), mesh, "middle"), 0.5)
    del mesh.cell_data["2DELEM_Plast_Strn_Layer___3_"]
    assert not available(variable("epl"), mesh, "middle")


def test_energy_and_time_step_are_read_from_their_arrays():
    mesh = tensor_mesh()
    assert not available(variable("ener"), mesh) and not available(variable("dt"), mesh)
    mesh.cell_data["2DELEM_Specific_Energy"] = np.full(mesh.n_cells, 7.0)
    mesh.cell_data["2DELEM_Element_Time_Step"] = np.full(mesh.n_cells, 1e-4)
    assert available(variable("ener"), mesh) and np.allclose(evaluate(variable("ener"), mesh), 7.0)
    assert np.allclose(evaluate(variable("dt"), mesh, "top"), 1e-4)  # not a layered quantity


def test_part_info_follows_include_files(tmp_path):
    from opencourantrp import project
    (tmp_path / "props.txt").write_text("/PROP/SHELL/1\nprop_1\n 24 0 0 0\n 0 0 0 0 0\n         5   1  1.5\n")
    (tmp_path / "A_0000.rad").write_text(
        "#include props.txt\n/PART/1\nbeam\n         1         1         0\n#include missing.txt\n")
    assert project.read_part_info(tmp_path, "A") == ({1: "beam"}, {1: 5})
    (tmp_path / "loop.txt").write_text("#include loop.txt\n")  # an include that includes itself must end
    (tmp_path / "B_0000.rad").write_text("#include loop.txt\n/PART/1\nx\n         1         1         0\n")
    assert project.read_part_info(tmp_path, "B")[0] == {1: "x"}


def solid_mesh(with_shells=False):
    """A unit cube (one hexahedron) with 3DELEM arrays, optionally joined to the shell plane of make_mesh()."""
    cube = pv.Cube().cast_to_unstructured_grid()
    hexa = pv.UnstructuredGrid(np.array([8, 0, 1, 2, 3, 4, 5, 6, 7]), np.array([12]), np.asarray(cube.points)[:8])
    n = hexa.n_cells
    stress = np.zeros((n, 9))
    stress[:, 0] = 50.0  # xx
    stress[:, 4] = 20.0  # yy
    hexa.cell_data["3DELEM_Stress"] = stress
    hexa.cell_data["3DELEM_Strain"] = stress * 1e-3
    hexa.cell_data["3DELEM_Specific_Energy"] = np.full(n, 7.0)
    hexa.cell_data["3DELEM_Plastic_Strain"] = np.full(n, 0.05)
    hexa.cell_data["EROSION_STATUS"] = np.ones(n, dtype=int)
    hexa.point_data["Velocity"] = np.zeros((hexa.n_points, 3))
    hexa.point_data["Displacement"] = np.zeros((hexa.n_points, 3))
    if not with_shells:
        return hexa
    shells = make_mesh()
    shells.point_data.clear()
    shells.point_data["Velocity"] = np.zeros((shells.n_points, 3))
    shells.point_data["Displacement"] = np.zeros((shells.n_points, 3))
    merged = shells.merge(hexa, merge_points=False)
    solid = np.asarray(merged.celltypes) == 12
    for key in hexa.cell_data.keys():  # the merge keeps only the arrays both parts have: write them by hand
        data = np.asarray(hexa.cell_data[key])
        full = np.zeros((merged.n_cells,) + data.shape[1:], dtype=data.dtype)
        full[solid] = data
        merged.cell_data[key] = full
    merged.cell_data["EROSION_STATUS"] = np.ones(merged.n_cells, dtype=int)
    return merged


def test_solid_only_file_reads_the_3delem_arrays():
    mesh = solid_mesh()
    assert np.allclose(evaluate(variable("sxx"), mesh), 50)
    assert np.allclose(evaluate(variable("svm"), mesh), np.sqrt(50 ** 2 - 50 * 20 + 20 ** 2))
    assert np.allclose(evaluate(variable("exx"), mesh), 0.05)
    assert np.allclose(evaluate(variable("ener"), mesh), 7) and np.allclose(evaluate(variable("epl"), mesh), 0.05)
    assert all(available(variable(k), mesh) for k in ("sxx", "svm", "epl", "ener"))
    assert not available(variable("dt"), mesh) and not available(variable("damage"), mesh)
    assert not shell_available(variable("sxx"), mesh) and has_solids(mesh) and not has_shells(mesh)


def test_solids_ignore_thickness_and_axes():
    mesh = solid_mesh()
    for thickness in ("top", "max", "membrane"):
        assert np.allclose(evaluate(variable("sxx"), mesh, thickness, "local"), 50)
    assert np.allclose(evaluate(variable("sxx"), mesh, "middle", "global"), 50)


def test_solid_von_mises_falls_back_to_the_solver_value():
    mesh = solid_mesh()
    del mesh.cell_data["3DELEM_Stress"]
    mesh.cell_data["3DELEM_Von_Mises"] = np.full(mesh.n_cells, 12.0)
    assert np.allclose(evaluate(variable("svm"), mesh), 12)


def test_mixed_file_gives_each_kind_its_own_value():
    mesh = solid_mesh(with_shells=True)
    solid = np.asarray(mesh.celltypes) == 12
    assert solid.sum() == 1 and has_shells(mesh) and has_solids(mesh)
    shells = tensor_mesh()
    for name in shells.cell_data.keys():
        if name.startswith("2DELEM_"):
            data = np.asarray(shells.cell_data[name])
            full = np.zeros((mesh.n_cells,) + data.shape[1:])
            full[~solid] = data
            mesh.cell_data[name] = full
    top = evaluate(variable("sxx"), mesh, "top")
    assert np.allclose(top[~solid], 300) and np.allclose(top[solid], 50)  # the solid ignores "top"
    assert np.allclose(evaluate(variable("epl"), mesh, "bottom")[~solid], 0.1)
    assert np.allclose(evaluate(variable("epl"), mesh, "bottom")[solid], 0.05)
    assert shell_available(variable("sxx"), mesh, "top")


def test_prepare_draws_solids():
    shown, name, vmin, vmax = prepare(solid_mesh(), variable("sxx"))
    assert shown.n_cells == 1 and vmin == 50


def test_nodal_time_step_is_a_node_array():
    mesh = solid_mesh()
    var = variable("ndt")
    assert not available(var, mesh)
    mesh.point_data["Time_Step"] = np.linspace(1e-4, 2e-4, mesh.n_points)
    assert available(var, mesh) and var.nodal
    assert np.allclose(evaluate(var, mesh), mesh.point_data["Time_Step"])
    shown, name, vmin, vmax = prepare(mesh, var)
    assert len(shown[name]) == shown.n_points and np.isclose(vmin, 1e-4)
    mesh.point_data["Time_Step"][:2] = (0.0, 1e6)  # rigid node and "not computed" placeholder
    assert np.isnan(evaluate(var, mesh)[:2]).all() and np.isfinite(evaluate(var, mesh)[2:]).all()
    mesh.point_data["Time_Step"] = np.full(mesh.n_points, 1e6)  # a run without /DT/NODA
    assert not available(var, mesh)


def entity_mesh():
    """A hexahedron, a quad shell, a rigid-wall quad (ELEMENT_ID 0), a rigid line (id 0) and a spring line (id 7)."""
    from opencourantrp import entities  # noqa: F401
    pts = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
                    [2, 0, 0], [3, 0, 0], [3, 1, 0], [2, 1, 0], [4, 0, 0], [5, 0, 0], [5, 1, 0], [4, 1, 0],
                    [6, 0, 0], [7, 0, 0]], dtype=float)
    cells = [8, 0, 1, 2, 3, 4, 5, 6, 7, 4, 8, 9, 10, 11, 4, 12, 13, 14, 15, 2, 16, 17, 2, 0, 1]
    mesh = pv.UnstructuredGrid(np.array(cells), np.array([12, 9, 9, 3, 3]), pts)
    mesh.cell_data["ELEMENT_ID"] = np.array([1, 2, 0, 0, 7])
    mesh.cell_data["PART_ID"] = np.array([1, 1, 1, 2, 3])
    mesh.cell_data["EROSION_STATUS"] = np.ones(5, dtype=int)
    mesh.cell_data["3DELEM_Von_Mises"] = np.array([5.0, 0, 0, 0, 0])
    mesh.cell_data["2DELEM_Von_Mises"] = np.array([0, 9.0, -99.0, 0, 0])
    return mesh


def test_entities_are_told_apart():
    from opencourantrp import entities
    assert entities.classify(entity_mesh()).tolist() == ["solid", "shell", "wall", "rigid", "spring"]


def test_fixed_entities_leave_the_result_range_and_are_returned_apart():
    from opencourantrp import entities
    from opencourantrp.viewer import prepare_view
    mesh = entity_mesh()
    shown, rest, name, vmin, vmax = prepare_view(mesh, variable("svm"), fixed=entities.FIXED)
    assert shown.n_cells == 2 and rest.n_cells == 3
    assert (vmin, vmax) == (5.0, 9.0)  # the rigid wall's -99 is not in the range
    assert prepare(mesh, variable("svm"))[2] == -99.0  # without the split every cell counts
    shown, rest, *_ = prepare_view(mesh, variable("svm"), fixed=entities.KEYS)
    assert shown is None and rest.n_cells == 5


def test_entity_colors_are_validated():
    from opencourantrp import entities
    assert entities.loads("not json") == entities.DEFAULTS
    got = entities.loads('{"shell": "#112233", "solid": "red", "rigid": 5}')
    assert got["shell"] == "#112233" and got["solid"] == entities.DEFAULTS["solid"] and got["rigid"] == entities.DEFAULTS["rigid"]
    assert entities.loads(entities.dumps(got)) == got


def test_nodal_results_leave_out_the_nodes_of_line_cells():
    mesh = entity_mesh()  # points 16 and 17 belong only to the spring line, 0 and 1 are shared with it
    mesh.point_data["Nodal_Temperature"] = np.full(mesh.n_points, 300.0)
    mesh.point_data["Nodal_Temperature"][[16, 17]] = 0.0
    got = evaluate(variable("temp"), mesh)
    assert np.isnan(got[[16, 17]]).all() and np.allclose(got[:16], 300.0)
    assert available(variable("temp"), mesh) and not available(variable("dmas"), mesh)


def test_hourglass_energy_of_solids():
    mesh = solid_mesh()
    mesh.cell_data["3DELEM_Hourglass_Energy_per_unit_mass"] = np.full(mesh.n_cells, 0.25)
    assert available(variable("hourg"), mesh) and np.allclose(evaluate(variable("hourg"), mesh), 0.25)


def test_rigid_walls_are_a_pseudo_part_of_their_own():
    from opencourantrp import entities
    from opencourantrp.viewer import prepare_view
    mesh = entity_mesh()  # the wall quad carries PART_ID 1, like the shells of rigid_ball_impact
    assert entities.part_ids(mesh) == [1, 2, 3, entities.WALL_PART]
    kinds = lambda hidden: sorted(entities.classify(prepare_view(mesh, variable("svm"), hidden=hidden)[0]))  # noqa: E731
    assert kinds({1}) == ["rigid", "spring", "wall"]  # hiding part 1 keeps the wall
    assert kinds({entities.WALL_PART}) == ["rigid", "shell", "solid", "spring"]
    assert entities.part_ids(prepare(mesh, variable("svm"))[0]) == [1, 2, 3, entities.WALL_PART]


def test_model_colors_are_validated():
    from opencourantrp import modelcolors
    from opencourantrp.theme import DARK, LIGHT
    assert modelcolors.background_loads("") is None and modelcolors.background_loads("junk") is None
    assert modelcolors.background_loads('{"style": "plain", "top": "red", "bottom": "#000000"}') is None
    spec = modelcolors.background_loads('{"style": "gradient", "top": "#112233", "bottom": "#445566"}')
    assert spec == {"style": "gradient", "top": "#112233", "bottom": "#445566"}
    assert modelcolors.background_loads(modelcolors.background_dumps(spec)) == spec
    assert modelcolors.background_colors(spec, LIGHT) == ("#112233", "#445566")
    assert modelcolors.background_colors({**spec, "style": "plain"}, LIGHT) == ("#112233", "#112233")
    assert modelcolors.background_colors(None, DARK) == (DARK.view_top, DARK.view_bottom)
    assert modelcolors.triad_loads("junk") == modelcolors.TRIAD_DEFAULTS
    got = modelcolors.triad_loads('{"x": "#010203", "y": "green", "letters": "#ffffff"}')
    assert got["x"] == "#010203" and got["y"] == modelcolors.TRIAD_DEFAULTS["y"] and got["letters"] == "#ffffff"
    assert modelcolors.triad_loads(modelcolors.triad_dumps(got)) == got
    assert modelcolors.triad_loads("{}")["sphere"] == "" and modelcolors.triad_loads('{"sphere": "#ff00ff"}')["sphere"] == "#ff00ff"


def test_extremes_carry_the_deck_number_of_the_node_or_element():
    from opencourantrp.viewer import ResultViewer
    mesh = entity_mesh()
    mesh.cell_data["ELEMENT_ID"] = np.array([11, 22, 33, 44, 55])
    mesh.cell_data["v"] = np.array([1.0, 9.0, -3.0, 0.0, 2.0])
    (_, vmax, idmax), (_, vmin, idmin) = ResultViewer._extremes(mesh, "v")
    assert (vmax, idmax, vmin, idmin) == (9.0, "Element 22", -3.0, "Element 33")
    mesh.point_data["NODE_ID"] = np.arange(100, 100 + mesh.n_points)
    mesh.point_data["p"] = np.arange(mesh.n_points, dtype=float)
    assert [m[2] for m in ResultViewer._extremes(mesh, "p")] == [f"Node {100 + mesh.n_points - 1}", "Node 100"]
    del mesh.cell_data["ELEMENT_ID"]
    assert ResultViewer._extremes(mesh, "v")[0][2] == ""


def test_model_information_lines_and_font():
    from opencourantrp import fonts, units
    from opencourantrp.viewer import info_lines
    info = {"name": "VESSEL", "time": 0.33, "frame": 5, "total": 34}
    assert info_lines(info) == ["VESSEL", "Time = 0.33", "Frame 5 / 34"]
    assert info_lines(info, "ms")[1] == "Time = 0.33 ms"
    assert info_lines({**info, "time": None})[1] == "Time = -" and info_lines(None) == []
    assert units.Units(time="ms").of("time") == "ms" and "info" in fonts.default_fonts()
    saved = fonts.loads('{"ruler": {"size": 20}}')  # settings written before the item existed
    assert saved["info"] == fonts.default_fonts()["info"] and saved["ruler"].size == 20


def test_view_cube_zones_views_and_turns():
    from opencourantrp import viewcube as vc
    down, up = (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)  # looking down at the +Z face, X to the right, Y up
    assert vc.region_at(down, up, 0.0, 0.0) == (0, 0, 1)
    assert vc.region_at(down, up, 0.5, 0.0) == (1, 0, 1)  # near the +X edge of the top face
    assert vc.region_at(down, up, -0.5, 0.5) == (-1, 1, 1)  # near a corner
    assert vc.region_at(down, up, 0.95, 0.0) is None  # beside the cube
    seen = set()
    rng = np.random.default_rng(1)
    for _ in range(400):
        d = rng.normal(size=3)
        region = vc.region_at(d, np.cross(d, rng.normal(size=3)), *rng.uniform(-0.8, 0.8, 2))
        if region:
            seen.add(region)
    assert len(seen) == 26  # 6 faces + 12 edges + 8 corners
    assert vc.view_for_region((0, 0, 1)) == ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0))
    assert vc.view_for_region((0, -1, 0)) == ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0))
    assert [len(vc.patch_quads(r)) for r in ((0, 0, 1), (1, 0, 1), (1, -1, 1))] == [1, 2, 3]
    a, b = np.array([1.0, 0, 0]), np.array([0.0, 1, 0])
    assert np.allclose(vc.slerp(a, b, 0.5), [0.7071, 0.7071, 0], atol=1e-3) and np.allclose(vc.slerp(a, -a, 1.0), -a)
    assert all(np.isclose(np.linalg.norm(vc.slerp(a, -a, t)), 1) for t in (0.0, 0.3, 0.5, 0.7, 1.0))


def test_view_cube_colors_follow_the_background():
    from opencourantrp import viewcube as vc
    assert vc.is_light("#ffffff", "#ffffff") and not vc.is_light("#293954", "#101725")
    assert vc.arrow_colour("#ffffff", "#ffffff", 0.5) == vc.PALETTES["light"]["arrow"]
    assert vc.arrow_colour("#000000", "#000000", 0.5) == "#383838"  # black lightened by 22 %
    tile = vc.tile_image("+X", "vivid", vc.PALETTES["dark"], 128)
    lit = vc.tile_image("+X", "vivid", vc.PALETTES["dark"], 128, hover=True)
    calmer = vc.tile_image("+X", "calmer", vc.PALETTES["dark"], 128)
    assert not np.array_equal(tile, calmer) and not np.array_equal(tile, lit)
    from opencourantrp import modelcolors
    assert [modelcolors.cube_style_loads(v) for v in ("calmer", "vivid", "x", None)] == ["calmer", "vivid", "vivid", "vivid"]
    assert tile.shape == (128, 128, 4) and tile[0, 0, 3] == 0 and tile[64, 20, 3] == 255  # rounded tile
    assert tuple(lit[64, 12, :3]) == tuple(int(vc.PALETTES["dark"]["accent"][i:i + 2], 16) for i in (1, 3, 5))


def test_colorbar_number_formats():
    from opencourantrp.viewer import number_format
    assert number_format(2).format(302.15) == "+3.02e+02" and number_format(2, "sci").format(-0.5) == "-5.00e-01"
    assert number_format(2, "dec").format(302.15) == "+302.15" and number_format(0, "dec").format(0.4) == "+0"
    assert number_format(99, "dec").format(1.0) == "+1.000000" and number_format(-3).format(1.0) == "+1e+00"  # digits are clamped


def test_rigid_lines_take_the_part_of_the_elements_they_touch():
    mesh = solid_mesh()
    pts = np.vstack([mesh.points, [[0.5, 0.5, 5.0]]])
    cells = np.concatenate([[8], np.arange(8), [2, 0, 8]])
    grid = pv.UnstructuredGrid(cells, np.array([12, 3]), pts)
    grid.cell_data["PART_ID"] = np.array([2, 1], dtype=np.int32)  # the line carries its rigid body id (1), not the part
    grid.cell_data["ELEMENT_ID"] = np.array([5, 0], dtype=np.int32)
    assert list(entities.cell_parts(grid)) == [2, 2]
    assert entities.part_ids(grid) == [2]


def rigid_body_mesh():
    """Two dead hexahedra: one with every node on a rigid link (a rigid body), one eroded (loose nodes), and the links."""
    cube = np.asarray(pv.Cube().cast_to_unstructured_grid().points)[:8]
    pts = np.vstack([cube, cube + [5.0, 0, 0], [[0.5, 0.5, 5.0]]])  # 8 + 8 + the master node (index 16)
    cells = [8, *range(8), 8, *range(8, 16)] + [c for i in range(8) for c in (2, 16, i)]
    grid = pv.UnstructuredGrid(np.array(cells), np.array([12, 12] + [3] * 8), pts)
    grid.cell_data["PART_ID"] = np.full(10, 2, dtype=np.int32)
    grid.cell_data["ELEMENT_ID"] = np.array([7, 8] + [0] * 8, dtype=np.int32)
    grid.cell_data["EROSION_STATUS"] = np.array([0, 0] + [1] * 8, dtype=np.int32)  # the bricks are dead, the links alive
    grid.cell_data["3DELEM_Stress"] = np.zeros((10, 9))
    grid.point_data["Displacement"] = np.zeros((17, 3))
    return grid


def test_rigid_body_solids_are_drawn_and_links_can_be_hidden():
    mesh = rigid_body_mesh()
    assert list(entities.rigid_elements(mesh)[:2]) == [True, False]  # the second hexahedron has loose nodes: eroded
    var = variable("U")
    shown, rest, *_ = prepare_view(mesh, var, fixed=entities.KEYS)
    assert shown is None and rest.n_cells == 9  # the rigid solid + eight links
    assert set(entities.classify(rest)) == {"rigid"}
    _, rest, *_ = prepare_view(mesh, var, fixed=entities.KEYS, links=False)
    assert rest.n_cells == 1 and entities.has_links(mesh)
    shown, rest, *_ = prepare_view(mesh, var, fixed=())  # without "rigid" in fixed the dead solids stay hidden
    assert rest is None and shown.n_cells == 8


def test_ghost_is_the_undeformed_skin_with_eroded_elements():
    mesh = solid_mesh()
    mesh.point_data["Displacement"] = np.tile([0.0, 0.0, 3.0], (mesh.n_points, 1))
    mesh.points = np.asarray(mesh.points) + [0.0, 0.0, 3.0]  # the file stores the current positions
    mesh.cell_data["PART_ID"] = np.array([4], dtype=np.int32)
    mesh.cell_data["EROSION_STATUS"] = np.zeros(1, dtype=np.int32)  # eroded: the deformed view hides it, the ghost keeps it
    ghost = ghost_view(mesh, scale=1.0)
    assert ghost is not None and ghost.n_cells == 6  # the six faces of the hexahedron, no inner faces
    assert np.allclose(ghost.bounds, (-0.5, 0.5, -0.5, 0.5, -0.5, 0.5))  # original position, not the displaced one
    assert ghost_view(mesh, hidden={4}) is None  # a hidden part leaves the ghost too
    assert ghost_view(mesh, scale=None) is None  # the undeformed view has nothing to compare with
    assert ghost_view(mesh, section=(2, 100.0, False)) is None  # the section plane keeps no cell
    del mesh.point_data["Displacement"]
    assert ghost_view(mesh) is None


def test_a_shell_with_one_integration_point_has_its_middle_in_layer_1():
    mesh = make_mesh()
    stress = np.zeros((mesh.n_cells, 9))
    stress[:, 0] = 70.0
    for key in ("2DELEM_Stress_(layer__1)_", "2DELEM_Stress_(upper)", "2DELEM_Stress_(lower)"):  # /ANIM/SHELL/TENS/STRESS/ALL, N = 1
        mesh.cell_data[key] = stress.copy()
    assert available(variable("sxx"), mesh)  # the default "middle" no longer asks for layer 3
    assert np.allclose(evaluate(variable("sxx"), mesh, "middle"), 70)
    five = tensor_mesh()  # with the five layers the centre is still layer 3
    for layer in (1, 2, 4, 5):
        five.cell_data[f"2DELEM_Stress_(layer__{layer})_"] = np.zeros((five.n_cells, 9))
    assert np.allclose(evaluate(variable("sxx"), five, "middle"), 100)


def test_dead_shells_of_a_rigid_body_are_drawn_like_its_solids():
    cube = np.asarray(pv.Cube().cast_to_unstructured_grid().points)[:8]
    pts = np.vstack([cube, [[0.5, 0.5, 5.0]]])  # the master node is index 8
    cells = [4, 0, 1, 2, 3, 4, 4, 5, 6, 7] + [c for i in range(4) for c in (2, 8, i)]  # two quads, four links to the first one
    grid = pv.UnstructuredGrid(np.array(cells), np.array([9, 9] + [3] * 4), pts)
    grid.cell_data["ELEMENT_ID"] = np.array([5, 6, 0, 0, 0, 0], dtype=np.int32)
    grid.cell_data["EROSION_STATUS"] = np.array([0, 0, 1, 1, 1, 1], dtype=np.int32)  # both quads are dead
    assert list(entities.rigid_elements(grid)[:2]) == [True, False]  # only the one whose nodes all lie on the links


def test_acceleration_pressure_density_and_truss_energy():
    from opencourantrp import units
    mesh = solid_mesh()
    assert not any(available(variable(k), mesh) for k in ("A", "Ax", "pres", "dens"))
    acc = np.zeros((mesh.n_points, 3)); acc[:, 1] = 3.0; acc[:, 2] = 4.0
    mesh.point_data["Acceleration"] = acc
    assert available(variable("A"), mesh) and np.allclose(evaluate(variable("A"), mesh), 5.0)
    assert np.allclose(evaluate(variable("Ay"), mesh), 3.0)
    mesh.cell_data["3DELEM_Pressure"] = np.full(mesh.n_cells, -2.5)
    mesh.cell_data["3DELEM_Density"] = np.full(mesh.n_cells, 0.001)
    assert np.allclose(evaluate(variable("pres"), mesh), -2.5) and np.allclose(evaluate(variable("dens"), mesh), 0.001)
    assert units.Units(acceleration="mm/s2").of(variable("A").quantity) == "mm/s2"
    assert units.Units(stress="MPa").of(variable("pres").quantity) == "MPa"
    assert units.Units(mass="t", length="mm").of(variable("dens").quantity) == "t/mm^3"
    assert units.Units(mass="t").of("mass/volume") == ""
