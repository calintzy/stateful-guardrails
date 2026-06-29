"""pipeline.escalation — 에스컬레이션 3단계 결정 (탐지 → 액션, 운영 가치 레이어).

목적(독립 추가): 측정 thesis가 보인 '조기 탐지'를 '선제 이관'이라는 구체 액션으로
연결한다. 누적 위기 점수 S_t를 동결 임계 t1·t2에 매핑해 3단계로 라우팅한다.

  S_t < t1            → STAGE 0 (봇 자동응대)
  t1 ≤ S_t < t2       → STAGE 1 (상담사 이관)
  S_t ≥ t2            → STAGE 2 (매니저·이탈방지팀 이관)

핵심 가치: stateless 단발(B1)은 매 턴 독립이라 '언제 사람에게 넘길지'를 누적으로
결정 못 한다. 약한 불만이 여러 턴 쌓이면 STATEFUL은 명시적 위기 선언(환불·해지) *이전에*
선제 이관할 수 있다 — 조기 탐지가 '그래서 가능하게 하는 액션'이다.

설계 규율(.ai.md):
  - 결정적(deterministic). LLM 자율 결정 금지 → 감사 로그 재현 가능.
  - 신호는 규칙 기반 per-turn risk(임베딩·LLM 불요)를 누적식 S_t로 집계한다.
  - 동결 파라미터(t1·t2·λ·S_max) 재사용. 재튜닝 금지.

측정 규율 불변: 본 모듈은 mini.md 측정 파이프라인을 건드리지 않는다(독립 운영 레이어).

레이어 규칙: core + adapters import 가능. interfaces import 금지.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from stateful_guardrails.core.policy import Message
from stateful_guardrails.core.state import update_cumulative
from stateful_guardrails.pipeline.engine import EngineParams
from stateful_guardrails.pipeline.policies import RuleKeywordEscalationPolicy

# ---------------------------------------------------------------------------
# 에스컬레이션 단계 정의 (재번호 금지 — 감사 로그 안정 키)
# ---------------------------------------------------------------------------

STAGE_BOT = 0       # 봇 자동응대 — 위기 신호 누적 미달
STAGE_AGENT = 1     # 상담사 이관 — 누적 위기 t1 도달
STAGE_MANAGER = 2   # 매니저·이탈방지팀 이관 — 누적 위기 t2 도달

STAGE_LABELS: dict[int, str] = {
    STAGE_BOT: "봇 자동응대",
    STAGE_AGENT: "상담사 이관",
    STAGE_MANAGER: "매니저·이탈방지팀 이관",
}

# 기본 데이터 디렉토리(세션 ID 검색용)
_DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_KNOWN_DATA_FILES = ["c1.test.jsonl", "c1.calib.jsonl", "c3.test.jsonl", "c3.calib.jsonl"]


# ---------------------------------------------------------------------------
# 결과 레코드
# ---------------------------------------------------------------------------

@dataclass
class TurnEscalation:
    """단일 턴의 에스컬레이션 판정 레코드 (감사 추적, ISC-4.2)."""
    turn_ordinal: int        # user-턴 0-based 순서
    user_text: str
    risk: float              # per-turn 규칙 risk = signal_t (stateless 단발 신호)
    cumulative_score: float  # STATEFUL 누적 S_t
    stage: int               # STATEFUL 누적 기준 단계 (0/1/2)
    b1_stage: int            # per-turn(stateless) 단독 기준 단계 — 비교용
    reason: str              # 판정 근거(규칙 증거 + 누적값 + 단계 전이)


@dataclass
class EscalationResult:
    """세션 전체 에스컬레이션 시퀀스 + 최초 이관 권고 턴."""
    session_id: str
    turns: list[TurnEscalation]
    t1: float
    t2: float
    params: EngineParams
    # STATEFUL 누적 기준 최초 이관/매니저 권고 턴 (없으면 None)
    first_handoff_turn: int | None = None       # stage ≥ 1 최초 user-턴
    first_manager_turn: int | None = None       # stage ≥ 2 최초 user-턴
    # per-turn(stateless) 단독 기준 — 선제성 비교용
    b1_first_handoff_turn: int | None = None
    b1_first_manager_turn: int | None = None
    category: str = ""
    label: str = ""
    generation_model: str = ""


# ---------------------------------------------------------------------------
# 핵심 순수 로직
# ---------------------------------------------------------------------------

def stage_for_score(score: float, t1: float, t2: float) -> int:
    """누적 위기 점수를 3단계로 매핑한다 (경계 포함: t1·t2 이상이면 승급).

    score < t1        → STAGE_BOT(0)
    t1 ≤ score < t2   → STAGE_AGENT(1)
    score ≥ t2        → STAGE_MANAGER(2)
    """
    if score >= t2:
        return STAGE_MANAGER
    if score >= t1:
        return STAGE_AGENT
    return STAGE_BOT


def escalate_session(
    user_texts: list[str],
    t1: float,
    t2: float,
    params: EngineParams,
    session_id: str = "",
    policy: RuleKeywordEscalationPolicy | None = None,
) -> EscalationResult:
    """세션을 턴별로 흘리며 각 턴의 에스컬레이션 단계와 최초 이관 권고 턴을 산출한다.

    결정적: 동일 입력 → 동일 출력 (규칙 정책 + 누적식, 외부 호출 없음).
    STATEFUL 단계는 누적 S_t 기준, B1 단계는 per-turn risk 단독 기준으로 병렬 산출해
    '누적이 단발보다 더 이른 턴에 사람에게 넘긴다'는 선제성을 가시화한다.
    """
    policy = policy or RuleKeywordEscalationPolicy()
    turns: list[TurnEscalation] = []
    s = 0.0
    prev_stage = STAGE_BOT
    first_handoff = first_manager = None
    b1_first_handoff = b1_first_manager = None

    for i, text in enumerate(user_texts):
        signal = policy.evaluate(Message(text=text, turn_index=i))
        risk = signal.risk
        s = update_cumulative(s, risk, params.lambda_decay, params.s_max)
        stage = stage_for_score(s, t1, t2)
        b1_stage = stage_for_score(risk, t1, t2)

        # 최초 이관 권고 턴 (STATEFUL 누적 기준)
        if stage >= STAGE_AGENT and first_handoff is None:
            first_handoff = i
        if stage >= STAGE_MANAGER and first_manager is None:
            first_manager = i
        # per-turn(stateless) 단독 기준
        if b1_stage >= STAGE_AGENT and b1_first_handoff is None:
            b1_first_handoff = i
        if b1_stage >= STAGE_MANAGER and b1_first_manager is None:
            b1_first_manager = i

        transition = ""
        if stage != prev_stage:
            transition = (
                f" | 단계 전이 {STAGE_LABELS[prev_stage]}→{STAGE_LABELS[stage]}"
            )
        reason = (
            f"signal={risk:.2f}({signal.evidence}); "
            f"S_t={s:.2f} vs t1={t1}/t2={t2} → {STAGE_LABELS[stage]}{transition}"
        )
        turns.append(TurnEscalation(
            turn_ordinal=i,
            user_text=text,
            risk=risk,
            cumulative_score=s,
            stage=stage,
            b1_stage=b1_stage,
            reason=reason,
        ))
        prev_stage = stage

    return EscalationResult(
        session_id=session_id,
        turns=turns,
        t1=t1,
        t2=t2,
        params=params,
        first_handoff_turn=first_handoff,
        first_manager_turn=first_manager,
        b1_first_handoff_turn=b1_first_handoff,
        b1_first_manager_turn=b1_first_manager,
    )


# ---------------------------------------------------------------------------
# 세션 로드 (세션 ID 또는 파일 경로)
# ---------------------------------------------------------------------------

def _session_to_texts(d: dict) -> tuple[list[str], str, str, str]:
    user_texts = [m["text"] for m in d.get("messages", []) if m.get("role") == "user"]
    return user_texts, d.get("category", ""), d.get("label", ""), d.get("generation_model", "")


def load_session(
    session_ref: str,
    data_dir: Path | None = None,
) -> tuple[str, list[str], str, str, str]:
    """세션 ID 또는 .jsonl 파일 경로로 세션을 로드한다.

    session_ref가 존재하는 .jsonl 경로면 그 파일의 첫 세션을 사용한다.
    아니면 세션 ID로 보고 data_dir의 알려진 데이터 파일에서 검색한다.
    반환: (session_id, user_texts, category, label, generation_model).
    """
    data_dir = data_dir or _DEFAULT_DATA_DIR

    ref_path = Path(session_ref)
    if ref_path.suffix == ".jsonl" and ref_path.exists():
        for line in ref_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            ut, cat, lab, gm = _session_to_texts(d)
            return d.get("session_id", ref_path.stem), ut, cat, lab, gm
        raise ValueError(f"빈 파일: {session_ref}")

    # 세션 ID 검색
    for fname in _KNOWN_DATA_FILES:
        fpath = data_dir / fname
        if not fpath.exists():
            continue
        for line in fpath.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("session_id") == session_ref:
                ut, cat, lab, gm = _session_to_texts(d)
                return session_ref, ut, cat, lab, gm
    raise ValueError(
        f"세션을 찾을 수 없음: {session_ref!r} "
        f"(data_dir={data_dir}의 {_KNOWN_DATA_FILES}에서 미발견, .jsonl 경로도 아님)"
    )


def escalate_ref(
    session_ref: str,
    t1: float,
    t2: float,
    params: EngineParams,
    data_dir: Path | None = None,
) -> EscalationResult:
    """세션 ID/파일 경로를 로드해 에스컬레이션을 산출한다 (CLI 진입용)."""
    sid, user_texts, cat, lab, gm = load_session(session_ref, data_dir=data_dir)
    result = escalate_session(user_texts, t1, t2, params, session_id=sid)
    result.category = cat
    result.label = lab
    result.generation_model = gm
    return result


# ---------------------------------------------------------------------------
# 렌더링 (CLI 출력 + 감사 로그 ISC-4.2)
# ---------------------------------------------------------------------------

def render_escalation(result: EscalationResult) -> str:
    """턴별 위기점수·단계 + 최초 이관 권고 + 선제성 비교를 텍스트로 렌더링한다."""
    lines: list[str] = []
    lines.append(f"=== 에스컬레이션 3단계 데모 — 세션 {result.session_id} ===")
    if result.category or result.label:
        lines.append(f"category={result.category} label={result.label} "
                     f"gen={result.generation_model or '미상'}")
    p = result.params
    lines.append(f"동결 임계: t1={result.t1}(상담사) / t2={result.t2}(매니저)  "
                 f"| λ={p.lambda_decay} S_max={p.s_max}  (재튜닝 없음)")
    lines.append("매핑: S_t<t1=봇 자동응대 / t1≤S_t<t2=상담사 이관 / S_t≥t2=매니저 이관")
    lines.append("")
    lines.append(f"  {'턴':>3}  {'risk':>5}  {'S_t':>5}  {'STATEFUL 단계':<14}  {'B1(단발) 단계':<14}")
    lines.append(f"  {'-'*3}  {'-'*5}  {'-'*5}  {'-'*14}  {'-'*14}")
    for t in result.turns:
        lines.append(
            f"  {t.turn_ordinal:>3}  {t.risk:>5.2f}  {t.cumulative_score:>5.2f}  "
            f"{STAGE_LABELS[t.stage]:<14}  {STAGE_LABELS[t.b1_stage]:<14}"
        )
    lines.append("")
    lines.append(_handoff_summary(result))
    return "\n".join(lines)


def _turn_str(turn: int | None) -> str:
    return f"{turn}번째 턴" if turn is not None else "권고 없음"


def _handoff_summary(result: EscalationResult) -> str:
    """최초 이관 권고 턴 + 선제성(누적이 단발보다 이른가) 요약."""
    lines: list[str] = ["[이관 권고]"]
    lines.append(f"  STATEFUL(누적): 상담사 이관 = {_turn_str(result.first_handoff_turn)}"
                 f" / 매니저 이관 = {_turn_str(result.first_manager_turn)}")
    lines.append(f"  B1(stateless 단발): 상담사 이관 = {_turn_str(result.b1_first_handoff_turn)}"
                 f" / 매니저 이관 = {_turn_str(result.b1_first_manager_turn)}")
    # 선제성 판정 (상담사 이관 기준)
    st, b1 = result.first_handoff_turn, result.b1_first_handoff_turn
    if st is not None and b1 is not None and st < b1:
        lines.append(f"  → 선제 이관: STATEFUL이 B1보다 {b1 - st}턴 일찍 상담사에 넘긴다 "
                     "(약한 불만 누적이 명시적 위기 선언 *이전에* 사람 개입을 유도).")
    elif st is not None and b1 is None:
        lines.append("  → 선제 이관: STATEFUL은 이관했으나 B1(단발)은 끝까지 이관 못 함 "
                     "(누적만이 점진 불만을 위기로 판정).")
    else:
        lines.append("  → 이 세션은 누적·단발 이관 시점이 동일하다(정직 보고). "
                     "선제성은 약한 불만이 여러 턴 쌓이는 세션에서 드러난다.")
    return "\n".join(lines)


def render_audit(result: EscalationResult) -> str:
    """감사 로그 (ISC-4.2): 각 턴의 판정·조치·증거를 추적 가능한 레코드로 출력한다."""
    lines: list[str] = []
    lines.append(f"=== 감사 로그 (ISC-4.2) — 세션 {result.session_id} ===")
    lines.append(f"동결 임계 t1={result.t1} t2={result.t2} | λ={result.params.lambda_decay} "
                 f"S_max={result.params.s_max} | 결정적·재현 가능")
    lines.append("")
    for t in result.turns:
        action = STAGE_LABELS[t.stage]
        lines.append(f"[턴 {t.turn_ordinal}] 조치={action} (stage={t.stage})")
        lines.append(f"  메시지: {t.user_text}")
        lines.append(f"  근거  : {t.reason}")
    lines.append("")
    lines.append(f"최초 상담사 이관: {_turn_str(result.first_handoff_turn)} | "
                 f"최초 매니저 이관: {_turn_str(result.first_manager_turn)}")
    return "\n".join(lines)
