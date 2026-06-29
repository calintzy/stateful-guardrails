"""core.llm — LLM 어댑터 추상 인터페이스.

core는 외부 I/O를 모른다. 구체 구현은 adapters에 위치한다.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMAdapter(Protocol):
    """Provider-agnostic LLM 호출 인터페이스.

    adapters 레이어에서 OpenAI / Anthropic / Ollama 구현을 제공한다.
    core는 이 Protocol만 의존하며 구체 클래스를 import하지 않는다.
    """

    provider: str  # "openai" | "anthropic" | "ollama"

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        """단일 텍스트 완성. 응답 문자열 반환."""
        ...

    def classify(self, text: str, labels: list[str], *, model: str | None = None) -> str:
        """텍스트를 labels 중 하나로 분류. 선택된 label 반환."""
        ...
