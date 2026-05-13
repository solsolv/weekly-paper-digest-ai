"""provider 팩토리: config.yaml의 llm 설정으로 LLMProvider 인스턴스를 만든다."""
from __future__ import annotations

from ..config import Config
from .base import LLMProvider


def build_provider(cfg: Config) -> LLMProvider:
    provider_name = cfg.get("llm.provider", "claude")
    common = {
        "temperature": float(cfg.get("llm.temperature", 0.3)),
        "max_tokens": int(cfg.get("llm.max_output_tokens", 1200)),
    }
    pcfg = cfg.get(f"llm.{provider_name}", {}) or {}

    if provider_name == "claude":
        from .claude import ClaudeProvider

        return ClaudeProvider(
            model=pcfg.get("model", "claude-sonnet-4-6"),
            api_key_env=pcfg.get("api_key_env", "ANTHROPIC_API_KEY"),
            **common,
        )
    if provider_name == "openai_compat":
        from .openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(
            model=pcfg.get("model", "gpt-4o-mini"),
            base_url=pcfg.get("base_url", "https://api.openai.com/v1"),
            api_key_env=pcfg.get("api_key_env", "OPENAI_API_KEY"),
            **common,
        )
    if provider_name == "ollama":
        from .ollama import OllamaProvider

        return OllamaProvider(
            model=pcfg.get("model", "llama3.1:8b"),
            host=pcfg.get("host", "http://localhost:11434"),
            **common,
        )
    raise ValueError(f"알 수 없는 llm.provider: {provider_name!r} (claude|openai_compat|ollama 중 하나)")


__all__ = ["LLMProvider", "build_provider"]
