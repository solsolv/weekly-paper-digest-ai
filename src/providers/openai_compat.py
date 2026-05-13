"""OpenAI 호환 API provider (OpenAI / Together / Groq / vLLM / LM Studio 등)."""
from __future__ import annotations

from ..config import env
from .base import LLMProvider


class OpenAICompatProvider(LLMProvider):
    name = "openai_compat"

    def __init__(
        self,
        *,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        api_key_env: str = "OPENAI_API_KEY",
        **kw,
    ):
        super().__init__(model=model, **kw)
        api_key = env(api_key_env) or "not-needed"  # 로컬 서버는 키가 필요 없을 수 있음
        try:
            from openai import OpenAI  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("`openai` 패키지가 필요합니다: pip install openai") from exc
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def generate(self, system: str, prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return (resp.choices[0].message.content or "").strip()
