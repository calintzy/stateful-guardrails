"""ISC-2.7: C1 데이터 자연분포·K초과비율공개·K이내/초과 분층.

검증:
  (a) C1 세션 길이가 자연 분포 — K 이내 세션도 포함(인위적 min>K 제거 금지).
  (b) K 너머 장기복선 세션이 존재하고 비율을 산출 공개 가능.
  (c) 분층 경계(K)가 동결 파라미터로 고정 — K이내/초과 양 분층 모두 비어있지 않음.
  (d) time-to-detect 라벨(success_turn)·target_concept·generation_model 스키마 존재.
"""

from __future__ import annotations

import json
from pathlib import Path

_DATA = Path(__file__).parent.parent / "data"
K = 5  # 동결 파라미터 (calibration.json window_size_k)


def _load(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _n_user_turns(session: dict) -> int:
    return sum(1 for m in session["messages"] if m.get("role") == "user")


def test_frozen_k_matches_calibration():
    """분층 경계 K가 calibration.json 동결값과 일치한다."""
    calib = json.loads((_DATA / "calibration.json").read_text(encoding="utf-8"))
    assert calib["window_size_k"] == K


def test_c1_test_natural_distribution_has_both_strata():
    """C1 test가 K이내·K초과 양 분층을 모두 포함한다 (자연분포)."""
    sessions = _load(_DATA / "c1.test.jsonl")
    assert len(sessions) >= 5, "C1 test 세션이 너무 적음"
    within = [s for s in sessions if _n_user_turns(s) <= K]
    over = [s for s in sessions if _n_user_turns(s) > K]
    assert within, "K이내 세션이 없음 — 인위적 min>K 강제 의심 (자연분포 위반)"
    assert over, "K초과 장기복선 세션이 없음 — 잔여우위 측정 불가"


def test_c1_over_k_ratio_disclosable():
    """K초과 비율이 산출·공개 가능하다 (ISC-2.7 (b))."""
    sessions = _load(_DATA / "c1.test.jsonl")
    over = sum(1 for s in sessions if _n_user_turns(s) > K)
    ratio = over / len(sessions)
    assert 0.0 < ratio < 1.0, f"K초과 비율이 0 또는 1 (자연분포 아님): {ratio}"


def test_c1_total_session_count_in_range():
    """C1 데이터셋이 확대 범위 55~80세션(표본 확대 재측정 — eval 양성 풀 ≈60)."""
    calib = _load(_DATA / "c1.calib.jsonl")
    test = _load(_DATA / "c1.test.jsonl")
    total = len(calib) + len(test)
    assert 55 <= total <= 80, f"C1 세션 수가 55~80 범위 밖: {total}"


def test_c1_schema_has_required_fields():
    """각 C1 세션이 필수 스키마 필드를 가진다 (P1-4 success_turn·target_concept·생성모델)."""
    for fn in ["c1.calib.jsonl", "c1.test.jsonl"]:
        for s in _load(_DATA / fn):
            assert "success_turn" in s, f"{s.get('session_id')}: success_turn 누락 (P1-4)"
            assert "target_concept" in s, f"{s.get('session_id')}: target_concept 누락"
            assert "generation_model" in s and s["generation_model"], \
                f"{s.get('session_id')}: generation_model 누락 (ISC-2.8)"
            assert "threat_pattern" in s, f"{s.get('session_id')}: threat_pattern 누락"
            assert s.get("category") == "C1"
            assert s.get("lang") == "ko", "한국어 골드시드여야 함 (최소 완주선)"


def test_c1_generation_model_is_claude_family():
    """생성 모델이 claude 계열 — detector(qwen/bge)와 분리 (ISC-2.8)."""
    sessions = _load(_DATA / "c1.test.jsonl") + _load(_DATA / "c1.calib.jsonl")
    for s in sessions:
        assert "claude" in s["generation_model"].lower(), (
            f"{s['session_id']}: 생성모델이 claude 계열이 아님 → 동일계열 순환 위험"
        )


def test_c1_success_turn_is_user_turn():
    """success_turn이 실제 user 메시지의 turn_index와 일치한다 (위기 도달 턴 라벨)."""
    for fn in ["c1.calib.jsonl", "c1.test.jsonl"]:
        for s in _load(_DATA / fn):
            st = s["success_turn"]
            user_turn_indices = [
                m["turn_index"] for m in s["messages"] if m.get("role") == "user"
            ]
            assert st in user_turn_indices, (
                f"{s['session_id']}: success_turn={st}이 user 턴이 아님"
            )
            # 위기 도달(격분·환불/해지·이탈 선언)은 보통 마지막 user 턴
            assert st == max(user_turn_indices), (
                f"{s['session_id']}: success_turn이 마지막 user 턴이 아님"
            )
