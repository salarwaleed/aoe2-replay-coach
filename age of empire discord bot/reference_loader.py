"""
reference_loader.py
Loads the Voobly v1.6 server reference document at import time and exposes it
as a single string constant. Used to inject ruleset context into LLM system
prompts. Never raises — returns an empty string if the file is missing.
"""
import pathlib

_REF_PATH = pathlib.Path(__file__).parent / "reference_data" / "voobly_v16.md"

try:
    VOOBLY_V16 = _REF_PATH.read_text(encoding="utf-8")
except Exception:
    VOOBLY_V16 = ""
