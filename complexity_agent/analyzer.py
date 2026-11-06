"""Calls the chosen provider with the user's own key and returns a parsed complexity analysis.

The API key is used for this one request only: it is never stored, logged or echoed back.
"""
from __future__ import annotations

import anthropic
import httpx

from .prompt import SCHEMA, SYSTEM, Complexity, ParseError, parse_complexity, user_message
from .providers import Provider

TIMEOUT_S = 60.0
# Room for reasoning models (e.g. gpt-oss), whose thinking counts toward this limit.
MAX_OUTPUT_TOKENS = 4000
# Claude models that accept server-side refusal fallbacks (`fallbacks: "default"`).
CLAUDE_FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"}


class AgentError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class ModelNotFound(AgentError):
    """The provider doesn't offer this model (any more), so another one can be tried."""

    def __init__(self, provider: Provider, model: str):
        super().__init__(400, f"Model '{model}' is not available on {provider.name} (it may have been retired).")
        self.model = model


_MISSING_MODEL_HINTS = ("model_not_found", "model_decommissioned", "decommissioned", "does not exist", "not found", "no longer supported")


def _is_missing_model(res: httpx.Response) -> bool:
    if res.status_code == 404:
        return True
    if res.status_code != 400:
        return False
    try:
        err = res.json().get("error", {})
        text = f"{err.get('code', '')} {err.get('type', '')} {err.get('message', '')}".lower()
    except (ValueError, AttributeError):
        text = res.text.lower()
    return "model" in text and any(h in text for h in _MISSING_MODEL_HINTS)


def _status_error(provider: Provider, status: int, model: str) -> AgentError:
    if status in (401, 403):
        return AgentError(401, f"{provider.name} rejected the API key (or it can't use {model}).")
    if status == 404:
        return ModelNotFound(provider, model)
    if status == 429:
        return AgentError(429, f"{provider.name} rate limit reached; try again in a minute.")
    if status == 400:
        return AgentError(400, f"{provider.name} rejected the request (check the model name).")
    return AgentError(502, f"{provider.name} returned an error ({status}).")


async def _openai_compatible(
    client: httpx.AsyncClient, provider: Provider, key: str, model: str, prompt: str
) -> str:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body: dict = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": MAX_OUTPUT_TOKENS,
    }
    if provider.json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        res = await client.post(f"{provider.base_url}/chat/completions", json=body, headers=headers, timeout=TIMEOUT_S)
    except httpx.TimeoutException as e:
        raise AgentError(504, f"{provider.name} took too long to answer.") from e
    except httpx.HTTPError as e:
        hint = " Is Ollama running (ollama serve)?" if provider.id == "ollama" else ""
        raise AgentError(502, f"Could not reach {provider.name}.{hint}") from e
    if res.status_code >= 400:
        if _is_missing_model(res):
            raise ModelNotFound(provider, model)
        raise _status_error(provider, res.status_code, model)
    try:
        return res.json()["choices"][0]["message"]["content"] or ""
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise AgentError(502, f"{provider.name} returned an unexpected response.") from e


def make_anthropic_client(key: str) -> anthropic.AsyncAnthropic:
    """One client per request (the key is per request). Tests replace this."""
    return anthropic.AsyncAnthropic(api_key=key, max_retries=1, timeout=TIMEOUT_S)


async def _anthropic(
    client: httpx.AsyncClient, provider: Provider, key: str, model: str, prompt: str
) -> str:
    # The Anthropic SDK has its own HTTP stack (httpx2), so `client` isn't used here.
    async with make_anthropic_client(key) as claude:
        return await _anthropic_call(claude, model, prompt)


async def _anthropic_call(claude: anthropic.AsyncAnthropic, model: str, prompt: str) -> str:
    params: dict = {
        "model": model,
        "max_tokens": 16000,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": prompt}],
        "output_config": {"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
    }
    try:
        if model in CLAUDE_FALLBACK_MODELS:
            msg = await claude.beta.messages.create(
                **params, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
            )
        else:
            msg = await claude.messages.create(**params)
    except anthropic.AuthenticationError as e:
        raise AgentError(401, "Anthropic rejected the API key.") from e
    except anthropic.PermissionDeniedError as e:
        raise AgentError(401, f"This Anthropic key can't use {model}.") from e
    except anthropic.NotFoundError as e:
        raise ModelNotFound(provider, model) from e
    except anthropic.RateLimitError as e:
        raise AgentError(429, "Anthropic rate limit reached; try again in a minute.") from e
    except anthropic.BadRequestError as e:
        raise AgentError(400, "Anthropic rejected the request (check the model name).") from e
    except anthropic.APITimeoutError as e:
        raise AgentError(504, "Anthropic took too long to answer.") from e
    except anthropic.APIConnectionError as e:
        raise AgentError(502, "Could not reach api.anthropic.com.") from e
    except anthropic.APIStatusError as e:
        raise AgentError(502, f"Anthropic returned an error ({e.status_code}).") from e
    if msg.stop_reason == "refusal":
        raise AgentError(422, "Claude declined to analyse this code.")
    if msg.stop_reason == "max_tokens":
        raise AgentError(502, "The analysis was cut off; try a shorter snippet.")
    return "".join(b.text for b in msg.content if b.type == "text")


# Model ids that are not chat models (speech, safety classifiers, embeddings, ...).
_NOT_CHAT = ("whisper", "tts", "guard", "embed", "orpheus", "playai", "moderation", "rerank", "vision", "image", "audio", "compound")
# Preferred families, best first, when picking a replacement model.
_PREFER = ("gpt-oss-120b", "70b", "gpt-oss", "qwen", "llama-4", "llama", "mistral", "gemma", "gpt-4")


async def list_models(client: httpx.AsyncClient, provider: Provider, key: str) -> list[str]:
    """Chat models this key can use, from the provider's OpenAI-compatible /models list."""
    if provider.protocol == "anthropic":
        return list(provider.models)
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        res = await client.get(f"{provider.base_url}/models", headers=headers, timeout=15.0)
    except httpx.HTTPError as e:
        raise AgentError(502, f"Could not list {provider.name} models.") from e
    if res.status_code >= 400:
        raise _status_error(provider, res.status_code, "the model list")
    try:
        data = res.json()
        items = data.get("data", data) if isinstance(data, dict) else data
        ids = [m["id"] if isinstance(m, dict) else str(m) for m in items]
    except (ValueError, KeyError, TypeError) as e:
        raise AgentError(502, f"{provider.name} returned an unexpected model list.") from e
    return [i for i in ids if isinstance(i, str) and not any(w in i.lower() for w in _NOT_CHAT)]


def pick_model(provider: Provider, available: list[str], exclude: str = "") -> str | None:
    """The best replacement: a known-good model first, then the preferred families."""
    pool = [m for m in available if m != exclude]
    for m in provider.models:
        if m in pool:
            return m
    for family in _PREFER:
        for m in pool:
            if family in m.lower():
                return m
    return pool[0] if pool else None


async def analyse_with_fallback(
    client: httpx.AsyncClient,
    provider: Provider,
    key: str,
    model: str,
    chosen_by_user: bool,
    code: str,
    language: str | None = None,
    title: str | None = None,
) -> tuple[str, Complexity]:
    """Like `analyse`, but if the default model was retired, retries once with an available one.

    A model the user typed explicitly is never swapped; the error lists what is available instead.
    Returns the model actually used and the result.
    """
    try:
        return model, await analyse(client, provider, key, model, code, language, title)
    except ModelNotFound as missing:
        try:
            available = await list_models(client, provider, key)
        except AgentError:
            raise missing from None
        if chosen_by_user:
            names = ", ".join(available[:6])
            hint = f" Available: {names}." if names else ""
            raise AgentError(400, f"{missing.message}{hint}") from None
        replacement = pick_model(provider, available, exclude=model)
        if not replacement:
            raise missing from None
        return replacement, await analyse(client, provider, key, replacement, code, language, title)


async def analyse(
    client: httpx.AsyncClient,
    provider: Provider,
    key: str,
    model: str,
    code: str,
    language: str | None = None,
    title: str | None = None,
) -> Complexity:
    prompt = user_message(code, language, title)
    call = _anthropic if provider.protocol == "anthropic" else _openai_compatible
    text = await call(client, provider, key, model, prompt)
    try:
        result = parse_complexity(text)
    except ParseError as e:
        raise AgentError(502, f"{e} Try again or pick another model.") from e
    if not result.is_code:
        raise AgentError(422, "That doesn't look like source code.")
    return result
