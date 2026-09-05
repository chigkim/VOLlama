"""Judgements about file content: is it text, does it parse, is it abbreviated.

Pure functions over bytes and strings. What a refusal means for a write is
`test_files.py`'s job; these are the questions it asks.
"""

import pytest

from vollama.tools import content


# --------------------------------------------------------------------- bytes


def test_a_nul_byte_is_what_makes_content_binary():
    assert content.binary(b"text\x00more")
    assert not content.binary("héllo · 안녕".encode())


@pytest.mark.parametrize(
    "raw, named",
    [
        (b"\x89PNG\r\n\x1a\n rest", "PNG image"),
        (b"%PDF-1.7", "PDF document"),
        (b"PK\x03\x04", "zip archive"),
        (b"RIFF....WAVE", "WAV audio"),
        (b"....ftypmp42", "MP4 or QuickTime video"),
    ],
)
def test_binary_content_is_named_so_the_model_knows_which_mistake_it_made(raw, named):
    """A wrong path and a right path in the wrong tool have different fixes."""
    assert named in content.describe_bytes(raw)


def test_bytes_nothing_recognises_are_not_guessed_at():
    assert content.describe_bytes(b"\x01\x02\x03\x04") is None


def test_a_size_is_reported_in_units_a_person_reads():
    assert content.size_of(12) == "12 bytes"
    assert content.size_of(5 * 1024) == "5.0 KB"
    assert content.size_of(3 * 1024 * 1024) == "3.0 MB"


# -------------------------------------------------------------------- syntax


def test_a_parse_error_is_named_with_the_format_and_the_line():
    problem = content.parse_error("thing.json", "{oops}")
    assert "not valid JSON" in problem
    assert content.parse_error("thing.json", '{"ok": 1}') is None


def test_a_file_type_with_no_parser_is_never_refused():
    assert content.parse_error("notes.txt", "{oops}") is None


def test_only_an_error_the_write_would_add_is_reported():
    """A file that is already broken is usually the reason it is being written."""
    assert content.introduced("f.py", "def (", "def (") is None
    assert content.introduced("f.py", "x = 1", "def (") is not None


def test_the_formats_that_another_program_reads_fail_closed():
    assert content.fails_closed("config.JSON")
    assert content.fails_closed("stack.yml")
    assert not content.fails_closed("module.py")


# --------------------------------------------------------------- placeholders


@pytest.mark.parametrize(
    "line",
    [
        "# ... rest of the code unchanged ...",
        "// ... existing code ...",
        "<!-- ... rest of the file ... -->",
        "/* ...unchanged... */",
    ],
)
def test_a_comment_standing_in_for_the_rest_of_the_file_is_found(line):
    found = content.placeholder(f"real = 1\n{line}\nmore = 2\n")
    assert found == (2, line)


@pytest.mark.parametrize(
    "text",
    [
        'print("...")',  # a string, not a comment
        "# ...",  # says nothing about the rest of the file
        "# unchanged since 2019",  # no ellipsis
        "value = 'rest of the code'",
    ],
)
def test_content_that_only_looks_like_a_placeholder_is_left_alone(text):
    assert content.placeholder(text) is None


def test_a_line_that_is_not_a_comment_has_no_commentary():
    assert content.commentary("x = 1") is None
    assert content.commentary("# note") == "note"
