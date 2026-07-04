"""Pytest bootstrap: make both importable code roots reachable.

`pipeline` is a normal package at the repo root (pytest puts the root on
sys.path automatically). The bot modules live in a directory whose name has
spaces and is not a package, so add it explicitly here so tests can
`import voice_listen`, `import cloud_llm`, etc.
"""
import pathlib
import sys

_BOT_DIR = pathlib.Path(__file__).parent / "age of empire discord bot"
if _BOT_DIR.is_dir() and str(_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_BOT_DIR))
