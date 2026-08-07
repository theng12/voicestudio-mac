"""Speech-friendly text normalization for TTS input.

Some local TTS models (observed on OmniVoice) mispronounce raw digit
sequences while reading spelled-out number words correctly every time. This
module expands digits, currency amounts, clock times, and ordinals into the
word form a TTS model should say, so callers can run outbound text through
``normalize_for_speech`` immediately before synthesis.

Design notes
------------
* Standard library only. No ``num2words``/``inflect``/etc. dependency.
* Pure function: no I/O, no module-level mutable state, no globals mutated.
* Only tokens that look like *standalone* numbers are touched. A digit
  sequence is only eligible for expansion when it sits at a "word boundary"
  on both sides in the regex sense -- i.e. it is not glued to surrounding
  letters. Concretely this means the digits must not have a letter
  immediately before them (no ``\\b`` between two word characters). That
  naturally leaves alphanumeric tokens such as ``MP3`` or ``B2B`` untouched,
  because in both cases the digit is adjacent to a letter with no boundary
  for the regex to anchor on, without needing a special-cased word list.
* Bracketed non-verbal tags such as ``[laughter]`` are matched and emitted
  unchanged as a single token, so any digits accidentally inside a tag
  (e.g. ``[2x speed]``) are never touched either.
* Year reading (e.g. "1998" -> "nineteen ninety-eight") only fires for bare
  4-digit numbers in the 1900-2099 range with no thousands separator. This
  is deliberately narrower than a plain "4 digit number" rule: a comma
  ("1,998") means the writer explicitly wants a magnitude reading, and a
  value like "1200" is treated as a plain thousands-grouped cardinal
  ("one thousand two hundred") rather than a year, matching how such
  figures are normally intended in dollar/quantity contexts rather than as
  a calendar year.
"""
from __future__ import annotations

import re

__all__ = ["normalize_for_speech"]

_ONES = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
)
_TENS = (
    "", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
    "eighty", "ninety",
)
_SCALES = ("", "thousand", "million", "billion", "trillion", "quadrillion")

_ORDINAL_IRREGULAR = {
    "one": "first",
    "two": "second",
    "three": "third",
    "four": "fourth",
    "five": "fifth",
    "eight": "eighth",
    "nine": "ninth",
    "twelve": "twelfth",
}

# Order matters: earlier alternatives win when they can start at the same
# string position, so the more specific patterns (tag, currency, time,
# ordinal) are listed before the general catch-all number pattern.
_TOKEN_RE = re.compile(
    r"""
    (?P<tag>\[[^\]]*\])
    |(?P<currency>\$-?\d{1,3}(?:,\d{3})*(?:\.\d+)?)
    |(?P<time>\b(?:[01]?\d|2[0-3]):[0-5]\d\b)
    |(?P<ordinal>\b\d+(?:st|nd|rd|th)\b)
    |(?P<number>-?\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|-?\b\d+(?:\.\d+)?\b)
    """,
    re.VERBOSE,
)


def _two_digit_words(n: int) -> str:
    """Words for 0 <= n < 100."""
    if n < 20:
        return _ONES[n]
    tens_word = _TENS[n // 10]
    remainder = n % 10
    return tens_word if remainder == 0 else f"{tens_word}-{_ONES[remainder]}"


def _three_digit_words(n: int) -> str:
    """Words for 0 <= n < 1000."""
    hundreds, remainder = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(f"{_ONES[hundreds]} hundred")
    if remainder:
        parts.append(_two_digit_words(remainder))
    return " ".join(parts) if parts else "zero"


def _cardinal_words(n: int) -> str:
    """Words for a non-negative integer of arbitrary size."""
    if n == 0:
        return "zero"
    groups = []
    remaining = n
    while remaining > 0:
        groups.append(remaining % 1000)
        remaining //= 1000
    parts = []
    for index in range(len(groups) - 1, -1, -1):
        group_value = groups[index]
        if group_value == 0:
            continue
        words = _three_digit_words(group_value)
        scale = _SCALES[index] if index < len(_SCALES) else ""
        if scale:
            words = f"{words} {scale}"
        parts.append(words)
    return " ".join(parts)


def _ordinal_suffix_word(word: str) -> str:
    if word in _ORDINAL_IRREGULAR:
        return _ORDINAL_IRREGULAR[word]
    if word.endswith("y"):
        return word[:-1] + "ieth"
    return word + "th"


def _cardinal_to_ordinal_words(n: int) -> str:
    words = _cardinal_words(n)
    if "-" in words:
        prefix, last = words.rsplit("-", 1)
        return f"{prefix}-{_ordinal_suffix_word(last)}"
    parts = words.split(" ")
    parts[-1] = _ordinal_suffix_word(parts[-1])
    return " ".join(parts)


def _year_words(n: int) -> str:
    """Natural "nineteen ninety-eight" style reading for 1900 <= n <= 2099."""
    first_two, last_two = divmod(n, 100)
    first_word = _two_digit_words(first_two)
    if last_two == 0:
        return f"{first_word} hundred"
    if last_two < 10:
        return f"{first_word} oh {_ONES[last_two]}"
    return f"{first_word} {_two_digit_words(last_two)}"


def _digits_spoken_individually(digits: str) -> str:
    return " ".join(_ONES[int(d)] for d in digits if d.isdigit())


def _number_token_words(token: str) -> str:
    negative = token.startswith("-")
    core = token[1:] if negative else token

    if "." in core:
        int_part, dec_part = core.split(".", 1)
        n = int(int_part.replace(",", "")) if int_part else 0
        words = f"{_cardinal_words(n)} point {_digits_spoken_individually(dec_part)}"
    else:
        has_comma = "," in core
        n = int(core.replace(",", ""))
        if (
            not has_comma
            and not negative
            and len(core) == 4
            and core[0] != "0"
            and 1900 <= n <= 2099
        ):
            words = _year_words(n)
        else:
            words = _cardinal_words(n)

    return f"minus {words}" if negative else words


def _ordinal_token_words(token: str) -> str:
    n = int(token[:-2])
    return _cardinal_to_ordinal_words(n)


def _currency_token_words(token: str) -> str:
    body = token[1:]  # strip leading "$"
    negative = body.startswith("-")
    body = body[1:] if negative else body

    if "." in body:
        dollars_str, cents_str = body.split(".", 1)
    else:
        dollars_str, cents_str = body, ""

    dollars = int(dollars_str.replace(",", "")) if dollars_str else 0
    words = _cardinal_words(dollars)
    words += " dollar" if dollars == 1 else " dollars"

    if cents_str:
        cents = int((cents_str + "0")[:2])
        if cents > 0:
            cent_words = _cardinal_words(cents)
            words += f" and {cent_words} cent" if cents == 1 else f" and {cent_words} cents"

    return f"minus {words}" if negative else words


def _time_token_words(token: str) -> str:
    hour_str, minute_str = token.split(":")
    hour = int(hour_str)
    minute = int(minute_str)
    hour_words = _two_digit_words(hour)

    if minute == 0:
        return f"{hour_words} o'clock"
    if minute < 10:
        return f"{hour_words} oh {_ONES[minute]}"
    return f"{hour_words} {_two_digit_words(minute)}"


def _replace_token(match: "re.Match[str]") -> str:
    kind = match.lastgroup
    text = match.group()
    if kind == "tag":
        return text
    if kind == "currency":
        return _currency_token_words(text)
    if kind == "time":
        return _time_token_words(text)
    if kind == "ordinal":
        return _ordinal_token_words(text)
    if kind == "number":
        return _number_token_words(text)
    return text  # pragma: no cover - defensive, every branch above is exhaustive


def normalize_for_speech(text: str) -> str:
    """Expand digits, currency, clock times, and ordinals into spoken words.

    Pure function: takes a string, returns a string, performs no I/O, and
    reads only local/module-constant state. Text with no eligible tokens
    (already spelled out, or non-verbal tags like ``[laughter]``) is
    returned unchanged.
    """
    if not text:
        return text
    return _TOKEN_RE.sub(_replace_token, text)
