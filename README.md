# stateful-guardrails

![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![LLM: local (Ollama)](https://img.shields.io/badge/LLM-local%20(Ollama)-success)
![Tests: 89 passed](https://img.shields.io/badge/tests-89%20passed-brightgreen)

**한국어** · [English](README.en.md)

> 대화형 AI에서 개별 메시지는 약한 불만이지만, 누적하면 위기(이탈·격분)가 된다.
> 누적 위기 점수 엔진(`S_t = λ·S_{t-1} + signal_t`), 3단계 에스컬레이션 이관, O(N) 경제성으로 구성된
> **stateful 위기 조기경보 컴포넌트**를 만들고, 그 효과를 강한 baseline 상대로 정직하게 측정했다.

이 프로젝트의 산출물은 두 가지다. **동작하는 안전 컴포넌트** — 누적 위기 점수 엔진, 3단계 에스컬레이션, 감사 추적이 `sgr escalate`로 즉시 실행된다. 그리고 **그 효과의 반증 가능한 측정** — stateful이 sliding-window 대비 정말 조기 탐지를 하는지 강한 baseline 상대로 McNemar 검정·부트스트랩 CI·λ-sweep으로 물었고, 한정 성립 + FPR 비용까지 있는 그대로 보고했다.

---

## 배경 / 왜 만들었나

**누적형 위협의 구조적 사각지대.** AI 에이전트가 실서비스에 배포되면서, 단발 가드레일이 통과시키는 *점진적 조작* — 개별 메시지는 무해해 보이지만 여러 턴에 걸쳐 누적되면 AI가 경계를 넘거나 위험한 방향으로 유도되는 패턴 — 이 현실 위협이 됐다. 메타 고객지원 챗봇 사고(2026.6)는 그 한 사례다. 핵심은 단발 사고냐 아니냐가 아니라, **"개별로 무해 → 누적하면 위기"라는 구조가 단발 가드레일의 사각지대**라는 점이다.

우리가 시도한 것은 이 누적형 위협의 **차단이 아니라 탐지·조기경보**다. stateful(대화 이력 전체를 누적 추적)이 stateless(단발·슬라이딩 윈도우)보다 이상 누적을 더 일찍 알아채는지를 반증 가능하게 측정하고, 그 답을 정직하게 보고하는 것이 목적이다.

**도메인 피벗 — 안전정책 충돌을 인지하고 회피한 판단.** 조작·탈옥 데이터를 직접 생성하면 안전정책과 충돌한다. "개별 불만 메시지는 단발로 무해하지만 누적하면 위기가 된다"는 구조가 누적형 조작과 동형이므로, **고객지원 위기 에스컬레이션을 안전한 대리 도메인(proxy)으로 선택**했다. 측정 골격(signal 설계, baseline 비교, McNemar, 작동점 정렬, CI)은 도메인 무관이라 조작 탐지로의 이론적 전이가 가능하다.

결과는 아래에 정직하게 보고한다.

---

## 탐지 이후 — 운영 가치

> 에스컬레이션 데모와 경제성 비교는 컴포넌트가 *무엇을 가능하게 하는지*를 보인다.
> 측정 결과(아래 섹션)는 그 효과를 수치로 검증한다.
> 데모는 합성 세션, 비용은 모델 추정이다(과장 없음).

### 1. 에스컬레이션 3단계 — 탐지를 액션으로

누적 위기 점수 `S_t`를 동결 임계 `t1=0.7`·`t2=0.9`에 매핑해 라우팅한다(재튜닝 없음):
`S_t<t1` = 봇 자동응대 / `t1≤S_t<t2` = 상담사 이관 / `S_t≥t2` = 매니저·이탈방지팀 이관.

```
$ sgr escalate --session c1-test-004

  턴   risk    S_t  STATEFUL 단계        B1(단발) 단계
    0   0.00   0.00  봇 자동응대            봇 자동응대
    1   0.42   0.42  봇 자동응대            봇 자동응대     ← "몇 번을 다시 로그인해도 튕겨요"
    2   0.55   0.84  상담사 이관            봇 자동응대     ← "사흘째 연락하는데 그대로네요. 답답해요"
    3   0.90   1.00  매니저·이탈방지팀 이관   매니저·이탈방지팀 이관  ← "탈퇴할게요"

[이관 권고]
  STATEFUL(누적): 상담사 이관 = 2번째 턴 / 매니저 이관 = 3번째 턴
  B1(stateless 단발): 상담사 이관 = 3번째 턴 / 매니저 이관 = 3번째 턴
  → 선제 이관: STATEFUL이 B1보다 1턴 일찍 상담사에 넘긴다
    (약한 불만 누적이 명시적 위기 선언 *이전에* 사람 개입을 유도)
```

stateless 단발(B1)은 매 턴 독립이라 "언제 사람에게 넘길지"를 누적으로 결정하지 못한다.
2번째 턴 "답답해요"(risk 0.55<t1)는 단발로는 봇 응대지만, 누적 `S_t=0.84`는 상담사
이관 임계를 넘겨 **고객이 "탈퇴"를 선언하기 한 턴 전에** 사람에게 넘긴다. 조기 탐지가
"그래서 가능하게 하는 액션"이다. 각 판정은 감사 추적된다(`sgr audit --session <id>`, ISC-4.2).

> 정직 규율: 모든 C1 세션에서 선제성이 나타나지는 않는다. 약한 불만이 한 턴씩 띄엄띄엄
> 들어오면 λ=0.7 감쇠로 누적이 흩어져 단발과 이관 시점이 같아지는 세션도 있다(있는 그대로 보고).

### 2. 경제성 — judge 재투입 비용 (모델 추정)

STATEFUL은 매 턴 O(1) 고정 상태(스칼라 `S_{t-1}` 1개)만 참조한다. B1.5는 최근 K=5턴을,
B2는 전체 세션을 매 턴 judge에 재투입한다. N턴 세션 누적 judge 입력 토큰:

| N(세션 턴) | STATEFUL O(N) | B1.5 O(N·K) | B2 O(N²) | B1.5/ST | B2/ST |
|---|---|---|---|---|---|
| 10 | 210 | 760 | 1,045 | ×3.6 | ×5.0 |
| 20 | 420 | 1,710 | 3,990 | ×4.1 | ×9.5 |
| 50 | 1,050 | 4,560 | 24,225 | ×4.3 | ×23.1 |
| 100 | 2,100 | 9,310 | 95,950 | ×4.4 | ×45.7 |

B2/STATEFUL 배수가 N에 비례해 단조 증가한다(O(N²) vs O(N)) — 긴 세션·online 운영에서
전체 재투입(B2)은 비용상 사용 불가, B1.5도 K배 비용이다. 이것이 측정 결론의
"B2와 동급 정확도를 B2의 1/N 비용으로"라는 정당성 축을 숫자로 받친다.

> ⚠ caveat: **실측이 아니라 모델 추정**이다. 턴당 토큰(≈19, 동봉 데이터 평균 ≈28자/한국어
> 기준)·judge 단가 가정을 명시했다. 로컬 Ollama 실금전비용은 0이며, 표는 클라우드 judge
> 환산 시의 *상대 규모*를 보인다. 재현: `sgr cost-model` → [`out/cost.md`](out/cost.md).

---

## 한 줄 결론 (정직)

**한 detector(target_aware)에서 STATEFUL이 stateless를 작동점 정렬·CI·λ 전구간에서 견고하게 이김(McNemar p=0.000). 단 비순환 통제군(agnostic)은 미성립이라 순환 가능성을 완전히 배제하지 못하며, recall 우위는 장기정상 FPR 18% 비용을 동반한다.**

---

## 강건성 검증 자산

"FPR으로 샀다" / "소표본 노이즈" 반론을 세 겹으로 닫았다.

1. **작동점 정렬**: 같은 test-FPR 예산에서 STATEFUL이 B1.5를 일관되게 이김 (≤5%: +19.4%p / ≤10%: +22.6%p / ≤20%: +38.7%p).
2. **부트스트랩 CI**: 95% CI [+40.3%p, +66.1%p] — 하한이 0을 배제, 방향 부호가 확실.
3. **λ-sweep 전구간 양수**: λ=0.5·0.7·0.9·1.0 전 구간에서 vs B1.5 델타 +32~+53%p, 부호 반전 없음.

비순환 통제군(target_agnostic, p=0.250, CI [-11.3%p, +0.0%p], λ 전구간 비양수)은 "통제군이 작동해 한쪽만 걸러낸 정직성"으로 읽는다 — agnostic 미성립이 곧 target_aware의 신호가 임의가 아님을 부분 지지한다.

---

## 결과

평가 원본: [`out/mini.md`](out/mini.md) — C1(누적 위기) 양성 test 62세션 (c1.test 47 + c1.calib 합류 15), C3(정상 해결) test 40세션 (장기양성 22 포함), K=5

### detector = `target_aware` — **성립(강화)**

| 비교 | Δrecall(전체) | Δrecall(K초과) | ΔTTD(전체) | McNemar p |
|---|---|---|---|---|
| STATEFUL − B1 (per-turn) | +19.4%p | +29.6%p | −0.02 | 0.004 |
| STATEFUL − B1.5 (sliding-window) | **+53.2%p** | **+63.0%p** | **+0.30** | **0.000 ✓** |

> TTD = time-to-detect (success_turn − detect_turn), 양수 = STATEFUL이 더 이른 턴에 탐지.
> 부트스트랩 95% CI (vs B1.5): **[+40.3%p, +66.1%p]** — 하한 > 0, 0 배제.

오탐 비용(장기-양성 FPR): STATEFUL **18%** (4/22) vs B1.5 9% (2/22) ⚠ — recall 우위는 공짜가 아니다.

### detector = `target_agnostic` — **미성립**

| 비교 | Δrecall(전체) | McNemar p |
|---|---|---|
| STATEFUL − B1 (per-turn) | +0.0%p | 1.000 |
| STATEFUL − B1.5 (sliding-window) | **−4.8%p** | **0.250** |

> 95% CI (vs B1.5): [-11.3%p, +0.0%p] — 0 포함, 비유의.
> ⚠ 소표본 caveat: McNemar는 불일치쌍에만 의존하므로 표본이 작으면 검정력이 낮다(유의=강증거, 비유의≠반증).

---

## 정직한 해석

| 항목 | 내용 |
|---|---|
| 성립 detector | `target_aware` 1개 (vs B1.5, p=0.000, CI 하한 > 0, λ 전구간 양수, 작동점 정렬) |
| 미성립 detector | `target_agnostic` (목표 개념 비참조 시 stateful 우위 없음 — 통제군이 제 역할을 함) |
| 성립의 의미 | sliding-window가 K턴 밖으로 흘린 불만 신호를, stateful 누적이 무한 룩백으로 잡음 |
| 비용 | target_aware 장기-양성 오탐 18% — "긴 세션이라 위기"와 "에스컬레이션이라 위기"를 완전히 분리하지 못함 |
| 순환 가능성 | agnostic 미성립이 완전한 역통제는 아님 — 순환을 완전히 배제 못 함(정직 표기) |
| target_agnostic 미성립 이유 후보 | 직전 N턴 대비 의미 이동량은 위기·정상 세션 모두에서 유사하게 증가, 위기 신호로서 분리력이 낮음 |
| 교란 발견 | 1차 측정에서 C3(정상)가 C1(위기)보다 짧아 stateful 점수가 길이에 비례해 부풀려짐 → 장기-양성 대조군 확대(22개)로 통제 |

**"한정 성립 + FPR 비용 + agnostic 미성립을 정직하게 보고"하는 것이 이 프로젝트의 결론이다.** Mycelium의 `graph_weight=0.0` 정신 계승 — 유불리와 무관하게 수치를 그대로 보고한다.

---

## 측정 규율 (프로젝트의 핵심 자산)

좋은 수치보다 **어떻게 측정했는가**가 더 중요하다. 이 프로젝트를 단순 "정직 negative 보고"가 아니라 **반증 가능한 실험 설계 역량**으로 포지셔닝하는 근거다.

1. **공정한 강 baseline** — B1(per-turn stateless), B1.5(sliding-window K=5), STATEFUL을 동일 FPR 예산(5%)으로 비교. "sliding-window의 손실 압축일 뿐" 반론에 직접 답한다.
2. **길이 교란 탐지·통제** — C3 중앙값 6턴 vs C1 중앙값 5턴. 장기-양성 대조군(K초과 정상 세션) 22개로 확대해 길이 교란 통제 검정력 보강.
3. **holdout 프로토콜** — λ=0.7·K=5·임계(t1·t2)를 calibration-split에서만 결정 후 동결. test-split 성능 측정 시 재튜닝 없음.
4. **자기충족 방어** — `target_aware`(목표 개념 향한 누적 코사인 이동) + `target_agnostic`(직전 N턴 대비 의미 이동량) 병렬 비교. 한쪽만 성립 → 데이터 설계가 탐지축으로 누출되지 않음을 부분 확인.
5. **생성↔평가 모델 분리** — 데이터 생성: claude-opus(Anthropic) / 평가·임베딩: bge-m3 + qwen2.5:14b(Alibaba). 다른 계열로 분리해 생성 문체 순환 위험 완화.
6. **McNemar 검정** — 점추정 부호만으로 성립 선언하지 않는다. p<0.05일 때만 성립.
7. **K 이내/초과 분층 보고** — K=5 이내 세션(35개)과 K 초과 세션(27개)을 분리 보고. K 이내에서 B1.5≈STATEFUL(구조적 동등)임을 그대로 공개.
8. **작동점 정렬 재비교** — 동일 test-FPR 예산에서 recall을 재산출. "작동점이 달라 비교 불공정"하다는 반론을 직접 닫는다.
9. **부트스트랩 CI** — 2000회 짝지은 복원추출, seed 고정(재현 가능). 점추정 부호와 함께 불확실성을 정직 노출.
10. **λ-sweep** — λ∈{0.5, 0.7, 0.9, 1.0} 전구간에서 델타 곡선 산출. 부호 반전 시 그대로 게시(정직성 증거). 결과: [`out/lambda.md`](out/lambda.md)

---

## 아키텍처

의존 방향: `interfaces → pipeline → adapters → core` (클린 아키텍처, Mycelium 계승)

```
interfaces/   CLI(typer, sgr 명령) — 입출력 진입점
pipeline/     판정 파이프라인 오케스트레이션
              (메시지 인입 → 정책 실행 → 에스컬레이션 결정 → 감사로그)
adapters/     외부 경계: LLM/임베딩 provider(Ollama), 상태 영속화(JSON), 감사로그
core/         순수 도메인: Policy 인터페이스, SessionState, 누적 판정 알고리즘
              (외부 I/O·프레임워크 의존 없음 — 수치 연산은 stdlib math만)
```

**누적 공식:** `S_t = clip(λ·S_{t-1} + signal_t, 0, S_max)` (λ=0.7, 지수 감쇠)

Baseline은 별도 코드가 아니라 **동일 엔진의 한 모드**다.
`session_state=None`이면 B1(per-turn), 최근 K턴 슬라이딩이면 B1.5, 누적 상태를 참조하면 STATEFUL.
같은 데이터·같은 정책 위에서 세 경로의 델타를 측정한다.

설계 결정 (D-1~D-10): [`docs/DESIGN.md`](docs/DESIGN.md)
실행 계획 + 검증 ISC: [`docs/PLAN.md`](docs/PLAN.md)

---

## 빠른 시작

### 1. 설치

```bash
git clone <repo-url> stateful-guardrails
cd stateful-guardrails
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

### 2. Ollama + 모델 준비

```bash
# https://ollama.com 설치 후
ollama serve
ollama pull bge-m3        # 임베딩 (1.2 GB)
ollama pull qwen2.5:14b   # judge LLM (9 GB) — eval 시에만 필요
```

### 3. 기본 명령

```bash
sgr --version                                          # 버전 확인 (ISC-0.1)
sgr catalog                                            # 정책 카탈로그 (category, stateless|stateful)
sgr scan --input data/c1.test.jsonl                    # 단발 스캔 (stateless 모드)
sgr eval --mini --dataset data/ --report out/mini.md  # 미니 평가 — thesis 사활점
```

### 4. 측정 재현

```bash
# 동봉 합성 데이터(data/) + 동결 파라미터(data/calibration.json) 기반
sgr eval --mini --dataset data/ --report out/mini.md
# 결과를 동봉 out/mini.md와 비교해 재현 확인

# λ-sweep (ISC-5.6)
sgr eval --mini --lambda-sweep 0.5,0.7,0.9,1.0 --report out/lambda.md --dataset data/
```

---

## 데이터

`data/` 디렉토리에 합성 대화 세션만 포함된다(민감정보 없음):

| 파일 | 내용 |
|---|---|
| `c1.{calib,test}.jsonl` | 누적 위기 에스컬레이션 세션 (합성 한국어 포함) |
| `c3.{calib,test}.jsonl` | 정상 해결 대화 + 장기-양성 대조군 세션 (합성) |
| `calibration.json` | 동결 파라미터 (λ, K, N, S_max, 임계, FPR 예산) |

실데이터(실제 고객 상담 로그)는 없다. 합성 데이터는 Mycelium의 `sample_vault/`와 같은 역할 —
클론 즉시 평가를 재현할 수 있도록 동봉했다.

---

## 스택

Python 3.12 · typer · httpx · Ollama(`bge-m3` 임베딩 + `qwen2.5:14b` judge)
수치 연산은 외부 라이브러리 없이 stdlib `math`만 사용(core 레이어 의존성 최소화).

---

## 라이선스

MIT
