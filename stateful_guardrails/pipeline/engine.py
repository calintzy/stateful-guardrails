"""pipeline.engine — stateful 판정 엔진. B1 / B1.5 / STATEFUL 세 경로 분기.

신호 집계(detector가 만든 턴별 signal_t를 세션 점수로):
  - B1       (per_turn)       : score_t = signal_t                       (per-turn max)
  - B1.5     (sliding_window) : score_t = mean(signals[t-K+1 .. t])      (O(K) online)
  - STATEFUL (cumulative)     : S_t = clip(λ·S_{t-1} + signal_t, 0, S_max)  (무한 룩백·O(1))

session_state=None이면 B1로 환원(동일 코드, 고정사실 — DESIGN 2.4).
B2(full-session long-context judge)는 [가산] — 본 Phase 미구현.

레이어 규칙: core + adapters import 가능. interfaces import 금지.
"""

from __future__ import annotations

from dataclasses import dataclass

from stateful_guardrails.core.policy import SessionState
from stateful_guardrails.core.state import apply_signal, update_cumulative


@dataclass(frozen=True)
class EngineParams:
    """동결 파라미터 (calibration.json에서 로드). test 전 재튜닝 금지 (ISC-2.6)."""
    lambda_decay: float = 0.7
    window_size_k: int = 5
    state_window_n: int = 10
    s_max: float = 1.0


@dataclass
class BaselineRun:
    """단일 baseline 경로의 세션 실행 결과.

    score_series: 턴별 누적/집계 점수.
    detect_turn_index: threshold를 처음 넘긴 user 턴의 ordinal(0-based), 미탐이면 None.
    session_score: 세션 대표 점수(score_series의 max).
    """
    baseline_id: str
    score_series: list[float]
    detect_turn_index: int | None
    session_score: float


# ---------------------------------------------------------------------------
# 세 경로 신호 집계 (순수 함수)
# ---------------------------------------------------------------------------

def _per_turn_series(signals: list[float]) -> list[float]:
    """B1: 각 턴 독립 (signal_t 그대로). 세션 점수 = max."""
    return list(signals)


def _sliding_window_series(signals: list[float], k: int) -> list[float]:
    """B1.5: 최근 K턴 평균 (online·O(K)). K턴 밖 신호는 윈도우에서 소실된다."""
    out: list[float] = []
    for i in range(len(signals)):
        start = max(0, i - k + 1)
        window = signals[start : i + 1]
        out.append(sum(window) / len(window))
    return out


def _cumulative_series(signals: list[float], lambda_decay: float, s_max: float) -> list[float]:
    """STATEFUL: EWMA 누적. 무한 룩백(K턴 밖 신호 보존)·O(1) 상태."""
    out: list[float] = []
    s = 0.0
    for x in signals:
        s = update_cumulative(s, x, lambda_decay, s_max)
        out.append(s)
    return out


def compute_series(signals: list[float], baseline_id: str, params: EngineParams) -> list[float]:
    """baseline_id에 따라 신호 집계 시계열을 반환한다."""
    if baseline_id == "B1":
        return _per_turn_series(signals)
    if baseline_id == "B1.5":
        return _sliding_window_series(signals, params.window_size_k)
    if baseline_id == "STATEFUL":
        return _cumulative_series(signals, params.lambda_decay, params.s_max)
    raise ValueError(f"알 수 없는 baseline: {baseline_id!r} (B2는 [가산] 미구현)")


def _first_crossing(series: list[float], threshold: float) -> int | None:
    """series에서 threshold 이상이 되는 첫 인덱스. 없으면 None."""
    for i, v in enumerate(series):
        if v >= threshold:
            return i
    return None


def run_baseline(
    signals: list[float],
    baseline_id: str,
    threshold: float,
    params: EngineParams,
) -> BaselineRun:
    """단일 baseline 경로로 세션을 판정한다."""
    series = compute_series(signals, baseline_id, params)
    detect = _first_crossing(series, threshold)
    session_score = max(series) if series else 0.0
    return BaselineRun(
        baseline_id=baseline_id,
        score_series=series,
        detect_turn_index=detect,
        session_score=session_score,
    )


# ---------------------------------------------------------------------------
# session_state=None → B1 환원 (DESIGN 2.4 고정사실, 동일 코드 경로)
# ---------------------------------------------------------------------------

def evaluate_session(
    signals: list[float],
    session_state: SessionState | None,
    params: EngineParams,
) -> list[float]:
    """세션 신호를 판정한다.

    session_state=None → B1(per-turn) 환원: stateless 비교군 (공짜 산출).
    session_state 주입 → STATEFUL(누적): longitudinal 경로.

    동일 함수가 None 분기로 stateless/stateful을 갈라 측정 공정성을 보장한다.
    """
    if session_state is None:
        return compute_series(signals, "B1", params)
    return compute_series(signals, "STATEFUL", params)


# ---------------------------------------------------------------------------
# 증분(incremental) stateful 처리 — 영속화 기반 (ISC-2.2)
# ---------------------------------------------------------------------------

def process_turn(
    state: SessionState,
    detector_id: str,
    signal: float,
) -> float:
    """SessionState에 한 턴 신호를 누적하고 갱신된 S_t를 반환한다.

    엔진을 한 턴씩 진행하며 상태를 영속화하는 online 운영 경로.
    state.lambda_decay·state.s_max를 동결 파라미터로 사용한다.
    """
    return apply_signal(state, detector_id, signal)
