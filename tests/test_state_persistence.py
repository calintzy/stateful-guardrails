"""ISC-2.2: 프로세스 재시작 후 SessionState 복원.

JSONStateStore로 누적 상태를 영속화하고, 새 스토어 인스턴스(=재시작 모사)로
복원해 누적을 이어가도, 재시작 없이 처리한 결과와 동일함을 검증한다.
"""

from __future__ import annotations

from pathlib import Path

from stateful_guardrails.adapters.state_store import JSONStateStore
from stateful_guardrails.core.policy import SessionState
from stateful_guardrails.core.state import update_cumulative
from stateful_guardrails.pipeline.engine import process_turn

DETECTOR = "target_aware"
SIGNALS = [0.12, 0.18, 0.05, 0.22, 0.30, 0.10, 0.15, 0.08]
LAMBDA = 0.7
S_MAX = 1.0


def _run_no_restart(signals: list[float]) -> float:
    state = SessionState(session_id="s-norestart", lambda_decay=LAMBDA, s_max=S_MAX)
    last = 0.0
    for sig in signals:
        last = process_turn(state, DETECTOR, sig)
    return last


def test_update_cumulative_math():
    """누적식 S_t=clip(λ·S_{t-1}+signal,0,S_max) 수학·경계 검증."""
    assert update_cumulative(0.0, 0.5, 0.7, 1.0) == 0.5
    assert update_cumulative(0.5, 0.5, 0.7, 1.0) == 0.85
    # 상한 clip
    assert update_cumulative(1.0, 1.0, 0.7, 1.0) == 1.0
    # 하한 clip (음수 신호 가정 시)
    assert update_cumulative(0.0, -5.0, 0.7, 1.0) == 0.0


def test_state_restored_after_restart(tmp_path: Path):
    """중간에 스토어를 새로 열어 상태를 복원해도 결과가 동일하다."""
    root = tmp_path / "state"
    sid = "s-restart"

    # 1단계: 앞 4턴 처리 후 영속화
    store1 = JSONStateStore(root)
    state = SessionState(session_id=sid, lambda_decay=LAMBDA, s_max=S_MAX)
    for sig in SIGNALS[:4]:
        process_turn(state, DETECTOR, sig)
    store1.put(state)

    # 2단계: 재시작 모사 — 새 스토어 인스턴스로 복원
    store2 = JSONStateStore(root)
    restored = store2.get(sid)
    assert restored is not None, "재시작 후 상태 복원 실패"
    assert restored.turn_count == 4
    # 누적 점수가 정확히 복원됐는지
    expected_after_4 = 0.0
    for sig in SIGNALS[:4]:
        expected_after_4 = update_cumulative(expected_after_4, sig, LAMBDA, S_MAX)
    assert abs(restored.policy_scores[DETECTOR] - expected_after_4) < 1e-9

    # 3단계: 복원된 상태로 나머지 4턴 이어서 처리
    final_restart = 0.0
    for sig in SIGNALS[4:]:
        final_restart = process_turn(restored, DETECTOR, sig)
    store2.put(restored)

    # 4단계: 재시작 없이 전체 처리한 결과와 동일해야 함
    final_norestart = _run_no_restart(SIGNALS)
    assert abs(final_restart - final_norestart) < 1e-9, (
        f"재시작 복원 결과 불일치: restart={final_restart} norestart={final_norestart}"
    )
    assert restored.turn_count == len(SIGNALS)

    # 5단계: 최종 상태도 디스크에서 재로드 가능
    store3 = JSONStateStore(root)
    reloaded = store3.get(sid)
    assert reloaded is not None
    assert abs(reloaded.policy_scores[DETECTOR] - final_norestart) < 1e-9
