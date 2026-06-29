"""pipeline.policies — stateless 정책 카탈로그 (Phase 1).

레이어 규칙: core + adapters import 가능. interfaces import 금지. httpx 직접 호출 금지.

Phase 1 범위: C1(누적 위기 에스컬레이션) 탐지용 stateless per-turn detector 2종.
  P-RULE-ESC-01 — 규칙 기반 불만·이탈 신호 탐지 (결정적, 비용 0)
  P-LLM-ESC-01  — LLM 기반 불만·이탈 강도 분류 (qwen2.5:14b, temperature=0)

공정 강baseline 규율(P2-2): stateless detector를 약하게 만들지 않는다.
허수아비 baseline 금지 — 합리적으로 강한 per-turn 판정(명시적 불만·이탈 표현은 강하게 잡는다).
단, thesis 사활점은 '개별 메시지는 약한 불만, 누적되어야 위기'이므로 per-turn 단발로는
강한 명시 신호만 잡히고 점진 누적 불만은 STATEFUL이 잡는 구조다.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from stateful_guardrails.core.policy import (
    Message,
    PolicySignal,
    RiskCategory,
    SessionState,
    SuggestedAction,
)

if TYPE_CHECKING:
    from stateful_guardrails.core.llm import LLMAdapter


# ---------------------------------------------------------------------------
# 규칙 기반 패턴 (P-RULE-ESC-01)
# 고객 불만·부정 감정·이탈 의사 신호 목록. (pattern, risk_score) 쌍.
# 공정 강baseline 규율: 명시적 이탈·격분 표현은 강하게(per-turn) 잡는다.
# ---------------------------------------------------------------------------
_ESCALATION_RULES: list[tuple[re.Pattern[str], float]] = [
    # --- 명시적 이탈/계약 종료 의사 (강) ---
    (re.compile(r"환불\s*(해|받|요청|처리|해줘|해주세요)?", re.I), 0.95),
    (re.compile(r"(해지|해약)\s*(할|하겠|해줘|요청|처리)?", re.I), 0.95),
    (re.compile(r"(계약|구독|멤버십|서비스)\s*(을|를)?\s*(취소|중단|끊)", re.I), 0.92),
    (re.compile(r"탈퇴\s*(할|하겠|하고|처리)?", re.I), 0.90),
    (re.compile(r"(이제)?\s*그만\s*(두|둘|둬|쓰|쓸|써|씁|할|하겠|관둘|관두)", re.I), 0.90),
    (re.compile(r"다\s*(시|신)\s*(는|은)?.{0,12}?안\s*(쓰|쓸|써|씁|이용|구매|구입|사|살|삽|샀|봐|보|봅|올|와)", re.I), 0.92),
    (re.compile(r"(다른|타)\s*(업체|회사|서비스|곳)\s*(으로|로)?\s*(갈|옮|바꾸|넘어)", re.I), 0.88),
    # --- 격분/극단 부정 (강) ---
    (re.compile(r"최악", re.I), 0.88),
    (re.compile(r"사기\s*(아니|아닌|꾼|당|같|예요|네요|치)", re.I), 0.90),
    (re.compile(r"(고소|법적\s*대응|소송)", re.I), 0.92),
    (re.compile(r"(소비자(원|보호원)|신고|민원)", re.I), 0.85),
    (re.compile(r"어이(가)?\s*없", re.I), 0.80),
    (re.compile(r"두\s*번\s*다시", re.I), 0.82),
    (re.compile(r"진짜\s*너무\s*하", re.I), 0.80),
    # --- 부정 감정 (중) ---
    (re.compile(r"실망", re.I), 0.62),
    (re.compile(r"(화가\s*나|화나|빡|짜증)", re.I), 0.60),
    (re.compile(r"불만", re.I), 0.58),
    (re.compile(r"답답", re.I), 0.55),
    (re.compile(r"별로(예요|네요|입니다|다)", re.I), 0.55),
    (re.compile(r"불친절", re.I), 0.60),
    # --- 약한 불만/반복 호소 (약) ---
    (re.compile(r"아직(도)?\s*(안|못)", re.I), 0.40),
    (re.compile(r"언제까지\s*(기다|해야)", re.I), 0.42),
    (re.compile(r"또\s*(안|밀리|늦|문제)", re.I), 0.40),
    (re.compile(r"왜\s*(안|아직|이렇게)", re.I), 0.38),
    (re.compile(r"몇\s*번(을|째)", re.I), 0.42),
]


class RuleKeywordEscalationPolicy:
    """P-RULE-ESC-01 — 규칙 기반 불만·이탈 신호 탐지기.

    결정적(deterministic): 같은 입력 → 같은 출력 보장.
    비용: O(패턴 수 × 텍스트 길이), 외부 호출 없음.
    category: ESCALATION (C1·이탈 신호 모두 커버)
    is_stateful: False — session_state 불참조.
    """

    id: str = "P-RULE-ESC-01"
    category: RiskCategory = RiskCategory.ESCALATION
    is_stateful: bool = False

    def evaluate(
        self,
        message: Message,
        session_state: SessionState | None = None,
    ) -> PolicySignal:
        """규칙 매칭으로 불만·이탈 risk를 반환한다."""
        text = message.text
        max_risk = 0.0
        matched_patterns: list[str] = []

        for pattern, risk in _ESCALATION_RULES:
            if pattern.search(text):
                if risk > max_risk:
                    max_risk = risk
                matched_patterns.append(pattern.pattern)

        if max_risk >= 0.85:
            # 명시적 이탈·격분 신호 → 매니저·이탈방지팀 에스컬레이션
            action = SuggestedAction.ESCALATE
            evidence = f"규칙 매칭(강): {matched_patterns[:3]!r}"
        elif max_risk > 0:
            # 부정 감정·약한 불만 → 상담사 이관 큐
            action = SuggestedAction.FLAG
            evidence = f"규칙 매칭: {matched_patterns[:3]!r}"
        else:
            action = SuggestedAction.PASS
            evidence = "매칭 없음"

        return PolicySignal(
            risk=max_risk,
            evidence=evidence,
            suggested_action=action,
            policy_id=self.id,
        )


# ---------------------------------------------------------------------------
# LLM 기반 분류기 (P-LLM-ESC-01)
# ---------------------------------------------------------------------------

_LLM_CLASSIFY_PROMPT = """\
당신은 고객 불만·이탈 신호 분석가입니다. 아래 고객 메시지에서 불만·부정 감정·\
이탈(해지/환불/거래 중단/타사 이동) 의사의 강도를 판단하세요.

메시지:
{text}

분류 규칙:
- "high": 격분, 명시적 이탈·해지·환불 요구, 강한 실망 등 위기 신호가 뚜렷하거나 강하게 의심됨
- "low": 단순 문의, 정상적 대화, 또는 약한 불만에 그침

반드시 "high" 또는 "low" 중 하나만 출력하고, 다른 설명 없이 단어 하나만 출력하세요.
"""


class LLMClassifyEscalationPolicy:
    """P-LLM-ESC-01 — LLM 기반 불만·이탈 강도 분류기 (qwen2.5:14b).

    temperature=0으로 호출해 결정성을 최대화한다.
    adapter를 주입하지 않으면 OllamaAdapter를 지연 초기화한다 (테스트에서 mock 주입 가능).
    category: ESCALATION
    is_stateful: False — session_state 불참조.
    """

    id: str = "P-LLM-ESC-01"
    category: RiskCategory = RiskCategory.ESCALATION
    is_stateful: bool = False

    def __init__(self, adapter: LLMAdapter | None = None) -> None:
        self._adapter = adapter
        self._model = "qwen2.5:14b"

    def _get_adapter(self) -> LLMAdapter:
        if self._adapter is None:
            from stateful_guardrails.adapters.llm import OllamaAdapter
            self._adapter = OllamaAdapter(model=self._model)
        return self._adapter

    def evaluate(
        self,
        message: Message,
        session_state: SessionState | None = None,
    ) -> PolicySignal:
        """LLM으로 불만·이탈 강도를 분류하고 risk signal을 반환한다."""
        prompt = _LLM_CLASSIFY_PROMPT.format(text=message.text)
        adapter = self._get_adapter()

        try:
            raw = adapter.complete(prompt).strip().lower()
        except Exception as exc:
            # LLM 호출 실패 시 안전하게 중간 위험도 반환
            return PolicySignal(
                risk=0.5,
                evidence=f"LLM 호출 오류 (fallback): {exc}",
                suggested_action=SuggestedAction.FLAG,
                policy_id=self.id,
            )

        is_high = "high" in raw

        if is_high:
            risk = 0.85
            action = SuggestedAction.ESCALATE
            evidence = f"LLM 분류: high (원문: {raw[:50]!r})"
        else:
            risk = 0.05
            action = SuggestedAction.PASS
            evidence = f"LLM 분류: low (원문: {raw[:50]!r})"

        return PolicySignal(
            risk=risk,
            evidence=evidence,
            suggested_action=action,
            policy_id=self.id,
        )
