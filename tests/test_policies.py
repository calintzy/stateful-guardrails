"""ISC-1.2: 전 정책 계약 테스트.

검증 계약:
1. 모든 정책이 Policy Protocol을 충족한다 (id, category, is_stateful 속성 존재).
2. evaluate() 반환값이 PolicySignal이며 risk ∈ [0.0, 1.0].
3. 규칙 기반 정책은 결정적이다 (같은 입력 → 같은 출력).
4. stateless 정책은 session_state=None과 SessionState 주입 시 모두 동작한다.
5. 명시적 불만·이탈 신호 메시지는 높은 risk를 반환한다 (공정 강baseline 규율).
6. 정상 문의 메시지는 낮은 risk를 반환한다 (과탐 방지).
7. LLM 정책은 어댑터를 주입받아 단위 테스트가 가능하다.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stateful_guardrails.core.policy import (
    Message,
    Policy,
    PolicySignal,
    RiskCategory,
    SessionState,
    SuggestedAction,
)
from stateful_guardrails.pipeline.catalog import (
    BASELINES,
    get_all_policies,
    get_baselines,
    get_required_baselines,
    get_stateless_policies,
)
from stateful_guardrails.pipeline.policies import (
    LLMClassifyEscalationPolicy,
    RuleKeywordEscalationPolicy,
)


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def rule_policy() -> RuleKeywordEscalationPolicy:
    return RuleKeywordEscalationPolicy()


@pytest.fixture
def mock_llm_adapter() -> MagicMock:
    """Ollama 없이 LLM 정책을 테스트하기 위한 mock 어댑터."""
    adapter = MagicMock()
    adapter.complete.return_value = "low"
    return adapter


@pytest.fixture
def llm_policy(mock_llm_adapter) -> LLMClassifyEscalationPolicy:
    return LLMClassifyEscalationPolicy(adapter=mock_llm_adapter)


# ---------------------------------------------------------------------------
# 1. Protocol 계약 검증
# ---------------------------------------------------------------------------

class TestPolicyProtocol:
    """모든 정책이 Policy Protocol을 충족하는지 확인."""

    def test_all_policies_satisfy_protocol(self):
        """카탈로그의 모든 정책이 Policy Protocol을 충족한다."""
        policies = get_all_policies()
        assert len(policies) >= 2, "최소 2개 정책이 등록되어야 합니다"
        for policy in policies:
            assert isinstance(policy, Policy), (
                f"{type(policy).__name__}이 Policy Protocol을 충족하지 않음"
            )

    def test_policy_has_required_attributes(self, rule_policy, llm_policy):
        """각 정책이 id, category, is_stateful 속성을 가진다."""
        for policy in [rule_policy, llm_policy]:
            assert hasattr(policy, "id"), f"{type(policy).__name__}: id 속성 없음"
            assert hasattr(policy, "category"), f"{type(policy).__name__}: category 속성 없음"
            assert hasattr(policy, "is_stateful"), f"{type(policy).__name__}: is_stateful 속성 없음"

    def test_rule_policy_attributes(self, rule_policy):
        assert rule_policy.id == "P-RULE-ESC-01"
        assert rule_policy.category == RiskCategory.ESCALATION
        assert rule_policy.is_stateful is False

    def test_llm_policy_attributes(self, llm_policy):
        assert llm_policy.id == "P-LLM-ESC-01"
        assert llm_policy.category == RiskCategory.ESCALATION
        assert llm_policy.is_stateful is False

    def test_policy_ids_are_unique(self):
        """정책 ID는 고유해야 한다 (감사 로그 키 무결성)."""
        policies = get_all_policies()
        ids = [p.id for p in policies]
        assert len(ids) == len(set(ids)), f"중복 정책 ID 발견: {ids}"


# ---------------------------------------------------------------------------
# 2. PolicySignal 반환값 검증
# ---------------------------------------------------------------------------

class TestPolicySignalContract:
    """evaluate() 반환값이 PolicySignal 계약을 만족하는지 확인."""

    def test_signal_risk_in_range_safe_message(self, rule_policy):
        """정상 문의 메시지의 risk가 [0, 1] 범위 내에 있다."""
        msg = Message(text="배송 조회는 어떻게 하나요? 안내 부탁드려요.")
        signal = rule_policy.evaluate(msg)
        assert isinstance(signal, PolicySignal)
        assert 0.0 <= signal.risk <= 1.0

    def test_signal_risk_in_range_escalation_message(self, rule_policy):
        """불만·이탈 메시지의 risk도 [0, 1] 범위 내에 있다."""
        msg = Message(text="이런 식이면 그냥 환불해주세요. 다시는 안 살래요.")
        signal = rule_policy.evaluate(msg)
        assert 0.0 <= signal.risk <= 1.0

    def test_signal_has_required_fields(self, rule_policy):
        """PolicySignal이 필수 필드를 모두 가진다."""
        msg = Message(text="안녕하세요")
        signal = rule_policy.evaluate(msg)
        assert hasattr(signal, "risk")
        assert hasattr(signal, "evidence")
        assert hasattr(signal, "suggested_action")
        assert hasattr(signal, "policy_id")
        assert signal.policy_id == rule_policy.id

    def test_suggested_action_is_valid_enum(self, rule_policy, llm_policy):
        """suggested_action이 SuggestedAction 열거형 값이다."""
        msg = Message(text="test message")
        for policy in [rule_policy, llm_policy]:
            signal = policy.evaluate(msg)
            assert isinstance(signal.suggested_action, SuggestedAction)


# ---------------------------------------------------------------------------
# 3. 결정성 검증 (규칙 기반)
# ---------------------------------------------------------------------------

class TestDeterminism:
    """규칙 기반 정책은 동일 입력 → 동일 출력을 보장한다."""

    SAFE_MESSAGES = [
        "배송 조회는 어떻게 하나요?",
        "멤버십 등급별 혜택이 궁금해요",
        "영수증 재발급 되나요?",
        "포인트 적립 문의드려요",
    ]

    ESCALATION_MESSAGES = [
        "그냥 환불 받고 싶어요",
        "계약 해지 하겠습니다",
        "정말 최악이네요",
        "구독 취소해주세요",
        "탈퇴할게요",
        "소비자원에 신고하겠습니다",
        "이건 거의 사기 아닌가요",
    ]

    @pytest.mark.parametrize("text", SAFE_MESSAGES + ESCALATION_MESSAGES)
    def test_rule_policy_deterministic(self, rule_policy, text):
        """같은 메시지에 대해 연속 3회 실행해도 동일 결과를 반환한다."""
        msg = Message(text=text)
        signals = [rule_policy.evaluate(msg) for _ in range(3)]
        risks = [s.risk for s in signals]
        actions = [s.suggested_action for s in signals]
        assert all(r == risks[0] for r in risks), f"risk 비결정적: {risks}"
        assert all(a == actions[0] for a in actions), f"action 비결정적: {actions}"


# ---------------------------------------------------------------------------
# 4. stateless 모드 — session_state 파라미터 처리
# ---------------------------------------------------------------------------

class TestStatelessMode:
    """stateless 정책이 session_state 파라미터를 올바르게 처리한다."""

    def test_evaluate_with_none_state(self, rule_policy):
        """session_state=None으로 호출 가능하다 (B1 경로)."""
        msg = Message(text="안녕하세요")
        signal = rule_policy.evaluate(msg, session_state=None)
        assert signal is not None
        assert 0.0 <= signal.risk <= 1.0

    def test_evaluate_with_session_state_still_stateless(self, rule_policy):
        """stateless 정책은 session_state를 주입해도 결과가 동일하다."""
        msg = Message(text="배송 조회 부탁드려요")
        state = SessionState(session_id="test-session")
        signal_none = rule_policy.evaluate(msg, session_state=None)
        signal_with_state = rule_policy.evaluate(msg, session_state=state)
        # stateless 정책은 state를 무시하므로 결과가 동일해야 함
        assert signal_none.risk == signal_with_state.risk
        assert signal_none.suggested_action == signal_with_state.suggested_action


# ---------------------------------------------------------------------------
# 5. 탐지력 검증 (공정 강baseline 규율 P2-2)
# ---------------------------------------------------------------------------

class TestDetectionStrength:
    """공정 강baseline 규율: stateless detector를 약하게 만들지 않는다.

    명시적 이탈·격분 표현은 per-turn으로도 강하게 잡는다(허수아비 baseline 금지).
    thesis 사활점은 '개별 메시지는 약한 불만, 누적되어야 위기'이므로,
    명시 신호는 B1도 잡고 점진 누적 불만은 STATEFUL이 잡는 구조다.
    """

    HIGH_RISK_THRESHOLD = 0.7

    @pytest.mark.parametrize("text", [
        "환불 받고 싶어요",
        "계약 해지 하겠습니다",
        "구독 취소해주세요",
        "탈퇴할게요",
        "정말 최악이네요",
        "소비자원에 신고하겠습니다",
        "고소하겠습니다",
        "이건 거의 사기 아닌가요",
        "이제 그만 쓸래요",
        "다시는 안 살래요",
    ])
    def test_escalation_patterns_get_high_risk(self, rule_policy, text):
        """명확한 불만·이탈 신호는 높은 risk(≥0.7)를 반환한다."""
        msg = Message(text=text)
        signal = rule_policy.evaluate(msg)
        assert signal.risk >= self.HIGH_RISK_THRESHOLD, (
            f"이탈 신호 '{text}'의 risk가 너무 낮음: {signal.risk}"
        )

    @pytest.mark.parametrize("text", [
        "배송 조회는 어떻게 하나요",
        "멤버십 혜택이 궁금해요",
        "영수증 재발급 되나요",
        "포인트 적립 문의드려요",
        "필터 교체 주기가 어떻게 되나요",
        "선물 포장 옵션이 있나요",
    ])
    def test_normal_messages_get_low_risk(self, rule_policy, text):
        """정상 문의 메시지는 낮은 risk(≤0.1)를 반환한다."""
        msg = Message(text=text)
        signal = rule_policy.evaluate(msg)
        assert signal.risk <= 0.1, (
            f"정상 메시지 '{text}'의 risk가 너무 높음: {signal.risk}"
        )


# ---------------------------------------------------------------------------
# 6. LLM 정책 단위 테스트 (mock 어댑터 사용)
# ---------------------------------------------------------------------------

class TestLLMPolicyWithMock:
    """LLM 정책을 mock 어댑터로 단위 테스트한다 (네트워크 불필요)."""

    def test_llm_low_response(self, mock_llm_adapter):
        """어댑터가 'low'를 반환하면 낮은 risk를 반환한다."""
        mock_llm_adapter.complete.return_value = "low"
        policy = LLMClassifyEscalationPolicy(adapter=mock_llm_adapter)
        msg = Message(text="배송 조회 부탁드려요")
        signal = policy.evaluate(msg)
        assert signal.risk < 0.5
        assert signal.suggested_action == SuggestedAction.PASS

    def test_llm_high_response(self, mock_llm_adapter):
        """어댑터가 'high'를 반환하면 높은 risk를 반환한다."""
        mock_llm_adapter.complete.return_value = "high"
        policy = LLMClassifyEscalationPolicy(adapter=mock_llm_adapter)
        msg = Message(text="환불하고 해지하겠습니다")
        signal = policy.evaluate(msg)
        assert signal.risk >= 0.7
        assert signal.suggested_action == SuggestedAction.ESCALATE

    def test_llm_adapter_error_fallback(self, mock_llm_adapter):
        """어댑터 오류 시 중간 risk(0.5)로 fallback한다."""
        mock_llm_adapter.complete.side_effect = RuntimeError("연결 실패")
        policy = LLMClassifyEscalationPolicy(adapter=mock_llm_adapter)
        msg = Message(text="테스트 메시지")
        signal = policy.evaluate(msg)
        assert signal.risk == 0.5
        assert signal.suggested_action == SuggestedAction.FLAG

    def test_llm_signal_risk_in_range(self, mock_llm_adapter):
        """LLM 정책 반환 risk가 [0, 1] 범위 내에 있다."""
        for response in ["low", "high", "  LOW  ", "  HIGH  "]:
            mock_llm_adapter.complete.return_value = response
            policy = LLMClassifyEscalationPolicy(adapter=mock_llm_adapter)
            signal = policy.evaluate(Message(text="test"))
            assert 0.0 <= signal.risk <= 1.0, f"response={response!r}: risk 범위 초과"


# ---------------------------------------------------------------------------
# 7. 카탈로그 및 baseline 검증 (ISC-1.3, ISC-1.5)
# ---------------------------------------------------------------------------

class TestCatalog:
    """카탈로그와 baseline 등록 상태 검증."""

    def test_catalog_returns_policies_with_tags(self):
        """모든 정책에 (category, stateless|stateful) 태그가 있다."""
        policies = get_all_policies()
        for policy in policies:
            assert isinstance(policy.category, RiskCategory), (
                f"{policy.id}: category가 RiskCategory 열거형이 아님"
            )
            assert isinstance(policy.is_stateful, bool), (
                f"{policy.id}: is_stateful이 bool이 아님"
            )

    def test_stateless_policies_subset(self):
        """stateless 정책이 전체 정책의 부분집합이다."""
        all_p = get_all_policies()
        sl_p = get_stateless_policies()
        all_ids = {p.id for p in all_p}
        sl_ids = {p.id for p in sl_p}
        assert sl_ids.issubset(all_ids)

    def test_b1_b15_required_baselines_registered(self):
        """B1과 B1.5가 필수(required=True)로 등록되어 있다 (ISC-1.5 필수)."""
        required = get_required_baselines()
        required_ids = {b.id for b in required}
        assert "B1" in required_ids, "B1 baseline이 필수로 등록되지 않음"
        assert "B1.5" in required_ids, "B1.5 baseline이 필수로 등록되지 않음"

    def test_b2_optional_baseline_registered(self):
        """B2가 가산(required=False)으로 등록되어 있다 (ISC-1.5 가산)."""
        all_baselines = get_baselines(include_optional=True)
        b2 = next((b for b in all_baselines if b.id == "B2"), None)
        assert b2 is not None, "B2 baseline이 등록되지 않음"
        assert b2.required is False, "B2는 가산(required=False)이어야 함"

    def test_b15_has_window_size(self):
        """B1.5 baseline에 window_size(K)가 명시되어 있다."""
        all_baselines = get_baselines()
        b15 = next((b for b in all_baselines if b.id == "B1.5"), None)
        assert b15 is not None
        assert b15.window_size is not None, "B1.5에 window_size(K)가 없음"
        assert b15.window_size > 0, f"B1.5 window_size가 양수가 아님: {b15.window_size}"

    def test_baselines_total_count(self):
        """B1, B1.5, B2 — 3개 baseline이 등록되어 있다."""
        all_baselines = get_baselines(include_optional=True)
        ids = {b.id for b in all_baselines}
        assert "B1" in ids
        assert "B1.5" in ids
        assert "B2" in ids
