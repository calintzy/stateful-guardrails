"""adapters.llm — LLM provider 구현체.

core.llm.LLMAdapter Protocol을 구현한다.
현재 Phase 0: OllamaAdapter만 동작 구현. OpenAI/Anthropic는 스텁.
"""

from __future__ import annotations

import json
import os

import httpx

from stateful_guardrails.core.llm import LLMAdapter  # noqa: F401 (Protocol 참조)


_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


class OllamaAdapter:
    """Ollama 로컬 서버 어댑터."""

    provider = "ollama"

    def __init__(self, model: str = "qwen2.5:14b", base_url: str = _OLLAMA_BASE_URL) -> None:
        self._model = model
        self._base_url = base_url

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        """Ollama /api/generate 엔드포인트 호출. 스트리밍 비활성화."""
        target_model = model or self._model
        payload = {"model": target_model, "prompt": prompt, "stream": False}
        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{self._base_url}/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
            return data["response"].strip()

    def classify(self, text: str, labels: list[str], *, model: str | None = None) -> str:
        """텍스트를 labels 중 하나로 분류."""
        label_str = ", ".join(f'"{lb}"' for lb in labels)
        prompt = (
            f"다음 텍스트를 아래 레이블 중 하나로만 분류하라. 레이블 이름만 출력하고 다른 설명은 금지.\n"
            f"레이블: {label_str}\n"
            f"텍스트: {text}"
        )
        result = self.complete(prompt, model=model)
        # 레이블 중 일치하는 것을 찾아 반환; 없으면 첫 번째 반환
        for lb in labels:
            if lb.lower() in result.lower():
                return lb
        return labels[0]


class OpenAIAdapter:
    """OpenAI API 어댑터 (Phase 0 스텁)."""

    provider = "openai"

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        raise NotImplementedError("OpenAI 어댑터는 Phase 1 이후 구현 예정")

    def classify(self, text: str, labels: list[str], *, model: str | None = None) -> str:
        raise NotImplementedError("OpenAI 어댑터는 Phase 1 이후 구현 예정")


class AnthropicAdapter:
    """Anthropic API 어댑터 (Phase 0 스텁)."""

    provider = "anthropic"

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        raise NotImplementedError("Anthropic 어댑터는 Phase 1 이후 구현 예정")

    def classify(self, text: str, labels: list[str], *, model: str | None = None) -> str:
        raise NotImplementedError("Anthropic 어댑터는 Phase 1 이후 구현 예정")


def get_adapter(provider: str, **kwargs) -> OllamaAdapter | OpenAIAdapter | AnthropicAdapter:
    """provider 이름으로 어댑터 인스턴스를 반환한다."""
    match provider.lower():
        case "ollama":
            return OllamaAdapter(**kwargs)
        case "openai":
            return OpenAIAdapter(**kwargs)
        case "anthropic":
            return AnthropicAdapter(**kwargs)
        case _:
            raise ValueError(f"지원하지 않는 provider: {provider!r}")
