"""read, write and edit: file tools that spare the model quoting a file inside Python.

All three could be done with run, and that is the point. Doing it there
means the file's own text has to survive being a Python string literal first,
quotes, backslashes and triple quotes and all, which is where a small model
fails and fails silently: you get a file with a literal \\n in it rather than an
error. As a tool parameter the same text is one JSON string, escaped by the
layer that is good at escaping.

edit adds the one thing a hand-written replace cannot. text.replace(old, new)
changes every occurrence and text.replace(old, new, 1) changes an arbitrary one,
and either way the file is already wrong before anyone notices the match was
ambiguous. Here every edit in a call is located and checked against the original
file before any of them is written, so an ambiguous or missing match leaves the
file exactly as it was.
"""

import difflib
import json
import os
import re
import unicodedata

from Settings import settings

# How much of a file one read returns. Lines first, since that is how a model
# asks for more, and bytes as well because one minified line can be a megabyte.
MAX_LINES = 2000
MAX_BYTES = 50 * 1024

# How much of one line is worth returning. A minified file is a single line of
# a megabyte, and without this the byte cap cannot save you from it: cutting the
# read off before its first line would return nothing at all.
MAX_LINE = 2000

# A file bigger than this is not going to be read as text at all.
MAX_FILE = 10 * 1024 * 1024

# How much of an edit's diff is worth showing back. Enough to confirm the right
# place changed, not enough to repeat the file.
MAX_DIFF = 4000
DIFF_CONTEXT = 2

# How much of a near miss is worth showing when an old_text does not match, and
# how alike it has to be before showing it is help rather than noise.
SUGGESTIONS = 3
CLOSE_ENOUGH = 0.3
SNIPPET_LINES = 20
SEARCH_LINES = 20000

# How many places an ambiguous old_text is shown at, and how much of each line.
# A bare count leaves the model to find them itself, which it does by reading
# the file again and sending the same edit.
SITES = 5
SITE_WIDTH = 120

# Paths that are not files even though they parse as one. Writing to a Windows
# reserved name talks to a device instead of the disk and reports success, and
# a character device under /dev never ends.
DEVICES = (
    {"con", "prn", "aux", "nul"}
    | {f"com{n}" for n in range(1, 10)}
    | {f"lpt{n}" for n in range(1, 10)}
)


def working_dir():
    """Where a relative path is taken from. What the Chat menu's CD shows.

    Checked on the way out rather than when it is set, since a directory chosen
    in an earlier session can be gone, on a drive that is not mounted, by the
    time it is used.
    """
    chosen = (settings.workdir or "").strip()
    if chosen and os.path.isdir(chosen):
        return chosen
    return os.getcwd()


def resolve(path):
    """Absolute path for what the model asked for, relative to the working directory."""
    path = os.path.expanduser((path or "").strip())
    if not path:
        raise ValueError("No path was given.")
    if not os.path.isabs(path):
        path = os.path.join(working_dir(), path)
    return os.path.normpath(path)


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


def load(path):
    """The file as text with \\n line endings, plus the endings and BOM it has.

    Reading with universal newlines means everything downstream, the model's
    old_text included, is written with plain \\n and a CRLF file does not have to
    be matched byte for byte. What the file had is handed back so writing can put
    it back the way it was.

    A byte order mark comes off the front for the same reason. Left in, it is an
    invisible character on line 1 that makes a perfectly correct old_text fail to
    match, with nothing in the error to say why.
    """
    with open(path, "rb") as f:
        raw = f.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE:
        raise ValueError(
            f"{path} is larger than {MAX_FILE // (1024 * 1024)} MB. "
            "Read it in pieces with run instead."
        )
    if binary(raw[:8192]):
        # Named rather than just refused, because "binary file" leaves the model
        # to guess whether it asked for the wrong path or the right one in the
        # wrong tool, and those have different fixes.
        kind = describe_bytes(raw) or "binary data"
        raise ValueError(
            f"{path} is not text: {kind}, {size_of(len(raw))}. "
            "Use run if you need its bytes."
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(
            f"{path} is not valid UTF-8 ({e.reason} at byte {e.start}). "
            "Editing it here would corrupt it, so open it with run instead."
        )
    bom = "\ufeff" if text.startswith("\ufeff") else ""
    text = text[len(bom):]
    newline = "\r\n" if "\r\n" in text else "\n"
    return text.replace("\r\n", "\n"), newline, bom


def save(path, text, newline, bom=""):
    """Write text back, restoring the line endings and BOM the file had."""
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline=newline) as f:
        f.write(bom + text)


def device(full):
    """Whether this path names a device rather than a file on disk.

    Each platform's rule only applies on that platform. /dev is a folder name
    like any other on Windows, where C:\\dev is where a good many people keep
    their code, and nul is an ordinary filename on Linux.
    """
    if os.name == "nt":
        # con.txt is the console too, so the extension comes off first.
        return os.path.basename(full).split(".")[0].lower() in DEVICES
    return full.startswith("/dev/")


def suggest(full):
    """Names in the same folder close to the one asked for, as a sentence.

    A path that is wrong is usually wrong by a character or a plural, and the
    answer is sitting in the same directory listing we already have to touch to
    know the file is missing.
    """
    parent = os.path.dirname(full) or "."
    try:
        names = os.listdir(parent)
    except OSError:
        return ""
    close = difflib.get_close_matches(os.path.basename(full), names, n=3, cutoff=0.6)
    if not close:
        return ""
    return " Did you mean " + ", ".join(close) + "?"


def checked(path, must_exist=True):
    """Turn a path into one we can act on, or say why we cannot."""
    full = resolve(path)
    if device(full):
        raise ValueError(
            f"{full} is a device, not a file. Reading one may never return and "
            "writing one throws the text away, so it is refused here. Use run "
            "if you really mean the device."
        )
    if os.path.isdir(full):
        raise ValueError(f"{full} is a directory, not a file.")
    if must_exist and not os.path.exists(full):
        raise ValueError(
            f"There is no file at {full}. Relative paths are taken from "
            f"{working_dir()}.{suggest(full)}"
        )
    return full


def read(path, offset=1, limit=MAX_LINES):
    """Return part of a text file, with a footer saying how to see the rest."""
    try:
        full = checked(path)
        text, _, _ = load(full)
    except (ValueError, OSError) as e:
        return str(e)

    lines = text.split("\n")
    # A trailing newline makes a last empty piece that is not a line of the file.
    if lines and lines[-1] == "":
        lines.pop()
    total = len(lines)
    if not total:
        return f"{full} is empty."

    try:
        offset = max(1, int(offset))
        limit = max(1, min(int(limit), MAX_LINES))
    except (TypeError, ValueError):
        return "offset and limit must be whole numbers."
    if offset > total:
        return f"{full} has {total} lines, so there is nothing at line {offset}."

    start = offset - 1
    shown = lines[start : start + limit]

    # Each line first, because one of them can be the whole file. The byte cap
    # below stops before its first line rather than returning nothing, so
    # without this a single enormous line would come back whole.
    cut = 0
    for i, line in enumerate(shown):
        if len(line) > MAX_LINE:
            cut += 1
            shown[i] = (
                line[:MAX_LINE]
                + f"... [line {start + i + 1} cut off at {MAX_LINE} of "
                f"{len(line)} characters]"
            )

    # Line count is the limit a model can reason about; byte count is the one
    # that protects the context window when the lines are enormous.
    size = 0
    for i, line in enumerate(shown):
        size += len(line.encode("utf-8")) + 1
        if size > MAX_BYTES and i:
            shown = shown[:i]
            break

    end = start + len(shown)
    body = "\n".join(shown)
    note = ""
    if cut:
        # Said once, because a cut line is no longer the file's text and passing
        # it to edit as old_text would not match.
        note = (
            " Long lines are cut off where marked, so do not use one as "
            "old_text; run something like sed to see one in full."
        )
    if end >= total and offset == 1 and not cut:
        return body
    footer = f"[Showing lines {offset}-{end} of {total}."
    if end < total:
        footer += f" Use offset={end + 1} to continue."
    return f"{body}\n\n{footer}{note}]"


def check_python(text):
    compile(text, "<write>", "exec")


def check_json(text):
    import json

    json.loads(text)


def check_yaml(text):
    import yaml

    yaml.safe_load(text)


def check_toml(text):
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib

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
# unchanged code become refused writes.
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


def write(path, content):
    """Create or replace a file with exactly the text given."""
    content = (content or "").replace("\r\n", "\n")
    # Before the path is even resolved: this content is not a file, whatever it
    # was going to be written to.
    left = placeholder(content)
    if left:
        return (
            f"Nothing was written, because line {left[0]} of the content says "
            f"the rest of the file goes there rather than containing it:\n"
            f"  {left[1]}\n"
            "write replaces the whole file, so this would delete everything the "
            "line stands for. Send the file complete, or use edit to change only "
            "the parts that differ."
        )
    try:
        full = checked(path, must_exist=False)
        existed = os.path.exists(full)
        # A file that is already there keeps the line endings and BOM it has; a
        # new one gets \n and no BOM, which is what everything except Notepad
        # expects.
        before, newline, bom = load(full) if existed else (None, "\n", "")
        broke = introduced(full, before, content)
        if broke and os.path.splitext(full)[1].lower() in FAIL_CLOSED:
            return (
                f"Nothing was written to {full}, because {broke}. Fix it and "
                "send the whole file again."
            )
        save(full, content, newline, bom)
    except (ValueError, OSError) as e:
        return str(e)
    count = content.count("\n") + (0 if content.endswith("\n") or not content else 1)
    lines = "1 line" if count == 1 else f"{count} lines"
    was = "Replaced" if existed else "Created"
    ending = "CRLF" if newline == "\r\n" else "LF"
    note = f" Warning: {broke}." if broke else ""
    return f"{was} {full}: {lines}, {len(content)} characters, {ending}.{note}"


# A model that builds old_text by writing Python rather than by copying the
# file sends \n as two characters. This is the one failure these tools exist to
# prevent, so when an exact match fails it is worth trying the text with its
# escaping undone before giving up. Ported from gemini-cli's
# unescapeStringForGeminiBug.
ESCAPED = re.compile(r"\\+(n|t|r|'|\"|`|\\|\n)")
UNESCAPED = {"n": "\n", "t": "\t", "r": "\r", "\n": "\n"}


def unescape(text):
    """The same text with over-escaped characters turned back into characters."""
    return ESCAPED.sub(lambda m: UNESCAPED.get(m.group(1), m.group(1)), text)


def occurrences(text, old):
    """Where old appears, not counting overlaps, the way str.replace counts."""
    out = []
    at = text.find(old)
    while at != -1:
        out.append(at)
        at = text.find(old, at + len(old))
    return out


def visible(text):
    """The same text with its spaces and tabs made visible."""
    return text.replace("\t", "→").replace(" ", "·")


# Characters a model writes as something else, or that it cannot see at all.
# A file that has been through a word processor, a web page, a chat client or
# another model's output is full of them: a curly quote where the source had a
# straight one, an en dash for a hyphen, a zero-width space left over from
# copied HTML. NFKC handles the non-breaking and full width families and the
# ellipsis; these are the ones it deliberately leaves alone.
FOLDED = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "―": "-", "−": "-",
    # Invisible, so a mismatch caused by one is a mismatch with nothing in the
    # error to explain it. Dropped rather than folded.
    "​": "", "‌": "", "‍": "", "⁠": "", "­": "",
    "﻿": "",
}

# Tabs and spaces are deliberately not made equivalent. Folding them would let
# an old_text indented with spaces match a file indented with tabs, and since
# new_text is written exactly as sent, the file would come back with its
# indentation quietly mixed. Trailing whitespace is dropped, which has no such
# hazard: it is invisible and carries no meaning.


def fold(text):
    """The text with confusable characters folded, and a map back to it.

    Every character of the result comes from exactly one character of the
    input, and the map records which, so a match found in here can be handed
    back in the original text's own coordinates. That is what makes this safe:
    the fold is only ever used to find the place, and the file's own characters
    are what gets edited.

    One input character may fold to none or to several, never the reverse, so
    the map stays in order and a span end can always be looked up. A span that
    starts or ends inside one character's expansion is caught by the caller
    re-folding what it found.
    """
    out = []
    index = []
    pending = []  # whitespace held back until we know it is not trailing
    for i, ch in enumerate(text):
        for c in FOLDED.get(ch, unicodedata.normalize("NFKC", ch)):
            if c in " \t":
                pending.append((i, c))
            elif c == "\n":
                pending = []
                out.append(c)
                index.append(i)
            else:
                for j, held in pending:
                    out.append(held)
                    index.append(j)
                pending = []
                out.append(c)
                index.append(i)
    index.append(len(text))  # so the end of a match at the end still maps
    return "".join(out), index


def fold_match(text, old):
    """Where old goes when the only difference is a character it cannot see.

    Lookup only. Each span comes back as offsets into the original text and is
    verified by folding the original slice again, so an unclear mapping refuses
    the whole edit instead of applying it to a guess.
    """
    needle, _ = fold(old)
    if not needle.strip():
        return []
    hay, index = fold(text)
    if hay == text and needle == old:
        # Nothing was folded on either side, so this is the exact match that
        # has already failed.
        return []
    spans = []
    for at in occurrences(hay, needle):
        start, end = index[at], index[at + len(needle)]
        if end <= start or fold(text[start:end])[0] != needle:
            return []
        spans.append((start, end))
    return spans


class NotFound(ValueError):
    """An old_text that matched nothing, as opposed to one that matched too much."""


def applied(text, new):
    """Whether this edit's new_text is already in the file, exactly once.

    Re-sending an edit that has already landed is the commonest way a batch
    fails, and failing it is wrong twice: the file is already what was asked
    for, and the model's next move is to read the file and send the same edit
    again. Uniqueness is the guard against reading a coincidence as a landed
    edit, and it is a strong one: a fragment long enough to be somebody's
    new_text appears once or not at all.
    """
    new = (new or "").strip()
    return bool(new) and len(occurrences(text, new)) == 1


def ambiguous(text, found, where, path):
    """Why an old_text matching several places was refused, and where they are."""
    sites = []
    for start, _ in found[:SITES]:
        line = text.count("\n", 0, start) + 1
        first = text[start:].split("\n", 1)[0].strip()
        sites.append(f"  line {line}: {first[:SITE_WIDTH]}")
    if len(found) > SITES:
        sites.append(f"  ... and {len(found) - SITES} more")
    return (
        f"Found {len(found)} occurrences of {where} in {path}, so it is not "
        "clear which one you meant. Nothing was changed. They start at:\n"
        + "\n".join(sites)
        + "\nInclude more of the surrounding lines to pick one of them out, or "
        "set replace_all to true to change every one."
    )


def edits_of(edits):
    """The list of edits, out of the shapes a model actually sends.

    The array arriving as a JSON string, one edit as a bare object, the whole
    thing wrapped in a second edits key: each is unambiguous, so reading it is
    better than spending a turn on the shape of the argument.
    """
    for _ in range(3):
        if isinstance(edits, str):
            try:
                edits = json.loads(edits)
            except ValueError:
                return None
            continue
        if isinstance(edits, dict):
            inner = edits.get("edits")
            if inner is not None and "old_text" not in edits:
                edits = inner
                continue
            edits = [edits]
        break
    if not isinstance(edits, list) or not edits:
        return None
    unpacked = []
    for item in edits:
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except ValueError:
                pass
        unpacked.append(item)
    return unpacked


def nearest(text, old):
    """The places in text that most look like old, closest first.

    An exact match has already failed by the time this runs, and the useful
    thing to say then is not that it failed but where it nearly did not. A model
    shown the lines it came close to can correct its own old_text; one told only
    that nothing matched reads the whole file again and sends the same thing.
    """
    lines = text.split("\n")[:SEARCH_LINES]
    wanted = old.strip("\n").split("\n")
    span = min(len(wanted), SNIPPET_LINES)

    # Anchored on one line rather than compared window by window. Comparing a
    # twenty line block against every position in a large file is minutes of
    # work for an error message; one line against each line is a moment, and it
    # lands in the same place, since a block that nearly matches has to start
    # somewhere that nearly matches.
    key = next((line for line in wanted if line.strip()), wanted[0]).strip()
    matcher = difflib.SequenceMatcher(a="", b=key, autojunk=False)

    scored = []
    for start, line in enumerate(lines):
        matcher.set_seq1(line.strip())
        # Two cheap upper bounds first, since there is one comparison per line.
        if matcher.real_quick_ratio() < CLOSE_ENOUGH:
            continue
        if matcher.quick_ratio() < CLOSE_ENOUGH:
            continue
        score = matcher.ratio()
        if score >= CLOSE_ENOUGH:
            scored.append((-score, start, "\n".join(lines[start : start + span])))
    scored.sort()

    picked = []
    for item in scored:
        # The windows overlap, so without this the three suggestions are three
        # views of the same lines.
        if any(abs(item[1] - other[1]) < span for other in picked):
            continue
        picked.append(item)
        if len(picked) == SUGGESTIONS:
            break
    return [(start + 1, window) for _, start, window in picked]


def indent_of(line):
    """How the line is indented, as a count of spaces and of tabs."""
    lead = line[: len(line) - len(line.lstrip(" \t"))]
    return lead.count(" "), lead.count("\t")


def spell(spaces, tabs):
    """A count of spaces and tabs in words, since the characters do not show."""
    parts = []
    if spaces:
        parts.append(count_of(spaces, "space", "spaces"))
    if tabs:
        parts.append(count_of(tabs, "tab", "tabs"))
    return " and ".join(parts) or "nothing"


def count_of(n, one, many):
    """A count with its noun, singular when it should be."""
    return f"{n} {one if n == 1 else many}"


def column(mine, theirs):
    """The 1-based column where these two lines first differ."""
    for at, (a, b) in enumerate(zip(mine, theirs)):
        if a != b:
            return at + 1
    return min(len(mine), len(theirs)) + 1


def diverges(sent, found):
    """The first line of these two blocks that is not the same, as a pair."""
    mine = sent.strip("\n").split("\n")
    theirs = found.strip("\n").split("\n")
    for pair in zip(mine, theirs):
        if pair[0] != pair[1]:
            return pair
    return None


def kind(mine, theirs):
    """What sort of difference this is, named, in openclaw's order.

    Naming it is the whole point. "It must match exactly" tells a model what the
    rule is, which it already knew; the reason its text did not match is a fact
    about these two lines, and indentation and escaping are the two it cannot
    see by reading either one of them again.
    """
    if mine.strip() == theirs.strip():
        want, have = indent_of(mine), indent_of(theirs)
        if want != have:
            return (
                f"the indentation differs: you sent {spell(*want)}, the file "
                f"has {spell(*have)}"
            )
        return "the difference is whitespace inside the line or at the end of it"
    slash = "\\"
    # Only when the backslashes are the whole of the difference. Two unrelated
    # lines usually differ in backslash count too, and calling that an escaping
    # problem sends the model after something that is not wrong.
    if mine.replace(slash, "") == theirs.replace(slash, ""):
        return (
            "the escaping differs: you sent "
            f"{count_of(mine.count(slash), 'backslash', 'backslashes')}, the "
            f"file has {theirs.count(slash)}"
        )
    return f"they first differ at column {column(mine, theirs)}"


def divergence(sent, found):
    """The first difference between what was sent and the closest thing found."""
    pair = diverges(sent, found)
    if pair is None:
        return [
            "",
            "Every line you sent matches one of those; the difference is in how "
            "many lines there are or in the lines around them.",
        ]
    mine, theirs = pair
    named = kind(mine, theirs)
    if "whitespace" in named or "indentation" in named:
        # Shown with the whitespace made visible, or the two lines print the
        # same and the error reads as though there is no difference at all.
        return [
            "",
            f"The first line that differs: {named}. Shown with \u2192 for a tab "
            "and \u00b7 for a space.",
            "You sent:      " + visible(mine[:MAX_DIFF]),
            "The file has:  " + visible(theirs[:MAX_DIFF]),
        ]
    lines = [
        "",
        f"The first line that differs: {named}.",
        "You sent:      " + mine[:MAX_DIFF],
        "The file has:  " + theirs[:MAX_DIFF],
    ]
    at = column(mine, theirs)
    if at <= MAX_DIFF:
        lines.append(" " * (len("The file has:  ") + at - 1) + "^")
    return lines


def no_match(text, old, where, path):
    """Why an old_text did not match, and what in the file came closest to it."""
    message = (
        f"Could not find {where} in {path}. It must match the file exactly, "
        "whitespace and line breaks included."
    )
    close = nearest(text, old)
    if not close:
        return message + (
            " Nothing in the file is close to it, so read the file again to see "
            "what is actually there."
        )

    parts = [message, "", "Did you mean one of these?"]
    for line, window in close:
        parts.append(f"--- {path} line {line} ---")
        parts.append(window)

    top = close[0][1]
    if top == old:
        return "\n".join(parts)
    if " ".join(top.split()) == " ".join(old.split()):
        # The whole difference is whitespace, which is exactly the difference a
        # model cannot see in its own output or in the file it was given.
        parts += [
            "",
            "Those lines differ from yours in whitespace only, shown here with "
            "→ for a tab and · for a space.",
            "You sent:",
            visible(old[:MAX_DIFF]),
            "The file has:",
            visible(top[:MAX_DIFF]),
        ]
    else:
        parts += divergence(old, top)
    return "\n".join(parts)


def label(index, count):
    """What to call one edit when reporting it: its position, or just the field."""
    return f"edits[{index}]" if count > 1 else "old_text"


def locate(text, old, index, count, path, every=False):
    """Where one edit goes, or why it does not go anywhere.

    Returns the spans as (start, end) offsets into text, and how they were
    found: None for an exact match, or the name of the one fallback that had to
    be used.

    Exact first, always. The fallbacks are tried in the order of how sure they
    are, they are lookup only, and each is named in the result so the model
    learns what it got wrong. Both failures are reported before anything is
    written, since an edit that matched three places is a model that does not
    know which one it meant, and guessing for it is how a file quietly ends up
    wrong. Unless it said so: replace_all is that model saying it meant all of
    them.
    """
    where = label(index, count)
    if not old:
        raise ValueError(f"{where} is empty. It must be the text you want replaced.")
    if not old.strip():
        raise ValueError(
            f"{where} is nothing but whitespace, which cannot say which part of "
            f"{path} you mean. Include the line you want changed."
        )

    how = None
    found = [(at, at + len(old)) for at in occurrences(text, old)]
    if not found:
        plain = unescape(old)
        if plain != old:
            found = [(at, at + len(plain)) for at in occurrences(text, plain)]
            if found:
                how = "escape"
    if not found:
        found = fold_match(text, old)
        if found:
            how = "unicode"
    if not found:
        raise NotFound(no_match(text, old, where, path))
    if len(found) > 1 and not every:
        raise ValueError(ambiguous(text, found, where, path))
    return found, how


REPAIRS = {
    "escape": (
        "only matched once its escaping was undone: you sent a backslash and an "
        "n where the file has a line break. Send the text as it is, not as it "
        "would look inside a Python string."
    ),
    "unicode": (
        "only matched once characters you cannot see were folded: a curly quote, "
        "a dash, a zero-width space or whitespace at the end of a line, written "
        "differently from the file. The file's own characters were kept "
        "everywhere you did not replace them."
    ),
}


def edit(path, edits):
    """Replace unique pieces of a file, all of them or none of them."""
    edits = edits_of(edits)
    if edits is None:
        return "edits must be a list of {old_text, new_text} objects."

    try:
        full = checked(path)
        before, newline, bom = load(full)
    except (ValueError, OSError) as e:
        return str(e)

    # Located against the original text, never against the result of the edit
    # before, so the model does not have to imagine the file part way through.
    spans = []
    repairs = {}
    already = []
    try:
        for i, item in enumerate(edits):
            if not isinstance(item, dict):
                raise ValueError(f"edits[{i}] must be an object with old_text and new_text.")
            old = (item.get("old_text") or "").replace("\r\n", "\n")
            new = (item.get("new_text") or "").replace("\r\n", "\n")
            every = bool(item.get("replace_all"))
            if old and new == old:
                # Caught here rather than by the no-op check at the end, so a
                # model sending one good edit and one that changes nothing is
                # told which, instead of having the whole call quietly succeed.
                name = f"edits[{i}]" if len(edits) > 1 else "This edit"
                raise ValueError(
                    f"{name} has the same new_text as old_text, so it would not "
                    "change anything. Nothing was written."
                )
            try:
                found, how = locate(before, old, i, len(edits), full, every)
            except NotFound:
                # The old text is gone and the new text is already there, once:
                # this edit has already been made. Reporting that as a failure
                # sends the model round the same loop again.
                if applied(before, new):
                    already.append(i)
                    continue
                raise
            if how:
                repairs[how] = repairs.get(how, 0) + 1
            for start, end in found:
                spans.append((start, end, new, i))
    except ValueError as e:
        return str(e)

    if not spans:
        made = "The edit was" if len(edits) == 1 else f"All {len(edits)} edits were"
        return (
            f"{made} already made in {full}, so there was nothing left to do "
            "and nothing was written. The file is already what you asked for."
        )

    spans.sort()
    for (start, end, _, i), (later, _, _, j) in zip(spans, spans[1:]):
        if later < end:
            return (
                f"edits[{i}] and edits[{j}] both cover the same part of {full}. "
                "Nothing was changed. Make it one edit, or move them apart."
            )

    pieces = []
    at = 0
    for start, end, new, _ in spans:
        pieces.append(before[at:start])
        pieces.append(new)
        at = end
    pieces.append(before[at:])
    after = "".join(pieces)

    if after == before:
        return f"Nothing changed in {full}: the new text is the same as the old."

    # Checked here as well as in write, since an edit breaks a config file the
    # same way a rewrite does, and by the time another program trips over it the
    # tool call that did it is several messages back.
    broke = introduced(full, before, after)
    if broke and os.path.splitext(full)[1].lower() in FAIL_CLOSED:
        return (
            f"Nothing was changed in {full}, because the result would not "
            f"parse: {broke}. This is what the edit would have done:\n"
            f"{diff(before, after, full)}"
        )
    try:
        save(full, after, newline, bom)
    except OSError as e:
        return str(e)

    count = len(spans)
    made = "1 edit" if count == 1 else f"{count} edits"
    notes = [f" One old_text {REPAIRS[how]}" for how in sorted(repairs)]
    if already:
        which = ", ".join(f"edits[{i}]" for i in already)
        notes.append(
            f" {which} had already been made, so it was skipped rather than "
            "counted above."
        )
    if broke:
        notes.append(f" Warning: {broke}.")
    return f"Made {made} in {full}.{''.join(notes)}\n{diff(before, after, full)}"


def diff(before, after, path):
    """A short unified diff, so the model can see it changed what it meant to."""
    # Trimmed of the trailing empty piece, or a file that ends in a newline
    # shows a blank context line under every hunk.
    lines = difflib.unified_diff(
        before.rstrip("\n").split("\n"),
        after.rstrip("\n").split("\n"),
        fromfile=path,
        tofile=path,
        lineterm="",
        n=DIFF_CONTEXT,
    )
    text = "\n".join(lines)
    if len(text) > MAX_DIFF:
        text = text[:MAX_DIFF] + f"\n... diff truncated at {MAX_DIFF} characters ..."
    return text


READ_TOOL = {
    "type": "function",
    "function": {
        "name": "read",
        "description": (
            "Read a text file. Returns the text as it is, with no line numbers "
            "added, so anything you copy out of it can be passed straight back "
            f"to edit. At most {MAX_LINES} lines at a time; when there is more, "
            "the last line says which offset to ask for next. A line longer "
            f"than {MAX_LINE} characters is cut off and marked where it ends. "
            "Relative paths are taken from the working directory. Use run for "
            "anything that is not text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file to read.",
                },
                "offset": {
                    "type": "integer",
                    "description": (
                        "Line to start at, counting from 1. Defaults to 1."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        f"How many lines to return. Defaults to {MAX_LINES}, "
                        "which is also the most it will give you."
                    ),
                },
            },
            "required": ["path"],
        },
    },
}

WRITE_TOOL = {
    "type": "function",
    "function": {
        "name": "write",
        "description": (
            "Write a text file, creating it and any missing folders, or "
            "replacing it whole if it is already there. The content is written "
            "exactly as given, so send the finished file and not a fragment. To "
            "change part of a file that already exists, use edit instead: it "
            "does not need you to repeat the parts you are leaving alone. "
            "Python, JSON, YAML and TOML are parsed before they are written; a "
            "JSON, YAML or TOML file that does not parse is refused rather than "
            "written, and you are told what is wrong with it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file to write.",
                },
                "content": {
                    "type": "string",
                    "description": "The entire contents of the file.",
                },
            },
            "required": ["path", "content"],
        },
    },
}

EDIT_TOOL = {
    "type": "function",
    "function": {
        "name": "edit",
        "description": (
            "Replace exact pieces of an existing file. Each old_text must "
            "appear once and only once in the file as it is now, unless you set "
            "replace_all, and the edits must not overlap; matching is exact, "
            "including indentation and line breaks. If any one of them is "
            "missing or matches more than one place, nothing is written at all "
            "and you are told which, along with the lines in the file that came "
            "closest, so read the file first and include enough surrounding "
            "lines to be sure. An edit whose new_text is already in the file is "
            "one you have already made, and is skipped rather than treated as a "
            "failure. Returns a diff of what changed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file to change.",
                },
                "edits": {
                    "type": "array",
                    "description": "The replacements to make, all or none.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_text": {
                                "type": "string",
                                "description": (
                                    "The text to replace, exactly as it appears "
                                    "in the file and unique within it."
                                ),
                            },
                            "new_text": {
                                "type": "string",
                                "description": (
                                    "What to put there instead. Empty to delete "
                                    "the old text."
                                ),
                            },
                            "replace_all": {
                                "type": "boolean",
                                "description": (
                                    "Replace every occurrence rather than "
                                    "requiring exactly one. Use it for a "
                                    "rename. Defaults to false."
                                ),
                            },
                        },
                        "required": ["old_text", "new_text"],
                    },
                },
            },
            "required": ["path", "edits"],
        },
    },
}

TOOLS = [READ_TOOL, WRITE_TOOL, EDIT_TOOL]
FUNCTIONS = {"read": read, "write": write, "edit": edit}


def describe(name, arguments):
    """What the transcript shows for a file call: the path, and how much of it."""
    path = arguments.get("path") or ""
    if name == "read":
        offset = arguments.get("offset")
        return f"read {path}" + (f" from line {offset}" if offset else "")
    if name == "write":
        return f"write {path}"
    edits = arguments.get("edits")
    count = len(edits) if isinstance(edits, list) else 1
    return f"edit {path}" + (f" ({count} edits)" if count > 1 else "")
