"""Anthropic Claude provider (기본)."""
from __future__ import annotations

from ..config import env
from .base import LLMProvider


class ClaudeProvider(LLMProvider):
    name = "claude"

    def __init__(self, *, model: str, api_key_env: str = "ANTHROPIC_API_KEY", **kw):
        super().__init__(model=model, **kw)
        api_key = env(api_key_env)
        if not api_key:
            raise RuntimeError(
                f"환경변수 {api_key_env} 가 설정되지 않았습니다. Claude API 키를 등록하세요."
            )
        try:
            import anthropic  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("`anthropic` 패키지가 필요합니다: pip install anthropic") from exc
        self._client = anthropic.Anthropic(api_key=api_key)

    def generate(self, system: str, prompt: str) -> str:
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [block.text for block in msg.content if getattr(block, "type", "") == "text"]
        return "\n".join(parts).strip()
