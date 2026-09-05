"""run and poll: reporting a command, and the jobs that outlive a call."""

import re
import sys
import time

import pytest

from vollama.tools import shell


# ------------------------------------------------------- reading an exit code


def test_a_program_name_is_read_past_its_runner():
    assert shell.program("uv run pytest -q") == "pytest"
    assert shell.program("python -m mypy .") == "mypy"
    assert shell.program("git diff --exit-code") == "git"


@pytest.mark.parametrize(
    "command, code, expected",
    [
        ("grep needle file", 1, "not a failure"),
        ("cmd", 127, "not installed"),
        ("build", 137, "running out of memory"),
        ("pytest", 5, "no tests were collected"),
        ("anything", 0, None),
    ],
)
def test_an_exit_code_is_explained(command, code, expected):
    meaning = shell.explain(command, code)
    if expected is None:
        assert meaning is None
    else:
        assert expected in meaning


def test_report_puts_the_exit_code_and_its_meaning_after_the_output():
    out = shell.report("some output", 1, command="grep x")
    assert out.startswith("some output")
    assert "Exit code: 1 (no lines matched" in out


def test_a_silent_success_still_says_something():
    # An empty tool message reads to a model as a broken tool, and some servers
    # refuse to accept one at all.
    assert shell.report("", 0) == shell.NO_OUTPUT


# -------------------------------------------------------- backgrounding itself


@pytest.mark.parametrize(
    "command", ["nohup ./server", "setsid ./server", "npm run build & disown"]
)
def test_a_command_that_detaches_is_warned_about(command):
    assert "backgrounds a process itself" in shell.detached(command)


def test_a_keyword_inside_a_quoted_string_is_not_the_command_doing_it():
    assert shell.detached('echo "nohup is a program"') is None


def test_npm_start_is_not_a_detaching_start():
    assert shell.detached("npm start") is None


def test_asking_a_program_for_its_flags_never_detaches():
    assert shell.detached("nohup --help") is None


# --------------------------------------------------------------- the buffer


def test_a_stream_hands_back_only_what_is_new():
    stream = shell.Stream()
    stream.write("first\n")
    assert stream.take() == ("first\n", 0)
    assert stream.take() == ("", 0)
    stream.write("second\n")
    assert stream.take() == ("second\n", 0)


def test_output_dropped_off_the_front_is_counted_not_hidden(monkeypatch):
    monkeypatch.setattr(shell, "MAX_BUFFER", 10)
    stream = shell.Stream()
    stream.write("0123456789")
    stream.write("abcde")
    text, missed = stream.take()
    assert text == "56789abcde"
    assert missed == 5
    assert shell.dropped(missed) in stream.all() or stream.base == 5


def test_a_trimmed_output_says_where_the_cut_is(monkeypatch):
    monkeypatch.setattr(shell, "MAX_OUTPUT", 100)
    out = shell.shorten("a" * 500, path="C:/tmp/run.log")
    assert "characters omitted out of 500" in out
    assert "C:/tmp/run.log" in out
    assert out.startswith("a") and out.endswith("a")


# ------------------------------------------------------------ running things


def test_a_quick_command_reports_its_output(isolated, tmp_path):
    isolated.workdir = str(tmp_path)
    assert "hello" in shell.run("echo hello")


def test_a_command_in_a_directory_that_is_not_there_is_refused():
    assert "no directory" in shell.run("echo hi", workdir="/nowhere/at/all")


def test_an_empty_command_is_refused():
    assert shell.run("   ") == "No command given."


def slow_script(tmp_path):
    script = tmp_path / "slow.py"
    script.write_text(
        "import time, sys\n"
        "print('starting', flush=True)\n"
        "time.sleep(1.5)\n"
        "print('done', flush=True)\n",
        encoding="utf-8",
    )
    return f'"{sys.executable}" "{script}"'


def test_a_slow_command_becomes_a_session_that_poll_can_finish(monkeypatch, tmp_path):
    # Shortened so the test does not have to wait the real ten seconds; what is
    # under test is the handover, not the length of the window.
    monkeypatch.setattr(shell, "YIELD_SECONDS", 0.3)
    table = shell.JobTable()
    monkeypatch.setattr(shell, "jobs", table)

    started = shell.run(slow_script(tmp_path), workdir=str(tmp_path))
    assert "starting" in started
    session = re.search(r"Session: (\S+)", started).group(1)

    finished = shell.poll(session, wait=10)
    assert "finished with exit code 0" in finished
    assert "done" in finished
    # Output already handed over is not handed over twice.
    assert "starting" not in finished

    table.kill_all()


def test_a_job_is_named_rather_than_numbered(monkeypatch, tmp_path):
    monkeypatch.setattr(shell, "YIELD_SECONDS", 0.3)
    table = shell.JobTable()
    monkeypatch.setattr(shell, "jobs", table)

    shell.run(slow_script(tmp_path), workdir=str(tmp_path))
    shell.run(slow_script(tmp_path), workdir=str(tmp_path))

    names = [job.id for job in table.all()]
    assert len(set(names)) == 2
    for name in names:
        adjective, animal = name.split("-")
        assert adjective in shell.ADJECTIVES
        assert animal in shell.ANIMALS

    table.kill_all()


def test_a_job_that_ends_nudges_until_it_is_collected(monkeypatch, tmp_path):
    monkeypatch.setattr(shell, "YIELD_SECONDS", 0.3)
    monkeypatch.setattr(shell, "SWEEP_SECONDS", 0.05)
    table = shell.JobTable()
    monkeypatch.setattr(shell, "jobs", table)
    nudges = []
    table.on_finished = lambda: nudges.append(1)

    shell.run(slow_script(tmp_path), workdir=str(tmp_path))
    deadline = time.monotonic() + 10
    while not nudges and time.monotonic() < deadline:
        time.sleep(0.05)

    # The nudge carries nothing: what is worth saying is notes(), and the
    # listener may be mid-turn and unable to act on the first one, so it repeats.
    assert nudges
    note = table.notes()
    assert "finished with exit code 0" in note
    assert "Poll" in note

    collected = len(nudges)
    time.sleep(0.2)
    assert len(nudges) == collected
    table.kill_all()


def test_the_note_leaves_the_output_for_poll(monkeypatch, tmp_path):
    monkeypatch.setattr(shell, "YIELD_SECONDS", 0.3)
    table = shell.JobTable()
    monkeypatch.setattr(shell, "jobs", table)

    started = shell.run(slow_script(tmp_path), workdir=str(tmp_path))
    session = re.search(r"Session: (\S+)", started).group(1)
    deadline = time.monotonic() + 10
    while table.notes_waiting() is False and time.monotonic() < deadline:
        time.sleep(0.05)

    # The note names the ending and nothing else: a model reads it and polls,
    # and that poll has to answer with the output rather than "No new output".
    note = table.notes()
    assert "done" not in note
    assert "done" in shell.poll(session)
    table.kill_all()


def test_a_job_whose_output_nobody_read_is_kept_longer(monkeypatch, tmp_path):
    monkeypatch.setattr(shell, "YIELD_SECONDS", 0.3)
    monkeypatch.setattr(shell, "SWEEP_SECONDS", 0.05)
    monkeypatch.setattr(shell, "FINISHED_TTL", 0)
    table = shell.JobTable()
    monkeypatch.setattr(shell, "jobs", table)

    started = shell.run(slow_script(tmp_path), workdir=str(tmp_path))
    session = re.search(r"Session: (\S+)", started).group(1)
    deadline = time.monotonic() + 10
    while table.notes_waiting() is False and time.monotonic() < deadline:
        time.sleep(0.05)
    table.notes()

    # Reported but unread, so the sweeper leaves it where the poll the note
    # asked for can still find it, however long the user takes to look.
    time.sleep(0.3)
    assert table.find(session) is not None
    assert "done" in shell.poll(session)

    # Read now, so the short clock applies and it is forgotten.
    deadline = time.monotonic() + 5
    while table.find(session) is not None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert table.find(session) is None
    table.kill_all()


def test_an_ending_the_model_has_had_is_not_waiting_any_more(monkeypatch, tmp_path):
    monkeypatch.setattr(shell, "YIELD_SECONDS", 0.3)
    table = shell.JobTable()
    monkeypatch.setattr(shell, "jobs", table)

    started = shell.run(slow_script(tmp_path), workdir=str(tmp_path))
    session = re.search(r"Session: (\S+)", started).group(1)
    shell.poll(session, wait=10)

    assert table.notes_waiting() is False
    assert table.notes() == ""
    table.kill_all()


def test_polling_a_session_that_never_existed_says_so():
    assert "There is no background command" in shell.poll("no-such-job")


def test_listing_with_nothing_running():
    assert shell.JobTable().listing() == "There are no background commands."


def test_the_transcript_summary_is_the_command_itself():
    assert shell.summarize_run({"command": "git status"}) == "git status"
    assert shell.summarize_poll({"session_id": "brave-otter", "kill": True}) == (
        "poll brave-otter (stop it)"
    )
