"""Finding the text an edit names, and explaining why it was not found.

`edit` promises that every edit in a call is located against the original file
and checked before any of them is written. This module is where that locating
happens, and it is deliberately kept away from the file: everything here is a
function of two strings, so the interesting parts — the fallbacks and the
diagnostics — can be read and tested without a disk.

`locate` is the entry point. Exact match first, always; then two fallbacks, in
the order of how sure they are, each of them lookup only and each named in the
result so the model learns what it got wrong:

    unescape()    a literal backslash-n where the file has a line break,
                  which is what a model that built old_text by writing Python
                  sends. Ported from gemini-cli's unescapeStringForGeminiBug.
    fold_match()  the characters a model cannot see it got wrong: a curly
                  quote, an en dash, a zero-width space, trailing whitespace.
                  openclaw's buildNfkcBoundaries / translateFuzzySpan shape,
                  fail-closed check included.

The ladder stops there. Tabs and spaces are deliberately not made equivalent,
and nothing here trims a line or normalizes indentation: those buy matches at
the price of occasionally editing the wrong region, and `new_text` is written
exactly as it was sent, so a match found by ignoring indentation leaves the
file's own indentation quietly mixed.

The other half of the module is the wording of a failure. "It must match
exactly" tells the model the rule, which it already knew; what it does not know
is which of the two lines is wrong and how, so `no_match` shows the lines that
came closest and `divergence` names the kind of difference. `ambiguous` says
where the other matches are rather than how many, because a model told only a
count goes and reads the whole file again.
"""

import difflib
import re
import unicodedata


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

# How much of one line an explanation may quote. A minified file is a single
# line of a megabyte, and the point of quoting it is the first place it
# differs, which is at the front.
MAX_SHOWN = 4000

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
            "You sent:      " + visible(mine[:MAX_SHOWN]),
            "The file has:  " + visible(theirs[:MAX_SHOWN]),
        ]
    lines = [
        "",
        f"The first line that differs: {named}.",
        "You sent:      " + mine[:MAX_SHOWN],
        "The file has:  " + theirs[:MAX_SHOWN],
    ]
    at = column(mine, theirs)
    if at <= MAX_SHOWN:
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
            visible(old[:MAX_SHOWN]),
            "The file has:",
            visible(top[:MAX_SHOWN]),
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
