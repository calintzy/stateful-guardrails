"""경제성 비용 모델 단위 검증 (운영 가치 레이어).

규율: 비용은 모델 추정(순수 함수)이므로 결정적으로 단위 검증 가능하다.
복잡도 차수(STATEFUL O(N) < B1.5 O(N·K) < B2 O(N²))가 누적 비용에 반영되는지 본다.
측정 thesis·수치는 건드리지 않는 독립 추가다.
"""

from __future__ import annotations

from stateful_guardrails.pipeline.cost import (
    CostAssumptions,
    build_cost_table,
    cumulative_tokens,
    per_turn_tokens,
)

A = CostAssumptions(tokens_per_turn=19, c_state_tokens=2, window_k=5)


class TestPerTurnCost:
    """턴당 비용이 차수 정의대로다."""

    def test_stateful_is_constant_per_turn(self):
        """STATEFUL 턴당 비용은 t에 무관하게 고정(O(1))."""
        c1 = per_turn_tokens("STATEFUL", 1, A)
        c100 = per_turn_tokens("STATEFUL", 100, A)
        assert c1 == c100 == A.tokens_per_turn + A.c_state_tokens

    def test_b15_caps_at_window_k(self):
        """B1.5 턴당 비용은 K턴에서 상한(min(t,K))."""
        assert per_turn_tokens("B1.5", 3, A) == 3 * A.tokens_per_turn
        assert per_turn_tokens("B1.5", 5, A) == 5 * A.tokens_per_turn
        assert per_turn_tokens("B1.5", 50, A) == 5 * A.tokens_per_turn  # K 상한

    def test_b2_grows_linearly_per_turn(self):
        """B2 턴당 비용은 t에 비례(O(t))."""
        assert per_turn_tokens("B2", 10, A) == 10 * A.tokens_per_turn
        assert per_turn_tokens("B2", 50, A) == 50 * A.tokens_per_turn


class TestCumulativeOrdering:
    """누적 비용 순서: STATEFUL ≤ B1.5 ≤ B2 (N>K에서 강한 부등호)."""

    def test_ordering_for_long_session(self):
        n = 50  # > K=5
        st = cumulative_tokens("STATEFUL", n, A)
        b15 = cumulative_tokens("B1.5", n, A)
        b2 = cumulative_tokens("B2", n, A)
        assert st < b15 < b2

    def test_ratio_grows_with_n(self):
        """B2/STATEFUL 배수가 N에 비례해 단조 증가(O(N²) vs O(N))."""
        rows = build_cost_table([10, 20, 50, 100], A)
        ratios = [r.ratio_vs_stateful["B2"] for r in rows]
        assert ratios == sorted(ratios)
        assert ratios[-1] > ratios[0]

    def test_stateful_linear(self):
        """STATEFUL 누적은 N에 선형 — 2N턴은 N턴의 정확히 2배."""
        assert cumulative_tokens("STATEFUL", 100, A) == 2 * cumulative_tokens("STATEFUL", 50, A)
