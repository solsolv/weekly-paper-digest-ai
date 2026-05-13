"""로컬 LLM provider — Ollama (http://localhost:11434)."""
from __future__ import annotations

import requests

from .base import LLMProvider


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, *, model: str, host: str = "http://localhost:11434", **kw):
        super().__init__(model=model, **kw)
        self.host = host.rstrip("/")

    def generate(self, system: str, prompt: str) -> str:
        resp = requests.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "stream": False,
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
        return (data.get("message", {}).get("content") or "").strip()
