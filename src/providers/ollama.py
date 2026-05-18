"""로컬 LLM provider — Ollama (http://localhost:11434)."""
from __future__ import annotations

import requests

from .base import LLMProvider


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(
        self,
        *,
        model: str,
        host: str = "http://localhost:11434",
        think: bool = False,
        **kw,
    ):
        super().__init__(model=model, **kw)
        self.host = host.rstrip("/")
        # Qwen3 등 reasoning 모델은 기본적으로 thinking에 토큰을 소진해 content가 비어
        # 나오는 경우가 잦다. 요약 태스크에선 think=False가 안전한 기본값.
        # 비추론 모델에는 Ollama가 이 필드를 그냥 무시한다.
        self.think = think

    def generate(self, system: str, prompt: str) -> str:
        resp = requests.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "stream": False,
                "think": self.think,
                "options": {
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                },
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=600,
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data.get("message", {}) or {}
        content = (msg.get("content") or "").strip()
        # 안전망: think=True인데 content가 비고 thinking만 채워졌으면 thinking을 사용
        if not content and msg.get("thinking"):
            content = str(msg["thinking"]).strip()
        return content
