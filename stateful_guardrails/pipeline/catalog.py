"""pipeline.catalog — 정책 레지스트리 + baseline 정의.

ISC-1.3: sgr catalog → 각 정책에 (category, stateless|stateful) 태그 출력.
ISC-1.5: sgr catalog --baselines → B1·B1.5(필수) + B2(가산) 등록 확인.

레이어 규칙: core + pipeline 내부 import 가능. interfaces import 금지.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from stateful_guardrails.core.policy import Policy, RiskCategory
from stateful_guardrails.pipeline.policies import (
    LLMClassifyEscalationPolicy,
    RuleKeywordEscalationPolicy,
)


# ---------------------------------------------------------------------------
# 정책 레지스트리
# ---------------------------------------------------------------------------

# 싱글턴 인스턴스 — 카탈로그 수명 동안 재사용.
# LLMClassifyEscalationPolicy는 어댑터를 지연 초기화하므로 여기서 생성해도 네트워크 호출 없음.
_POLICY_REGISTRY: list[Policy] = [
    RuleKeywordEscalationPolicy(),
    LLMClassifyEscalationPolicy(),
]


def get_all_policies() -> list[Policy]:
    """등록된 전체 정책 목록을 반환한다."""
    return list(_POLICY_REGISTRY)


def get_stateless_policies() -> list[Policy]:
    """stateless 정책(session_state 불참조)만 반환한다."""
    return [p for p in _POLICY_REGISTRY if not p.is_stateful]


def get_stateful_policies() -> list[Policy]:
    """stateful 정책(session_state 참조)만 반환한다. Phase 2+에서 채워진다."""
    return [p for p in _POLICY_REGISTRY if p.is_stateful]


# ---------------------------------------------------------------------------
# Baseline 정의 (A.2.5)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BaselineSpec:
    """Baseline 스펙. 동결 파라미터 포함.

    id: "B1" | "B1.5" | "B2"
    mode: "per_turn" | "sliding_window" | "full_session"
    window_size: K (B1.5 only), None otherwise
    required: True=필수, False=가산(ISC 보존·컷 가능)
    """
    id: str
    name: str
    description: str
    mode: Literal["per_turn", "sliding_window", "full_session"]
    window_size: int | None  # K for B1.5
    required: bool
    note: str = ""


# 동결 파라미터 K=5 잠정 기본값. calibration 단계에서 확정 가능.
# PLAN A.2.5: "K는 동결 파라미터 — 잠정 기본값(예: K=5)을 명시하고
#              calibration 단계에서 확정 가능하게."
DEFAULT_WINDOW_SIZE_K: int = 5

BASELINES: list[BaselineSpec] = [
    BaselineSpec(
        id="B1",
        name="per-turn stateless (max)",
        mode="per_turn",
        window_size=None,
        required=True,
        description=(
            "각 메시지를 독립 판정, session_state=None으로 공짜 산출. "
            "전 정책 per-turn risk의 최대값을 세션 점수로 사용. "
            "별도 예산·구현 없이 동일 코드 경로 재사용."
        ),
        note="session_state=None → 동일 코드 경로. 추가 구현 비용 0.",
    ),
    BaselineSpec(
        id="B1.5",
        name=f"sliding-window stateless (window=K={DEFAULT_WINDOW_SIZE_K})",
        mode="sliding_window",
        window_size=DEFAULT_WINDOW_SIZE_K,
        required=True,
        description=(
            f"최근 K={DEFAULT_WINDOW_SIZE_K}턴만 judge에 투입. online·O(K) 저비용. "
            "사활 경쟁자: 누적식 S_t=clip(λ·S_{t-1}+signal,0,S_max)는 EWMA(손실 압축)이므로 "
            "'stateful은 sliding-window의 손실 압축' 반론을 B1.5가 방어한다. "
            "K 이내에서는 B1.5 ≈ STATEFUL (정직 보고 대상). "
            "STATEFUL의 잔여 우위는 무한 룩백·O(1) 상태·세션 경계 처리."
        ),
        note=f"K={DEFAULT_WINDOW_SIZE_K} 잠정 기본값. calibration.json에서 확정.",
    ),
    BaselineSpec(
        id="B2",
        name="full-session long-context judge (오프라인 상한선)",
        mode="full_session",
        window_size=None,
        required=False,  # [가산] — B1.5만으로 thesis 성립
        description=(
            "전체 세션을 한 번에 long-context judge에 투입해 판정. "
            "별도 경로·별도 예산·별도 구현 필요 (session_state=None으로 공짜 아님). "
            "오프라인 상한선(upper bound) 참조군. "
            "STATEFUL이 B2와 대등/열위여도 서사 붕괴 아님 — "
            "정당성은 'B2의 1/N 비용·고정윈도우·online·무한룩백'."
        ),
        note="[가산] Phase 2에서 별도 구현. ISC 보존.",
    ),
]


def get_baselines(include_optional: bool = True) -> list[BaselineSpec]:
    """등록된 baseline 목록을 반환한다.

    include_optional=False 시 필수(required=True) baseline만 반환.
    """
    if include_optional:
        return list(BASELINES)
    return [b for b in BASELINES if b.required]


def get_required_baselines() -> list[BaselineSpec]:
    """필수(required=True) baseline만 반환한다."""
    return [b for b in BASELINES if b.required]
