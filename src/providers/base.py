"""LLM provider 추상 인터페이스."""
from __future__ import annotations

import abc


class LLMProvider(abc.ABC):
    """요약 생성을 담당하는 provider. 구현체는 generate()만 채우면 된다."""

    name: str = "base"

    def __init__(self, *, model: str, temperature: float = 0.3, max_tokens: int = 1200):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    @abc.abstractmethod
    def generate(self, system: str, prompt: str) -> str:
        """system 지시 + 사용자 프롬프트를 받아 생성 텍스트를 반환."""
        raise NotImplementedError
