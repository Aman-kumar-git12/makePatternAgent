import json

import httpx
import httpx2
import pytest

import anthropic
from complexity_agent import analyzer
from fastapi.testclient import TestClient

from complexity_agent.api import create_app
from complexity_agent.prompt import ParseError, parse_complexity

GOOD = {
    "is_code": True,
    "time_complexity": "O(n log n)",
    "space_complexity": "O(n)",
    "time_explanation": "Sorting dominates.",
    "space_explanation": "The sorted copy.",
    "variables": [{"name": "n", "meaning": "length of nums"}],
    "is_optimal": False,
    "better_complexity": "O(n) time",
    "suggestion": "Use a hash set instead of sorting.",
    "confidence": "high",
}
CODE = "def f(nums):\n    return sorted(nums)\n"


def make_client(handler):
    seen = []

    def wrapped(request: httpx.Request):
        seen.append(request)
        return handler(request)

    app = create_app(http_client=httpx.AsyncClient(transport=httpx.MockTransport(wrapped)))
    return TestClient(app), seen


def openai_reply(content: str, status: int = 200):
    return lambda req: httpx.Response(status, json={"choices": [{"message": {"content": content}}]})


def test_health_and_providers():
    client, _ = make_client(openai_reply("{}"))
    with client:
        assert client.get("/health").json() == {"status": "ok"}
        ids = {p["id"] for p in client.get("/api/providers").json()}
        assert {"groq", "gemini", "openrouter", "openai", "anthropic", "ollama"} <= ids
        assert client.get("/").status_code == 200


def test_groq_analysis_uses_pasted_key_and_default_model():
    client, seen = make_client(openai_reply(json.dumps(GOOD)))
    with client:
        r = client.post("/api/analyze", json={"provider": "groq", "code": CODE}, headers={"X-API-Key": "gsk_test"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["time_complexity"] == "O(n log n)" and body["model"] == "openai/gpt-oss-120b"
    assert body["is_optimal"] is False and body["better_complexity"] == "O(n) time" and "hash set" in body["suggestion"]
    req = seen[0]
    assert str(req.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer gsk_test"
    sent = json.loads(req.content)
    assert sent["response_format"] == {"type": "json_object"}
    assert "<code>" in sent["messages"][1]["content"]
    assert "gsk_test" not in r.text  # the key is never echoed


def test_bearer_header_and_custom_model():
    client, seen = make_client(openai_reply(json.dumps(GOOD)))
    with client:
        r = client.post(
            "/api/analyze",
            json={"provider": "openrouter", "model": "x/y:free", "code": CODE},
            headers={"Authorization": "Bearer or-key"},
        )
    assert r.status_code == 200
    assert seen[0].headers["authorization"] == "Bearer or-key"
    assert "response_format" not in json.loads(seen[0].content)
    assert r.json()["model"] == "x/y:free"


def test_missing_key_is_401(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    client, seen = make_client(openai_reply("{}"))
    with client:
        r = client.post("/api/analyze", json={"provider": "groq", "code": CODE})
    assert r.status_code == 401 and not seen


def test_env_key_fallback(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "from-env")
    client, seen = make_client(openai_reply(json.dumps(GOOD)))
    with client:
        r = client.post("/api/analyze", json={"provider": "groq", "code": CODE})
    assert r.status_code == 200 and seen[0].headers["authorization"] == "Bearer from-env"


def test_ollama_needs_no_key():
    client, seen = make_client(openai_reply(json.dumps(GOOD)))
    with client:
        r = client.post("/api/analyze", json={"provider": "ollama", "code": CODE})
    assert r.status_code == 200
    assert "authorization" not in seen[0].headers
    assert str(seen[0].url).startswith("http://localhost:11434/v1/")


@pytest.mark.parametrize("upstream,expected", [(401, 401), (403, 401), (404, 400), (429, 429), (500, 502)])
def test_upstream_errors_are_mapped(upstream, expected):
    client, _ = make_client(openai_reply("", status=upstream))
    with client:
        r = client.post("/api/analyze", json={"provider": "groq", "code": CODE}, headers={"X-API-Key": "k"})
    assert r.status_code == expected
    assert "k" != r.json()["detail"]


def test_unknown_provider_and_validation():
    client, _ = make_client(openai_reply("{}"))
    with client:
        assert client.post("/api/analyze", json={"provider": "nope", "code": CODE}, headers={"X-API-Key": "k"}).status_code == 400
        assert client.post("/api/analyze", json={"provider": "groq", "code": ""}, headers={"X-API-Key": "k"}).status_code == 422
        big = "x" * 20_001
        assert client.post("/api/analyze", json={"provider": "groq", "code": big}, headers={"X-API-Key": "k"}).status_code == 422


def test_not_code_is_422():
    client, _ = make_client(openai_reply(json.dumps({"is_code": False})))
    with client:
        r = client.post("/api/analyze", json={"provider": "groq", "code": "hello there"}, headers={"X-API-Key": "k"})
    assert r.status_code == 422


def test_garbage_output_is_502():
    client, _ = make_client(openai_reply("I think it is quadratic."))
    with client:
        r = client.post("/api/analyze", json={"provider": "groq", "code": CODE}, headers={"X-API-Key": "k"})
    assert r.status_code == 502


def mock_anthropic(monkeypatch, handler):
    seen = []

    def wrapped(req):
        seen.append(req)
        return handler(req)

    monkeypatch.setattr(
        analyzer,
        "make_anthropic_client",
        lambda key: anthropic.AsyncAnthropic(
            api_key=key, max_retries=0, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(wrapped))
        ),
    )
    return seen


def test_anthropic_uses_sdk_with_structured_output_and_fallbacks(monkeypatch):
    def handler(req):
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": json.dumps(GOOD)}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10},
        })

    seen = mock_anthropic(monkeypatch, handler)
    client, _ = make_client(openai_reply("{}"))
    with client:
        r = client.post("/api/analyze", json={"provider": "anthropic", "code": CODE}, headers={"X-API-Key": "sk-ant-x"})
    assert r.status_code == 200, r.text
    req = seen[0]
    assert req.url.host == "api.anthropic.com" and req.headers["authorization"] == "Bearer sk-ant-x"
    assert "server-side-fallback-2026-07-01" in req.headers["anthropic-beta"]
    sent = json.loads(req.content)
    assert sent["model"] == "claude-opus-5-5" and sent["fallbacks"] == "default"
    assert sent["output_config"]["format"]["type"] == "json_schema"


def test_anthropic_auth_error(monkeypatch):
    mock_anthropic(monkeypatch, lambda req: httpx2.Response(401, json={"type": "error", "error": {"type": "authentication_error", "message": "bad"}}))
    client, _ = make_client(openai_reply("{}"))
    with client:
        r = client.post("/api/analyze", json={"provider": "anthropic", "model": "claude-haiku-5-5", "code": CODE}, headers={"X-API-Key": "bad"})
    assert r.status_code == 401


def test_parser_tolerates_think_and_fences():
    text = "<think>hmm {not json}</think>\nHere you go:\n```json\n" + json.dumps(GOOD) + "\n```"
    assert parse_complexity(text).time_complexity == "O(n log n)"
    assert parse_complexity("prefix " + json.dumps({**GOOD, "confidence": "HIGH"}) + " suffix").confidence == "high"
    with pytest.raises(ParseError):
        parse_complexity('{"time_complexity": ""}')


def test_rate_limit(monkeypatch):
    client, _ = make_client(openai_reply(json.dumps(GOOD)))
    with client:
        client.app.state.limiter.per_minute = 2
        codes = [client.post("/api/analyze", json={"provider": "groq", "code": CODE}, headers={"X-API-Key": "k"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_optimal_clears_better_complexity_and_old_models_default():
    reply = {**GOOD, "is_optimal": True, "better_complexity": "should be dropped"}
    client, _ = make_client(openai_reply(json.dumps(reply)))
    with client:
        r = client.post("/api/analyze", json={"provider": "groq", "code": CODE}, headers={"X-API-Key": "k"})
    assert r.json()["is_optimal"] is True and r.json()["better_complexity"] == ""
    # A model that leaves out the review fields still gives a usable answer.
    minimal = {k: GOOD[k] for k in ("time_complexity", "space_complexity", "time_explanation", "space_explanation")}
    assert parse_complexity(json.dumps(minimal)).suggestion == ""


def retired_then_ok(available):
    """Groq-style: the first chat call says the model is decommissioned, /models lists what's left."""
    calls = {"chat": 0}

    def handler(req: httpx.Request):
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"object": "list", "data": [{"id": m} for m in available]})
        calls["chat"] += 1
        body = json.loads(req.content)
        if calls["chat"] == 1:
            return httpx.Response(400, json={"error": {"code": "model_decommissioned", "message": f"The model `{body['model']}` has been decommissioned"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(GOOD)}}]})

    return handler


def test_retired_default_model_falls_back_to_an_available_one():
    client, seen = make_client(retired_then_ok(["whisper-large-v3", "meta-llama/llama-guard-4-12b", "qwen/qwen3.6-27b", "openai/gpt-oss-20b"]))
    with client:
        r = client.post("/api/analyze", json={"provider": "groq", "code": CODE}, headers={"X-API-Key": "k"})
    assert r.status_code == 200, r.text
    assert r.json()["model"] == "openai/gpt-oss-20b"  # known-good list order, never whisper/guard
    assert [json.loads(q.content)["model"] for q in seen if q.method == "POST"] == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]


def test_a_model_the_user_typed_is_not_swapped():
    client, seen = make_client(retired_then_ok(["openai/gpt-oss-120b", "qwen/qwen3.6-27b"]))
    with client:
        r = client.post("/api/analyze", json={"provider": "groq", "model": "old-model", "code": CODE}, headers={"X-API-Key": "k"})
    assert r.status_code == 400
    assert "old-model" in r.json()["detail"] and "openai/gpt-oss-120b" in r.json()["detail"]
    assert sum(1 for q in seen if q.method == "POST") == 1


def test_models_endpoint_lists_chat_models():
    client, seen = make_client(retired_then_ok(["whisper-large-v3", "openai/gpt-oss-120b"]))
    with client:
        r = client.get("/api/models", params={"provider": "groq"}, headers={"X-API-Key": "k"})
        assert client.get("/api/models", params={"provider": "nope"}).status_code == 400
    assert r.json() == {"provider": "groq", "models": ["openai/gpt-oss-120b"]}
    assert seen[0].headers["authorization"] == "Bearer k"


def test_pick_model_prefers_known_then_families():
    from complexity_agent.analyzer import pick_model
    from complexity_agent.providers import PROVIDERS

    assert pick_model(PROVIDERS["cerebras"], ["foo-8b", "llama-4-scout", "bar"]) == "llama-4-scout"
    assert pick_model(PROVIDERS["groq"], ["openai/gpt-oss-120b"], exclude="openai/gpt-oss-120b") is None
