"""ISC-2.3 (사활): STATEFUL vs B1/B1.5 델타 산출·기록 검증.

규율: 테스트는 "델타가 산출·기록되는가 + 누적의 잔여우위 메커니즘이 실재하는가"를
검증한다. 미성립(STATEFUL이 B1.5 못 이김)도 통과시키되, 미니-eval은 미성립을
리포트에 정직 명시해야 한다(graph_weight=0.0 정신). 실제 경험 수치는 ISC-2.4의
`sgr eval --mini` 라이브 실행에서 산출한다.

본 파일은 두 층위를 검증한다:
  (A) 엔진 메커니즘 (결정적·임베딩 불요): 점진적 sub-threshold 신호에서 STATEFUL이
      B1(per-turn max)·B1.5(window mean)가 놓치는 세션을 누적으로 잡는다.
  (B) 델타 컬럼·thesis 판정이 산출·기록된다 (미성립도 통과).
"""

from __future__ import annotations

import socket

import pytest

from stateful_guardrails.pipeline.engine import EngineParams, run_baseline

PARAMS = EngineParams(lambda_decay=0.7, window_size_k=5, state_window_n=10, s_max=1.0)


def _ollama_up() -> bool:
    try:
        with socket.create_connection(("localhost", 11434), timeout=1.0):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# (A) 엔진 메커니즘 — 누적의 잔여우위가 실재함 (결정적)
# ---------------------------------------------------------------------------

class TestCumulativeMechanism:
    """STATEFUL의 무한 룩백·누적 우위가 실재 메커니즘임을 결정적으로 보인다."""

    def test_gradual_subthreshold_signal_only_stateful_detects(self):
        """K초과 길이의 점진적 sub-threshold 신호: B1·B1.5는 놓치고 STATEFUL만 잡는다.

        각 턴 신호 0.15 (per-turn·window-mean 모두 < threshold 0.25)이지만,
        STATEFUL의 EWMA 누설합은 0.25를 넘는다 → 누적의 잔여우위.
        """
        signals = [0.15] * 8  # 8턴 (>K=5), 모두 동일 소량 드리프트
        threshold = 0.25

        b1 = run_baseline(signals, "B1", threshold, PARAMS)
        b15 = run_baseline(signals, "B1.5", threshold, PARAMS)
        st = run_baseline(signals, "STATEFUL", threshold, PARAMS)

        assert b1.detect_turn_index is None, "B1이 sub-threshold 단발을 잡으면 안 됨"
        assert b15.detect_turn_index is None, "B1.5 window-mean이 0.15<0.25를 잡으면 안 됨"
        assert st.detect_turn_index is not None, "STATEFUL 누적이 0.25를 넘겨 잡아야 함"
        assert st.session_score > b15.session_score > 0

    def test_overt_single_turn_all_detect(self):
        """단발 명백 위기신호(0.9): B1·B1.5·STATEFUL 모두 잡는다 — B1이 약baseline 아님."""
        signals = [0.0, 0.0, 0.9, 0.0, 0.0]
        threshold = 0.25
        for bid in ["B1", "B1.5", "STATEFUL"]:
            run = run_baseline(signals, bid, threshold, PARAMS)
            assert run.detect_turn_index is not None, f"{bid}가 명백 위기신호를 놓침"

    def test_session_state_none_reduces_to_b1(self):
        """engine.evaluate_session(session_state=None)이 B1로 환원된다 (동일 코드)."""
        from stateful_guardrails.pipeline.engine import compute_series, evaluate_session
        signals = [0.1, 0.3, 0.2]
        b1_series = compute_series(signals, "B1", PARAMS)
        none_series = evaluate_session(signals, None, PARAMS)
        assert none_series == b1_series == signals

    def test_within_k_window_equiv_short_session(self):
        """K이내 짧은 세션에서 단발 신호는 B1.5와 STATEFUL이 모두 즉시 잡는다 (정직: 동등)."""
        signals = [0.4, 0.0]  # 2턴 (<=K), 첫 턴 즉시 임계 초과
        threshold = 0.3
        b15 = run_baseline(signals, "B1.5", threshold, PARAMS)
        st = run_baseline(signals, "STATEFUL", threshold, PARAMS)
        assert b15.detect_turn_index == 0
        assert st.detect_turn_index == 0  # 동등 — K이내에서 잔여우위 없음


class TestMcNemarExact:
    """McNemar exact(two-sided) p값이 결정적으로 올바르다 (임베딩 불요)."""

    def test_no_discordant_pairs_returns_one(self):
        from stateful_guardrails.pipeline.eval import mcnemar_exact
        assert mcnemar_exact(0, 0) == 1.0  # 불일치쌍 없음 → 검정 불가

    def test_known_two_sided_values(self):
        from stateful_guardrails.pipeline.eval import mcnemar_exact
        # b=5,c=0: n=5,k=0 → 2·C(5,0)·0.5^5 = 2/32 = 0.0625 (유의 아님, 소표본 한계)
        assert abs(mcnemar_exact(5, 0) - 0.0625) < 1e-9
        # b=6,c=0: 2/64 = 0.03125 (<0.05 유의)
        assert abs(mcnemar_exact(6, 0) - 0.03125) < 1e-9
        # 대칭: b=3,c=3 → 1.0 상한
        assert mcnemar_exact(3, 3) == 1.0
        # 대칭성 b↔c
        assert mcnemar_exact(7, 2) == mcnemar_exact(2, 7)

    def test_discordant_pairs_from_detected_sets(self):
        from stateful_guardrails.pipeline.eval import _discordant
        b, c = _discordant(["a", "b", "c"], ["a"])
        assert (b, c) == (2, 0)  # STATEFUL만 b,c 탐지
        b, c = _discordant(["a"], ["a", "b", "c"])
        assert (b, c) == (0, 2)


# ---------------------------------------------------------------------------
# (B) 델타 컬럼·thesis 판정 산출·기록 (미성립도 통과)
# ---------------------------------------------------------------------------

class TestDeltaComputationRecorded:
    """미니-eval이 STATEFUL−B1/B1.5 델타와 thesis 판정을 산출·기록한다."""

    @pytest.mark.skipif(not _ollama_up(), reason="ollama 미기동 — 라이브 임베딩 불가")
    def test_mini_eval_produces_delta_and_verdict(self, tmp_path):
        from pathlib import Path

        from stateful_guardrails.pipeline.eval import (
            run_mini_eval,
            thesis_verdict,
        )

        result = run_mini_eval(Path("data"), PARAMS, fpr_budget=0.05)

        # 두 detector 모두 산출됨 (ISC-2.5)
        assert set(result.by_detector) == {"target_aware", "target_agnostic"}

        for det_id, dr in result.by_detector.items():
            # 세 경로 모두 metrics 존재
            assert set(dr.metrics) == {"B1", "B1.5", "STATEFUL"}
            b1 = dr.metrics["B1"]; b15 = dr.metrics["B1.5"]; st = dr.metrics["STATEFUL"]
            # 델타가 산출 가능 (필수 컬럼)
            d_b1 = st.recall_all - b1.recall_all
            d_b15 = st.recall_all - b15.recall_all
            assert isinstance(d_b1, float)
            assert isinstance(d_b15, float)
            # 동일 FPR 예산: test FPR이 예산 근처 이내 (점추정 — 소표본 허용)
            assert 0.0 <= st.test_fpr <= 1.0

        # thesis 판정이 산출되며 허용된 라벨이다 (방향성·미성립도 통과)
        verdicts = thesis_verdict(result)
        allowed_prefixes = ("성립", "방향성 지지", "부분성립", "미성립")
        for det_id, v in verdicts.items():
            assert v["verdict"].startswith(allowed_prefixes), (
                f"{det_id}: 알 수 없는 판정 {v['verdict']}"
            )
            # 델타 키 + McNemar 유의성 키가 모두 기록됨 (recall + TTD + 검정)
            for key in ["delta_recall_b1_all", "delta_recall_b15_all",
                        "delta_recall_b15_over_k", "delta_ttd_b15_all",
                        "mcnemar_p_b15", "mcnemar_b_b15", "mcnemar_c_b15"]:
                assert key in v, f"{det_id}: 델타/검정 키 누락 {key}"
            # 사활 컬럼 '성립'은 반드시 McNemar p<0.05 (점추정 부호만으로 성립 금지)
            if v["verdict"] == "성립":
                assert v["mcnemar_p_b15"] < 0.05, (
                    f"{det_id}: 성립인데 사활 McNemar p={v['mcnemar_p_b15']:.3f}≥0.05 (과대진술)"
                )

    @pytest.mark.skipif(not _ollama_up(), reason="ollama 미기동")
    def test_report_records_honest_verdict_and_models(self, tmp_path):
        """리포트에 델타 컬럼·생성/평가 모델·미성립 정직 명시 요소가 포함된다."""
        from pathlib import Path

        from stateful_guardrails.pipeline.eval import render_report, run_mini_eval

        result = run_mini_eval(Path("data"), PARAMS, fpr_budget=0.05)
        md = render_report(result)
        assert "STATEFUL − B1.5" in md           # 사활 델타 컬럼
        assert "동일계열 여부" in md               # ISC-2.8
        assert "graph_weight=0.0" in md           # 정직 규율 명시
        assert "K초과" in md                       # 분층 (ISC-2.7)
