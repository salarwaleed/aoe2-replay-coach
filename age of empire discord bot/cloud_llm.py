"""Unified cloud-LLM client — the "new tech" backbone for bot.py commands.

Per TELEMETRY_PLAN.md, live Discord answers are meant to come from a cheap
cloud LLM (Gemini via an Openclaw-style proxy), with the heavy overnight
synthesis done locally by Ollama (pipeline 3). This module is the single
entry point every bot command routes through to ask that cloud LLM a
question, so command code never talks to an HTTP API directly.

Configuration (environment variables, e.g. in `.env`):
    OPENCLAW_ENDPOINT  — full chat-completions URL of the proxy/provider
                         (OpenAI-style `/v1/chat/completions` assumed by default)
    OPENCLAW_API_KEY   — bearer token
    OPENCLAW_MODEL     — model name (e.g. "gemini-2.0-flash")

Until those are set, `is_configured()` returns False and `ask()` raises
`CloudLLMNotConfigured` with a clear message. Command code should call
`is_configured()` first and degrade gracefully (tell the user the AI backend
isn't set up yet) rather than crashing — see `safe_ask()` for a helper that
does exactly that.

Design note: the endpoint *format* (OpenAI-style chat/completions vs native
Gemini `:generateContent`) was left open in TELEMETRY_PLAN.md. We default to
the OpenAI-style shape because Openclaw-style proxies expose that, and gate it
behind `OPENCLAW_API_STYLE` so switching to native Gemini later is a config
change, not a code change.
"""

from __future__ import annotations

import os


class CloudLLMNotConfigured(RuntimeError):
    """Raised when an LLM call is attempted before the cloud backend is set up."""


def _cfg() -> dict[str, str | None]:
    return {
        "endpoint": os.getenv("OPENCLAW_ENDPOINT"),
        "api_key": os.getenv("OPENCLAW_API_KEY"),
        "model": os.getenv("OPENCLAW_MODEL"),
        "style": os.getenv("OPENCLAW_API_STYLE", "openai"),
        "timeout": float(os.getenv("OPENCLAW_TIMEOUT", "30")),
    }


def is_configured() -> bool:
    """True only if endpoint, key, and model are all present."""
    c = _cfg()
    return bool(c["endpoint"] and c["api_key"] and c["model"])


_NOT_CONFIGURED_MSG = (
    "The AI backend isn't configured yet. Set OPENCLAW_ENDPOINT, "
    "OPENCLAW_API_KEY, and OPENCLAW_MODEL in the bot's .env to enable "
    "LLM-powered answers."
)


def ask(
    prompt: str,
    *,
    system: str | None = None,
    temperature: float = 0.4,
    max_tokens: int = 800,
) -> str:
    """Send a single-turn prompt to the configured cloud LLM and return the text.

    Raises CloudLLMNotConfigured if the backend isn't set up. Network/HTTP
    errors propagate as the underlying exception (callers that want a friendly
    message should use `safe_ask`).
    """
    if not is_configured():
        raise CloudLLMNotConfigured(_NOT_CONFIGURED_MSG)

    import requests  # local import: only needed when actually calling out

    c = _cfg()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    if c["style"] == "openai":
        resp = requests.post(
            c["endpoint"],
            headers={
                "Authorization": f"Bearer {c['api_key']}",
                "Content-Type": "application/json",
            },
            json={
                "model": c["model"],
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=c["timeout"],
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    # Native Gemini :generateContent shape (used if OPENCLAW_API_STYLE=gemini).
    if c["style"] == "gemini":
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system:
            body["system_instruction"] = {"parts": [{"text": system}]}
        resp = requests.post(
            f"{c['endpoint']}?key={c['api_key']}",
            headers={"Content-Type": "application/json"},
            json=body,
            timeout=c["timeout"],
        )
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

    raise CloudLLMNotConfigured(
        f"Unknown OPENCLAW_API_STYLE={c['style']!r}; expected 'openai' or 'gemini'."
    )


def safe_ask(prompt: str, **kwargs) -> str:
    """Like `ask`, but returns a user-facing message instead of raising when
    the backend isn't configured. Use this from command handlers."""
    if not is_configured():
        return f"⚠️ {_NOT_CONFIGURED_MSG}"
    return ask(prompt, **kwargs)
