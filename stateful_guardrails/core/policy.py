"""core.policy — Policy Protocol, PolicySignal, RiskCategory, Message.

레이어 규칙: stdlib만 import 가능. adapters/pipeline/interfaces/외부라이브러리 금지.
ISC-0.2 정적 검증 대상 파일.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


class RiskCategory(str, Enum):
    """MLCommons 14 카테고리 매핑 + 자체 확장 위험 분류.

    string 상속으로 JSON 직렬화·리포트 키 사용 가능.
    ID는 재번호 금지 (감사 로그·리포트의 안정적 참조 키).
    """
    # C1 누적 위기 에스컬레이션 — 약한 불만 누적 → 격분·환불/해지·이탈 선언
    ESCALATION = "escalation"
    # 고객 이탈(churn) 의사 신호 — 거래 중단 의향
    CHURN_INTENT = "churn_intent"
    # C2 오염된 고객 컨텍스트 기록 (Phase 2+)
    CONTEXT_CORRUPTION = "context_corruption"
    # C3 정상 해결 대화 (오탐 대조군)
    NORMAL = "normal"


class SuggestedAction(str, Enum):
    """정책이 권고하는 조치. 에스컬레이션 엔진의 1차 입력."""
    PASS = "pass"          # 봇 자동응대 — 위기 신호 없음
    FLAG = "flag"          # 상담사 이관 큐 (0→1 에스컬레이션 신호)
    BLOCK = "block"        # 강경 대응 보류 — 위기 도메인 미사용(레거시)
    ESCALATE = "escalate"  # 매니저·이탈방지팀 에스컬레이션 (위험도 2)


@dataclass
class Message:
    """단일 메시지. 세션 내 위치(turn_index)와 역할 포함.

    turn_index: 0-based 세션 내 순서.
    role: "user" | "assistant" | "system"
    """
    text: str
    role: str = "user"
    turn_index: int = 0


@dataclass
class SessionState:
    """세션 누적 상태. Phase 2에서 구체화.

    session_state=None → stateless 모드 (B1 baseline 경로, 공짜 산출).
    session_state 주입 → stateful 모드 (누적 상태 참조).

    policy_scores: 정책 ID → 누적 점수 (EWMA S_t 값).
    """
    session_id: str
    policy_scores: dict[str, float] = field(default_factory=dict)
    turn_count: int = 0
    # Phase 2: 감쇠 파라미터 (v1 기본값, calibration에서 확정)
    lambda_decay: float = 0.7
    s_max: float = 1.0


@dataclass
class PolicySignal:
    """정책 evaluate() 반환값. risk 0~1, 증거, 권고 조치.

    risk: 0.0(불만 없음) ~ 1.0(확실한 위기 신호). 이 범위를 항상 보장해야 한다.
    evidence: 탐지 근거 문자열 (감사 로그·리포트용, 비어도 됨).
    suggested_action: 이 신호 단독 기준 권고 조치.
    policy_id: 어느 정책에서 나온 신호인지 추적.
    """
    risk: float
    evidence: str
    suggested_action: SuggestedAction
    policy_id: str

    def __post_init__(self) -> None:
        if not (0.0 <= self.risk <= 1.0):
            raise ValueError(f"risk는 [0, 1] 범위여야 합니다: {self.risk}")


@runtime_checkable
class Policy(Protocol):
    """모든 정책이 따르는 계약 (D-4). stateless·stateful 모두 동일 인터페이스.

    session_state=None → stateless 모드 (B1 baseline: 각 메시지 독립 판정).
    session_state 주입 → stateful 모드 (누적 상태 참조, Phase 2+).

    계약 불변식:
    - evaluate()는 결정적이어야 한다 (같은 입력 → 같은 출력).
    - 반환 PolicySignal.risk는 항상 [0.0, 1.0].
    - id는 재번호 금지 (감사 로그·리포트의 안정적 키).
    """

    id: str              # 안정적 정책 ID — 재번호·재명명 금지
    category: RiskCategory
    is_stateful: bool    # False = stateless detector (session_state 불참조)

    def evaluate(
        self,
        message: Message,
        session_state: SessionState | None = None,
    ) -> PolicySignal:
        """메시지를 평가하고 risk signal을 반환한다.

        stateless 정책은 session_state를 무시한다.
        stateful 정책은 session_state에서 누적 신호를 읽고 갱신한다.
        """
        ...
