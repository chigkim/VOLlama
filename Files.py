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
import os
import re

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


def checked(path, must_exist=True):
    """Turn a path into one we can act on, or say why we cannot."""
    full = resolve(path)
    if os.path.isdir(full):
        raise ValueError(f"{full} is a directory, not a file.")
    if must_exist and not os.path.exists(full):
        raise ValueError(
            f"There is no file at {full}. Relative paths are taken from "
            f"{working_dir()}."
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


def write(path, content):
    """Create or replace a file with exactly the text given."""
    content = (content or "").replace("\r\n", "\n")
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
    if top != old and " ".join(top.split()) == " ".join(old.split()):
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
    return "\n".join(parts)


def label(index, count):
    """What to call one edit when reporting it: its position, or just the field."""
    return f"edits[{index}]" if count > 1 else "old_text"


def locate(text, old, index, count, path, every=False):
    """Where one edit goes, or why it does not go anywhere.

    Returns the positions, the text that actually matched, and whether it only
    matched after its escaping was undone.

    Both failures are reported before anything is written, since an edit that
    matched three places is a model that does not know which one it meant, and
    guessing for it is how a file quietly ends up wrong. Unless it said so:
    replace_all is that model saying it meant all of them.
    """
    where = label(index, count)
    if not old:
        raise ValueError(f"{where} is empty. It must be the text you want replaced.")

    found = occurrences(text, old)
    repaired = False
    if not found:
        plain = unescape(old)
        if plain != old:
            found = occurrences(text, plain)
            if found:
                old, repaired = plain, True
    if not found:
        raise ValueError(no_match(text, old, where, path))
    if len(found) > 1 and not every:
        raise ValueError(
            f"Found {len(found)} occurrences of {where} in {path}, so it is not "
            "clear which one you meant. Nothing was changed. Include more of the "
            "surrounding lines to make it unique, or set replace_all to true to "
            "change every one of them."
        )
    return found, old, repaired


def edit(path, edits):
    """Replace unique pieces of a file, all of them or none of them."""
    if isinstance(edits, dict):
        edits = [edits]
    if not isinstance(edits, list) or not edits:
        return "edits must be a list of {old_text, new_text} objects."

    try:
        full = checked(path)
        before, newline, bom = load(full)
    except (ValueError, OSError) as e:
        return str(e)

    # Located against the original text, never against the result of the edit
    # before, so the model does not have to imagine the file part way through.
    spans = []
    repaired = 0
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
            found, old, fixed = locate(before, old, i, len(edits), full, every)
            repaired += bool(fixed)
            for at in found:
                spans.append((at, at + len(old), new, i))
    except ValueError as e:
        return str(e)

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
    try:
        save(full, after, newline, bom)
    except OSError as e:
        return str(e)

    count = len(spans)
    made = "1 edit" if count == 1 else f"{count} edits"
    note = ""
    if repaired:
        note = (
            " One old_text only matched once its escaping was undone: you sent "
            "a backslash and an n where the file has a line break. Send the "
            "text as it is, not as it would look inside a Python string."
        )
    return f"Made {made} in {full}.{note}\n{diff(before, after, full)}"


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
            "lines to be sure. Returns a diff of what changed."
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
