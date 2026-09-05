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

This module is the part that touches a file: reading it, writing it back the
way it was, and the three tool contracts. The two questions it asks along the
way live where they can be read on their own — `tools.content` for whether text
is text and whether writing it would damage the file, `tools.matching` for
where an old_text goes and why it did not go anywhere.
"""

import difflib
import json
import os

from vollama.tools import matching
from vollama.tools.content import (
    binary,
    describe_bytes,
    fails_closed,
    introduced,
    placeholder,
    size_of,
)
from vollama.tools.workspace import checked

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
        ) from e
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


def write(path, content):
    """Create or replace a file with exactly the content given."""
    content = (content or "").replace("\r\n", "\n")
    # Before the path is even resolved: this is not a file, whatever it was
    # going to be written to.
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
        if broke and fails_closed(full):
            return (
                f"Nothing was written to {full}, because {broke}. Fix it and "
                "send the whole file again."
            )
        save(full, content, newline, bom)
    except (ValueError, OSError) as e:
        return str(e)
    ends = content.endswith("\n") or not content
    count = content.count("\n") + (0 if ends else 1)
    lines = "1 line" if count == 1 else f"{count} lines"
    was = "Replaced" if existed else "Created"
    ending = "CRLF" if newline == "\r\n" else "LF"
    note = f" Warning: {broke}." if broke else ""
    return f"{was} {full}: {lines}, {len(content)} characters, {ending}.{note}"


# A model that builds old_text by writing Python rather than by copying the
# file sends \n as two characters. This is the one failure these tools exist to
# prevent, so when an exact match fails it is worth trying the text with its
# escaping undone before giving up. Ported from gemini-cli's

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

    try:
        spans, repairs, already = _plan(before, edits, full)
    except ValueError as e:
        # Every refusal comes back as text, and none of them has written
        # anything: the whole call is planned against the original file first.
        return str(e)

    if not spans:
        made = "The edit was" if len(edits) == 1 else f"All {len(edits)} edits were"
        return (
            f"{made} already made in {full}, so there was nothing left to do "
            "and nothing was written. The file is already what you asked for."
        )
    after = _splice(before, spans)
    if after == before:
        return f"Nothing changed in {full}: the new text is the same as the old."

    # Checked here as well as in write, since an edit breaks a config file the
    # same way a rewrite does, and by the time another program trips over it the
    # tool call that did it is several messages back.
    broke = introduced(full, before, after)
    if broke and fails_closed(full):
        return (
            f"Nothing was changed in {full}, because the result would not "
            f"parse: {broke}. This is what the edit would have done:\n"
            f"{diff(before, after, full)}"
        )
    try:
        save(full, after, newline, bom)
    except OSError as e:
        return str(e)
    return _report(full, before, after, spans, repairs, already, broke)


def _plan(before, edits, path):
    """Where every edit goes in the original text, or raise saying why not.

    Returns the spans as (start, end, new_text, which edit), the fallbacks that
    had to be used, and the edits that turned out to have been made already.
    Located against `before` throughout, never against the result of the edit
    before it: that is what lets a whole batch be refused without the file
    having been touched, and what spares the model imagining the file part way
    through.
    """
    spans = []
    repairs = {}
    already = []
    for i, item in enumerate(edits):
        if not isinstance(item, dict):
            raise ValueError(
                f"edits[{i}] must be an object with old_text and new_text."
            )
        old = (item.get("old_text") or "").replace("\r\n", "\n")
        new = (item.get("new_text") or "").replace("\r\n", "\n")
        if old and new == old:
            # Named here rather than caught by the no-op check on the result, so
            # a model sending one good edit and one that changes nothing is told
            # which, instead of having the whole call quietly succeed.
            which = f"edits[{i}]" if len(edits) > 1 else "This edit"
            raise ValueError(
                f"{which} has the same new_text as old_text, so it would not "
                "change anything. Nothing was written."
            )
        try:
            found, how = matching.locate(
                before, old, i, len(edits), path, bool(item.get("replace_all"))
            )
        except matching.NotFound:
            # The old text is gone and the new text is already there, once: this
            # edit has already been made. Reporting that as a failure sends the
            # model round the same loop again.
            if matching.applied(before, new):
                already.append(i)
                continue
            raise
        if how:
            repairs[how] = repairs.get(how, 0) + 1
        spans.extend((start, end, new, i) for start, end in found)
    spans.sort()
    _overlapping(spans, path)
    return spans, repairs, already


def _overlapping(spans, path):
    """Refuse two edits that cover the same text. `spans` must be sorted."""
    for (_, end, _, i), (later, _, _, j) in zip(spans, spans[1:]):
        if later < end:
            raise ValueError(
                f"edits[{i}] and edits[{j}] both cover the same part of {path}. "
                "Nothing was changed. Make it one edit, or move them apart."
            )


def _splice(before, spans):
    """The text with every span replaced. `spans` must be sorted and disjoint."""
    pieces = []
    at = 0
    for start, end, new, _ in spans:
        pieces.append(before[at:start])
        pieces.append(new)
        at = end
    pieces.append(before[at:])
    return "".join(pieces)


def _report(path, before, after, spans, repairs, already, broke):
    """What the model is told about an edit that was written."""
    made = "1 edit" if len(spans) == 1 else f"{len(spans)} edits"
    notes = [f" One old_text {matching.REPAIRS[how]}" for how in sorted(repairs)]
    if already:
        which = ", ".join(f"edits[{i}]" for i in already)
        notes.append(
            f" {which} had already been made, so it was skipped rather than "
            "counted above."
        )
    if broke:
        notes.append(f" Warning: {broke}.")
    return f"Made {made} in {path}.{''.join(notes)}\n{diff(before, after, path)}"


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


def summarize_read(arguments):
    """The one line the transcript shows for a read call."""
    offset = arguments.get("offset")
    path = arguments.get("path") or ""
    return f"read {path}" + (f" from line {offset}" if offset else "")


def summarize_write(arguments):
    return f"write {arguments.get('path') or ''}"


def summarize_edit(arguments):
    edits = arguments.get("edits")
    count = len(edits) if isinstance(edits, list) else 1
    path = arguments.get("path") or ""
    return f"edit {path}" + (f" ({count} edits)" if count > 1 else "")
