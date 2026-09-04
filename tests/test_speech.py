"""The parts of `speech` that are not a platform API.

No backend is imported: three of the four need a library that exists on one
platform only. What is testable is the arrangement — how voices are grouped and
labelled — which is the part that was wrong.
"""

from vollama.speech import Voice, described, group

# What macOS actually reports, identifier and VoiceName both, for a machine with
# Korean and English voices installed. The identifiers sort these voices into
# three engine families and the names do not mention the engine at all, which is
# the whole reason grouping by identifier failed.
MAC_VOICES = [
    Voice("com.apple.speech.synthesis.voice.Alex", "Alex", "English (United States)"),
    Voice("com.apple.voice.compact.en-US.Samantha", "Samantha", "English (United States)"),
    Voice("com.apple.voice.enhanced.en-US.Samantha", "Samantha (Enhanced)", "English (United States)"),
    Voice(
        "com.apple.ttsbundle.gryphon-neuralAX_Nora_en-US_premium",
        "Voice 4",
        "English (United States)",
    ),
    Voice("com.apple.voice.compact.ko-KR.Yuna", "Yuna", "Korean (South Korea)"),
    Voice(
        "com.apple.eloquence.ko-KR.Eddy",
        "Eddy (Korean (South Korea))",
        "Korean (South Korea)",
    ),
    Voice("com.apple.voice.compact.en-GB.Daniel", "Daniel", "English (United Kingdom)"),
]


def test_voices_group_by_language_rather_than_by_engine():
    """The nine Korean voices on a real machine were in three separate places."""
    languages = group(MAC_VOICES)
    assert sorted(languages) == [
        "English (United Kingdom)",
        "English (United States)",
        "Korean (South Korea)",
    ]
    # Yuna is com.apple.voice.compact.* and Eddy is com.apple.eloquence.*, so
    # grouping by identifier put them under different top-level entries.
    assert [voice.name for voice in languages["Korean (South Korea)"]] == [
        "Yuna",
        "Eddy (Korean (South Korea))",
    ]


def test_the_siri_voice_is_grouped_by_a_name_someone_could_find():
    """Its identifier contains neither "Siri" nor its own name."""
    english = group(MAC_VOICES)["English (United States)"]
    assert "Voice 4" in [voice.name for voice in english]


def test_every_voice_is_reachable_from_exactly_one_group():
    found = [voice for voices in group(MAC_VOICES).values() for voice in voices]
    assert sorted(found, key=lambda voice: voice.identifier) == sorted(
        MAC_VOICES, key=lambda voice: voice.identifier
    )


def test_voices_keep_the_order_the_backend_gave_them():
    """The backend sorts; group() must not undo it."""
    voices = [Voice(f"id.{n}", n, "Thai") for n in ("Kanya", "Anna", "Zoe")]
    assert [voice.name for voice in group(voices)["Thai"]] == ["Kanya", "Anna", "Zoe"]


def test_voices_with_no_language_stay_at_the_top_level():
    """An empty heading tells the user nothing; a flat list at least works."""
    voices = [Voice("Microsoft David", "Microsoft David")]
    assert group(voices) == {"": voices}


def test_no_voices_is_an_empty_grouping_rather_than_an_error():
    assert group([]) == {}


# --------------------------------------------------------------------- labels


def test_a_name_that_repeats_its_language_does_not_repeat_it_in_the_submenu():
    voice = Voice("com.apple.eloquence.ko-KR.Eddy", "Eddy (Korean (South Korea))", "Korean (South Korea)")
    assert voice.within("Korean (South Korea)") == "Eddy"


def test_a_name_that_only_looks_like_its_language_is_left_alone():
    assert Voice("id", "Samantha (Enhanced)", "English (United States)").within(
        "English (United States)"
    ) == "Samantha (Enhanced)"


def test_a_name_that_is_nothing_but_its_language_keeps_the_name():
    """Stripping would leave an empty menu item."""
    assert Voice("id", "(Thai)", "Thai").within("Thai") == "(Thai)"


def test_the_button_says_the_voice_and_its_language():
    voice = Voice("com.apple.ttsbundle.gryphon-neuralAX_Nora_en-US_premium", "Voice 4", "English (US)")
    assert voice.describe() == "Voice 4, English (US)"


def test_a_voice_with_no_language_is_described_by_name_alone():
    assert Voice("Microsoft David", "Microsoft David").describe() == "Microsoft David"


# ----------------------------------------------------------- sapi descriptions


def test_a_sapi_description_splits_into_a_name_and_a_language():
    voice = described("Microsoft Zira Desktop - English (United States)")
    # The identifier keeps the whole description, which is what settings hold.
    assert voice.identifier == "Microsoft Zira Desktop - English (United States)"
    assert voice.name == "Microsoft Zira Desktop"
    assert voice.language == "English (United States)"


def test_a_sapi_description_that_does_not_split_keeps_working():
    voice = described("Microsoft David")
    assert voice == Voice("Microsoft David", "Microsoft David", "")


def test_a_sapi_name_containing_the_separator_splits_at_the_last_one():
    voice = described("Vocalizer Expressive - Tom - English (United States)")
    assert voice.name == "Vocalizer Expressive - Tom"
    assert voice.language == "English (United States)"


def test_a_sapi_description_with_an_empty_half_is_not_split():
    """Otherwise a voice ends up named "" and shows as a blank menu item."""
    assert described("Microsoft David - ").name == "Microsoft David - "
    assert described(" - English").name == " - English"
