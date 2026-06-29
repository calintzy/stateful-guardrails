"""pipeline.eval — 미니-eval 하니스 (ISC-2.3·2.4·2.5·2.7·2.8 사활점).

프로토콜(정직 측정 규율):
  1) C3 calibration-split에서 (detector × baseline)별 임계를 동일 FPR 예산으로 산출·동결.
  2) 동결 임계를 C1 test-split(recall·time-to-detect)·C3 test-split(오탐)에 적용.
  3) STATEFUL−B1 / STATEFUL−B1.5 델타(필수)를 recall·time-to-detect로 산출.
  4) 동일 작동점(matched test-FPR) 재비교 + recall 델타 부트스트랩 CI(ISC-2.3).
  5) 세션 길이 K이내/초과 분층(ISC-2.7), target_aware/agnostic 병렬(ISC-2.5),
     생성↔평가 모델 식별자·동일계열 여부(ISC-2.8) 보고.

C1 양성 표본 확대: c1.calib(C3-FPR 기반 캘리브에 미사용)을 c1.test에 합류해 검정력 보강.
  → C1 누수 없음(캘리브레이션은 C3 calib만 사용). 동결 파라미터 5종은 재튜닝하지 않는다.

동결 파라미터 5종(t1·t2·λ·K·N·S_max)은 calibration-split 파생, test 동결(ISC-2.6).
B1.5를 못 이기면 thesis 미성립을 정직 명시(graph_weight=0.0 정신).

레이어 규칙: core + adapters import 가능. interfaces import 금지.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from math import comb
from pathlib import Path
from typing import TypedDict

from stateful_guardrails.adapters.embeddings import OllamaEmbedder
from stateful_guardrails.pipeline.detectors import get_detector
from stateful_guardrails.pipeline.engine import EngineParams, run_baseline

# ---------------------------------------------------------------------------
# 상수 (파일 상단 집약 — code-reviewer)
# ---------------------------------------------------------------------------

# 평가 대상 baseline (B2는 [가산] — 본 Phase 미구현)
BASELINE_IDS = ["B1", "B1.5", "STATEFUL"]
DETECTOR_IDS = ["target_aware", "target_agnostic"]

# 평가/detector 모델 식별자 (anti-circular ISC-2.8)
EVAL_DETECTOR_MODEL = "bge-m3 (임베딩) + qwen2.5:14b (judge, 본 Phase 미사용)"
EVAL_MODEL_FAMILY = "qwen/bge (Alibaba)"
GEN_MODEL_FAMILY = "claude (Anthropic)"

SIG_ALPHA = 0.05  # McNemar 유의수준 (사활 컬럼 vs B1.5 성립 기준)

# 임계 후보 그리드 (0.00 ~ 1.01, 0.01 step). 1.01이면 FPR=0 보장(도달 불가 임계).
_THRESHOLD_UNREACHABLE = 2.0  # session_score 계산용 더미 임계(threshold 무관, 점수만 추출)
_THRESHOLD_CANDIDATES = [i / 100.0 for i in range(0, 102)]  # 0.00..1.01

# 동일 작동점 비교 대상 test-FPR 작동점 (critic 최강 지적: 작동점 정렬 후 recall 재비교)
MATCHED_FPR_POINTS = [0.05, 0.10, 0.20]

# recall 델타 부트스트랩 (ISC-2.3 신뢰구간) — stdlib random, seed 고정(재현성 ISC-5.5)
BOOTSTRAP_N = 2000
BOOTSTRAP_SEED = 20260629
BOOTSTRAP_CI = 0.95


# ---------------------------------------------------------------------------
# 데이터 로드
# ---------------------------------------------------------------------------

@dataclass
class Session:
    session_id: str
    category: str
    label: str
    user_texts: list[str]
    n_user_turns: int
    success_turn_ordinal: int    # 위기 도달 user-턴 ordinal (= n_user_turns-1)
    generation_model: str
    threat_pattern: str = ""


def _load_sessions(path: Path) -> list[Session]:
    sessions: list[Session] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            user_texts = [
                m["text"] for m in d.get("messages", []) if m.get("role") == "user"
            ]
            n = len(user_texts)
            sessions.append(
                Session(
                    session_id=d["session_id"],
                    category=d.get("category", ""),
                    label=d.get("label", ""),
                    user_texts=user_texts,
                    n_user_turns=n,
                    success_turn_ordinal=max(0, n - 1),
                    generation_model=d.get("generation_model", ""),
                    threat_pattern=d.get("threat_pattern", ""),
                )
            )
    return sessions


def _load_c1_positive_pool(dataset_dir: Path) -> tuple[list[Session], int, int]:
    """C1 양성 test 풀을 로드한다 (표본 확대: c1.calib 합류).

    c1.calib은 C3-FPR 기반 캘리브레이션에 사용되지 않으므로 test 양성으로 합류해도
    누수가 없다(검정력 보강). 반환: (합류 세션, c1.test 수, c1.calib 합류 수).
    """
    test = _load_sessions(dataset_dir / "c1.test.jsonl")
    calib_path = dataset_dir / "c1.calib.jsonl"
    calib = _load_sessions(calib_path) if calib_path.exists() else []
    return test + calib, len(test), len(calib)


# ---------------------------------------------------------------------------
# 신호 계산 (detector별 세션 신호 캐시)
# ---------------------------------------------------------------------------

def _compute_signals(
    sessions: list[Session],
    detector_id: str,
    embedder: OllamaEmbedder,
    params: EngineParams,
) -> dict[str, list[float]]:
    """세션ID → 턴별 signal_t."""
    detector = get_detector(detector_id, embedder=embedder, window_n=params.state_window_n)
    out: dict[str, list[float]] = {}
    for s in sessions:
        out[s.session_id] = detector.signals(s.user_texts)
    return out


# ---------------------------------------------------------------------------
# 임계 캘리브레이션 (C3 calib, 동일 FPR 예산)
# ---------------------------------------------------------------------------

def _calibrate_threshold(
    c3_signals: dict[str, list[float]],
    baseline_id: str,
    params: EngineParams,
    fpr_budget: float,
) -> tuple[float, float]:
    """C3 calib 신호에서 FPR ≤ budget를 만족하는 최저(최민감) 임계를 산출한다.

    반환: (threshold, fpr_achieved). 동일 FPR 예산을 모든 baseline에 적용해 공정성 확보.
    세션 점수 = score_series의 max. score ≥ threshold면 오탐(정상인데 탐지).
    """
    session_scores: list[float] = []
    for sig in c3_signals.values():
        run = run_baseline(sig, baseline_id, threshold=_THRESHOLD_UNREACHABLE, params=params)
        session_scores.append(run.session_score)

    n = len(session_scores)
    if n == 0:
        return 0.5, 0.0

    # 낮은 임계가 더 민감(FPR↑). 예산 내에서 가장 낮은 임계를 택한다(오름차순 첫 충족).
    for thr in _THRESHOLD_CANDIDATES:
        fp = sum(1 for sc in session_scores if sc >= thr)
        fpr = fp / n
        if fpr <= fpr_budget:
            return thr, fpr
    return 1.01, 0.0


# ---------------------------------------------------------------------------
# 평가 (C1 test recall·time-to-detect, C3 test FPR)
# ---------------------------------------------------------------------------

@dataclass
class BaselineMetrics:
    baseline_id: str
    threshold: float
    calib_fpr: float
    test_fpr: float                       # C3 test 전체 오탐율
    test_fpr_short: float                 # 단기 음성(K이내) 오탐율
    test_fpr_long: float                  # 장기-양성(K초과) 오탐율 ← 길이교란 통제 핵심 FPR
    n_c3_short: int                       # C3 test 단기음성 세션 수
    n_c3_long: int                        # C3 test 장기양성 세션 수
    fp_short: int                         # 단기음성 오탐 건수
    fp_long: int                          # 장기양성 오탐 건수
    recall_all: float                     # C1 test 전체 recall
    recall_within_k: float                # K이내 분층 recall
    recall_over_k: float                  # K초과 분층 recall
    n_within_k: int
    n_over_k: int
    detected_sessions: list[str] = field(default_factory=list)
    ttd_all: float | None = None          # 평균 time-to-detect (탐지 세션, user-턴 단위)
    ttd_within_k: float | None = None
    ttd_over_k: float | None = None


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


# ---------------------------------------------------------------------------
# McNemar exact 검정 (STATEFUL vs baseline 짝지은 탐지 불일치쌍, 점추정 부호 과대진술 차단)
# ---------------------------------------------------------------------------

def mcnemar_exact(b: int, c: int) -> float:
    """McNemar exact(two-sided binomial) p값.

    b = STATEFUL이 탐지·baseline은 미탐(STATEFUL 우위 불일치쌍)
    c = baseline이 탐지·STATEFUL은 미탐(baseline 우위 불일치쌍)
    일치쌍(둘 다 탐지/둘 다 미탐)은 McNemar에서 무정보 → 제외.

    귀무가설: 불일치쌍이 양방향 동확률(p=0.5). n=b+c, k=min(b,c)에서
      p = 2·Σ_{i=0..k} C(n,i)·0.5^n  (1.0 상한).
    n=0이면 불일치쌍 없음 → 검정 불가, p=1.0(유의 아님) 반환.
    stdlib math.comb만 사용(외부 의존 없음·결정적).
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(comb(n, i) for i in range(k + 1))
    p = 2.0 * tail / (2 ** n)
    return min(1.0, p)


def _discordant(detected_stateful: list[str], detected_baseline: list[str]) -> tuple[int, int]:
    """짝지은 탐지 불일치쌍 (b, c) 산출. C1 test는 전부 양성이라 탐지=진양성."""
    st = set(detected_stateful)
    base = set(detected_baseline)
    b = len(st - base)   # STATEFUL만 탐지
    c = len(base - st)   # baseline만 탐지
    return b, c


def _bootstrap_delta_ci(
    all_ids: list[str],
    detected_st: set[str],
    detected_base: set[str],
    n_boot: int = BOOTSTRAP_N,
    seed: int = BOOTSTRAP_SEED,
    ci: float = BOOTSTRAP_CI,
) -> tuple[float, float, float]:
    """짝지은 recall 델타(STATEFUL−baseline)의 부트스트랩 신뢰구간 (ISC-2.3).

    세션별 짝지은 지표 d_i = 1[탐지_st] − 1[탐지_base] ∈ {-1,0,+1}.
    세션을 복원추출로 n_boot회 재표집해 mean(d_i) 분포의 백분위 CI를 산출한다.
    stdlib random(seed 고정)만 사용 — 결정적·재현 가능(ISC-5.5).
    반환: (점추정 Δrecall, CI 하한, CI 상한).
    """
    n = len(all_ids)
    if n == 0:
        return 0.0, 0.0, 0.0
    d = [(1 if sid in detected_st else 0) - (1 if sid in detected_base else 0) for sid in all_ids]
    point = sum(d) / n
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(n_boot):
        s = 0
        for _ in range(n):
            s += d[rng.randrange(n)]
        means.append(s / n)
    means.sort()
    lo_idx = int((1 - ci) / 2 * n_boot)
    hi_idx = min(n_boot - 1, int((1 + ci) / 2 * n_boot))
    return point, means[lo_idx], means[hi_idx]


def _evaluate_baseline(
    baseline_id: str,
    threshold: float,
    calib_fpr: float,
    c1_test: list[Session],
    c1_signals: dict[str, list[float]],
    c3_test: list[Session],
    c3_test_signals: dict[str, list[float]],
    params: EngineParams,
) -> BaselineMetrics:
    # C3 test FPR — 단기음성(K이내)/장기양성(K초과) 분층 (길이 교란 통제)
    c3_fp = fp_short = fp_long = 0
    n_short = n_long = 0
    for s in c3_test:
        run = run_baseline(c3_test_signals[s.session_id], baseline_id,
                           threshold=threshold, params=params)
        fired = run.detect_turn_index is not None
        is_long = s.n_user_turns > params.window_size_k
        if is_long:
            n_long += 1
            if fired:
                fp_long += 1
        else:
            n_short += 1
            if fired:
                fp_short += 1
        if fired:
            c3_fp += 1
    n_c3 = len(c3_test)
    test_fpr = c3_fp / n_c3 if n_c3 else 0.0
    test_fpr_short = fp_short / n_short if n_short else 0.0
    test_fpr_long = fp_long / n_long if n_long else 0.0

    # C1 test recall + time-to-detect, 분층
    detected_all: list[str] = []
    ttd_all: list[float] = []
    within_total = over_total = 0
    within_hit = over_hit = 0
    ttd_within: list[float] = []
    ttd_over: list[float] = []

    for s in c1_test:
        sig = c1_signals[s.session_id]
        run = run_baseline(sig, baseline_id, threshold=threshold, params=params)
        is_within = s.n_user_turns <= params.window_size_k
        if is_within:
            within_total += 1
        else:
            over_total += 1
        if run.detect_turn_index is not None:
            detected_all.append(s.session_id)
            ttd = s.success_turn_ordinal - run.detect_turn_index  # 양수=조기탐지
            ttd_all.append(ttd)
            if is_within:
                within_hit += 1
                ttd_within.append(ttd)
            else:
                over_hit += 1
                ttd_over.append(ttd)

    n_all = len(c1_test)
    return BaselineMetrics(
        baseline_id=baseline_id,
        threshold=threshold,
        calib_fpr=calib_fpr,
        test_fpr=test_fpr,
        test_fpr_short=test_fpr_short,
        test_fpr_long=test_fpr_long,
        n_c3_short=n_short,
        n_c3_long=n_long,
        fp_short=fp_short,
        fp_long=fp_long,
        recall_all=len(detected_all) / n_all if n_all else 0.0,
        recall_within_k=within_hit / within_total if within_total else 0.0,
        recall_over_k=over_hit / over_total if over_total else 0.0,
        n_within_k=within_total,
        n_over_k=over_total,
        detected_sessions=detected_all,
        ttd_all=_mean(ttd_all),
        ttd_within_k=_mean(ttd_within),
        ttd_over_k=_mean(ttd_over),
    )


# ---------------------------------------------------------------------------
# 동일 작동점(matched test-FPR) 재비교 (critic 최강 지적)
# ---------------------------------------------------------------------------

@dataclass
class OperatingPoint:
    """특정 test-FPR 작동점에서의 baseline별 recall (작동점 정렬 비교)."""
    target_fpr: float
    by_baseline: dict[str, tuple[float, float, float]]  # bid → (threshold, achieved_fpr, recall)


def _fpr_at(c3_signals: dict[str, list[float]], c3_sessions: list[Session],
            baseline_id: str, threshold: float, params: EngineParams) -> float:
    fp = 0
    for s in c3_sessions:
        run = run_baseline(c3_signals[s.session_id], baseline_id, threshold=threshold, params=params)
        if run.detect_turn_index is not None:
            fp += 1
    return fp / len(c3_sessions) if c3_sessions else 0.0


def _recall_at(c1_signals: dict[str, list[float]], c1_sessions: list[Session],
               baseline_id: str, threshold: float, params: EngineParams) -> float:
    hit = 0
    for s in c1_sessions:
        run = run_baseline(c1_signals[s.session_id], baseline_id, threshold=threshold, params=params)
        if run.detect_turn_index is not None:
            hit += 1
    return hit / len(c1_sessions) if c1_sessions else 0.0


def _matched_operating_points(
    c1_signals: dict[str, list[float]],
    c1_sessions: list[Session],
    c3_signals: dict[str, list[float]],
    c3_sessions: list[Session],
    params: EngineParams,
    fpr_points: list[float] = MATCHED_FPR_POINTS,
) -> list[OperatingPoint]:
    """각 target test-FPR에서 baseline별 임계를 '동일 FPR'로 정렬한 뒤 recall을 재산출한다.

    임계를 동일 FPR 예산이 아니라 **동일 작동점(test-FPR)**으로 맞춘다 →
    'STATEFUL FPR 43% vs B1.5 14%' 처럼 작동점이 달라 recall 비교가 불공정하다는
    critic 지적에 답한다. 같은 FPR 예산에서도 STATEFUL이 B1.5를 이기는지 산출.
    """
    out: list[OperatingPoint] = []
    for f in fpr_points:
        by_b: dict[str, tuple[float, float, float]] = {}
        for bid in BASELINE_IDS:
            # target FPR 이하를 만족하는 최저(최민감) 임계를 c3.test에서 직접 탐색
            chosen_thr = 1.01
            chosen_fpr = 0.0
            for thr in _THRESHOLD_CANDIDATES:
                fpr = _fpr_at(c3_signals, c3_sessions, bid, thr, params)
                if fpr <= f:
                    chosen_thr = thr
                    chosen_fpr = fpr
                    break
            recall = _recall_at(c1_signals, c1_sessions, bid, chosen_thr, params)
            by_b[bid] = (chosen_thr, chosen_fpr, recall)
        out.append(OperatingPoint(target_fpr=f, by_baseline=by_b))
    return out


# ---------------------------------------------------------------------------
# 전체 미니-eval 실행
# ---------------------------------------------------------------------------

@dataclass
class DetectorResult:
    detector_id: str
    metrics: dict[str, BaselineMetrics]   # baseline_id → metrics
    c1_signals: dict[str, list[float]] = field(default_factory=dict)
    c3_test_signals: dict[str, list[float]] = field(default_factory=dict)
    matched_ops: list[OperatingPoint] = field(default_factory=list)


@dataclass
class MiniEvalResult:
    params: EngineParams
    fpr_budget: float
    c1_test: list[Session]
    c3_test: list[Session]
    c3_test_n: int
    by_detector: dict[str, DetectorResult]   # detector_id → result
    gen_models: list[str]
    c1_test_n: int = 0       # c1.test 단독 세션 수
    c1_calib_merged: int = 0  # c1.calib 합류 세션 수 (표본 확대)


def run_mini_eval(
    dataset_dir: Path,
    params: EngineParams,
    fpr_budget: float = 0.05,
    embedder: OllamaEmbedder | None = None,
    detector_ids: list[str] | None = None,
) -> MiniEvalResult:
    """미니-eval 전체 파이프라인을 실행한다."""
    detector_ids = detector_ids or DETECTOR_IDS
    embedder = embedder or OllamaEmbedder()

    c3_calib = _load_sessions(dataset_dir / "c3.calib.jsonl")
    c3_test = _load_sessions(dataset_dir / "c3.test.jsonl")
    c1_test, c1_test_n, c1_calib_merged = _load_c1_positive_pool(dataset_dir)

    by_detector: dict[str, DetectorResult] = {}
    for det_id in detector_ids:
        c3_calib_sig = _compute_signals(c3_calib, det_id, embedder, params)
        c3_test_sig = _compute_signals(c3_test, det_id, embedder, params)
        c1_test_sig = _compute_signals(c1_test, det_id, embedder, params)

        metrics: dict[str, BaselineMetrics] = {}
        for bid in BASELINE_IDS:
            thr, calib_fpr = _calibrate_threshold(c3_calib_sig, bid, params, fpr_budget)
            metrics[bid] = _evaluate_baseline(
                bid, thr, calib_fpr, c1_test, c1_test_sig, c3_test, c3_test_sig, params
            )
        matched = _matched_operating_points(
            c1_test_sig, c1_test, c3_test_sig, c3_test, params
        )
        by_detector[det_id] = DetectorResult(
            detector_id=det_id, metrics=metrics,
            c1_signals=c1_test_sig, c3_test_signals=c3_test_sig, matched_ops=matched,
        )

    gen_models = sorted({s.generation_model for s in c1_test if s.generation_model})
    return MiniEvalResult(
        params=params,
        fpr_budget=fpr_budget,
        c1_test=c1_test,
        c3_test=c3_test,
        c3_test_n=len(c3_test),
        by_detector=by_detector,
        gen_models=gen_models,
        c1_test_n=c1_test_n,
        c1_calib_merged=c1_calib_merged,
    )


# ---------------------------------------------------------------------------
# λ 민감도 곡선 (ISC-5.6) — λ만 변화, B1/B1.5는 λ 무관(고정)
# ---------------------------------------------------------------------------

def lambda_sweep(
    dataset_dir: Path,
    base_params: EngineParams,
    lambdas: list[float],
    fpr_budget: float = 0.05,
    embedder: OllamaEmbedder | None = None,
    detector_ids: list[str] | None = None,
) -> dict:
    """λ∈lambdas에서 STATEFUL−B1·STATEFUL−B1.5 델타 곡선을 산출한다 (ISC-5.6).

    detector 신호는 λ 무관이므로 1회 계산 후 재사용. B1/B1.5 recall도 λ 무관(고정).
    λ별로 STATEFUL 임계만 C3 calib에서 재캘리브(동일 FPR 예산) → recall·델타 산출.
    부호 반전 구간이 있으면 그대로 표기(정직성 증거).
    """
    detector_ids = detector_ids or DETECTOR_IDS
    embedder = embedder or OllamaEmbedder()
    c3_calib = _load_sessions(dataset_dir / "c3.calib.jsonl")
    c1_test, _, _ = _load_c1_positive_pool(dataset_dir)

    out: dict = {"lambdas": lambdas, "fpr_budget": fpr_budget, "by_detector": {}}
    for det_id in detector_ids:
        c3_calib_sig = _compute_signals(c3_calib, det_id, embedder, base_params)
        c1_sig = _compute_signals(c1_test, det_id, embedder, base_params)

        # B1/B1.5 (λ 무관) — 1회 캘리브·recall
        fixed: dict[str, float] = {}
        for bid in ["B1", "B1.5"]:
            thr, _ = _calibrate_threshold(c3_calib_sig, bid, base_params, fpr_budget)
            fixed[bid] = _recall_at(c1_sig, c1_test, bid, thr, base_params)

        rows = []
        for lam in lambdas:
            p = EngineParams(
                lambda_decay=lam,
                window_size_k=base_params.window_size_k,
                state_window_n=base_params.state_window_n,
                s_max=base_params.s_max,
            )
            thr, cfpr = _calibrate_threshold(c3_calib_sig, "STATEFUL", p, fpr_budget)
            recall_st = _recall_at(c1_sig, c1_test, "STATEFUL", thr, p)
            rows.append({
                "lambda": lam,
                "threshold": thr,
                "calib_fpr": cfpr,
                "recall_stateful": recall_st,
                "delta_b1": recall_st - fixed["B1"],
                "delta_b15": recall_st - fixed["B1.5"],
            })
        out["by_detector"][det_id] = {"fixed": fixed, "rows": rows}
    return out


def render_lambda_sweep(sweep: dict) -> str:
    lines: list[str] = []
    lines.append("# λ 민감도 곡선 — STATEFUL−B1 / STATEFUL−B1.5 (ISC-5.6)\n")
    lines.append("> detector 신호는 λ 무관 → 1회 계산. B1/B1.5 recall도 λ 무관(고정).")
    lines.append("> λ별 STATEFUL 임계만 C3 calib에서 동일 FPR 예산으로 재캘리브.")
    lines.append("> 부호 반전 구간이 있으면 그대로 게시한다(정직성 증거).\n")
    lines.append(f"- FPR 예산={sweep['fpr_budget']*100:.0f}% / λ 후보={sweep['lambdas']}\n")
    for det_id, d in sweep["by_detector"].items():
        lines.append(f"## detector = `{det_id}`\n")
        lines.append(f"- 고정 recall(λ무관): B1={d['fixed']['B1']*100:.0f}% / B1.5={d['fixed']['B1.5']*100:.0f}%\n")
        lines.append("| λ | STATEFUL 임계 | calibFPR | recall(STATEFUL) | Δrecall vs B1 | **Δrecall vs B1.5** |")
        lines.append("|---|---|---|---|---|---|")
        signs_b15 = []
        for r in d["rows"]:
            signs_b15.append(r["delta_b15"])
            lines.append(
                f"| {r['lambda']} | {r['threshold']:.2f} | {r['calib_fpr']*100:.0f}% | "
                f"{r['recall_stateful']*100:.0f}% | {_fmt_delta(r['delta_b1'], pct=True)} | "
                f"**{_fmt_delta(r['delta_b15'], pct=True)}** |"
            )
        # 부호 반전 탐지 (사활 컬럼 vs B1.5)
        reversed_b15 = any(
            (a > 0 and b < 0) or (a < 0 and b > 0)
            for a, b in zip(signs_b15, signs_b15[1:])
        )
        flag = "**있음 — 정직 게시**" if reversed_b15 else "없음"
        lines.append(f"\n> vs B1.5 델타 부호 반전: {flag}\n")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 리포트 렌더링 (섹션별 private 함수 — render_report는 조립만)
# ---------------------------------------------------------------------------

def _fmt(x: float | None, pct: bool = False) -> str:
    if x is None:
        return "—"
    if pct:
        return f"{x*100:.1f}%"
    return f"{x:+.2f}" if x < 0 or x == 0 else f"{x:.2f}"


def _fmt_delta(x: float, pct: bool = False) -> str:
    if pct:
        return f"{x*100:+.1f}%p"
    return f"{x:+.2f}"


def _render_header(result: MiniEvalResult) -> list[str]:
    lines = ["# 미니-eval 리포트 — STATEFUL vs B1/B1.5 (Phase 2 사활점)\n"]
    lines.append("> 검증 자세: \"stateful이 이긴다\"가 아니라 \"stateful의 가치를 반증 가능하게 검증\"한다.")
    lines.append("> 미성립(STATEFUL이 B1.5 못 이김)도 유효한 결과 — graph_weight=0.0 정신. 수치는 있는 그대로.\n")
    return lines


def _render_model_separation(result: MiniEvalResult) -> list[str]:
    lines = ["## 생성↔평가 모델 분리 (ISC-2.8, anti-circular)\n"]
    lines.append(f"- 데이터 생성 모델: `{', '.join(result.gen_models) or '미상'}` (계열: {GEN_MODEL_FAMILY})")
    lines.append(f"- 평가·detector 모델: `{EVAL_DETECTOR_MODEL}` (계열: {EVAL_MODEL_FAMILY})")
    same = GEN_MODEL_FAMILY.split()[0] == EVAL_MODEL_FAMILY.split()[0]
    lines.append(f"- **동일계열 여부: {'같음' if same else '다름'}**")
    if same:
        lines.append("- ⚠ caveat: 생성·평가 동일계열 — '생성문체 순환' 가능성 존재.")
    else:
        lines.append("- 생성(claude)·평가(qwen/bge) 계열 분리 → 생성문체 순환 위험 완화.")
    lines.append("")
    return lines


def _render_frozen_params(result: MiniEvalResult) -> list[str]:
    p = result.params
    lines = ["## 동결 파라미터 (calibration-split 파생·test 동결, ISC-2.6)\n"]
    lines.append(f"- λ(감쇠)={p.lambda_decay}, K(sliding-window)={p.window_size_k}, "
                 f"N(상태 윈도우)={p.state_window_n}, S_max={p.s_max}")
    lines.append(f"- FPR 예산={result.fpr_budget*100:.0f}% (모든 baseline 동일 예산 — 공정성)")
    lines.append("- 임계는 (detector×baseline)별로 C3 calib에서 동일 FPR 예산 충족 최저값으로 동결.\n")
    return lines


def _render_c1_distribution(result: MiniEvalResult) -> list[str]:
    p = result.params
    lens = sorted(s.n_user_turns for s in result.c1_test)
    within = sum(1 for n in lens if n <= p.window_size_k)
    over = sum(1 for n in lens if n > p.window_size_k)
    lines = ["## C1 test 데이터 분포 (ISC-2.7 자연분포·분층 + 표본 확대)\n"]
    lines.append(f"- C1 양성 test 풀: **{len(result.c1_test)}개** "
                 f"(c1.test {result.c1_test_n} + c1.calib 합류 {result.c1_calib_merged})")
    lines.append("- 합류 근거: c1.calib은 C3-FPR 기반 캘리브에 미사용 → C1 누수 없이 양성 표본 확대(검정력 보강).")
    lines.append(f"- user-턴 분포={lens}")
    lines.append(f"- K(={p.window_size_k}) 이내: {within}개 / K 초과(장기복선): {over}개 "
                 f"(K초과 비율 {over/len(lens)*100:.0f}%)")
    lines.append("- 규율: K이내는 B1.5≈STATEFUL 예상(정직 보고), 잔여 우위는 K초과(무한 룩백)에서 기대.\n")
    return lines


def _render_c3_distribution(result: MiniEvalResult) -> list[str]:
    p = result.params
    lens = sorted(s.n_user_turns for s in result.c1_test)
    c3_lens = sorted(s.n_user_turns for s in result.c3_test)
    c3_short = sum(1 for n in c3_lens if n <= p.window_size_k)
    c3_long = sum(1 for n in c3_lens if n > p.window_size_k)
    c1_med = lens[len(lens) // 2]
    c3_med = c3_lens[len(c3_lens) // 2]
    lines = ["## C3 test 데이터 분포 + 길이 교란 통제 (장기-양성 대조군 확대)\n"]
    lines.append(f"- C3 test(오탐 대조군): {result.c3_test_n}개")
    lines.append(f"- 단기 음성(K이내): {c3_short}개 / **장기-양성(K초과, 긴데 정상 해소): {c3_long}개** "
                 "(7→20+ 확대로 길이 교란 통제 검정력 보강)")
    lines.append(f"- C1 중앙값={c1_med}턴 vs C3 중앙값={c3_med}턴")
    lines.append("- **교란 통제 핵심**: STATEFUL 누적식은 길이 비례 증가 → '길어서 위기'가 아니라 "
                 "'에스컬레이션이라 위기'임을 보이려면 '긴데 정상'인 장기-양성에서 오탐하지 않아야 한다.")
    lines.append("- 아래 detector표 testFPR을 **단기음성/장기양성으로 분리** 보고(장기양성 FPR=길이통제 후 진짜 오탐율).\n")
    return lines


def _render_detector_main_table(det_id: str, dr: DetectorResult) -> list[str]:
    lines = [f"## detector = `{det_id}`\n"]
    lines.append("| baseline | 임계 | calibFPR | testFPR | recall(전체) | recall(K이내) | recall(K초과) | TTD(전체) | TTD(K초과) |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for bid in BASELINE_IDS:
        m = dr.metrics[bid]
        lines.append(
            f"| {bid} | {m.threshold:.2f} | {m.calib_fpr*100:.0f}% | {m.test_fpr*100:.0f}% | "
            f"{m.recall_all*100:.0f}% | {m.recall_within_k*100:.0f}% ({m.n_within_k}) | "
            f"{m.recall_over_k*100:.0f}% ({m.n_over_k}) | "
            f"{_fmt(m.ttd_all)} | {_fmt(m.ttd_over_k)} |"
        )
    return lines


def _render_delta_columns(dr: DetectorResult, c1_ids: list[str]) -> list[str]:
    b1 = dr.metrics["B1"]; b15 = dr.metrics["B1.5"]; st = dr.metrics["STATEFUL"]
    lines = ["", "**델타 컬럼 (필수 — STATEFUL 기준):**\n"]
    lines.append("| 비교 | Δrecall(전체) | Δrecall(K초과) | ΔTTD(전체) |")
    lines.append("|---|---|---|---|")
    dttd_b1 = (st.ttd_all - b1.ttd_all) if (st.ttd_all is not None and b1.ttd_all is not None) else None
    dttd_b15 = (st.ttd_all - b15.ttd_all) if (st.ttd_all is not None and b15.ttd_all is not None) else None
    lines.append(f"| STATEFUL − B1 | {_fmt_delta(st.recall_all-b1.recall_all, pct=True)} | "
                 f"{_fmt_delta(st.recall_over_k-b1.recall_over_k, pct=True)} | "
                 f"{('—' if dttd_b1 is None else _fmt_delta(dttd_b1))} |")
    lines.append(f"| STATEFUL − B1.5 | {_fmt_delta(st.recall_all-b15.recall_all, pct=True)} | "
                 f"{_fmt_delta(st.recall_over_k-b15.recall_over_k, pct=True)} | "
                 f"{('—' if dttd_b15 is None else _fmt_delta(dttd_b15))} |")
    lines.append("\n> TTD(time-to-detect)=success_turn−detect_turn, user-턴 단위. 양수=조기 탐지(클수록 좋음).\n")

    # 부트스트랩 CI (ISC-2.3) — recall 델타 신뢰구간
    st_set = set(st.detected_sessions)
    pt_b1, lo_b1, hi_b1 = _bootstrap_delta_ci(c1_ids, st_set, set(b1.detected_sessions))
    pt_b15, lo_b15, hi_b15 = _bootstrap_delta_ci(c1_ids, st_set, set(b15.detected_sessions))
    lines.append("**Δrecall 부트스트랩 95% CI (ISC-2.3, 짝지은 복원추출 "
                 f"{BOOTSTRAP_N}회·seed={BOOTSTRAP_SEED}):**\n")
    lines.append("| 비교 | Δrecall 점추정 | 95% CI |")
    lines.append("|---|---|---|")
    lines.append(f"| STATEFUL − B1 | {_fmt_delta(pt_b1, pct=True)} | "
                 f"[{_fmt_delta(lo_b1, pct=True)}, {_fmt_delta(hi_b1, pct=True)}] |")
    lines.append(f"| STATEFUL − B1.5 | {_fmt_delta(pt_b15, pct=True)} | "
                 f"[{_fmt_delta(lo_b15, pct=True)}, {_fmt_delta(hi_b15, pct=True)}] |")
    ci_excl = lo_b15 > 0
    lines.append(f"\n> 사활 컬럼(vs B1.5) CI {'하한>0 → 부호가 0을 배제(유의)' if ci_excl else '0을 포함(비유의 가능)'}. "
                 "점추정 부호와 함께 CI로 불확실성을 정직 노출.\n")
    return lines


def _render_matched_operating_points(dr: DetectorResult) -> list[str]:
    """동일 작동점(matched test-FPR)에서 recall 재비교 (critic 최강 지적)."""
    lines = ["**동일 작동점(matched test-FPR) recall 재비교 (작동점 정렬 — critic 지적):**\n"]
    lines.append("> 임계를 동일 FPR 예산이 아니라 동일 test-FPR로 맞춘 뒤 recall 비교. "
                 "'STATEFUL FPR≠B1.5 FPR이라 recall 비교 불공정'에 답한다.\n")
    lines.append("| target FPR | B1 recall (FPR) | B1.5 recall (FPR) | STATEFUL recall (FPR) | **ΔSTATEFUL−B1.5** |")
    lines.append("|---|---|---|---|---|")
    for op in dr.matched_ops:
        b1_t, b1_f, b1_r = op.by_baseline["B1"]
        b15_t, b15_f, b15_r = op.by_baseline["B1.5"]
        st_t, st_f, st_r = op.by_baseline["STATEFUL"]
        lines.append(
            f"| ≤{op.target_fpr*100:.0f}% | {b1_r*100:.0f}% ({b1_f*100:.0f}%) | "
            f"{b15_r*100:.0f}% ({b15_f*100:.0f}%) | {st_r*100:.0f}% ({st_f*100:.0f}%) | "
            f"**{_fmt_delta(st_r-b15_r, pct=True)}** |"
        )
    lines.append("\n> 괄호=해당 임계에서 실제 달성 test-FPR. 같은 FPR 예산에서도 ΔSTATEFUL−B1.5가 "
                 "양수면 작동점 정렬 후에도 우위가 유지된다는 증거.\n")
    return lines


def _render_fpr_stratified(dr: DetectorResult) -> list[str]:
    lines = ["**testFPR 분층 (길이 교란 통제 — 장기-양성에서의 오탐이 진짜 FPR):**\n"]
    lines.append("| baseline | testFPR(전체) | FPR(단기음성 K이내) | **FPR(장기양성 K초과)** |")
    lines.append("|---|---|---|---|")
    for bid in BASELINE_IDS:
        m = dr.metrics[bid]
        lines.append(
            f"| {bid} | {m.test_fpr*100:.0f}% ({m.fp_short + m.fp_long}/{m.n_c3_short + m.n_c3_long}) | "
            f"{m.test_fpr_short*100:.0f}% ({m.fp_short}/{m.n_c3_short}) | "
            f"**{m.test_fpr_long*100:.0f}% ({m.fp_long}/{m.n_c3_long})** |"
        )
    lines.append("\n> 장기양성 FPR = '긴데 정상 해소' 세션에서의 오탐율. 이 값이 낮아야 STATEFUL의 "
                 "위기탐지가 '세션 길이'가 아니라 '에스컬레이션'을 잡는 것임이 통제된다.\n")
    return lines


def _render_verdicts(result: MiniEvalResult) -> list[str]:
    verdicts = thesis_verdict(result)
    lines = ["## Thesis 판정 (정직 — 수치 근거)\n"]
    lines.append("> 판정 규율: **'성립'은 사활 컬럼(vs B1.5) McNemar exact p<0.05일 때만**. "
                 "유의 아니면 '방향성 지지(비유의)' — 점추정 부호만으로 성립 선언 금지.\n")
    for det_id, v in verdicts.items():
        lines.append(f"### detector=`{det_id}` → **{v['verdict']}**")
        lines.append(f"- Δrecall(STATEFUL−B1, 전체)={_fmt_delta(v['delta_recall_b1_all'], pct=True)}")
        lines.append(f"- Δrecall(STATEFUL−B1.5, 전체)={_fmt_delta(v['delta_recall_b15_all'], pct=True)}  ← 사활 컬럼")
        lines.append(f"- Δrecall(STATEFUL−B1.5) 95% CI=[{_fmt_delta(v['boot_ci_b15_low'], pct=True)}, "
                     f"{_fmt_delta(v['boot_ci_b15_high'], pct=True)}]  ← 부트스트랩(ISC-2.3)")
        lines.append(f"- Δrecall(STATEFUL−B1.5, K초과)={_fmt_delta(v['delta_recall_b15_over_k'], pct=True)}  ← 무한룩백 잔여우위(recall)")
        dttd = v.get("delta_ttd_b15_all")
        dttd_o = v.get("delta_ttd_b15_over_k")
        lines.append(f"- ΔTTD(STATEFUL−B1.5, 전체)={'—' if dttd is None else _fmt_delta(dttd)} "
                     f"/ K초과={'—' if dttd_o is None else _fmt_delta(dttd_o)}  ← 조기탐지 축(양수=STATEFUL이 더 이른 턴에 탐지)")
        lines.append(f"- **McNemar exact (STATEFUL vs B1.5): p={v['mcnemar_p_b15']:.3f}** "
                     f"(불일치쌍 b={v['mcnemar_b_b15']}·c={v['mcnemar_c_b15']}; "
                     f"b=STATEFUL만 탐지, c=B1.5만 탐지) ← 사활 유의성")
        lines.append(f"- McNemar exact (STATEFUL vs B1): p={v['mcnemar_p_b1']:.3f} "
                     f"(불일치쌍 b={v['mcnemar_b_b1']}·c={v['mcnemar_c_b1']})")
        sig15 = "유의(p<0.05)" if v['mcnemar_p_b15'] < SIG_ALPHA else "비유의(p≥0.05)"
        lines.append(f"- → vs B1.5 {sig15}")
        lines.append("")
    lines.extend(_render_verdict_summary(result, verdicts))
    return lines


def _render_verdict_summary(result: MiniEvalResult, verdicts: dict) -> list[str]:
    aware_v = verdicts.get("target_aware", {}).get("verdict", "")
    agno_v = verdicts.get("target_agnostic", {}).get("verdict", "")
    all_v = list(verdicts.values())
    any_strict = any(x["verdict"] == "성립" for x in all_v)
    all_strict = all(x["verdict"] == "성립" for x in all_v)
    any_direction = any(x["verdict"].startswith("방향성") for x in all_v)
    lines = ["### 종합 (정직 결론)"]
    lines.append(f"- target_aware: {aware_v} / target_agnostic: {agno_v}")
    lines.append("- 두 detector 모두 유의 성립이면 자기충족(circular) 아님. 한쪽만/방향성/미성립이면 그대로 정직 보고.")
    if all_strict:
        lines.append("- **두 detector 모두 사활 컬럼(vs B1.5)에서 McNemar p<0.05 유의 → thesis 성립**(소표본 caveat 하).")
    elif any_strict:
        sig_dets = [d for d, x in verdicts.items() if x["verdict"] == "성립"]
        dir_dets = [d for d, x in verdicts.items() if x["verdict"].startswith("방향성")]
        lines.append(f"- **{', '.join(sig_dets)}만 사활 컬럼 유의(p<0.05)로 성립**, "
                     f"{', '.join(dir_dets) or '나머지'}는 방향성 지지(비유의). "
                     "→ '유의 성립 detector만 한정 성립, 나머지는 방향성'으로 정직 보고(graph_weight=0.0 정신).")
    elif any_direction:
        lines.append("- **어느 detector도 사활 컬럼(vs B1.5)에서 유의(p<0.05)에 도달 못 함 → thesis 미성립(유의 기준).** "
                     "점추정상 우위 방향은 있으나 소표본 McNemar로 유의하지 않음 → '방향성 지지(비유의)'로만 정직 보고.")
    else:
        lines.append("- **STATEFUL이 B1.5를 recall·TTD 어디서도 못 이김 → thesis 미성립을 정직 보고**(graph_weight=0.0 정신).")
    if not all_strict:
        lines.append("- 미성립/방향성의 엔지니어링적 이유 후보: 소표본으로 불일치쌍이 적어 McNemar 검정력이 낮거나,"
                     " 임계가 calib에 과적합되어 과탐하거나, 누적이 정상 세션에서도 포화해 임계가 밀려 미탐할 수 있으며,"
                     " 드리프트 신호의 정상/위기 분리력에 한계가 있다(detector별 수치로 판단).")
    lines.append("- **장기-양성(긴데 정상) 오탐 비용 정직 명시 — recall 우위는 공짜가 아니다:**")
    for det_id, dr in result.by_detector.items():
        st = dr.metrics["STATEFUL"]; b15 = dr.metrics["B1.5"]
        flag = " ⚠초과" if st.test_fpr_long > result.fpr_budget else ""
        lines.append(
            f"  - `{det_id}`: STATEFUL 장기양성 FPR={st.test_fpr_long*100:.0f}% "
            f"({st.fp_long}/{st.n_c3_long}){flag} vs B1.5 {b15.test_fpr_long*100:.0f}% "
            f"({b15.fp_long}/{b15.n_c3_long}). "
            f"calib 예산 {result.fpr_budget*100:.0f}%는 단기 위주 calib에서 동결되어 장기-양성 FPR을 직접 보장하지 않는다."
        )
    n_c1 = len(result.c1_test)
    lines.append(f"\n> ⚠ 소표본 caveat: C1 양성 풀 {n_c1}세션·C3 test {result.c3_test_n}세션. 표본을 확대했으나"
                 " 여전히 점추정이다. McNemar는 불일치쌍에만 의존하므로 표본이 작으면 검정력이 낮다(유의=강증거, 비유의≠반증).")
    lines.append("")
    return lines


def render_report(result: MiniEvalResult) -> str:
    """미니-eval 결과를 마크다운 리포트로 렌더링한다 (out/mini.md). 섹션 조립만 담당."""
    c1_ids = [s.session_id for s in result.c1_test]
    lines: list[str] = []
    lines += _render_header(result)
    lines += _render_model_separation(result)
    lines += _render_frozen_params(result)
    lines += _render_c1_distribution(result)
    lines += _render_c3_distribution(result)
    for det_id, dr in result.by_detector.items():
        lines += _render_detector_main_table(det_id, dr)
        lines += _render_delta_columns(dr, c1_ids)
        lines += _render_matched_operating_points(dr)
        lines += _render_fpr_stratified(dr)
    lines += _render_verdicts(result)
    return "\n".join(lines)


def write_report(result: MiniEvalResult, report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")


# ---------------------------------------------------------------------------
# Thesis 판정
# ---------------------------------------------------------------------------

class ThesisVerdict(TypedDict):
    """thesis_verdict 단일 detector 판정 레코드 (dict 접근 호환 유지)."""
    verdict: str
    delta_recall_b1_all: float
    delta_recall_b15_all: float
    delta_recall_b15_over_k: float
    delta_ttd_b15_all: float | None
    delta_ttd_b15_over_k: float | None
    mcnemar_p_b1: float
    mcnemar_b_b1: int
    mcnemar_c_b1: int
    mcnemar_p_b15: float
    mcnemar_b_b15: int
    mcnemar_c_b15: int
    boot_ci_b15_low: float
    boot_ci_b15_high: float


def thesis_verdict(result: MiniEvalResult) -> dict[str, ThesisVerdict]:
    """STATEFUL vs B1/B1.5 델타 + McNemar 유의성으로 thesis 판정.

    판정 규율(점추정 부호 과대진술 차단):
      성립         : recall이 B1·B1.5 모두 우위 AND **사활 컬럼(vs B1.5) McNemar p<0.05**.
                     점추정 부호만으로는 성립 선언하지 않는다.
      방향성 지지  : recall/TTD가 B1.5 대비 우위 방향이나 유의(p<0.05)는 아님(비유의).
                     소표본에서 흔한 결과 — 방향 증거로만 정직 보고.
      미성립       : 우위 방향이 없거나 열위.
    미성립·방향성 지지도 유효 결과 — 정직 보고(graph_weight=0.0 정신).
    """
    c1_ids = [s.session_id for s in result.c1_test]
    verdicts: dict[str, ThesisVerdict] = {}
    for det_id, dr in result.by_detector.items():
        b1 = dr.metrics["B1"]
        b15 = dr.metrics["B1.5"]
        st = dr.metrics["STATEFUL"]
        d_b1_all = st.recall_all - b1.recall_all
        d_b15_all = st.recall_all - b15.recall_all
        d_b15_over = st.recall_over_k - b15.recall_over_k

        def _ttd_delta(a, b):
            if a is None or b is None:
                return None
            return a - b
        dttd_b15_all = _ttd_delta(st.ttd_all, b15.ttd_all)
        dttd_b15_over = _ttd_delta(st.ttd_over_k, b15.ttd_over_k)

        # McNemar exact — 짝지은 탐지 불일치쌍 (STATEFUL vs B1, vs B1.5)
        b_b1, c_b1 = _discordant(st.detected_sessions, b1.detected_sessions)
        p_b1 = mcnemar_exact(b_b1, c_b1)
        b_b15, c_b15 = _discordant(st.detected_sessions, b15.detected_sessions)
        p_b15 = mcnemar_exact(b_b15, c_b15)

        # 부트스트랩 CI (사활 컬럼 Δrecall vs B1.5)
        _, lo_b15, hi_b15 = _bootstrap_delta_ci(
            c1_ids, set(st.detected_sessions), set(b15.detected_sessions)
        )

        # 우위 방향(recall 또는 K초과 recall 또는 조기탐지)
        has_direction = (
            d_b15_all > 0
            or d_b15_over > 0
            or (d_b15_all >= 0 and dttd_b15_all is not None and dttd_b15_all > 0)
        )

        if d_b1_all > 0 and d_b15_all > 0 and p_b15 < SIG_ALPHA:
            v = "성립"
        elif has_direction:
            v = "방향성 지지(비유의)"
        else:
            v = "미성립"
        verdicts[det_id] = ThesisVerdict(
            verdict=v,
            delta_recall_b1_all=d_b1_all,
            delta_recall_b15_all=d_b15_all,
            delta_recall_b15_over_k=d_b15_over,
            delta_ttd_b15_all=dttd_b15_all,
            delta_ttd_b15_over_k=dttd_b15_over,
            mcnemar_p_b1=p_b1,
            mcnemar_b_b1=b_b1,
            mcnemar_c_b1=c_b1,
            mcnemar_p_b15=p_b15,
            mcnemar_b_b15=b_b15,
            mcnemar_c_b15=c_b15,
            boot_ci_b15_low=lo_b15,
            boot_ci_b15_high=hi_b15,
        )
    return verdicts
