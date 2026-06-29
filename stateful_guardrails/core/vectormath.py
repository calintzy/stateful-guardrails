"""core.vectormath — 순수 벡터 연산 (stdlib만 사용).

임베딩 드리프트 detector가 사용하는 코사인 유사도·센트로이드.
레이어 규칙: stdlib(math)만 import. 외부 라이브러리·다른 레이어 금지.
"""

from __future__ import annotations

import math


def cosine(a: list[float], b: list[float]) -> float:
    """두 벡터의 코사인 유사도. 영벡터면 0.0 반환."""
    if len(a) != len(b):
        raise ValueError(f"벡터 차원 불일치: {len(a)} != {len(b)}")
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def centroid(vectors: list[list[float]]) -> list[float]:
    """벡터 목록의 평균(센트로이드). 빈 목록이면 ValueError."""
    if not vectors:
        raise ValueError("빈 벡터 목록의 센트로이드는 정의되지 않음")
    dim = len(vectors[0])
    acc = [0.0] * dim
    for v in vectors:
        if len(v) != dim:
            raise ValueError("센트로이드 계산 중 차원 불일치")
        for i, x in enumerate(v):
            acc[i] += x
    n = len(vectors)
    return [x / n for x in acc]
