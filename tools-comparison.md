# VOLlama's `run`/`poll`/`read`/`write`/`edit` vs six harnesses

Compared against: codex (`D:\code\node\codex`), opencode, pi, gemini-cli, hermes-agent
(`D:\code\git\hermes\hermes-agent`), openclaw.

Note on lineage: openclaw's file/shell tools (`src/agents/sessions/tools/`) are a fork of pi's —
same filenames, same functions. Treat them as one design with openclaw deltas. hermes is the
closest idiom to VOLlama (Python, same problems, same era).

**Status (2026-09-04):** all of Tier 1, Tier 2 items 10 and 11, and Tier 3 item 20 are
implemented, as are Tier 2 items 14, 16, 17 and 19 and Tier 3 item 24 (`read` already named
the total).
So are stderr-into-stdout at the pipe and `IDLE_TIMEOUT` as the primary liveness
kill. See `CLAUDE.md` for what shipped and why; the sections below are the original survey and
are left as written.

## 1. Where VOLlama already leads

Not everything needs borrowing. VOLlama is ahead of at least half the field on:

- **`edit` locates all edits against the original and validates before writing anything.** pi and
  openclaw do this too; opencode and gemini-cli apply one edit per call. This is the right
  invariant and it is already there.
- **`nearest()` on a failed match.** Only hermes (`find_closest_lines`, the source of the port),
  openclaw (`getCandidateHint`) and opencode (fuzzy sibling filenames, not lines) do anything here.
  codex and pi say "not found".
- **`write` syntax-checks before writing, fail-closed for data formats and warn for Python.** Only
  hermes matches this. pi's `write.ts` does no validation at all. opencode validates after, via LSP.
- **Per-line `MAX_LINE` cap in `read`, with a footer warning the cut line is not the file's text.**
  opencode caps lines; pi has a first-line path; nobody else warns that a cut line is unusable as
  `old_text`. That warning is VOLlama-specific and correct.
- **Naming a refused binary by magic bytes** (`describe_bytes`). Only hermes does this.
- **OEM-codepage per-line decoding on Windows.** Nobody else solves this. pi/openclaw set
  PowerShell's `[Console]::OutputEncoding`; codex ships Windows *prose* rules; everyone else
  assumes UTF-8 and gets replacement characters from `cmd` builtins.
- **Free tools (`poll`, `read`) not spending a tool round.** Unique.
- **`notes()`, the synthetic user turn for jobs that outlived their turn.** Only hermes has an
  equivalent (`drain_notifications`), and only VOLlama really needs it, because a GUI turn
  genuinely ends.

## 2. Per-tool comparison

### `run`

| | VOLlama | codex | opencode | pi | gemini-cli | hermes | openclaw |
|---|---|---|---|---|---|---|---|
| backgrounding | yield 10s → session id | yield `yield_time_ms` → session id | none | none | `is_background` flag | `background=true` | `yieldMs` → session, or `background` |
| PTY | no | yes (`tty`) | no | no | no | yes (`pty`) | yes |
| timeout | wall-clock, 300s default | per-call yield + 300s bg ceiling | wall-clock | none by default | **inactivity**, resets on output | 180s fg, rejects above max | `timeoutSeconds` (unit in the name) |
| big output | head 40% + tail, middle lost | head/tail 50/50 + token budget | **spill to file, path in footer** | **spill to file** | per-PID log file | **spill to file** | spill to private temp |
| stdout/stderr | separate blocks | merged (PTY) | **merged, interleaved** | **merged** | separate labels | separate | separate, stderr tail labeled |
| exit code | bare number | bare | bare | thrown as an error | labeled + signal | **interpreted** (`137 = OOM`, `grep 1 = no matches`) | bare |
| shell named to model | yes (`cmd.exe /c ...`) | Windows safety prose | **per-shell guidance file** | — | yes | yes, in env block | yes |
| stray `&`/nohup | leaks a grandchild | — | — | — | captures PIDs via `trap jobs -p` | **detects and warns** | — |

### `poll`

Only VOLlama, codex (`write_stdin`), gemini-cli (two tools: `list_background_processes` +
`read_background_output`), hermes (`process(action=...)`) and openclaw have one. pi and opencode
have no background mechanism at all.

VOLlama's `Stream` with absolute `base`/`cursor` and a missed-character count is the best of these
— gemini-cli re-reads a log file from the end and discards a partial line; hermes' `read_log` had a
falsy-`offset` bug it now documents in a comment. The gaps are that VOLlama *counts* dropped
characters but does not always *say so in the output*, and has no watch-pattern notification.

### `read`

VOLlama, pi and hermes are the same design (offset/limit, byte cap, continuation footer).
Differences worth noting:

- opencode **lists** a directory instead of refusing; openclaw refuses with an instruction
  ("List the directory, then read a specific file").
- opencode and openclaw answer a missing path with `Did you mean: ...?` from fuzzy sibling names.
- hermes trims to the **last complete line that fits** and returns `next_offset`, clamping a single
  oversized first line so a read is never empty.
- hermes blocks device paths by name (`/dev/zero`, `/dev/stdin`, `/dev/tty`, `/dev/fd/0`) — reading
  them hangs the process. Path check only, no I/O.
- opencode, pi and openclaw return images as model attachments.
- gemini-cli's truncation banner is prescriptive: `IMPORTANT:` / `Status:` / `Action: use
  start_line: N`.
- hermes returns line numbers (`LINE_NUM|CONTENT`); VOLlama deliberately does not, so `edit`'s
  exact matching still works. pi agrees with VOLlama. This is a real fork in the field and VOLlama
  is on the right side of it.

### `write`

- gemini-cli **refuses** content containing an omission placeholder (`// rest of code ...`) —
  `omissionPlaceholderDetector.ts`, a small closed set of prefixes, each requiring a literal `...`.
- hermes and openclaw **verify after writing** (sha256 / byte-equality readback) and return
  `verified: true`, with the schema telling the model *"do NOT re-read the file to check the write
  landed."* hermes cites 154 pointless verify-reads in a 400k-message window.
- hermes filters lint output to errors the write **introduced** — same as VOLlama's `introduced()`.
- pi does nothing. opencode runs a formatter and appends LSP diagnostics.

### `edit`

This is where the field diverges most.

- **VOLlama and pi:** exact match only (VOLlama adds `unescape()` as a fallback). Safe, and fails
  more often.
- **openclaw:** exact, then **one** normalization stage (NFKC + trailing-space trim + smart quotes,
  dashes, exotic spaces), with a full grapheme-level offset map back to the original bytes, and a
  refusal when the span cannot be mapped unambiguously. Fuzzy matching is **lookup-only**;
  replacements always splice into the original.
- **opencode and hermes:** a 9-stage ladder (exact → line-trimmed → whitespace-normalized →
  indentation-flexible → escape-normalized → trimmed-boundary → unicode-normalized → block-anchor
  → context-aware), each stage yielding the **literal span present in the file**.
- **gemini-cli:** four stages including a regex-token stage and a Levenshtein fuzzy stage, plus an
  **LLM self-correction call** when all four fail.

The instructive part is hermes' own history, recorded in its comments: `block_anchor`'s thresholds
were raised from 0.10/0.30 to 0.50/0.70 ("a 10% middle-section similarity could match completely
unrelated blocks") and `context_aware` went from "50% of lines" to "every non-blank line ≥0.80"
("the old threshold accepted half-garbage patterns and destroyed the non-matching lines"). The
loose end of the ladder is where wrong-region edits come from.

Tolerance also opens corruption vectors that need their own guards, all of which hermes has:

- re-indenting `new_text` from the matched region's own indentation (`_reindent_replacement`;
  gemini-cli's `applyIndentation`; credited to Roo Code) — without this, whitespace tolerance means
  the model's indentation wins, which silently breaks Python
- escape-drift refusal: `\'`/`\"` in the model's arguments but not in the file
- backslash-doubling refusal, so `C:\Users` does not become `C:\\Users`
- Unicode preservation on replace, via SequenceMatcher opcodes, so an em-dash outside the changed
  span is not flattened to `--`
- refusing `replace_all` when the match came from a similarity strategy
- opencode's `isDisproportionateMatch`: refuse when the matched span is much larger than `oldString`

## 3. What to borrow, in priority order

### Tier 1 — cheap, self-contained, clear win

1. **Spill oversized output to a file and name the path in the footer.**
   All five other harnesses with shell tools do this; only VOLlama destroys the middle permanently
   (`shorten()`) and drops the front (`Stream`). It pairs perfectly with VOLlama's own paging `read`
   and `nearest()` — the model can grep or page the full log.
   Copy hermes' `hook_output_spill.py` invariants: never raise, fall back to plain truncation with
   an in-prompt notice, head+tail preview, per-session directory, owner-only exclusive create
   (openclaw's `private-temp-file.ts`: `flags: "wx"`, `mode: 0o600`, random name).
   *`Tools.py` — `shorten()`, `report()`, `Stream.take()`.*

2. **Interpret exit codes and signals in `report()`.**
   hermes' `_interpret_exit_code` / `_interpret_signal_exit`: split the command on `|| && | ;`, take
   the last segment, basename it, look up a small table — `grep 1 = No matches found (not an
   error)`, `diff 1 = Files differ (expected)`, `137 = OOM kill`, `curl 7 = Failed to connect`.
   Negative codes are stated as definite, `128+signum` hedged with "usually". Pure Python, about 60
   lines, and it kills a whole class of wasted turns.
   *`Tools.py` — `report()`.*

3. **Say when output was dropped, in the output.**
   `Stream` already tracks missed characters. Do what openclaw's `formatStderrTail` does and label
   it inline — *"[N characters of earlier output discarded at the 200,000-character cap]"* — so a
   truncated diagnostic cannot look complete.
   *`Tools.py` — `Stream.take()`, `Job.news()`.*

4. **Reject a whitespace-only `old_text` by name.**
   hermes: *"old_string is only whitespace — provide non-blank text to match."* It matches
   trivially, and under `replace_all` it mass-replaces. VOLlama has no such guard.
   *`Files.py` — `edit()`.*

5. **List the sites when `old_text` is ambiguous.**
   hermes' `_format_match_locations`: up to 5 lines of `  L<line>: <snippet>` then `... and N more`.
   VOLlama's `nearest()` is the mirror of this for *no* match; *too many* currently gets a count
   only, so the model guesses at more context.
   *`Files.py` — `occurrences()` / `locate()`.*

6. **Run the `write` syntax checks on `edit` too.**
   `introduced()` already exists and `edit` already returns a diff. hermes runs the same
   delta-filtered check on both paths. Closing this asymmetry is a few lines.
   *`Files.py` — `edit()`.*

7. **Argument repair for `edits`.**
   pi's comment names the models: *"Some models (Opus 4.6, GLM-5.1) send edits as a JSON string
   instead of an array. Others send a single edit object instead of a one-element edits array."*
   Ten lines in `call()` or at the head of `edit()`.
   *`Tools.py` — `call()`, or `Files.py` — `edit()`.*

8. **Block device paths in `read` by name.**
   hermes' `_BLOCKED_DEVICE_PATHS`: `/dev/zero`, `/dev/random`, `/dev/urandom`, `/dev/full`
   (infinite output), `/dev/stdin`, `/dev/tty`, `/dev/console` (block forever), `/dev/std*`,
   `/dev/fd/0..2`. Path comparison, no I/O. Mac-relevant only, but a hang is a hang.
   *`Files.py` — `resolve()` or `load()`.*

9. **`Did you mean ...?` for a missing path.**
   opencode's `miss()` / openclaw's suggestion list, from fuzzy sibling filenames, max 3. Exactly
   the philosophy `nearest()` already embodies, applied one level up.
   *`Files.py` — `read()`.*

### Tier 2 — high value, needs a design decision

10. **Inactivity timeout instead of wall-clock.**
    gemini-cli resets the timer on every output event, and reports *"exceeded the timeout of N
    minutes without output."* A chatty 20-minute build survives; a hung process still dies.
    VOLlama's `DEFAULT_TIMEOUT`/`MAX_TIMEOUT` would become the ceiling rather than the whole
    policy. Decide whether both apply.
    *`Tools.py` — `Job`, `sweep()`.*

11. **Timeout and stop messages that carry the output so far and say what to do next.**
    pi throws `Command timed out after N seconds` with output attached; opencode says *"retry with a
    larger timeout value in milliseconds"*; gemini-cli says *"Below is the output before it was
    cancelled."* VOLlama's `settle()`/`status()` should never return a bare status when there is
    text.
    *`Tools.py` — `report()`, `Job.status()`.*

12. **A single Unicode/whitespace normalization stage in `edit`, in openclaw's shape.**
    Not the 9-stage ladder. One stage: NFKC, trailing whitespace per line, smart quotes, dashes,
    exotic spaces (hermes' `UNICODE_MAP` is the more complete character table); locate in normalized
    space; **translate the span back to original coordinates and splice into the original**; refuse
    when the span cannot be mapped unambiguously (`getUnsafeFuzzyBoundaryError`). This is safe by
    construction — the file's own bytes are what gets replaced — and it fixes the single most common
    real failure, a model retyping text containing an em-dash or a non-breaking space.
    Pair it with a disproportionate-match guard and hermes' escape-drift / backslash-doubling
    refusals, which are what make tolerance safe rather than dangerous.
    Do **not** take `block_anchor` or `context_aware`.
    *`Files.py` — `locate()`, `edit()`.*

13. **`is_already_applied()` → a success-shaped no-op.**
    hermes: *"Production trajectory mining shows the most common patch failure is a re-send of an
    edit that already landed."* Return *"File already contains the target text — the edit appears to
    be already applied. No write performed; do not re-send this patch."* Guards: `new_text` ≥ 8
    stripped characters, must appear **exactly** (never via a tolerant stage), and `old_text` must
    be gone. VOLlama currently refuses a no-op edit by name — right for identical strings, wrong for
    the re-send case, which is a different situation with a different fix.
    *`Files.py` — `edit()`.*

14. **Name the *kind* of difference in a no-match error, with a caret.**
    openclaw's `describeCandidateDifference()` reports, in order: `indentation differs (expected 4
    spaces, found 0 spaces and 1 tabs)`, `escaping differs (expected N backslashes, found M)`,
    `first difference at column N`, or `this line matches; surrounding lines differ` — and renders
    `expected:` / `found:` / `^^^^` under the divergence. VOLlama's `visible()` already prints
    `→`/`·` for whitespace-only differences; this is a strict improvement on the same idea, and
    covers the escaping case too.
    *`Files.py` — `no_match()`, `visible()`.*

15. **Post-write verification with an explicit `verified` signal.**
    hermes (sha256) and openclaw (stat size + byte readback) both do this, and both tell the model
    in the schema not to re-read. Cheap on the write path, and it removes a whole category of wasted
    turn. Add it to `edit` as well; hermes re-reads after patching too.
    *`Files.py` — `save()`, `write()`, `edit()`.*

16. **Guidance when a foreground command looks long-lived or self-backgrounds.**
    hermes' `_foreground_background_guidance` strips quoted content first (so a keyword inside a
    string does not false-positive), exempts `--help`/`--version`, then warns about `nohup`,
    `disown`, `setsid`, a trailing `&`, and known server patterns. Directly relevant: `run "x &"`
    currently leaks a grandchild past VOLlama's process-group kill.
    *`Tools.py` — `run()`, `run_description()`.*

17. **Refuse a `write` whose content contains an omission placeholder.**
    gemini-cli's detector, about 40 lines: strip `//`, strip wrapping parens, require a literal
    `...`, require the prefix to be in a closed set (`rest of`, `rest of code`, `unchanged code`,
    `unchanged method(s)`, ...). Exactly `introduced()`'s philosophy — refuse the write that would
    destroy the file rather than write it and hope.
    *`Files.py` — `write()`.*

18. **Model-settable yield time, clamped, with units in the parameter name.**
    codex's `yield_time_ms` (250–30000, Windows floor 10000) and openclaw's `yieldMs`, so a
    known-30-second build need not round-trip through `poll`. openclaw's `timeoutSeconds` is named
    for unit clarity *because* its sibling is in milliseconds — worth copying the naming discipline
    given `run` already has `timeout` in seconds.
    *`Tools.py` — `RUN_TOOL`, `run()`.*

19. **Windows safety prose and per-shell guidance in the `run` description.**
    codex appends a three-rule Windows block (no cross-shell destructive composition; verify
    resolved absolute paths before a recursive delete; `-WindowStyle Hidden` for background
    helpers). opencode ships a per-shell guidance file. hermes adds the two framings VOLlama's
    description is missing: *"output is auto-truncated with the full text saved to a file — never
    pipe through tail/head to shorten it"* and *"foreground returns INSTANTLY when the command
    finishes, even with a high timeout — set timeout generously for long builds."* That second line
    is worth having regardless; models under-set timeouts because they assume waiting costs.
    *`Tools.py` — `run_description()`.*

### Tier 3 — worth considering, weaker case

20. **Interleave stdout and stderr.** pi and opencode both merge them, and lose nothing; VOLlama's
    split discards causal ordering in build logs, where the error line's position among the warnings
    is the information. But the split is also more legible, and `Stream`'s two-buffer design is
    built on it. A judgement call, not a clear win.
21. **Watch patterns on background jobs.** hermes' `notify=['Application startup complete']`, with
    `WATCH_MIN_INTERVAL_SECONDS`, a strike limit, a lifetime hit cap and a global rate window. Fits
    VOLlama's `notes()` mechanism exactly. The rate limiting is what makes it safe, and it is most
    of the work.
22. **Capture PIDs backgrounded inside the command** — gemini-cli's `trap 'jobs -p > file' EXIT`
    subshell wrapper. POSIX only, no Windows equivalent, so it half-solves item 16.
23. **Stale-read warning.** hermes compares the read-time mtime and warns without blocking;
    gemini-cli hashes read-time content against disk before its self-correction call. VOLlama's
    `KEEP_TOOL_TURNS` already drops old reads, so the model re-reads anyway — lower value here than
    elsewhere, but the concurrent-edit case (the user edits the file mid-turn) is real.
24. **Out-of-bounds `offset` error naming the total** — pi's `Offset N is beyond end of file (M
    lines total)`. Trivial; check whether `read()` already covers it.
25. **Reconcile the oversized-line policy.** Three approaches exist: VOLlama cuts with a marker plus
    a once-only warning; hermes clamps and still advances the cursor; pi returns an actionable
    `Use bash: sed -n 'Np' path | head -c N`. VOLlama's is arguably already the best of the three —
    worth a deliberate confirmation rather than a change.
26. **Directory path → listing** (opencode) or an instruction to list it (openclaw), instead of a
    bare refusal.
27. **`read` returning images as attachments.** A genuine capability gap given VOLlama is already
    multimodal — but it crosses from `Files.py` into the message-construction path, so it is a
    feature, not a hardening.
28. **Explicit search ceilings.** `nearest()`'s anchor-on-one-line approach is already the right
    cost model; gemini-cli states its bail as `sourceLines * len(old)² > 4e8` ("Limit to 4e8 for
    < 1 second") and openclaw bounds candidate scanning at 1000 lines / 128 KB / 120 chars per line.
    Worth stating VOLlama's own ceilings the same way.
29. **Per-file mutation serialization** (pi/openclaw `file-mutation-queue.ts`, opencode `Semaphore`).
    VOLlama's tool calls are sequential within a turn, so this is currently moot.
30. **Structured JSON tool output** (codex's `unified_exec_output_schema`: `exit_code`,
    `wall_time_seconds`, `session_id`, `original_token_count`). Cleaner, but VOLlama's prose
    `report()` is what small local models parse best.
31. **Job checkpoint/recovery across restarts** (hermes' `processes.json`). Against VOLlama's design
    — `kill_all()` on exit is deliberate.

## 4. Rejected, as against VOLlama's stated design

- PTY sessions and `write_stdin` (codex, hermes, openclaw) — `run` is stateless by design.
- Tree-sitter command parsing for permission patterns (opencode) and any confirm-before-run dialog —
  CLAUDE.md: the Chat menu checkbox is the only gate.
- Sandbox/approval parameter surfaces (codex `sandbox_permissions`, gemini-cli), docker/ssh/modal
  backends and sudo handling (hermes), `host`/`elevated`/`ask` (openclaw).
- gemini-cli's LLM self-correction on a failed edit. A model *is* right there, but it turns a
  deterministic tool into a nested inference call, and `nearest()` plus item 14 gets most of the
  benefit for none of the latency.
- Line-numbered `read` output (hermes, opencode). VOLlama and pi are right: numbers break `edit`.
- gemini-cli's regex-token match stage. Padding delimiters and joining tokens with `\s*` matches
  too much.
