"""Settings, presets, parameters and the prompt library."""

import csv
import json
import os
import stat

import pytest

from vollama.config import parameters, presets, prompts, store
from vollama.config import settings as settings_module
from vollama.config.presets import Preset
from vollama.config.prompts import Prompt, PromptLibrary
from vollama.config.settings import SETTINGS_VERSION, Settings
from vollama.errors import ConfigError, VOLlamaError


# ------------------------------------------------------------------- the store


def test_settings_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    written = Settings(secret=store.new_secret(), workdir="D:/work", tools=True)
    store.write(path, written.to_dict())
    assert Settings.from_dict(store.read(path)) == written


def test_api_keys_are_not_readable_in_the_file(tmp_path):
    path = tmp_path / "settings.json"
    data = Settings(
        secret=store.new_secret(),
        presets={
            "one": Preset(
                api_key="chat-secret", embedding_api_key="embed-secret", model="m"
            ).to_dict()
        },
    ).to_dict()
    store.write(path, data)

    raw = path.read_text(encoding="utf-8")
    assert "embed-secret" not in raw
    assert "chat-secret" not in raw

    back = store.read(path)
    assert back["presets"]["one"]["api_key"] == "chat-secret"
    assert back["presets"]["one"]["embedding_api_key"] == "embed-secret"


def test_writing_does_not_encrypt_the_caller_s_own_presets(tmp_path):
    """The in-memory presets must survive a save as plaintext."""
    data = Settings(
        secret=store.new_secret(), presets={"one": {"api_key": "plain"}}
    ).to_dict()
    store.write(tmp_path / "settings.json", data)
    assert data["presets"]["one"]["api_key"] == "plain"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_the_settings_file_is_private(tmp_path):
    path = tmp_path / "settings.json"
    store.write(path, Settings(secret=store.new_secret()).to_dict())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_missing_file_is_a_first_run_not_a_failure(tmp_path):
    assert store.read(tmp_path / "nothing.json") is None


def test_an_unparseable_file_is_reported(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        store.read(path)


def test_loading_a_missing_file_writes_a_fresh_one(isolated):
    assert not store.settings_path().exists()  # the fixture saves nothing
    assert settings_module.load() is True
    assert isolated.writable is True
    assert store.settings_path().exists()


def test_a_file_from_another_version_is_refused_and_left_alone(isolated):
    """The user is told to reset, and their api keys stay where they are."""
    path = store.settings_path()
    path.write_text(
        json.dumps({"version": SETTINGS_VERSION + 1, "presets": {"one": {}}}),
        encoding="utf-8",
    )

    assert settings_module.load() is False
    assert isolated.presets == {}
    assert isolated.writable is False

    # And one menu toggle cannot save the defaults over it, which is what the
    # message shown to the user promises.
    isolated.sound = False
    isolated.save()
    assert json.loads(path.read_text(encoding="utf-8"))["presets"] == {"one": {}}


def test_unknown_and_missing_fields_take_defaults():
    loaded = Settings.from_dict({"tools": True, "invented_by_a_newer_build": 1})
    assert loaded.tools is True
    assert loaded.version == SETTINGS_VERSION
    assert loaded.workdir == Settings().workdir


# ----------------------------------------------------------------- parameters


def test_options_leaves_out_what_was_not_set():
    assert parameters.options({"temperature": 0.5, "stop": [], "top_p": None}) == {
        "temperature": 0.5
    }


def test_options_keeps_a_value_of_zero():
    """A temperature of 0 is a choice, and the falsiest one there is."""
    assert parameters.options({"temperature": 0.0}) == {"temperature": 0.0}


@pytest.mark.parametrize(
    "key, text, expected",
    [
        ("temperature", "", None),
        ("temperature", " 0.7 ", 0.7),
        ("seed", "42", 42),
        ("stop", "a, b ,", ["a", "b"]),
        ("reasoning_effort", "high", "high"),
    ],
)
def test_parse(key, text, expected):
    assert parameters.parse(key, text) == expected


def test_parse_rejects_a_number_that_is_not_one():
    with pytest.raises(ValueError):
        parameters.parse("seed", "soon")


def test_checked_keeps_what_the_schema_knows_and_drops_the_rest():
    kept = parameters.checked(
        {
            "temperature": 0.5,
            "max_tokens": 100,
            "stop": ["END"],
            "gone": 1,  # a parameter this build does not have
            "seed": "soon",  # not the kind of value seed takes
            "top_p": {"value": 0.9},  # the shape an older build stored
        }
    )
    assert kept == {"temperature": 0.5, "max_tokens": 100, "stop": ["END"]}


def test_checked_takes_a_whole_number_as_a_decimal():
    """A temperature typed as 1 in the file is a temperature of 1."""
    assert parameters.checked({"temperature": 1}) == {"temperature": 1}


# --------------------------------------------------------------------- presets


def usable(**kwargs):
    fields = {"base_url": "http://localhost/v1/", "model": "m"}
    fields.update(kwargs)
    return Preset(**fields)


def test_a_preset_needs_a_base_url_and_a_model():
    usable().validate()
    with pytest.raises(ConfigError, match="base URL"):
        Preset(model="m").validate()
    with pytest.raises(ConfigError, match="model"):
        Preset(base_url="http://localhost/v1/").validate()


def test_the_error_names_the_field_that_is_wrong():
    """Which is how the editor puts the focus where the fix is."""
    with pytest.raises(ConfigError) as refused:
        Preset(model="m").validate()
    assert refused.value.field == "base_url"
    with pytest.raises(ConfigError) as refused:
        Preset(base_url="http://localhost/v1/").validate()
    assert refused.value.field == "model"


def test_replace_stores_the_list_and_activates_the_named_one():
    presets.replace([("a", usable(model="one")), ("b", usable(model="two"))], "b")
    assert presets.names() == ["a", "b"]
    assert presets.active_name() == "b"
    assert presets.get("b").model == "two"


def test_replace_deletes_what_is_no_longer_in_the_list():
    presets.replace([("a", usable()), ("b", usable())], "a")
    presets.replace([("b", usable(model="two"))], "b")
    assert presets.names() == ["b"]
    assert presets.active_name() == "b"


def test_replace_lets_two_presets_swap_names():
    """One write, rather than a rename that has to dodge the other."""
    presets.replace([("a", usable(model="one")), ("b", usable(model="two"))], "a")
    presets.replace([("b", usable(model="one")), ("a", usable(model="two"))], "a")
    assert presets.get("a").model == "two"
    assert presets.get("b").model == "one"


def test_replace_refuses_an_empty_or_repeated_name():
    with pytest.raises(ConfigError, match="Enter a name"):
        presets.replace([("", usable())])
    with pytest.raises(ConfigError, match="two presets named"):
        presets.replace([("a", usable()), ("a", usable())])


def test_replace_falls_back_to_the_first_preset_and_to_none():
    presets.replace([("b", usable()), ("a", usable())], "gone")
    assert presets.active_name() == "a"
    presets.replace([])
    assert presets.names() == []
    assert presets.active_name() == ""


def test_an_active_name_that_no_longer_exists_is_corrected(isolated):
    presets.replace([("one", usable())], "one")
    isolated.active_preset = "deleted"
    assert presets.active_name() == "one"


def test_require_active_says_where_to_fix_it_and_which_field_it_is():
    with pytest.raises(ConfigError, match=r"control\+p"):
        presets.require_active()
    presets.replace([("one", Preset(base_url="http://localhost/v1/"))], "one")
    with pytest.raises(ConfigError) as refused:
        presets.require_active()
    assert "control+p" in str(refused.value)
    assert refused.value.field == "model"


def test_a_preset_survives_being_written_and_read(isolated):
    presets.replace(
        [
            (
                "one",
                usable(
                    api_key="k",
                    system="be brief",
                    context_window=4096,
                    parameters={"temperature": 0.5, "stop": ["END"]},
                ),
            )
        ],
        "one",
    )
    store.write(store.settings_path(), isolated.to_dict())
    saved = json.loads(store.settings_path().read_text(encoding="utf-8"))
    back = Preset.from_dict(store.read(store.settings_path())["presets"]["one"])
    assert back == presets.get("one")
    assert back.parameters == {"temperature": 0.5, "stop": ["END"]}
    assert saved["presets"]["one"]["api_key"] != "k"


def test_the_stored_preset_holds_values_and_not_the_parameter_schema():
    """The description and the range of a parameter are the program's, not data."""
    stored = usable(parameters={"temperature": 0.5}).to_dict()
    assert stored["parameters"] == {"temperature": 0.5}


def test_a_preset_whose_parameters_are_the_old_shape_loads_without_them(isolated):
    """The rest of it survives, which is why the file version is not bumped.

    A build before this one wrote the whole parameter schema into every preset,
    so the value of a parameter is a dict where a number belongs. The value is
    dropped and the server decides, which is what an unset parameter has always
    meant; the base URL, model and api key — the parts nobody can retype from
    memory — are kept.
    """
    back = Preset.from_dict(
        {
            "base_url": "http://localhost/v1/",
            "model": "m",
            "api_key": "k",
            "parameters": {
                "temperature": {"value": 0.7, "description": "...", "range": "0.0-2.0"}
            },
        }
    )
    assert (back.base_url, back.model, back.api_key) == (
        "http://localhost/v1/",
        "m",
        "k",
    )
    assert back.parameters == {}


def test_a_hand_edited_field_that_is_not_a_number_takes_the_default():
    back = Preset.from_dict(
        {"base_url": "u", "model": "m", "context_window": "lots", "chunk_size": 0}
    )
    assert back.context_window == presets.DEFAULT_CONTEXT_WINDOW
    assert back.chunk_size == Preset().chunk_size


def test_a_preset_written_before_the_retrieval_fields_takes_their_defaults():
    """An old settings.json still loads; the file version is not bumped for it.

    The cost is named rather than migrated around: a preset saved by an older
    build has no embedding URL of its own, so it gets the default one back.
    """
    back = Preset.from_dict({"base_url": "http://localhost/v1/", "model": "m"})
    assert back.embedding_base_url == presets.DEFAULT_EMBEDDING_URL
    assert back.embedding_model == presets.DEFAULT_EMBEDDING_MODEL
    assert (back.chunk_size, back.similarity_top_k) == (1024, 2)
    assert back.similarity_cutoff == 0.0


def test_the_retrieval_settings_are_read_from_the_active_preset(isolated):
    """Which is what switching preset switches, embedding endpoint included."""
    presets.replace(
        [
            ("local", usable(embedding_base_url="http://one/v1/")),
            ("hosted", usable(embedding_base_url="http://two/v1/")),
        ],
        "local",
    )

    presets.activate("local")
    assert presets.retrieval().embedding_base_url == "http://one/v1/"
    presets.activate("hosted")
    assert presets.retrieval().embedding_base_url == "http://two/v1/"


def test_retrieval_falls_back_to_the_defaults_when_no_preset_is_configured():
    """So indexing fails on the embedding request, where the reason is visible."""
    assert presets.retrieval() == Preset()


# ------------------------------------------------------------- prompt library


def test_prompts_are_unique_by_name_and_kept_sorted(tmp_path):
    library = PromptLibrary(tmp_path / "prompts.csv")
    library.put("beta", "second")
    library.put("alpha", "first")
    library.put("beta", "replaced")
    assert library.names() == ["alpha", "beta"]
    assert PromptLibrary(tmp_path / "prompts.csv").prompts[1].text == "replaced"


def test_a_merge_prefers_the_incoming_text(tmp_path):
    library = PromptLibrary(tmp_path / "prompts.csv")
    library.put("shared", "mine")
    library.merge([Prompt("shared", "theirs"), Prompt("new", "text")])
    assert library.names() == ["new", "shared"]
    assert [p.text for p in library.prompts] == ["text", "theirs"]


def test_find_says_which_saved_prompt_a_text_is_and_when_it_is_none(tmp_path):
    """The preset editor highlights `find`'s answer and clears on None.

    A None that came back as an index would leave the last preset's prompt
    highlighted, and choosing an already-highlighted prompt fires no event.
    """
    library = PromptLibrary(tmp_path / "prompts.csv")
    library.put("poet", "be a poet")
    assert library.find("be a poet") == 0
    assert library.find("something else") is None


def test_a_missing_library_is_empty_rather_than_an_error(tmp_path):
    assert PromptLibrary(tmp_path / "absent.csv").names() == []


class _serving:
    """Stands in for `requests`, answering every get with this text."""

    def __init__(self, text):
        self.text = text

    def get(self, url, timeout=None):
        return self

    def raise_for_status(self):
        pass

    RequestException = Exception


def test_a_prompt_longer_than_csv_s_own_limit_survives(tmp_path, monkeypatch):
    """The published collection has one; csv refuses a 131072-character field."""
    limit = csv.field_size_limit()
    long = "x" * (limit + 1000)
    served = "act,prompt\nlong," + long + "\n"
    monkeypatch.setattr(prompts, "requests", _serving(served))

    library = PromptLibrary(tmp_path / "prompts.csv")
    library.merge(prompts.fetch_shared())

    assert PromptLibrary(tmp_path / "prompts.csv").prompts[0].text == long
    # Raised for our own parsing only: the limit is process-wide.
    assert csv.field_size_limit() == limit


def test_a_download_that_will_not_parse_is_reported_as_ours(monkeypatch):
    """It reached the user as a traceback: only the request was wrapped."""
    monkeypatch.setattr(prompts, "MAX_FIELD", 10)
    unterminated = "act,prompt\nlong,\"" + "x" * 50
    monkeypatch.setattr(prompts, "requests", _serving(unterminated))

    with pytest.raises(VOLlamaError, match="Could not read the downloaded prompts"):
        prompts.fetch_shared()
    assert csv.field_size_limit() != 10
