"""What file content is, judged without touching a file.

Three questions, all of them about bytes or text that has been handed to us, and
none of them about a path:

    is this text at all, and if not what is it
    does this text parse as the format its name implies
    does this text say the rest of the file goes here instead of containing it

They live together and away from `files` because they are the judgements, not
the input and output: every function here is pure, and every one of them is the
reason a write is refused or warned about. `files.load` asks the first, `write`
and `edit` ask the other two.
"""

import json
import os


def binary(sample):
    """Whether these bytes look like something that is not text.

    A NUL byte is the whole test. It is what every editor uses, it never appears
    in UTF-8 text, and anything cleverer would guess wrong on a file of Chinese
    or a file of emoji.
    """
    return b"\x00" in sample


# Enough of a file's first bytes to name it. This is only ever the wording of a
# refusal, never a decision, so a guess that calls a .docx a zip archive is
# fine: it still tells the model more than "binary file" does.
SIGNATURES = [
    (b"\x89PNG\r\n\x1a\n", "PNG image"),
    (b"\xff\xd8\xff", "JPEG image"),
    (b"GIF87a", "GIF image"),
    (b"GIF89a", "GIF image"),
    (b"%PDF-", "PDF document"),
    (b"PK\x03\x04", "zip archive, which is also what docx, xlsx, epub and jar are"),
    (b"\x1f\x8b", "gzip archive"),
    (b"7z\xbc\xaf\x27\x1c", "7-Zip archive"),
    (b"Rar!\x1a\x07", "RAR archive"),
    (b"\xfd7zXZ\x00", "xz archive"),
    (b"SQLite format 3\x00", "SQLite database"),
    (b"\x7fELF", "ELF executable"),
    (b"\xd0\xcf\x11\xe0", "Microsoft Office document, pre-2007 format"),
    (b"OggS", "Ogg media"),
    (b"fLaC", "FLAC audio"),
    (b"ID3", "MP3 audio"),
    (b"\xca\xfe\xba\xbe", "Java class file"),
    (b"\x00\x00\x01\x00", "Windows icon"),
    (b"MZ", "Windows executable or DLL"),
    (b"BM", "BMP image"),
]


def describe_bytes(raw):
    """What these bytes look like, in a few words, or None if nothing fits."""
    if raw[:4] == b"RIFF":
        kind = raw[8:12]
        if kind == b"WAVE":
            return "WAV audio"
        if kind == b"AVI ":
            return "AVI video"
        return "RIFF media"
    if raw[4:8] == b"ftyp":
        return "MP4 or QuickTime video"
    for magic, name in SIGNATURES:
        if raw.startswith(magic):
            return name
    return None


def size_of(count):
    """A byte count a person can read."""
    if count < 1024:
        return f"{count} bytes"
    if count < 1024 * 1024:
        return f"{count / 1024:.1f} KB"
    return f"{count / (1024 * 1024):.1f} MB"


# One parser per format, imported where it is used: yaml is a third-party
# package that a stripped-down install may not have, and a check that cannot
# run must not refuse a write. tomllib is in the standard library of the Python
# this project requires, so there is no fallback to tomli.
def check_python(text):
    compile(text, "<write>", "exec")


def check_json(text):
    json.loads(text)


def check_yaml(text):
    import yaml

    yaml.safe_load(text)


def check_toml(text):
    import tomllib

    tomllib.loads(text)


CHECKS = {
    ".py": check_python,
    ".json": check_json,
    ".yaml": check_yaml,
    ".yml": check_yaml,
    ".toml": check_toml,
}
FORMATS = {".py": "Python", ".json": "JSON", ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML"}

# A file in one of these formats exists to be read by another program, and a
# broken one stops that program somewhere else entirely, several tool calls
# later. Refusing the write puts the error where the mistake was made. Python
# only gets a warning: a model writing a module in pieces has a reason to leave
# it briefly unparseable, and the file it breaks is its own.
FAIL_CLOSED = {".json", ".yaml", ".yml", ".toml"}


def fails_closed(path):
    """Whether a parse error in this file is worth refusing the write over."""
    return os.path.splitext(path)[1].lower() in FAIL_CLOSED


def parse_error(path, text):
    """What is wrong with this text as the format its name implies, if anything."""
    ext = os.path.splitext(path)[1].lower()
    check = CHECKS.get(ext)
    if not check:
        return None
    try:
        check(text)
    except ImportError:
        # The parser is not installed. Saying nothing is better than refusing a
        # write over a check that could not be run.
        return None
    except SyntaxError as e:
        where = f" at line {e.lineno}" if e.lineno else ""
        return f"it is not valid {FORMATS[ext]}: {e.msg}{where}"
    except Exception as e:
        return f"it is not valid {FORMATS[ext]}: {str(e).strip()}"
    return None


def introduced(path, before, after):
    """A parse error this write would add, ignoring one the file already had.

    A file that is already broken is usually the reason the model is writing it,
    so complaining about that error would trap it: the fix and the refusal would
    be the same write.
    """
    problem = parse_error(path, after)
    if problem and before is not None and parse_error(path, before):
        return None
    return problem


# Content that says the rest of the file goes here instead of containing it.
# write replaces the whole file, so a model that abbreviates one destroys it, and
# the damage is silent: the write succeeds and the missing code is only noticed
# when something else fails to import it. This is gemini-cli's detector.
#
# The phrases have to be a closed set, and the line has to be a comment with an
# ellipsis in it, or print("...") and a docstring that happens to mention

OMISSIONS = (
    "rest of the code",
    "rest of code",
    "rest of the file",
    "rest of file",
    "rest of the function",
    "rest of the class",
    "rest of the method",
    "rest of the implementation",
    "rest remains",
    "rest unchanged",
    "unchanged",
    "code unchanged",
    "existing code",
    "existing implementation",
    "previous code",
    "keep existing",
    "same as before",
    "no changes",
    "omitted for brevity",
    "truncated for brevity",
    "as before",
    "and so on",
)

# The markers that make a line a comment, in the languages this tool writes.
COMMENTS = ("<!--", "-->", "/*", "*/", "//", "--", "#", ";", "%", "*")

ELLIPSES = ("...", "\u2026")


def commentary(line):
    """The words of a comment line, or None if it is not one.

    Only comments are looked at, because that is what makes the check safe: a
    placeholder is a note to the reader, and a string containing the same words
    is data the file is supposed to have.
    """
    line = line.strip()
    marked = False
    changed = True
    while changed:
        changed = False
        for mark in COMMENTS:
            if line.startswith(mark):
                line, marked, changed = line[len(mark):].strip(), True, True
            if line.endswith(mark):
                line, marked, changed = line[: -len(mark)].strip(), True, True
    return line if marked else None


def placeholder(content):
    """Where this content says the rest of the file goes, as (line number, line).

    Named rather than just refused, since the model has to find the line to fix
    it and a file long enough to be abbreviated is long enough to search.
    """
    for number, line in enumerate(content.split("\n"), 1):
        words = commentary(line)
        if not words or not any(dots in words for dots in ELLIPSES):
            continue
        for dots in ELLIPSES:
            words = words.replace(dots, " ")
        # What is left once the ellipsis and the punctuation are gone. A bare
        # `# ...` says nothing about the rest of the file and is left alone.
        words = " ".join(words.lower().strip(" \t.,:;!-_()[]{}<>").split())
        if words and any(phrase in words for phrase in OMISSIONS):
            return number, line.strip()
    return None
