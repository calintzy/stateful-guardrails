"""pipeline.cost — 경제성 비용 모델 (STATEFUL vs B1.5 vs B2, 운영 가치 레이어).

목적(독립 추가): 측정 thesis의 '비용/online/무한룩백' 정당성 축(A.2.5)을 구체 숫자로
실증한다. judge 재투입 아키텍처의 턴당·세션당 토큰 비용을 모델링한다.

비용 구조(PLAN A.2.5):
  - STATEFUL : 매 턴 O(1) 고정 상태(스칼라 S_{t-1} 1개) + 현재 턴 1회 판정.
               턴당 비용 = tokens_per_turn + c_state (고정). 누적 = O(N).
  - B1.5     : 매 턴 최근 K턴을 judge에 재투입(O(K)).
               턴당 비용 = min(t, K)·tokens_per_turn. 누적 = O(N·K).
  - B2       : 매 턴 전체 세션을 judge에 재투입(O(t)).
               턴당 비용 = t·tokens_per_turn. 누적 = O(N²).

정직 규율(graph_weight=0.0 정신): 본 비용은 **실측이 아니라 모델 추정**이다.
토큰 단가·임베딩 비용·턴 길이 가정을 모두 명시한다. 측정 thesis·수치는 건드리지 않는다.

레이어 규칙: stdlib만 사용. 외부 I/O 없음(순수 계산).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 가정 (assumptions — 모두 명시, 추정치)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CostAssumptions:
    """비용 모델 가정. 전부 추정치이며 리포트에 명시한다(실측 아님).

    tokens_per_turn : 1 user 턴의 평균 입력 토큰 수.
                      동봉 데이터 user 메시지 평균 ≈28자(한국어) → ≈19토큰(자/1.5) 추정.
    c_state_tokens  : STATEFUL이 매 턴 참조하는 O(1) 상태의 토큰 환산(스칼라 S_{t-1} 1개).
                      극소(상수) — 누적식은 숫자 1개라 사실상 무시 가능, 보수적으로 2.
    window_k        : B1.5 sliding-window 크기 K (동결 파라미터, calibration.json).
    price_per_1k_tokens_usd : judge 입력 토큰 1k당 단가(USD) — 추정. 로컬 Ollama는 금전
                      비용 0이나, 연산량 비례 비용을 화폐로 환산해 규모를 보이기 위한 가정.
    embed_dim       : 임베딩 차원(bge-m3=1024). 연산량 환산 참조용 메타.
    """
    tokens_per_turn: int = 19
    c_state_tokens: int = 2
    window_k: int = 5
    price_per_1k_tokens_usd: float = 0.0005
    embed_dim: int = 1024


# ---------------------------------------------------------------------------
# 턴당·누적 토큰 비용 (순수 함수)
# ---------------------------------------------------------------------------

def per_turn_tokens(strategy: str, turn_ordinal: int, a: CostAssumptions) -> int:
    """1-based turn_ordinal에서 strategy의 judge 입력 토큰 수.

    turn_ordinal: 1..N (t번째 턴).
    strategy: "STATEFUL" | "B1.5" | "B2".
    """
    t = turn_ordinal
    tpt = a.tokens_per_turn
    if strategy == "STATEFUL":
        return tpt + a.c_state_tokens             # O(1): 현재 턴 + 고정 상태
    if strategy == "B1.5":
        return min(t, a.window_k) * tpt           # O(K): 최근 K턴 재투입
    if strategy == "B2":
        return t * tpt                            # O(t): 전체 세션 재투입
    raise ValueError(f"알 수 없는 strategy: {strategy!r}")


def cumulative_tokens(strategy: str, n_turns: int, a: CostAssumptions) -> int:
    """N턴 세션 동안 strategy의 누적 judge 입력 토큰 수."""
    return sum(per_turn_tokens(strategy, t, a) for t in range(1, n_turns + 1))


def tokens_to_usd(tokens: int, a: CostAssumptions) -> float:
    """토큰 수를 추정 화폐 비용(USD)으로 환산한다(추정 단가)."""
    return tokens / 1000.0 * a.price_per_1k_tokens_usd


# ---------------------------------------------------------------------------
# 비교 테이블 산출
# ---------------------------------------------------------------------------

STRATEGIES = ["STATEFUL", "B1.5", "B2"]


@dataclass
class CostRow:
    """단일 N(세션 길이)에서 세 전략의 누적 비용."""
    n_turns: int
    cumulative_tokens: dict[str, int] = field(default_factory=dict)
    # STATEFUL 대비 배수 (B1.5/B2가 STATEFUL의 몇 배인가)
    ratio_vs_stateful: dict[str, float] = field(default_factory=dict)


def build_cost_table(
    n_values: list[int],
    a: CostAssumptions,
) -> list[CostRow]:
    """N 후보별 세 전략 누적 토큰 + STATEFUL 대비 배수 표를 산출한다."""
    rows: list[CostRow] = []
    for n in n_values:
        cum = {s: cumulative_tokens(s, n, a) for s in STRATEGIES}
        base = cum["STATEFUL"] or 1
        ratio = {s: cum[s] / base for s in STRATEGIES}
        rows.append(CostRow(n_turns=n, cumulative_tokens=cum, ratio_vs_stateful=ratio))
    return rows


# ---------------------------------------------------------------------------
# 리포트 렌더링 (out/cost.md)
# ---------------------------------------------------------------------------

_DEFAULT_N_VALUES = [5, 10, 20, 50, 100]


def render_cost_report(
    a: CostAssumptions,
    n_values: list[int] | None = None,
) -> str:
    """비용 모델 리포트를 마크다운으로 렌더링한다 (out/cost.md, README 인용용)."""
    n_values = n_values or _DEFAULT_N_VALUES
    rows = build_cost_table(n_values, a)

    lines: list[str] = []
    lines.append("# 경제성 비용 모델 — STATEFUL vs B1.5 vs B2 (운영 가치 레이어)\n")
    lines.append("> ⚠ **실측이 아니라 모델 추정이다.** 아래 가정(토큰 단가·턴 길이·임베딩)을 "
                 "명시한다. 측정 thesis·수치(out/mini.md)는 건드리지 않는 독립 추가다.\n")
    lines.append("## 비용 구조 (judge 재투입 아키텍처, PLAN A.2.5)\n")
    lines.append("| 전략 | 매 턴 judge 입력 | 턴당 비용 | N턴 누적 | 복잡도 |")
    lines.append("|---|---|---|---|---|")
    lines.append(f"| STATEFUL | 현재 턴 + O(1) 고정 상태(스칼라 1개) | "
                 f"{a.tokens_per_turn}+{a.c_state_tokens} 토큰(고정) | 선형 | **O(N)** |")
    lines.append(f"| B1.5 | 최근 K={a.window_k}턴 재투입 | min(t,K)·{a.tokens_per_turn} 토큰 | "
                 "준선형 | **O(N·K)** |")
    lines.append(f"| B2 | 전체 세션 재투입 | t·{a.tokens_per_turn} 토큰 | 2차 | **O(N²)** |")
    lines.append("")
    lines.append("> STATEFUL은 누적 상태가 스칼라 1개라 매 턴 비용이 고정(O(1))이다. "
                 "B1.5는 윈도우 K에 비례, B2는 누적 턴 t에 비례해 매 턴 비용이 증가한다.\n")

    lines.append("## 가정 (assumptions — 전부 추정치)\n")
    lines.append(f"- 턴당 입력 토큰 `tokens_per_turn={a.tokens_per_turn}` "
                 "(동봉 데이터 user 메시지 평균 ≈28자/한국어 → ≈19토큰, 자/1.5 추정)")
    lines.append(f"- STATEFUL 상태 토큰 `c_state_tokens={a.c_state_tokens}` "
                 "(누적식은 스칼라 S_{t-1} 1개 — 사실상 무시 가능, 보수적 상수)")
    lines.append(f"- sliding-window `K={a.window_k}` (동결 파라미터, calibration.json)")
    lines.append(f"- 추정 judge 단가 `${a.price_per_1k_tokens_usd}/1k tokens` "
                 "(로컬 Ollama는 금전비용 0 — 연산량 규모를 화폐로 환산하기 위한 가정 단가)")
    lines.append(f"- 임베딩 차원 `embed_dim={a.embed_dim}` (bge-m3, 연산량 메타 참조)\n")

    lines.append("## N턴 누적 judge 입력 토큰 (STATEFUL 대비 배수)\n")
    lines.append("| N(세션 턴) | STATEFUL | B1.5 | B2 | B1.5/STATEFUL | B2/STATEFUL |")
    lines.append("|---|---|---|---|---|---|")
    for r in rows:
        st = r.cumulative_tokens["STATEFUL"]
        b15 = r.cumulative_tokens["B1.5"]
        b2 = r.cumulative_tokens["B2"]
        lines.append(
            f"| {r.n_turns} | {st:,} | {b15:,} | {b2:,} | "
            f"×{r.ratio_vs_stateful['B1.5']:.1f} | ×{r.ratio_vs_stateful['B2']:.1f} |"
        )
    lines.append("")
    lines.append("> B2/STATEFUL 배수가 N에 비례해 단조 증가한다(O(N²) vs O(N)) — "
                 "긴 세션·online 운영에서 B2(전체 재투입)는 비용상 사용 불가, "
                 "B1.5도 K배 비용. STATEFUL은 무한 세션에서도 턴당 고정 비용.\n")

    lines.append("## 추정 화폐 비용 (참고 — 가정 단가 기반)\n")
    lines.append("| N(세션 턴) | STATEFUL | B1.5 | B2 |")
    lines.append("|---|---|---|---|")
    for r in rows:
        lines.append(
            f"| {r.n_turns} | ${tokens_to_usd(r.cumulative_tokens['STATEFUL'], a):.5f} | "
            f"${tokens_to_usd(r.cumulative_tokens['B1.5'], a):.5f} | "
            f"${tokens_to_usd(r.cumulative_tokens['B2'], a):.5f} |"
        )
    lines.append("")
    lines.append("> ⚠ caveat: 화폐 비용은 추정 단가 가정 산물이다. 로컬 Ollama 실비용은 0이며, "
                 "본 표는 클라우드 judge로 환산 시의 *상대 규모*를 보이기 위한 모델 추정이다. "
                 "정확도 비교는 out/mini.md(측정), 본 표는 비용 축(추정)을 담당한다.\n")
    return "\n".join(lines)
