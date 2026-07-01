"""
reference_loader.py
Loads the Voobly v1.6 server reference document and the AoE2 game rates
reference at import time, exposing each as a string constant. Used to inject
ruleset and game-rate context into LLM system prompts. Never raises — returns
an empty string if a file is missing.
"""
import pathlib

_REF_PATH = pathlib.Path(__file__).parent / "reference_data" / "voobly_v16.md"
_RATES_PATH = pathlib.Path(__file__).parent / "reference_data" / "game_rates.md"

try:
    VOOBLY_V16 = _REF_PATH.read_text(encoding="utf-8")
except Exception:
    VOOBLY_V16 = ""

try:
    GAME_RATES = _RATES_PATH.read_text(encoding="utf-8")
except Exception:
    GAME_RATES = ""
