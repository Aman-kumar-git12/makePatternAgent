# Complexity agent

A small REST service that reviews code **only for complexity**: its time and space complexity, why, and whether a faster or leaner approach exists. It uses an LLM with **your own API key** and does nothing else.

## Run it

```bash
cd agent
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python app.py            # http://127.0.0.1:8001
```

Open http://127.0.0.1:8001, choose a provider, paste your API key and code, and click **Analyse complexity**. The Coding Journey extension uses the same API (Settings → Complexity agent).

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

Any model the provider offers can be used by passing `model`. Providers retire models over time: when a **default** model is gone, the agent asks the provider which models your key can use and retries once with a suitable one (the response's `model` says which). A model you typed yourself is never swapped; the error lists the available ones instead. `GET /api/models?provider=groq` (with your key) lists them too.

## API

| Method | Path | Description |
|---|---|---|
| GET | `/health` | `{"status": "ok"}` |
| GET | `/api/providers` | Provider list (id, name, tier, default model, key URL) |
| GET | `/api/models?provider=…` | Chat models your key can use on that provider |
| POST | `/api/analyze` | Analyse code |
| GET | `/docs` | Interactive OpenAPI docs |

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

Request body: `provider`, `code` (required, up to 20,000 characters), and optional `model`, `language`, `title`. The key goes in `X-API-Key` (or `Authorization: Bearer …`). Errors return `{"detail": "..."}` with 400 (bad provider/model), 401 (missing or rejected key), 422 (not code / invalid input), 429 (rate limited), 502/504 (provider failure or timeout).

## Privacy

- Your key is used for that one request to the provider you picked. The agent never stores or logs it and never returns it.
- Code is sent only to the chosen provider (or stays on your machine with Ollama).
- The server listens on `127.0.0.1` by default, so only your computer can reach it.
- Keys in `.env` are an optional fallback for your own use; leave them out when others use the agent.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

Tests mock every provider; no keys or network are needed.
