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

    import time

    import requests  # local import: only needed when actually calling out

    c = _cfg()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # Transient statuses worth a quick retry (Gemini is prone to 503 overloads).
    _TRANSIENT = {429, 500, 502, 503, 504}

    def _post_with_retry(url: str, headers: dict, json_body: dict):
        last = None
        for attempt in range(3):
            resp = requests.post(url, headers=headers, json=json_body, timeout=c["timeout"])
            if resp.status_code in _TRANSIENT:
                # Clean message (no URL/key) so it can't leak the API key upstream.
                last = requests.HTTPError(f"{resp.status_code} transient server error")
                time.sleep(1.5 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp
        raise last  # exhausted retries on a transient error

    if c["style"] == "openai":
        resp = _post_with_retry(
            c["endpoint"],
            {
                "Authorization": f"Bearer {c['api_key']}",
                "Content-Type": "application/json",
            },
            {
                "model": c["model"],
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        return resp.json()["choices"][0]["message"]["content"].strip()

    # Native Gemini :generateContent shape (used if OPENCLAW_API_STYLE=gemini).
    if c["style"] == "gemini":
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                # Disable hidden "thinking" (2.5 flash): thinking tokens count
                # against maxOutputTokens and can starve the visible answer,
                # yielding an empty response. Our chain-of-thought is prompt-driven
                # (the model writes its reasoning as normal output) so we don't
                # need the internal thinking budget.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        if system:
            body["system_instruction"] = {"parts": [{"text": system}]}
        resp = _post_with_retry(
            f"{c['endpoint']}?key={c['api_key']}",
            {"Content-Type": "application/json"},
            body,
        )
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError(
                "the model returned no answer (it may have been blocked by a safety filter)."
            )
        cand = candidates[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        if not text:
            reason = cand.get("finishReason", "unknown")
            raise RuntimeError(
                f"the model returned an empty answer (finishReason={reason}); try again."
            )
        return text

    raise CloudLLMNotConfigured(
        f"Unknown OPENCLAW_API_STYLE={c['style']!r}; expected 'openai' or 'gemini'."
    )


def safe_ask(prompt: str, **kwargs) -> str:
    """Like `ask`, but returns a user-facing message instead of raising when
    the backend isn't configured or when an HTTP error occurs."""
    if not is_configured():
        return f"⚠️ {_NOT_CONFIGURED_MSG}"
    try:
        return ask(prompt, **kwargs)
    except Exception as exc:
        # Strip the URL (which contains the API key) from the error message.
        msg = str(exc)
        if "http" in msg.lower() or "url" in msg.lower() or "key=" in msg.lower():
            return "⚠️ LLM request failed — check OPENCLAW credentials and model name in .env."
        return f"⚠️ LLM error: {msg}"
