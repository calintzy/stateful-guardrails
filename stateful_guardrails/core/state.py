"""core.state — 누적 longitudinal 상태 갱신 + 상태 저장소 추상 인터페이스.

핵심 누적식 (PLAN P0-3, 동결 파라미터):
    S_t = clip(λ·S_{t-1} + signal_t, 0, S_max)

레이어 규칙: stdlib만 import. 파일 I/O는 StateStore 구현(adapters)에 위임.
core는 저장 매체를 모른다 (D-1).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from stateful_guardrails.core.policy import SessionState


def update_cumulative(
    prev: float,
    signal: float,
    lambda_decay: float,
    s_max: float,
) -> float:
    """EWMA 누적 갱신: S_t = clip(λ·S_{t-1} + signal_t, 0, S_max).

    prev: S_{t-1} (직전 누적 점수)
    signal: signal_t (현재 턴 detector 출력, 0~1)
    lambda_decay: λ 감쇠 계수 (동결 파라미터)
    s_max: 누적 상한 (동결 파라미터)

    EWMA(손실 압축)이므로 "stateful은 sliding-window의 손실 압축" 반론의 대상.
    STATEFUL의 잔여 우위는 무한 룩백(K턴 밖 신호 보존)·O(1) 상태에서 나온다.
    """
    return max(0.0, min(lambda_decay * prev + signal, s_max))


def apply_signal(
    state: SessionState,
    detector_id: str,
    signal: float,
) -> float:
    """SessionState에 detector 신호를 한 턴 누적하고 갱신된 S_t를 반환한다.

    state.policy_scores[detector_id]에 누적 점수를 저장한다.
    state.lambda_decay·state.s_max를 동결 파라미터로 사용한다.
    """
    prev = state.policy_scores.get(detector_id, 0.0)
    new = update_cumulative(prev, signal, state.lambda_decay, state.s_max)
    state.policy_scores[detector_id] = new
    state.turn_count += 1
    return new


@runtime_checkable
class StateStore(Protocol):
    """세션 상태 영속화 인터페이스 (D-1). 구현은 adapters에 위치.

    프로세스 재시작 후에도 SessionState를 복원할 수 있어야 한다 (ISC-2.2).
    """

    def get(self, session_id: str) -> SessionState | None:
        """세션 상태를 로드한다. 없으면 None."""
        ...

    def put(self, state: SessionState) -> None:
        """세션 상태를 영속화한다."""
        ...
