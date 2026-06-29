"""ISC-4.3 (정신): 에스컬레이션 3단계 경계·최초 이관 턴 결정성 검증.

규율: 에스컬레이션은 결정적(deterministic)이어야 감사 로그가 재현 가능하다(.ai.md).
규칙 기반 신호 + 누적식이므로 임베딩·LLM 불요 — 순수 로직 단위 검증이 가능하다.

검증 층위:
  (A) stage_for_score 3단계 경계 (t1·t2 포함 경계).
  (B) escalate_session 최초 이관 턴 + 결정성.
  (C) 실제 C1 세션(c1-test-004)에서 STATEFUL이 B1보다 선제 이관 — 운영 가치 메커니즘.
"""

from __future__ import annotations

from stateful_guardrails.pipeline.engine import EngineParams
from stateful_guardrails.pipeline.escalation import (
    STAGE_AGENT,
    STAGE_BOT,
    STAGE_MANAGER,
    escalate_ref,
    escalate_session,
    stage_for_score,
)

PARAMS = EngineParams(lambda_decay=0.7, window_size_k=5, state_window_n=10, s_max=1.0)
T1, T2 = 0.7, 0.9


# ---------------------------------------------------------------------------
# (A) 3단계 경계 결정성
# ---------------------------------------------------------------------------

class TestStageBoundary:
    """stage_for_score의 t1·t2 경계 매핑이 결정적으로 올바르다."""

    def test_below_t1_is_bot(self):
        assert stage_for_score(0.0, T1, T2) == STAGE_BOT
        assert stage_for_score(0.69, T1, T2) == STAGE_BOT

    def test_t1_boundary_inclusive_is_agent(self):
        """t1 정확히 도달 → 상담사 이관(경계 포함)."""
        assert stage_for_score(0.70, T1, T2) == STAGE_AGENT

    def test_between_t1_t2_is_agent(self):
        assert stage_for_score(0.80, T1, T2) == STAGE_AGENT
        assert stage_for_score(0.89, T1, T2) == STAGE_AGENT

    def test_t2_boundary_inclusive_is_manager(self):
        """t2 정확히 도달 → 매니저 이관(경계 포함)."""
        assert stage_for_score(0.90, T1, T2) == STAGE_MANAGER

    def test_above_t2_is_manager(self):
        assert stage_for_score(1.0, T1, T2) == STAGE_MANAGER


# ---------------------------------------------------------------------------
# (B) 최초 이관 턴 + 결정성
# ---------------------------------------------------------------------------

class TestFirstHandoffTurn:
    """누적 S_t가 t1·t2를 넘는 최초 턴을 결정적으로 산출한다."""

    def test_gradual_accumulation_crosses_t1_before_overt_turn(self):
        """약한 신호 누적이 명시적 위기 턴 *이전에* 상담사 이관을 유발한다.

        signals=[0.55,0.55,...]: 단발은 0.55<t1=0.7로 봇 유지(B1 미이관),
        누적 S_t는 0.55→0.935로 t1·t2를 차례로 넘는다 → STATEFUL 선제 이관.
        """
        texts = ["답답해요"] * 4  # 규칙 risk 0.55 (단발 < t1)
        r = escalate_session(texts, T1, T2, PARAMS)
        # 단발(B1)은 0.55라 끝까지 봇 — 이관 없음
        assert r.b1_first_handoff_turn is None
        # 누적은 t1을 넘겨 상담사 이관 (선제)
        assert r.first_handoff_turn is not None
        assert r.first_handoff_turn < len(texts)

    def test_no_signal_no_handoff(self):
        """위기 신호 없는 정상 대화는 이관 권고가 없다."""
        texts = ["배송 언제 오나요?", "감사합니다", "잘 받았어요"]
        r = escalate_session(texts, T1, T2, PARAMS)
        assert r.first_handoff_turn is None
        assert r.first_manager_turn is None
        assert all(t.stage == STAGE_BOT for t in r.turns)

    def test_overt_single_turn_both_escalate(self):
        """명시적 환불 요구(0.95)는 단발·누적 모두 즉시 매니저 이관 — B1 약baseline 아님."""
        texts = ["환불해주세요"]
        r = escalate_session(texts, T1, T2, PARAMS)
        assert r.first_manager_turn == 0
        assert r.b1_first_manager_turn == 0

    def test_determinism_same_input_same_output(self):
        """동일 입력 → 동일 출력 (감사 재현성)."""
        texts = ["몇 번을 말해요", "답답해요", "탈퇴할게요"]
        r1 = escalate_session(texts, T1, T2, PARAMS)
        r2 = escalate_session(texts, T1, T2, PARAMS)
        assert [t.stage for t in r1.turns] == [t.stage for t in r2.turns]
        assert [t.cumulative_score for t in r1.turns] == [t.cumulative_score for t in r2.turns]
        assert r1.first_handoff_turn == r2.first_handoff_turn
        assert r1.first_manager_turn == r2.first_manager_turn


# ---------------------------------------------------------------------------
# (C) 실제 C1 세션 — 운영 가치 메커니즘 (순수 로직, ollama 불요)
# ---------------------------------------------------------------------------

class TestRealSessionProactiveHandoff:
    """실제 C1 세션에서 STATEFUL 누적이 B1 단발보다 선제 이관한다."""

    def test_c1_test_004_stateful_earlier_than_b1(self):
        """c1-test-004: STATEFUL은 t2(상담사)에 이관, B1은 t3(매니저)에야 이관 — 1턴 선제."""
        r = escalate_ref("c1-test-004", T1, T2, PARAMS)
        # STATEFUL 상담사 이관이 B1보다 이른 턴
        assert r.first_handoff_turn is not None
        assert r.b1_first_handoff_turn is not None
        assert r.first_handoff_turn < r.b1_first_handoff_turn
        # 감사 추적: 모든 턴에 근거 기록
        assert all(t.reason for t in r.turns)
