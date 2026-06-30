"""pipeline.detectors — longitudinal 신호 생산자 2종 (P0-3·P1-6·ISC-2.5).

세션의 user 메시지 시퀀스에서 턴별 signal_t(0~1)를 산출한다.
이 signal_t를 engine이 B1/B1.5/STATEFUL 세 경로로 집계한다.

두 detector는 anti-circular 대조군이다 (ISC-2.5):
  - target_aware   : 고정된 위기개념 앵커를 향한 임베딩 근접도(누적 드리프트 1급 신호).
  - target_agnostic: 목표개념 비참조, 직전 N턴 대비 의미 이동량(semantic shift).
둘 다 STATEFUL 우위를 내면 "데이터 목표개념을 탐지축으로 흘린 자기충족"이 아님.

레이어 규칙: core + adapters import 가능. interfaces import 금지.
"""

from __future__ import annotations

from stateful_guardrails.adapters.embeddings import OllamaEmbedder
from stateful_guardrails.core.vectormath import centroid, cosine

# target-aware 고정 위기개념 앵커 (한국어).
# 주의(anti-circular): 세션별 target_concept를 직접 참조하지 않는다.
# 위기 "카테고리"(고객 격분/이탈/거래 중단) 방향만 고정 앵커로 둔다 → 자기충족 위험 완화.
# 세션별 정답 payload를 탐지축으로 흘리지 않으므로 P1-6 circular 위험을 낮춘다.
TARGET_AWARE_ANCHOR = (
    "고객이 반복된 불만과 미해결 경험으로 격분하여 환불·해지·거래 중단을 요구하고, "
    "서비스를 떠나겠다고 선언하는 이탈 위기 상태."
)


class TargetAwareDriftDetector:
    """target_aware — 고정 위기개념 앵커를 향한 누적 코사인 '이동(드리프트)'.

    progress_t = cos(emb(user_t), emb(anchor))   # 앵커 근접도
    signal_t   = max(0, progress_t - progress_{t-1})   # 이번 턴의 앵커 방향 이동량

    설계 주석(정직성·교란 제거): bge-m3 절대 코사인은 무관한 한국어 문장쌍에서도
    baseline이 ~0.4로 높다. 절대 근접도를 그대로 누적하면 정상 세션도 EWMA가 1.0로
    포화되어 '길이 → 포화 → 탐지'라는 교란이 생긴다. 따라서 절대 위치가 아니라
    '앵커를 향한 이동(1차 차분의 양수부)'을 signal로 쓴다 — PLAN P0-3의
    '목표개념을 향한 누적 코사인 이동(드리프트)'을 충실히 구현한 형태.
    정상 해결 대화는 근접도가 등락(이동 상쇄)하여 누적이 낮고, 점진 에스컬레이션은
    위기 개념을 향해 단조 상승하여 작은 이동이 누적된다. B1(per-turn max)은 큰 단발
    점프가 없으면 놓치고, STATEFUL은 누적해 잡는다.

    후속 실험 기록(D-11, 미채택): 장기-양성 오탐(31%)을 줄이려 signed 변형
    (음수부도 반영, signal = progress_t - progress_{t-1})과 calib 장기-양성 보강을
    시도했다. dev에선 오탐이 줄고 recall 우위가 커 보였으나(낙관), 새 holdout 200세션
    1회 검증에서 오탐은 31%→5%로 해결됐지만 핵심 우위(STATEFUL−B1.5)가 −0.9%p로
    미재현됐다(p=1.000). '낮은 오탐'과 'recall 우위'가 트레이드오프임이 드러나, 검증된
    기존 양수부 신호를 유지한다. 상세: docs/DESIGN.md D-11, out/holdout_final.md.
    """

    id: str = "target_aware"

    def __init__(
        self,
        embedder: OllamaEmbedder | None = None,
        anchor_text: str = TARGET_AWARE_ANCHOR,
    ) -> None:
        self._embedder = embedder or OllamaEmbedder()
        self._anchor_text = anchor_text
        self._anchor_emb: list[float] | None = None

    def _anchor(self) -> list[float]:
        if self._anchor_emb is None:
            self._anchor_emb = self._embedder.embed(self._anchor_text)
        return self._anchor_emb

    def signals(self, user_texts: list[str]) -> list[float]:
        """user 메시지 시퀀스 → 턴별 앵커 방향 이동량 signal_t."""
        anchor = self._anchor()
        progress = [cosine(self._embedder.embed(t), anchor) for t in user_texts]
        out: list[float] = []
        for i in range(len(progress)):
            if i == 0:
                out.append(0.0)
            else:
                out.append(max(0.0, progress[i] - progress[i - 1]))
        return out


class TargetAgnosticShiftDetector:
    """target_agnostic — 직전 N턴 대비 의미 이동량 (목표개념 비참조).

    signal_t = max(0, 1 - cos(emb(user_t), centroid(emb(user_{t-N..t-1}))))
    첫 턴은 비교 대상이 없으므로 0.
    위기개념을 전혀 참조하지 않으므로 자기충족 방어 대조군이다 (P1-6).
    """

    id: str = "target_agnostic"

    def __init__(
        self,
        embedder: OllamaEmbedder | None = None,
        window_n: int = 10,
    ) -> None:
        self._embedder = embedder or OllamaEmbedder()
        self._window_n = window_n

    def signals(self, user_texts: list[str]) -> list[float]:
        """user 메시지 시퀀스 → 턴별 의미 이동량 signal_t."""
        embs = [self._embedder.embed(t) for t in user_texts]
        out: list[float] = []
        for i, emb in enumerate(embs):
            if i == 0:
                out.append(0.0)
                continue
            start = max(0, i - self._window_n)
            prev = embs[start:i]
            cen = centroid(prev)
            out.append(max(0.0, 1.0 - cosine(emb, cen)))
        return out


def get_detector(
    detector_id: str,
    embedder: OllamaEmbedder | None = None,
    window_n: int = 10,
):
    """detector_id로 detector 인스턴스를 반환한다."""
    if detector_id == "target_aware":
        return TargetAwareDriftDetector(embedder=embedder)
    if detector_id == "target_agnostic":
        return TargetAgnosticShiftDetector(embedder=embedder, window_n=window_n)
    raise ValueError(f"알 수 없는 detector: {detector_id!r}")
