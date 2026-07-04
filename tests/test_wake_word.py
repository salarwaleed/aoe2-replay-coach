"""Wake-word matching — including the onset-clipping and mishear cases that
were observed in live Discord voice testing (Gemini transcribed 'Teletron 1'
as 'Electron one', and Discord VAD clipped 'Teletron,' down to 'ron,')."""
import pytest

import voice_listen as vl

WAKES = ["teletron", "electron", "telethon", "teleron"]


def _match(text: str):
    for w in WAKES:
        q = vl.match_wake_word(text, w)
        if q is not None:
            return q
    return vl.match_clipped_wake(text)


@pytest.mark.parametrize("text,expected", [
    # Clean wake word.
    ("Teletron who is the most aggressive player", "who is the most aggressive player"),
    ("Teletron, can you answer a question for me?", "can you answer a question for me?"),
    ("Teletron one, defend please", "defend please"),
    # STT mishears of the made-up wake word.
    ("Electron one my name is Salar", "my name is salar"),
    # Discord VAD onset clipping ('Teletron,' -> 'ron,').
    ("Ron, who is the most aggressive player?", "who is the most aggressive player?"),
    ("ron who is the most defensive player", "who is the most defensive player"),
    ("Who is the Teleron? Who is the most defensive player?", "who is the most defensive player?"),
])
def test_wake_word_matches(text, expected):
    assert _match(text) == expected


@pytest.mark.parametrize("text", [
    "I", "Yeah", "Can you listen to me", "front of the base is falling",
    "Ronaldo is a footballer",  # must NOT false-trigger on 'ron' inside a word
    "",
])
def test_non_wake_utterances_ignored(text):
    assert _match(text) is None


def test_bare_wake_word_returns_empty_query():
    # Just the wake word with no question -> '' (bot prompts "yes?"), not None.
    assert vl.match_wake_word("teletron", "teletron") == ""
