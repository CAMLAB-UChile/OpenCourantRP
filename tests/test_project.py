import pytest

from opencourantrp import project


def touch(folder, *names):
    for n in names:
        (folder / n).write_text("")


def test_find_deck_name(tmp_path):
    touch(tmp_path, "a_0000.rad", "a_0001.rad")
    assert project.find_deck_name(tmp_path) == "a"


def test_name_mismatch(tmp_path):
    touch(tmp_path, "a_0000.rad", "b_0001.rad")
    with pytest.raises(project.DeckError, match="same name"):
        project.find_deck_name(tmp_path)


def test_missing_deck(tmp_path):
    touch(tmp_path, "a_0000.rad")
    with pytest.raises(project.DeckError):
        project.find_deck_name(tmp_path)


COMBINED = "\n".join(["#header", "/RUN/n/1", " 10", "/END/ENGINE", "/BEGIN", "n", "/PART/1", "part", "/END", ""])


def test_single_combined_deck(tmp_path):
    (tmp_path / "n_0000.rad").write_text(COMBINED)
    assert project.find_deck_name(tmp_path) == "n"
    assert project.is_combined_deck(tmp_path / "n_0000.rad")


def test_single_deck_without_engine_block_is_refused(tmp_path):
    (tmp_path / "n_0000.rad").write_text("/BEGIN\nn\n/END\n")
    with pytest.raises(project.DeckError, match="Need both"):
        project.find_deck_name(tmp_path)


def test_combined_deck_next_to_a_pair_is_ambiguous(tmp_path):
    (tmp_path / "n_0000.rad").write_text(COMBINED)
    (tmp_path / "m_0000.rad").write_text("")
    (tmp_path / "m_0001.rad").write_text("")
    with pytest.raises(project.DeckError, match="Ambiguous"):
        project.find_deck_name(tmp_path)


def test_part_names_of_a_combined_deck(tmp_path):
    (tmp_path / "n_0000.rad").write_text(COMBINED)
    assert project.read_part_names(tmp_path, "n") == {1: "part"}


def test_run_first_text():
    assert project.run_first_text("n", r"C:\OC", 8) == (
        '@echo off\ncall "%~dp0run_deck.bat" n "C:\OC" 8\npause\n'
    )


def test_write_batch_files_crlf(tmp_path):
    first = project.write_batch_files(tmp_path, "n", r"C:\OC", 4)
    assert first.name == "run_first.bat"
    data = first.read_bytes()
    assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")
    deck = (tmp_path / "run_deck.bat").read_bytes()
    assert deck.startswith(b"@echo off\r\nsetlocal EnableExtensions")


def test_list_vtk_sorted(tmp_path):
    touch(tmp_path, "n.vtk", "nA010.vtk", "nA002.vtk", "nA002", "nA100.vtk", "other_A001.vtk")
    assert [p.name for p in project.list_vtk(tmp_path, "n")] == ["nA002.vtk", "nA010.vtk", "nA100.vtk"]


def test_run_batch_ignores_h3d_cards():
    """/H3D cards need the H3D library and only write .h3d files RP does not read: the engine runs a filtered copy."""
    text = project.run_deck_text()
    assert "rp_prepare_engine.ps1" in text
    assert 'engine_win64.exe" -i "%ENGDECK%"' in text


def test_prepare_engine_script_is_written_and_filters_h3d(tmp_path):
    project.write_batch_files(tmp_path, "n", r"C:\OC", 4)
    script = (tmp_path / "rp_prepare_engine.ps1").read_text()
    assert "/H3D" in script and "/ANIM/VECT/DISP" in script


def test_list_gz_and_vtk_names(tmp_path):
    from opencourantrp import gzanim
    touch(tmp_path, "n_0000.rad", "nA010.gz", "nA002.gz", "nA002.vtk", "nA003", "other_A001.gz", "xA001.gz")
    files = gzanim.list_gz(tmp_path, "n")
    assert [f.step for f in files] == [2, 10]
    assert [f.converted for f in files] == [True, False]
    assert gzanim.vtk_path(files[1].path).name == "nA010.vtk"


def test_convert_reports_missing_converter_and_bad_files(tmp_path):
    from opencourantrp import gzanim
    (tmp_path / "nA001.gz").write_bytes(b"not gzip")
    with pytest.raises(RuntimeError, match="not found"):
        gzanim.convert(tmp_path / "nA001.gz", tmp_path)  # no solver in tmp_path
    exe = tmp_path / "exec"
    exe.mkdir()
    (exe / "anim_to_vtk_win64.exe").write_bytes(b"")
    with pytest.raises(RuntimeError, match="Could not read"):
        gzanim.convert(tmp_path / "nA001.gz", tmp_path)
    assert not (tmp_path / "nA001.vtk").exists() and not list(tmp_path.glob("*.tmp"))


def test_pending_gz_skips_converted_steps(tmp_path):
    from opencourantrp import gzanim
    touch(tmp_path, "n_0000.rad", "nA001.gz", "nA002.gz", "nA002.vtk", "nA003.gz")
    assert [f.step for f in gzanim.pending(tmp_path, "n")] == [1, 3]
