from __future__ import annotations

import pytest

from backend import text_normalization


normalize = text_normalization.normalize_for_speech


# ---------------------------------------------------------------------------
# 1. Thousands separators and plain integers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,200", "one thousand two hundred"),
        ("1200", "one thousand two hundred"),
        ("12,500", "twelve thousand five hundred"),
        ("12500", "twelve thousand five hundred"),
        ("3,000", "three thousand"),
        ("360", "three hundred sixty"),
        ("0", "zero"),
    ],
)
def test_thousands_separators_and_plain_integers(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


# ---------------------------------------------------------------------------
# 2. Currency
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$1,450.75", "one thousand four hundred fifty dollars and seventy-five cents"),
        ("$5", "five dollars"),
        ("$1", "one dollar"),
    ],
)
def test_currency(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


# ---------------------------------------------------------------------------
# 3. Years (1900-2099, no thousands separator)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1998", "nineteen ninety-eight"),
        ("2026", "twenty twenty-six"),
        ("1900", "nineteen hundred"),
    ],
)
def test_years(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


def test_comma_disqualifies_year_reading() -> None:
    # A thousands separator means the writer wants a magnitude reading, not
    # a calendar year, even though 1998 falls in the "year" range.
    assert normalize("1,998") == "one thousand nine hundred ninety-eight"


# ---------------------------------------------------------------------------
# 4. Clock times
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("3:47", "three forty-seven"),
        ("10:05", "ten oh five"),
        ("6:00", "six o'clock"),
    ],
)
def test_clock_times(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


# ---------------------------------------------------------------------------
# 5. Ordinals
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("3rd", "third"),
        ("1st", "first"),
        ("22nd", "twenty-second"),
    ],
)
def test_ordinals(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


# ---------------------------------------------------------------------------
# 6. Decimals outside currency
# ---------------------------------------------------------------------------

def test_plain_decimal() -> None:
    assert normalize("3.5") == "three point five"


# ---------------------------------------------------------------------------
# 7. Negative numbers
# ---------------------------------------------------------------------------

def test_negative_number() -> None:
    assert normalize("-4") == "minus four"


# ---------------------------------------------------------------------------
# 8a. Non-verbal tags must pass through exactly
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tag", ["[laughter]", "[cough]", "[sigh]"])
def test_non_verbal_tags_untouched(tag: str) -> None:
    assert normalize(tag) == tag


def test_non_verbal_tag_embedded_in_sentence_untouched() -> None:
    text = "That's hilarious [laughter] truly."
    assert normalize(text) == text


def test_tag_containing_digits_is_left_fully_alone() -> None:
    # Even if a tag happens to contain digits, the whole bracketed token is
    # a single opaque unit and must not be partially expanded.
    tag = "[2x speed]"
    assert normalize(tag) == tag


# ---------------------------------------------------------------------------
# 8b. Already spelled-out text must be unchanged
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "one thousand two hundred dollars",
        "The quick brown fox jumps over the lazy dog.",
        "twenty twenty-six was a great year.",
        "",
    ],
)
def test_already_spelled_out_text_unchanged(text: str) -> None:
    assert normalize(text) == text


# ---------------------------------------------------------------------------
# 8c. Digit-containing words that are NOT standalone numbers must be left
#     alone. Rule implemented: a digit run is only expanded when neither
#     side of it is glued to a letter (regex word-boundary on both ends of
#     the numeric token). "MP3" has a letter directly before the "3" so
#     there is no boundary there and it is skipped entirely; same for
#     "B2B" (letter immediately before AND after the digit).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    ["MP3", "B2B", "Q3", "4K", "H2O", "3D", "GPT4"],
)
def test_alphanumeric_tokens_untouched(text: str) -> None:
    assert normalize(text) == text


def test_alphanumeric_token_in_sentence_untouched() -> None:
    text = "Export the audio as an MP3 file for the B2B client."
    assert normalize(text) == text


# ---------------------------------------------------------------------------
# Combined / sentence-level sanity checks
# ---------------------------------------------------------------------------

def test_sentence_with_multiple_token_kinds() -> None:
    text = "In 1998 I paid $1,450.75 for it at 3:47 on the 3rd of March."
    expected = (
        "In nineteen ninety-eight I paid "
        "one thousand four hundred fifty dollars and seventy-five cents "
        "for it at three forty-seven on the third of March."
    )
    assert normalize(text) == expected


def test_pure_function_no_side_effects() -> None:
    text = "I have 1200 dollars"
    result_1 = normalize(text)
    result_2 = normalize(text)
    assert result_1 == result_2
    assert text == "I have 1200 dollars"  # input string itself is untouched


def test_idempotent_on_its_own_output() -> None:
    text = "1998 and 1,200 and $5 and 3rd"
    once = normalize(text)
    twice = normalize(once)
    assert once == twice


def test_generation_normalises_only_families_that_need_it() -> None:
    """OmniVoice has no normaliser of its own, so Voice Studio must expand digits
    before synthesis. Families that already normalise upstream must NOT be
    normalised twice, and the previously-dead `normalize_text` flag must now be
    able to force it for any family."""
    from backend import generation

    assert "omnivoice" in generation._NUMBER_NORMALISED_FAMILIES

    # Automatic for the family that needs it.
    assert generation._normalized_speech_text(
        "omnivoice", "closer to 1,200 people", {}
    ) == "closer to one thousand two hundred people"

    # Left alone for a family that is not on the allow-list...
    assert generation._normalized_speech_text(
        "kokoro-mlx", "closer to 1,200 people", {}
    ) == "closer to 1,200 people"

    # ...unless the caller explicitly asks. This flag used to be accepted and
    # silently ignored.
    assert generation._normalized_speech_text(
        "kokoro-mlx", "closer to 1,200 people", {"normalize_text": True}
    ) == "closer to one thousand two hundred people"


def test_normalisation_never_fails_a_job(monkeypatch) -> None:
    """Cosmetics must not take down a generation."""
    from backend import generation

    def boom(_):
        raise ValueError("bad input")

    monkeypatch.setattr(generation.text_normalization, "normalize_for_speech", boom)
    assert generation._normalized_speech_text(
        "omnivoice", "closer to 1,200 people", {}
    ) == "closer to 1,200 people"
