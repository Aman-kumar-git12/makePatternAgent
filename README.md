# MakePattern Complexity Agent

A small REST service that reviews code **only for complexity**. For each piece of code it gives the time and space complexity, a short reason for each, and a verdict on whether the solution is already optimal. It calls a large language model (LLM) from the provider you choose, using **your own API key**.

It powers the **AI review** in the [Coding Journey extension](../frontend/extension/README.md) and also has its own web page for pasting code.

- **Bring your own key.** Your key is used for that one request only; the agent never stores, logs or returns it.
- **13 providers.** Seven have free tiers, five are paid, and Ollama runs a model on your own machine with no key.
- **Only talks about complexity.** It never comments on readability or style, and never follows instructions hidden in the code.
- **Survives model retirements.** If a provider retires the default model, the agent picks a model your key can still use and retries.

## Contents

- [Quick start](#quick-start)
- [Providers](#providers)
- [How it works](#how-it-works)
- [API reference](#api-reference)
- [Configuration](#configuration)
- [Security and privacy](#security-and-privacy)
- [Testing](#testing)
- [Project structure](#project-structure)
- [Troubleshooting](#troubleshooting)

## Quick start

Requirements: Python 3.10 or newer.

```bash
cd agent
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py                     # http://127.0.0.1:8001
```

Then use it in one of two ways:

- **In the browser:** open http://127.0.0.1:8001, pick a provider, paste your API key and code, and click **Analyse complexity**.
- **In the extension:** go to Settings → **AI code review**, pick the same provider and paste your key. Then open any analysis and click **Review with …**.

Stop the agent with `Ctrl+C`. Next time you only need `source venv/bin/activate` and `python app.py`.

## Providers

| Provider | Tier | Default model | Get a key |
|---|---|---|---|
| Groq (default) | Free | `openai/gpt-oss-120b` | https://console.groq.com/keys |
| Google Gemini | Free | `gemini-2.5-flash` | https://aistudio.google.com/apikey |
| OpenRouter | Free models | `meta-llama/llama-3.3-70b-instruct:free` | https://openrouter.ai/keys |
| Mistral | Free | `mistral-small-latest` | https://console.mistral.ai/api-keys |
| Cerebras | Free | `llama-3.3-70b` | https://cloud.cerebras.ai |
| GitHub Models | Free (GitHub token) | `openai/gpt-4.1-mini` | https://github.com/settings/tokens |
| Hugging Face | Free | `meta-llama/Llama-3.3-70B-Instruct` | https://huggingface.co/settings/tokens |
| OpenAI | Paid | `gpt-4.1-mini` | https://platform.openai.com/api-keys |
| Anthropic Claude | Paid | `claude-opus-5-5` | https://console.anthropic.com/settings/keys |
| DeepSeek | Paid | `deepseek-chat` | https://platform.deepseek.com/api_keys |
| xAI Grok | Paid | `grok-3-mini` | https://console.x.ai |
| Together AI | Paid | `meta-llama/Llama-3.3-70B-Instruct-Turbo` | https://api.together.ai/settings/api-keys |
| Ollama | Local, no key | `llama3.2` | https://ollama.com/download |

You can use any other model a provider offers by sending its name in the `model` field.

Free-tier limits and model names are set by each provider and change often. When a **default** model has been retired, the agent asks the provider which models your key can use and retries once with a suitable one; the response's `model` field shows which model answered. A model you typed yourself is never swapped: the error lists the available models instead, and `GET /api/models` lists them too.

For Ollama, install it, run `ollama pull llama3.2`, and keep `ollama serve` running.

## How it works

```
 extension / web page / curl
            │  POST /api/analyze   X-API-Key: <your key>
            ▼
 ┌──────────────────────────────┐
 │ complexity agent (FastAPI)   │  validates input, rate-limits per client
 │  api.py → analyzer.py        │  builds the prompt (prompt.py)
 └─────────────┬────────────────┘
               │ OpenAI-compatible /chat/completions   (12 providers, via httpx)
               │ Anthropic Messages API                (official anthropic SDK)
               ▼
        chosen LLM provider
               │ JSON answer
               ▼
 tolerant parser + validation → AnalyzeResponse
```

- **Providers.** Every provider except Anthropic speaks the OpenAI-compatible protocol, so one client handles them all. Anthropic uses the official SDK with structured JSON output, and on Opus and Sonnet models it enables automatic fallback to another Claude model if a request is declined.
- **Prompt.** The model is told to talk only about complexity and to treat the code as data. That means it won't obey instructions written in comments or strings.
- **Parsing.** Model output is parsed tolerantly: it handles `<think>` reasoning blocks, Markdown code fences and extra text around the JSON. The answer is checked against a schema before it is returned.
- **Not code.** If the input isn't source code, the agent returns a clear 422 error instead of guessing.

## API reference

Interactive OpenAPI docs are served at http://127.0.0.1:8001/docs.

| Method | Path | Description |
|---|---|---|
| GET | `/` | Web page for pasting a key and code |
| GET | `/health` | Liveness check, returns `{"status": "ok"}` |
| GET | `/api/providers` | Supported providers (id, name, tier, default model, models, key URL, whether a key is needed) |
| GET | `/api/models?provider=<id>` | Chat models your key can use on that provider |
| POST | `/api/analyze` | Review code for complexity |

### `POST /api/analyze`

Send your key in the `X-API-Key` header, or as `Authorization: Bearer <key>`. Ollama needs no key.

| Field | Type | Required | Notes |
|---|---|---|---|
| `provider` | string | no (default `groq`) | A provider id from `/api/providers` |
| `code` | string | yes | Up to 20,000 characters |
| `model` | string | no | Leave empty to use the provider's default |
| `language` | string | no | For example `python` or `cpp` |
| `title` | string | no | The problem name, which gives the model context |

```bash
curl -X POST http://127.0.0.1:8001/api/analyze \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $GROQ_API_KEY" \
  -d '{"provider": "groq", "code": "def f(a):\n    return sorted(a)"}'
```

```json
{
  "provider": "groq",
  "model": "openai/gpt-oss-120b",
  "time_complexity": "O(n log n)",
  "space_complexity": "O(n)",
  "time_explanation": "sorted() performs a comparison sort over the n elements.",
  "space_explanation": "sorted() builds a new list of n elements.",
  "variables": [{"name": "n", "meaning": "length of a"}],
  "is_optimal": true,
  "better_complexity": "",
  "suggestion": "Comparison sorting can't beat O(n log n), so this is optimal.",
  "confidence": "high"
}
```

When `is_optimal` is `false`, `better_complexity` holds the better bound (for example `"O(n) time, O(1) space"`) and `suggestion` names the technique that achieves it.

### Errors

Errors return `{"detail": "<message that can be shown to the user>"}`.

| Status | Meaning |
|---|---|
| 400 | Unknown provider, or the model isn't available (the message lists available models) |
| 401 | Missing key, or the provider rejected it |
| 422 | Invalid input (empty or over 20,000 characters), the input isn't code, or the model declined |
| 429 | The agent's or the provider's rate limit was reached |
| 502 | The provider failed, couldn't be reached, or returned an unusable answer |
| 504 | The provider took longer than 60 seconds |

## Configuration

All settings are optional. To change them, copy `.env.example` to `.env`.

| Variable | Default | Description |
|---|---|---|
| `AGENT_HOST` | `127.0.0.1` | Address to listen on. Keep it local unless you add your own authentication. |
| `AGENT_PORT` | `8001` | Port |
| `AGENT_RATE_LIMIT` | `30` | Requests per minute per client IP |
| `AGENT_CORS_ORIGINS` | none | Extra browser origins, comma-separated. Browser extensions and `http://localhost` / `http://127.0.0.1` on any port are always allowed. |
| `AGENT_RELOAD` | `false` | Auto-reload on code changes (development) |
| `GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`, `CEREBRAS_API_KEY`, `GITHUB_TOKEN`, `HF_TOKEN`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `XAI_API_KEY`, `TOGETHER_API_KEY` | none | Optional fallback keys, used only when a request sends no key. Leave them unset if other people use your agent. |

## Security and privacy

- **Keys:** a pasted key is sent only to the provider you chose, for that one request. It is never written to disk, logged or included in a response. Tests check that keys are never echoed back.
- **Code:** your code goes only to the chosen provider, or stays on your machine with Ollama.
- **Network:** the server listens on `127.0.0.1`, so other machines can't reach it. It has no authentication of its own, so don't expose it publicly as it is.
- **Browsers:** CORS (which websites' scripts may call the agent) is limited to browser extensions, localhost and any origins you list.
- **Limits:** inputs are capped at 20,000 characters and requests are rate-limited per client.
- **Web page:** it keeps your key only for the browser tab you're using, unless you tick **Remember the key in this browser**.

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

Every provider is mocked, so no keys or network access are needed. The tests cover:
- request building for the OpenAI-compatible providers and for Anthropic, including key headers and structured output
- mapping provider errors to the statuses above
- input validation and rate limiting
- the tolerant parser
- retired-model fallback and the models endpoint

CI runs them on every push (`.github/workflows/ci.yml`).

## Project structure

```
agent/
├── app.py                    # entry point: python app.py
├── complexity_agent/
│   ├── api.py                # FastAPI app and routes, CORS, rate limiting
│   ├── analyzer.py           # provider calls, error mapping, retired-model fallback
│   ├── prompt.py             # system prompt, JSON schema, tolerant parser
│   ├── providers.py          # the 13 providers (keep in sync with frontend/extension/src/lib/complexityAgent.ts)
│   └── config.py             # environment settings
├── static/index.html         # the paste-a-key web page
├── tests/test_api.py
├── requirements.txt          # runtime dependencies
├── requirements-dev.txt      # + pytest
├── pyproject.toml            # project metadata and pytest config
└── .env.example
```

To add a provider, add an entry to `PROVIDERS` in `providers.py` (OpenAI-compatible providers only need a base URL), mirror it in `frontend/extension/src/lib/complexityAgent.ts`, and add it to the table above.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Can't reach the complexity agent` in the extension | Start the agent with `python app.py` and check the URL in extension settings (default `http://127.0.0.1:8001`). |
| `Model '…' is not available` | The provider retired it. Clear the Model field to use the default, or choose a model listed in the error. |
| `… rejected the API key` | Check you pasted the key for the provider you selected. Some keys need billing enabled even for the free tier. |
| `Could not reach Ollama` | Run `ollama serve`, and `ollama pull <model>` for the model you chose. |
| `rate limit reached` | Wait a minute. Free tiers limit requests per minute and per day. |
| Changes don't show up | Restart the agent after updating it. With `AGENT_RELOAD=true` it restarts on its own. |

## License

[MIT](../LICENSE), part of the [MakePattern](../README.md) monorepo. See [CONTRIBUTING.md](../CONTRIBUTING.md) to contribute.
