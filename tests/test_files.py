"""read, write and edit.

These are the tools that change the user's files, so the tests are about what
happens when the model is *wrong*: an old_text that matches nothing, or matches
too much, or has already been applied, or differs only in a character nobody
can see. The good case is one test; the rest of the file is the failures.
"""

import pytest

from vollama.tools import files

BACKSLASH = chr(92)


@pytest.fixture(autouse=True)
def here(isolated, tmp_path):
    """Relative paths in these tests mean the temporary directory."""
    isolated.workdir = str(tmp_path)
    return tmp_path


def write(here, name, text):
    path = here / name
    path.write_text(text, encoding="utf-8", newline="")
    return path


# ------------------------------------------------------------------- reading


def test_read_returns_the_text_unchanged(here):
    write(here, "a.txt", "one\ntwo\n")
    assert files.read("a.txt") == "one\ntwo"


def test_read_pages_and_says_how_to_continue(here):
    write(here, "big.txt", "".join(f"line {n}\n" for n in range(1, 51)))
    out = files.read("big.txt", offset=1, limit=10)
    assert "line 10" in out and "line 11" not in out
    assert "Use offset=11 to continue." in out


def test_read_past_the_end_says_how_long_the_file_is(here):
    write(here, "a.txt", "one\n")
    assert "nothing at line 9" in files.read("a.txt", offset=9)


def test_a_very_long_line_is_cut_off_and_marked(here):
    write(here, "min.js", "x" * (files.MAX_LINE + 500))
    out = files.read("min.js")
    assert "cut off at" in out
    assert "do not use one as old_text" in out


def test_a_binary_file_is_named_not_just_refused(here):
    (here / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    assert "PNG image" in files.read("logo.png")


def test_a_missing_file_suggests_the_near_miss(here):
    write(here, "settings.json", "{}")
    assert "settings.json" in files.read("setings.json")


# ------------------------------------------------------------------- writing


def test_write_creates_missing_folders_and_reports_what_it_did(here):
    result = files.write("deep/inside/a.txt", "hello\n")
    assert (here / "deep/inside/a.txt").read_text(encoding="utf-8") == "hello\n"
    assert "Created" in result and "1 line" in result


def test_write_refuses_content_that_stands_in_for_the_rest_of_the_file(here):
    write(here, "m.py", "real code\n")
    result = files.write("m.py", "def f():\n    pass\n# ... rest of the code unchanged ...\n")
    assert "Nothing was written" in result
    assert "line 3" in result
    assert (here / "m.py").read_text(encoding="utf-8") == "real code\n"


def test_an_ellipsis_that_is_not_a_placeholder_is_allowed(here):
    assert "Created" in files.write("m.py", 'print("...")\n# ...\n')


def test_broken_json_is_refused_and_broken_python_is_only_warned_about(here):
    refused = files.write("config.json", "{not json")
    assert "Nothing was written" in refused
    assert not (here / "config.json").exists()

    warned = files.write("m.py", "def broken(:\n")
    assert "Warning" in warned
    assert (here / "m.py").exists()


def test_a_file_that_was_already_broken_is_not_held_against_the_fix(here):
    write(here, "config.json", "{still broken")
    assert "Nothing was written" not in files.write("config.json", "{also broken")


def test_writing_keeps_the_line_endings_the_file_had(here):
    write(here, "crlf.txt", "one\r\ntwo\r\n")
    files.write("crlf.txt", "three\nfour\n")
    assert (here / "crlf.txt").read_bytes() == b"three\r\nfour\r\n"


# ------------------------------------------------------------------- editing


def test_one_edit_reports_a_diff(here):
    write(here, "a.txt", "alpha\nbeta\ngamma\n")
    result = files.edit("a.txt", [{"old_text": "beta", "new_text": "BETA"}])
    assert (here / "a.txt").read_text(encoding="utf-8") == "alpha\nBETA\ngamma\n"
    assert "Made 1 edit" in result
    assert "-beta" in result and "+BETA" in result


def test_edits_are_located_against_the_original_and_applied_together(here):
    write(here, "a.txt", "one\ntwo\nthree\n")
    files.edit(
        "a.txt",
        [
            {"old_text": "one", "new_text": "1"},
            {"old_text": "three", "new_text": "3"},
        ],
    )
    assert (here / "a.txt").read_text(encoding="utf-8") == "1\ntwo\n3\n"


def test_an_ambiguous_old_text_changes_nothing_and_says_where(here):
    write(here, "a.txt", "x = 1\ny = 2\nx = 1\n")
    result = files.edit("a.txt", [{"old_text": "x = 1", "new_text": "x = 9"}])
    assert "2 occurrences" in result
    assert "line 1" in result and "line 3" in result
    assert (here / "a.txt").read_text(encoding="utf-8") == "x = 1\ny = 2\nx = 1\n"


def test_replace_all_says_every_one_was_meant(here):
    write(here, "a.txt", "x\ny\nx\n")
    files.edit("a.txt", [{"old_text": "x", "new_text": "z", "replace_all": True}])
    assert (here / "a.txt").read_text(encoding="utf-8") == "z\ny\nz\n"


def test_a_missing_old_text_is_answered_with_what_came_closest(here):
    write(here, "a.txt", "def hello(name):\n    return name\n")
    result = files.edit(
        "a.txt", [{"old_text": "def hello(nome):", "new_text": "def hi(name):"}]
    )
    assert "Did you mean one of these?" in result
    assert "def hello(name):" in result
    assert "first differ at column" in result


def test_a_whitespace_only_difference_is_shown_with_the_whitespace_visible(here):
    write(here, "a.txt", "def f():\n\treturn 1\n")
    result = files.edit(
        "a.txt", [{"old_text": "    return 1", "new_text": "    return 2"}]
    )
    assert "differ from yours in whitespace only" in result
    assert "→return" in result and "····return" in result


def test_an_edit_that_was_already_made_is_skipped_not_failed(here):
    write(here, "a.txt", "new value\n")
    result = files.edit(
        "a.txt", [{"old_text": "old value", "new_text": "new value"}]
    )
    assert "already made" in result
    assert (here / "a.txt").read_text(encoding="utf-8") == "new value\n"


def test_one_landed_edit_does_not_stop_the_rest_of_the_batch(here):
    write(here, "a.txt", "done\nold\n")
    result = files.edit(
        "a.txt",
        [
            {"old_text": "was", "new_text": "done"},
            {"old_text": "old", "new_text": "new"},
        ],
    )
    assert (here / "a.txt").read_text(encoding="utf-8") == "done\nnew\n"
    assert "edits[0] had already been made" in result


def test_an_edit_that_would_change_nothing_is_named(here):
    write(here, "a.txt", "same\n")
    result = files.edit("a.txt", [{"old_text": "same", "new_text": "same"}])
    assert "would not change anything" in result


def test_whitespace_only_old_text_is_refused(here):
    write(here, "a.txt", "a    b\n")
    assert "nothing but whitespace" in files.edit(
        "a.txt", [{"old_text": "  ", "new_text": "-"}]
    )


def test_overlapping_edits_change_nothing(here):
    write(here, "a.txt", "abcdef\n")
    result = files.edit(
        "a.txt",
        [
            {"old_text": "abcd", "new_text": "X"},
            {"old_text": "cdef", "new_text": "Y"},
        ],
    )
    assert "same part" in result
    assert (here / "a.txt").read_text(encoding="utf-8") == "abcdef\n"


def test_an_over_escaped_old_text_matches_once_its_escaping_is_undone(here):
    write(here, "a.txt", "first\nsecond\n")
    result = files.edit(
        "a.txt", [{"old_text": "first" + BACKSLASH + "nsecond", "new_text": "only"}]
    )
    assert (here / "a.txt").read_text(encoding="utf-8") == "only\n"
    assert "escaping was undone" in result


def test_characters_the_model_cannot_see_are_folded_and_the_file_keeps_its_own(here):
    write(here, "a.txt", "say ‘hello’ now\nkeep ‘this’\n")
    result = files.edit(
        "a.txt", [{"old_text": "say 'hello' now", "new_text": "say goodbye now"}]
    )
    text = (here / "a.txt").read_text(encoding="utf-8")
    assert text == "say goodbye now\nkeep ‘this’\n"
    assert "cannot see were folded" in result


def test_editing_a_crlf_file_leaves_it_crlf(here):
    write(here, "a.txt", "one\r\ntwo\r\n")
    files.edit("a.txt", [{"old_text": "two", "new_text": "2"}])
    assert (here / "a.txt").read_bytes() == b"one\r\n2\r\n"


def test_a_byte_order_mark_does_not_break_matching_and_survives(here):
    (here / "a.txt").write_bytes("﻿header\nbody\n".encode("utf-8"))
    files.edit("a.txt", [{"old_text": "header", "new_text": "title"}])
    assert (here / "a.txt").read_bytes() == "﻿title\nbody\n".encode("utf-8")


def test_an_edit_that_would_break_a_config_file_is_refused_with_the_diff(here):
    write(here, "c.json", '{"a": 1}')
    result = files.edit("c.json", [{"old_text": '"a": 1', "new_text": '"a": '}])
    assert "Nothing was changed" in result
    assert "-" in result and "+" in result
    assert (here / "c.json").read_text(encoding="utf-8") == '{"a": 1}'


@pytest.mark.parametrize(
    "argument",
    [
        '[{"old_text": "a", "new_text": "b"}]',
        {"old_text": "a", "new_text": "b"},
        {"edits": [{"old_text": "a", "new_text": "b"}]},
    ],
)
def test_the_shapes_a_model_sends_edits_in_are_all_read(here, argument):
    write(here, "a.txt", "a\n")
    files.edit("a.txt", argument)
    assert (here / "a.txt").read_text(encoding="utf-8") == "b\n"


def test_edits_that_are_not_edits_are_reported(here):
    write(here, "a.txt", "a\n")
    assert "must be a list" in files.edit("a.txt", "not json at all")


# ------------------------------------------------------------------ summaries


def test_the_transcript_summary_names_the_file_and_the_work():
    assert files.summarize_read({"path": "a.py", "offset": 40}) == "read a.py from line 40"
    assert files.summarize_write({"path": "a.py"}) == "write a.py"
    assert files.summarize_edit({"path": "a.py", "edits": [1, 2]}) == "edit a.py (2 edits)"
