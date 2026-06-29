"""adapters.embeddings — bge-m3 임베딩 어댑터 (Ollama).

target-aware/target-agnostic detector가 사용하는 문장 임베딩을 제공한다.
in-memory 캐시로 동일 텍스트 재임베딩을 피한다 (재현성·속도).

레이어 규칙: 외부 I/O(httpx)는 adapters에서만.
"""

from __future__ import annotations

import os

import httpx

_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


class OllamaEmbedder:
    """Ollama bge-m3 임베딩 어댑터.

    embed(text) -> list[float] (1024차원).
    동일 텍스트는 캐시에서 반환해 결정성·재현성을 보장한다.
    """

    provider = "ollama"

    def __init__(
        self,
        model: str = "bge-m3",
        base_url: str = _OLLAMA_BASE_URL,
    ) -> None:
        self._model = model
        self._base_url = base_url
        self._cache: dict[str, list[float]] = {}

    @property
    def model(self) -> str:
        return self._model

    def embed(self, text: str) -> list[float]:
        """텍스트를 임베딩 벡터로 변환한다 (캐시 적용)."""
        if text in self._cache:
            return self._cache[text]
        payload = {"model": self._model, "prompt": text}
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{self._base_url}/api/embeddings", json=payload
            )
            response.raise_for_status()
            data = response.json()
            vec = data["embedding"]
        self._cache[text] = vec
        return vec
