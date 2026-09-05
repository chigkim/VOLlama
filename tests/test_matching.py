"""Locating the text an edit names, and the wording of a miss.

These are the parts of `edit` that never touch a file, which is why they are
their own module: every case here is two strings and an answer. What they mean
for a file on disk is `test_files.py`'s job.
"""

import pytest

from vollama.tools import matching


# ------------------------------------------------------------------ locating


def locate(text, old, every=False):
    """`matching.locate` with the reporting arguments filled in."""
    return matching.locate(text, old, 0, 1, "file.txt", every)


def test_an_exact_match_needs_no_repair():
    found, how = locate("alpha beta gamma", "beta")
    assert found == [(6, 10)]
    assert how is None


def test_over_escaped_text_matches_and_says_so():
    found, how = locate("one\ntwo\n", "one\\ntwo")
    assert found == [(0, 7)]
    assert how == "escape"
    assert how in matching.REPAIRS


def test_characters_the_model_cannot_see_are_folded_and_named():
    found, how = locate('say "hello" now', 'say “hello” now')
    assert found == [(0, 15)]
    assert how == "unicode"
    assert how in matching.REPAIRS


def test_tabs_and_spaces_are_not_folded_into_each_other():
    """The one fold that would leave a file's indentation quietly mixed."""
    with pytest.raises(matching.NotFound):
        locate("\tindented\n", "    indented")


def test_an_ambiguous_match_is_refused_unless_every_one_was_meant():
    text = "x\nx\nx\n"
    with pytest.raises(ValueError, match="3 occurrences"):
        locate(text, "x")
    found, _ = locate(text, "x", every=True)
    assert found == [(0, 1), (2, 3), (4, 5)]


def test_an_empty_or_blank_old_text_is_refused_by_name():
    with pytest.raises(ValueError, match="empty"):
        locate("anything", "")
    with pytest.raises(ValueError, match="whitespace"):
        locate("anything", "   ")


def test_a_missing_old_text_raises_the_failure_that_can_be_answered():
    """NotFound and not ValueError, so `edit` can ask whether it already landed."""
    with pytest.raises(matching.NotFound):
        locate("alpha\n", "omega")


# ------------------------------------------------------------------- folding


def test_folding_maps_every_character_back_to_the_original():
    text = "a“b”c"
    folded, index = matching.fold(text)
    assert folded == 'a"b"c'
    assert len(index) == len(folded) + 1
    for at, character in enumerate(folded):
        assert text[index[at]] in ("“", "”", character)


def test_folding_drops_the_invisible_and_the_trailing():
    assert matching.fold("a​b  \nc")[0] == "ab\nc"


def test_a_fold_that_cannot_be_mapped_back_refuses_the_whole_lookup():
    """Fail closed: an unclear mapping must not be applied to a guess."""
    assert matching.fold_match("plain text", "text") == []


# ------------------------------------------------------------------- wording


def test_an_ambiguous_match_says_where_rather_than_how_many():
    text = "keep\nsame\nkeep\n"
    sites = matching.ambiguous(text, [(0, 4), (10, 14)], "old_text", "f.py")
    assert "line 1" in sites and "line 3" in sites


def test_nothing_close_says_to_read_the_file_again():
    message = matching.no_match("nothing alike here", "xyzzy", "old_text", "f.py")
    assert "read the file again" in message


def test_a_near_miss_shows_the_lines_it_nearly_matched():
    text = "def one():\n    return 1\n\n\ndef two():\n    return 2\n"
    message = matching.no_match(text, "def two():\n    return 3", "old_text", "f.py")
    assert "Did you mean" in message
    assert "def two():" in message


def test_a_whitespace_difference_is_shown_with_the_whitespace_visible():
    message = matching.no_match("\tvalue = 1\n", "    value = 1", "old_text", "f.py")
    assert "→" in message and "·" in message


@pytest.mark.parametrize(
    "mine, theirs, said",
    [
        ("    x = 1", "\tx = 1", "indentation differs"),
        ("a\\nb", "a\\\\nb", "escaping differs"),
        ("alpha", "alpine", "column"),
        ("x = 1 ", "x = 1", "whitespace inside the line"),
    ],
)
def test_the_kind_of_difference_is_named(mine, theirs, said):
    assert said in matching.kind(mine, theirs)


def test_the_label_is_the_field_when_there_is_only_one_edit():
    assert matching.label(0, 1) == "old_text"
    assert matching.label(2, 3) == "edits[2]"


# ------------------------------------------------------------- already made


def test_new_text_already_in_the_file_exactly_once_is_a_landed_edit():
    assert matching.applied("a = 1\n", "a = 1")
    assert not matching.applied("a = 1\na = 1\n", "a = 1")
    assert not matching.applied("a = 1\n", "")
