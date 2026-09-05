"""Path rules: what a relative path means, and what is not a file."""

import os

import pytest

from vollama.tools import workspace


def test_relative_paths_come_from_the_chosen_directory(isolated, tmp_path):
    isolated.workdir = str(tmp_path)
    assert workspace.resolve("a/b.txt") == os.path.normpath(str(tmp_path / "a/b.txt"))


def test_a_working_directory_that_has_gone_falls_back_to_the_default(isolated):
    isolated.workdir = "/nowhere/at/all"
    assert workspace.working_dir() == workspace.default_dir()


def test_the_default_is_a_folder_in_the_user_home(isolated):
    """Spelled with expanduser, so it is the right folder on Windows and mac."""
    isolated.workdir = ""
    assert workspace.working_dir() == os.path.join(
        os.path.expanduser("~"), "VOLlama"
    )
    assert "~" not in workspace.working_dir()


def test_the_working_directory_is_created_on_demand(isolated, tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "HOME_DIR", str(tmp_path / "home" / "VOLlama"))
    isolated.workdir = ""
    made = workspace.ensure_working_dir()
    assert os.path.isdir(made)
    # Making it again is not an error, and does not move it.
    assert workspace.ensure_working_dir() == made


def test_an_absolute_path_is_left_alone(tmp_path):
    assert workspace.resolve(str(tmp_path)) == os.path.normpath(str(tmp_path))


def test_an_empty_path_is_refused():
    with pytest.raises(ValueError):
        workspace.resolve("   ")


@pytest.mark.skipif(os.name != "nt", reason="Windows device names")
def test_windows_device_names_are_devices_whatever_their_extension():
    assert workspace.device(os.path.join("C:", "x", "nul"))
    assert workspace.device(os.path.join("C:", "x", "con.txt"))
    assert not workspace.device(os.path.join("C:", "dev", "p", "main.py"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX device paths")
def test_dev_is_a_device_only_on_posix():
    assert workspace.device("/dev/urandom")
    assert not workspace.device("/home/me/nul")


def test_a_missing_file_suggests_the_name_it_nearly_matched(tmp_path):
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="settings.json"):
        workspace.checked(str(tmp_path / "setings.json"))


def test_a_directory_is_not_a_file(tmp_path):
    with pytest.raises(ValueError, match="directory"):
        workspace.checked(str(tmp_path))


def test_a_workdir_that_is_not_there_is_reported(tmp_path):
    with pytest.raises(ValueError, match="no directory"):
        workspace.checked_directory(str(tmp_path / "gone"))
    assert workspace.checked_directory(str(tmp_path)) == str(tmp_path)


def test_nothing_for_a_workdir_means_the_working_directory(isolated, tmp_path):
    isolated.workdir = str(tmp_path)
    assert workspace.checked_directory("") == str(tmp_path)


def test_a_relative_workdir_is_taken_from_the_working_directory(isolated, tmp_path):
    """The same rule as a relative path, since it goes through the same resolve."""
    isolated.workdir = str(tmp_path)
    (tmp_path / "inside").mkdir()
    assert workspace.checked_directory("inside") == str(tmp_path / "inside")
