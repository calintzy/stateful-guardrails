"""pipeline.scanner — stateless 스캔 및 FPR 캘리브레이션.

ISC-1.4: C3 calibration-split에서만 FPR ≤ 5% 임계 산출 (test-split 미사용).

레이어 규칙: core + adapters import 가능. interfaces import 금지.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from stateful_guardrails.core.policy import Message, Policy, PolicySignal
from stateful_guardrails.pipeline.catalog import (
    DEFAULT_WINDOW_SIZE_K,
    get_stateless_policies,
)


# ---------------------------------------------------------------------------
# 세션 스캔 결과
# ---------------------------------------------------------------------------

@dataclass
class SessionScanResult:
    """단일 세션 스캔 결과."""
    session_id: str
    turn_signals: list[list[PolicySignal]]   # [turn][policy] 형태
    max_risk_b1: float                        # B1: 전체 턴 중 max risk
    # 생성 모델 정보 (anti-circular ISC-2.8용)
    generation_model: str = ""


@dataclass
class CalibrationResult:
    """C3 calibration-split FPR 캘리브레이션 결과."""
    threshold_t1: float          # FPR ≤ fpr_budget 달성 최저 임계 (탐지 기준)
    threshold_t2: float          # 고위험 에스컬레이션 임계 (t1보다 높음)
    lambda_decay: float          # 감쇠 계수 λ (v1 기본값)
    window_size_k: int           # B1.5 sliding-window 크기 K
    state_window_n: int          # stateful 누적 상태 참조 턴 수
    s_max: float                 # 누적 점수 상한
    fpr_budget: float            # 목표 FPR 예산
    fpr_achieved: float          # 실제 달성 FPR (calibration-split)
    n_sessions: int              # 캘리브레이션에 사용된 세션 수
    calibration_split: str       # 캘리브레이션에 사용된 파일 경로
    test_split_note: str         # test-split 미사용 명시
    note: str = "동결 파라미터 — test-split 평가 시 재튜닝 금지 (ISC-2.6)"


# ---------------------------------------------------------------------------
# 핵심 스캔 함수
# ---------------------------------------------------------------------------

def scan_session_stateless(
    messages: list[dict],
    policies: list[Policy] | None = None,
    session_id: str = "",
) -> SessionScanResult:
    """단일 세션의 메시지를 stateless 정책으로 스캔한다.

    messages: [{"role": str, "text": str, "turn_index": int}, ...]
    policies: None이면 카탈로그의 stateless 정책 전체 사용.
    """
    if policies is None:
        policies = get_stateless_policies()

    turn_signals: list[list[PolicySignal]] = []
    max_risk_b1 = 0.0

    for msg_dict in messages:
        msg = Message(
            text=msg_dict.get("text", ""),
            role=msg_dict.get("role", "user"),
            turn_index=msg_dict.get("turn_index", 0),
        )
        turn_results: list[PolicySignal] = []
        for policy in policies:
            signal = policy.evaluate(msg, session_state=None)
            turn_results.append(signal)
            if signal.risk > max_risk_b1:
                max_risk_b1 = signal.risk
        turn_signals.append(turn_results)

    return SessionScanResult(
        session_id=session_id,
        turn_signals=turn_signals,
        max_risk_b1=max_risk_b1,
    )


def scan_file_stateless(
    input_path: Path,
    policies: list[Policy] | None = None,
) -> list[SessionScanResult]:
    """JSONL 파일의 모든 세션을 stateless 스캔하여 결과 목록을 반환한다.

    각 줄: {"session_id": ..., "messages": [...], ...}
    """
    if policies is None:
        policies = get_stateless_policies()

    results: list[SessionScanResult] = []
    with input_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            session = json.loads(line)
            result = scan_session_stateless(
                session.get("messages", []),
                policies=policies,
                session_id=session.get("session_id", ""),
            )
            result.generation_model = session.get("generation_model", "")
            results.append(result)
    return results


# ---------------------------------------------------------------------------
# FPR 캘리브레이션
# ---------------------------------------------------------------------------

# 탐색할 임계 후보 (내림차순 — 낮은 임계가 더 많이 탐지, FPR 증가)
_THRESHOLD_CANDIDATES = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1]


def calibrate_threshold(
    results: list[SessionScanResult],
    fpr_budget: float = 0.05,
) -> tuple[float, float]:
    """C3(정상) 세션 스캔 결과에서 FPR ≤ fpr_budget를 만족하는 최저 임계를 반환한다.

    반환: (threshold_t1, fpr_achieved)
    - threshold_t1: FPR 예산 내 가장 민감한 임계 (낮을수록 더 잘 잡음)
    - fpr_achieved: 선택 임계에서의 실제 FPR

    정상 데이터에서 risk ≥ threshold이면 false positive (오탐).
    FPR = 오탐 세션 수 / 전체 세션 수.
    """
    n = len(results)
    if n == 0:
        return 0.5, 0.0

    best_threshold = 0.9
    best_fpr = 0.0

    for threshold in _THRESHOLD_CANDIDATES:
        fp_count = sum(1 for r in results if r.max_risk_b1 >= threshold)
        fpr = fp_count / n
        if fpr <= fpr_budget:
            best_threshold = threshold
            best_fpr = fpr
            # 계속 내려가면서 더 낮은(더 민감한) 임계를 찾음

    return best_threshold, best_fpr


def run_calibration(
    input_path: Path,
    fpr_budget: float = 0.05,
    policies: list[Policy] | None = None,
    output_path: Path | None = None,
) -> CalibrationResult:
    """C3 calibration-split을 스캔하고 동결 파라미터를 산출한다.

    output_path가 지정되면 calibration.json으로 저장한다.
    test-split은 절대 열지 않는다 (ISC-1.4 / P1-7 BLOCK-3).
    """
    results = scan_file_stateless(input_path, policies=policies)

    threshold_t1, fpr_achieved = calibrate_threshold(results, fpr_budget=fpr_budget)
    # t2는 t1보다 높은 고위험 에스컬레이션 임계 (v1 경험값: t1 + 0.2, 최대 0.95)
    threshold_t2 = round(min(threshold_t1 + 0.2, 0.95), 2)

    calib = CalibrationResult(
        threshold_t1=threshold_t1,
        threshold_t2=threshold_t2,
        lambda_decay=0.7,        # v1 기본값 (PLAN P0-3)
        window_size_k=DEFAULT_WINDOW_SIZE_K,
        state_window_n=10,       # stateful 참조 턴 수 (Phase 2 확정)
        s_max=1.0,
        fpr_budget=fpr_budget,
        fpr_achieved=fpr_achieved,
        n_sessions=len(results),
        calibration_split=str(input_path),
        test_split_note=(
            "test-split(data/c3.test.jsonl) 미사용 — "
            "test-split은 Phase 2+ 평가에서만 사용 (ISC-2.6 split 동결)."
        ),
    )

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(asdict(calib), f, ensure_ascii=False, indent=2)

    return calib


def per_threshold_fpr_table(
    results: list[SessionScanResult],
    fpr_budget: float = 0.05,
) -> list[dict]:
    """임계별 FPR 표를 반환한다 (CLI 출력용)."""
    n = len(results)
    table = []
    for threshold in _THRESHOLD_CANDIDATES:
        fp_count = sum(1 for r in results if r.max_risk_b1 >= threshold)
        fpr = fp_count / n if n > 0 else 0.0
        table.append({
            "threshold": threshold,
            "fp_count": fp_count,
            "fpr": fpr,
            "within_budget": fpr <= fpr_budget,
        })
    return table
