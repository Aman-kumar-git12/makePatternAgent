"""Supported LLM providers.

Every provider except Anthropic speaks the OpenAI-compatible `/chat/completions` protocol, so one
client handles them all. Keep this list in sync with frontend/extension/src/lib/complexityAgent.ts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Tier = Literal["free", "paid", "local"]
Protocol = Literal["openai", "anthropic"]


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    tier: Tier
    default_model: str
    key_url: str
    base_url: str = ""
    protocol: Protocol = "openai"
    needs_key: bool = True
    # Whether the endpoint accepts `response_format: {"type": "json_object"}`.
    json_mode: bool = True
    # Environment variable the agent falls back to when no key is sent with the request.
    env_key: str = ""
    models: tuple[str, ...] = field(default_factory=tuple)

    def public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "tier": self.tier,
            "default_model": self.default_model,
            "models": list(self.models or (self.default_model,)),
            "key_url": self.key_url,
            "needs_key": self.needs_key,
        }


PROVIDERS: dict[str, Provider] = {
    p.id: p
    for p in [
        # ---- Free tiers ------------------------------------------------------------------
        Provider(
            # Groq retired llama-3.3-70b-versatile in Aug 2026 and recommends gpt-oss-120b.
            "groq", "Groq", "free", "openai/gpt-oss-120b", "https://console.groq.com/keys",
            base_url="https://api.groq.com/openai/v1", env_key="GROQ_API_KEY",
            models=("openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"),
        ),
        Provider(
            "gemini", "Google Gemini", "free", "gemini-2.5-flash", "https://aistudio.google.com/apikey",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai", env_key="GEMINI_API_KEY",
            models=("gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite"),
        ),
        Provider(
            "openrouter", "OpenRouter", "free", "meta-llama/llama-3.3-70b-instruct:free", "https://openrouter.ai/keys",
            base_url="https://openrouter.ai/api/v1", env_key="OPENROUTER_API_KEY", json_mode=False,
            models=("meta-llama/llama-3.3-70b-instruct:free", "deepseek/deepseek-chat-v3-0324:free"),
        ),
        Provider(
            "mistral", "Mistral", "free", "mistral-small-latest", "https://console.mistral.ai/api-keys",
            base_url="https://api.mistral.ai/v1", env_key="MISTRAL_API_KEY",
            models=("mistral-small-latest", "codestral-latest", "mistral-large-latest"),
        ),
        Provider(
            "cerebras", "Cerebras", "free", "llama-3.3-70b", "https://cloud.cerebras.ai",
            base_url="https://api.cerebras.ai/v1", env_key="CEREBRAS_API_KEY", json_mode=False,
        ),
        Provider(
            "github", "GitHub Models", "free", "openai/gpt-4.1-mini", "https://github.com/settings/tokens",
            base_url="https://models.github.ai/inference", env_key="GITHUB_TOKEN", json_mode=False,
            models=("openai/gpt-4.1-mini", "openai/gpt-4.1", "meta/Llama-3.3-70B-Instruct"),
        ),
        Provider(
            "huggingface", "Hugging Face", "free", "meta-llama/Llama-3.3-70B-Instruct", "https://huggingface.co/settings/tokens",
            base_url="https://router.huggingface.co/v1", env_key="HF_TOKEN", json_mode=False,
        ),
        # ---- Paid ------------------------------------------------------------------------
        Provider(
            "openai", "OpenAI", "paid", "gpt-4.1-mini", "https://platform.openai.com/api-keys",
            base_url="https://api.openai.com/v1", env_key="OPENAI_API_KEY",
            models=("gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"),
        ),
        Provider(
            "anthropic", "Anthropic Claude", "paid", "claude-opus-5-5", "https://console.anthropic.com/settings/keys",
            protocol="anthropic", env_key="ANTHROPIC_API_KEY",
            models=("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"),
        ),
        Provider(
            "deepseek", "DeepSeek", "paid", "deepseek-chat", "https://platform.deepseek.com/api_keys",
            base_url="https://api.deepseek.com/v1", env_key="DEEPSEEK_API_KEY",
        ),
        Provider(
            "xai", "xAI Grok", "paid", "grok-3-mini", "https://console.x.ai",
            base_url="https://api.x.ai/v1", env_key="XAI_API_KEY",
        ),
        Provider(
            "together", "Together AI", "paid", "meta-llama/Llama-3.3-70B-Instruct-Turbo", "https://api.together.ai/settings/api-keys",
            base_url="https://api.together.xyz/v1", env_key="TOGETHER_API_KEY",
        ),
        # ---- Local -----------------------------------------------------------------------
        Provider(
            "ollama", "Ollama (local)", "local", "llama3.2", "https://ollama.com/download",
            base_url="http://localhost:11434/v1", needs_key=False, env_key="",
        ),
    ]
}
