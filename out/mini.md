# 미니-eval 리포트 — STATEFUL vs B1/B1.5 (Phase 2 사활점)

> 검증 자세: "stateful이 이긴다"가 아니라 "stateful의 가치를 반증 가능하게 검증"한다.
> 미성립(STATEFUL이 B1.5 못 이김)도 유효한 결과 — graph_weight=0.0 정신. 수치는 있는 그대로.

## 생성↔평가 모델 분리 (ISC-2.8, anti-circular)

- 데이터 생성 모델: `claude-opus-4-8` (계열: claude (Anthropic))
- 평가·detector 모델: `bge-m3 (임베딩) + qwen2.5:14b (judge, 본 Phase 미사용)` (계열: qwen/bge (Alibaba))
- **동일계열 여부: 다름**
- 생성(claude)·평가(qwen/bge) 계열 분리 → 생성문체 순환 위험 완화.

## 동결 파라미터 (calibration-split 파생·test 동결, ISC-2.6)

- λ(감쇠)=0.7, K(sliding-window)=5, N(상태 윈도우)=10, S_max=1.0
- FPR 예산=5% (모든 baseline 동일 예산 — 공정성)
- 임계는 (detector×baseline)별로 C3 calib에서 동일 FPR 예산 충족 최저값으로 동결.

## C1 test 데이터 분포 (ISC-2.7 자연분포·분층 + 표본 확대)

- C1 양성 test 풀: **62개** (c1.test 47 + c1.calib 합류 15)
- 합류 근거: c1.calib은 C3-FPR 기반 캘리브에 미사용 → C1 누수 없이 양성 표본 확대(검정력 보강).
- user-턴 분포=[3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 7, 7, 7, 7, 7, 7, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 9]
- K(=5) 이내: 35개 / K 초과(장기복선): 27개 (K초과 비율 44%)
- 규율: K이내는 B1.5≈STATEFUL 예상(정직 보고), 잔여 우위는 K초과(무한 룩백)에서 기대.

## C3 test 데이터 분포 + 길이 교란 통제 (장기-양성 대조군 확대)

- C3 test(오탐 대조군): 40개
- 단기 음성(K이내): 18개 / **장기-양성(K초과, 긴데 정상 해소): 22개** (7→20+ 확대로 길이 교란 통제 검정력 보강)
- C1 중앙값=5턴 vs C3 중앙값=6턴
- **교란 통제 핵심**: STATEFUL 누적식은 길이 비례 증가 → '길어서 위기'가 아니라 '에스컬레이션이라 위기'임을 보이려면 '긴데 정상'인 장기-양성에서 오탐하지 않아야 한다.
- 아래 detector표 testFPR을 **단기음성/장기양성으로 분리** 보고(장기양성 FPR=길이통제 후 진짜 오탐율).

## detector = `target_aware`

| baseline | 임계 | calibFPR | testFPR | recall(전체) | recall(K이내) | recall(K초과) | TTD(전체) | TTD(K초과) |
|---|---|---|---|---|---|---|---|---|
| B1 | 0.10 | 0% | 10% | 50% | 51% (35) | 48% (27) | 1.42 | 2.08 |
| B1.5 | 0.05 | 0% | 5% | 16% | 17% (35) | 15% (27) | 1.10 | 1.25 |
| STATEFUL | 0.11 | 5% | 10% | 69% | 63% (35) | 78% (27) | 1.40 | 2.05 |

**델타 컬럼 (필수 — STATEFUL 기준):**

| 비교 | Δrecall(전체) | Δrecall(K초과) | ΔTTD(전체) |
|---|---|---|---|
| STATEFUL − B1 | +19.4%p | +29.6%p | -0.02 |
| STATEFUL − B1.5 | +53.2%p | +63.0%p | +0.30 |

> TTD(time-to-detect)=success_turn−detect_turn, user-턴 단위. 양수=조기 탐지(클수록 좋음).

**Δrecall 부트스트랩 95% CI (ISC-2.3, 짝지은 복원추출 2000회·seed=20260629):**

| 비교 | Δrecall 점추정 | 95% CI |
|---|---|---|
| STATEFUL − B1 | +19.4%p | [+8.1%p, +30.6%p] |
| STATEFUL − B1.5 | +53.2%p | [+40.3%p, +66.1%p] |

> 사활 컬럼(vs B1.5) CI 하한>0 → 부호가 0을 배제(유의). 점추정 부호와 함께 CI로 불확실성을 정직 노출.

**동일 작동점(matched test-FPR) recall 재비교 (작동점 정렬 — critic 지적):**

> 임계를 동일 FPR 예산이 아니라 동일 test-FPR로 맞춘 뒤 recall 비교. 'STATEFUL FPR≠B1.5 FPR이라 recall 비교 불공정'에 답한다.

| target FPR | B1 recall (FPR) | B1.5 recall (FPR) | STATEFUL recall (FPR) | **ΔSTATEFUL−B1.5** |
|---|---|---|---|---|
| ≤5% | 24% (5%) | 16% (5%) | 35% (5%) | **+19.4%p** |
| ≤10% | 50% (10%) | 47% (10%) | 69% (10%) | **+22.6%p** |
| ≤20% | 71% (18%) | 47% (10%) | 85% (18%) | **+38.7%p** |

> 괄호=해당 임계에서 실제 달성 test-FPR. 같은 FPR 예산에서도 ΔSTATEFUL−B1.5가 양수면 작동점 정렬 후에도 우위가 유지된다는 증거.

**testFPR 분층 (길이 교란 통제 — 장기-양성에서의 오탐이 진짜 FPR):**

| baseline | testFPR(전체) | FPR(단기음성 K이내) | **FPR(장기양성 K초과)** |
|---|---|---|---|
| B1 | 10% (4/40) | 0% (0/18) | **18% (4/22)** |
| B1.5 | 5% (2/40) | 0% (0/18) | **9% (2/22)** |
| STATEFUL | 10% (4/40) | 0% (0/18) | **18% (4/22)** |

> 장기양성 FPR = '긴데 정상 해소' 세션에서의 오탐율. 이 값이 낮아야 STATEFUL의 위기탐지가 '세션 길이'가 아니라 '에스컬레이션'을 잡는 것임이 통제된다.

## detector = `target_agnostic`

| baseline | 임계 | calibFPR | testFPR | recall(전체) | recall(K이내) | recall(K초과) | TTD(전체) | TTD(K초과) |
|---|---|---|---|---|---|---|---|---|
| B1 | 0.55 | 5% | 2% | 0% | 0% (35) | 0% (27) | — | — |
| B1.5 | 0.36 | 5% | 15% | 5% | 0% (35) | 11% (27) | 1.33 | 1.33 |
| STATEFUL | 1.01 | 0% | 0% | 0% | 0% (35) | 0% (27) | — | — |

**델타 컬럼 (필수 — STATEFUL 기준):**

| 비교 | Δrecall(전체) | Δrecall(K초과) | ΔTTD(전체) |
|---|---|---|---|
| STATEFUL − B1 | +0.0%p | +0.0%p | — |
| STATEFUL − B1.5 | -4.8%p | -11.1%p | — |

> TTD(time-to-detect)=success_turn−detect_turn, user-턴 단위. 양수=조기 탐지(클수록 좋음).

**Δrecall 부트스트랩 95% CI (ISC-2.3, 짝지은 복원추출 2000회·seed=20260629):**

| 비교 | Δrecall 점추정 | 95% CI |
|---|---|---|
| STATEFUL − B1 | +0.0%p | [+0.0%p, +0.0%p] |
| STATEFUL − B1.5 | -4.8%p | [-11.3%p, +0.0%p] |

> 사활 컬럼(vs B1.5) CI 0을 포함(비유의 가능). 점추정 부호와 함께 CI로 불확실성을 정직 노출.

**동일 작동점(matched test-FPR) recall 재비교 (작동점 정렬 — critic 지적):**

> 임계를 동일 FPR 예산이 아니라 동일 test-FPR로 맞춘 뒤 recall 비교. 'STATEFUL FPR≠B1.5 FPR이라 recall 비교 불공정'에 답한다.

| target FPR | B1 recall (FPR) | B1.5 recall (FPR) | STATEFUL recall (FPR) | **ΔSTATEFUL−B1.5** |
|---|---|---|---|---|
| ≤5% | 2% (5%) | 0% (2%) | 0% (0%) | **+0.0%p** |
| ≤10% | 3% (10%) | 2% (10%) | 0% (0%) | **-1.6%p** |
| ≤20% | 8% (20%) | 5% (15%) | 15% (18%) | **+9.7%p** |

> 괄호=해당 임계에서 실제 달성 test-FPR. 같은 FPR 예산에서도 ΔSTATEFUL−B1.5가 양수면 작동점 정렬 후에도 우위가 유지된다는 증거.

**testFPR 분층 (길이 교란 통제 — 장기-양성에서의 오탐이 진짜 FPR):**

| baseline | testFPR(전체) | FPR(단기음성 K이내) | **FPR(장기양성 K초과)** |
|---|---|---|---|
| B1 | 2% (1/40) | 6% (1/18) | **0% (0/22)** |
| B1.5 | 15% (6/40) | 0% (0/18) | **27% (6/22)** |
| STATEFUL | 0% (0/40) | 0% (0/18) | **0% (0/22)** |

> 장기양성 FPR = '긴데 정상 해소' 세션에서의 오탐율. 이 값이 낮아야 STATEFUL의 위기탐지가 '세션 길이'가 아니라 '에스컬레이션'을 잡는 것임이 통제된다.

## Thesis 판정 (정직 — 수치 근거)

> 판정 규율: **'성립'은 사활 컬럼(vs B1.5) McNemar exact p<0.05일 때만**. 유의 아니면 '방향성 지지(비유의)' — 점추정 부호만으로 성립 선언 금지.

### detector=`target_aware` → **성립**
- Δrecall(STATEFUL−B1, 전체)=+19.4%p
- Δrecall(STATEFUL−B1.5, 전체)=+53.2%p  ← 사활 컬럼
- Δrecall(STATEFUL−B1.5) 95% CI=[+40.3%p, +66.1%p]  ← 부트스트랩(ISC-2.3)
- Δrecall(STATEFUL−B1.5, K초과)=+63.0%p  ← 무한룩백 잔여우위(recall)
- ΔTTD(STATEFUL−B1.5, 전체)=+0.30 / K초과=+0.80  ← 조기탐지 축(양수=STATEFUL이 더 이른 턴에 탐지)
- **McNemar exact (STATEFUL vs B1.5): p=0.000** (불일치쌍 b=34·c=1; b=STATEFUL만 탐지, c=B1.5만 탐지) ← 사활 유의성
- McNemar exact (STATEFUL vs B1): p=0.004 (불일치쌍 b=14·c=2)
- → vs B1.5 유의(p<0.05)

### detector=`target_agnostic` → **미성립**
- Δrecall(STATEFUL−B1, 전체)=+0.0%p
- Δrecall(STATEFUL−B1.5, 전체)=-4.8%p  ← 사활 컬럼
- Δrecall(STATEFUL−B1.5) 95% CI=[-11.3%p, +0.0%p]  ← 부트스트랩(ISC-2.3)
- Δrecall(STATEFUL−B1.5, K초과)=-11.1%p  ← 무한룩백 잔여우위(recall)
- ΔTTD(STATEFUL−B1.5, 전체)=— / K초과=—  ← 조기탐지 축(양수=STATEFUL이 더 이른 턴에 탐지)
- **McNemar exact (STATEFUL vs B1.5): p=0.250** (불일치쌍 b=0·c=3; b=STATEFUL만 탐지, c=B1.5만 탐지) ← 사활 유의성
- McNemar exact (STATEFUL vs B1): p=1.000 (불일치쌍 b=0·c=0)
- → vs B1.5 비유의(p≥0.05)

### 종합 (정직 결론)
- target_aware: 성립 / target_agnostic: 미성립
- 두 detector 모두 유의 성립이면 자기충족(circular) 아님. 한쪽만/방향성/미성립이면 그대로 정직 보고.
- **target_aware만 사활 컬럼 유의(p<0.05)로 성립**, 나머지는 방향성 지지(비유의). → '유의 성립 detector만 한정 성립, 나머지는 방향성'으로 정직 보고(graph_weight=0.0 정신).
- 미성립/방향성의 엔지니어링적 이유 후보: 소표본으로 불일치쌍이 적어 McNemar 검정력이 낮거나, 임계가 calib에 과적합되어 과탐하거나, 누적이 정상 세션에서도 포화해 임계가 밀려 미탐할 수 있으며, 드리프트 신호의 정상/위기 분리력에 한계가 있다(detector별 수치로 판단).
- **장기-양성(긴데 정상) 오탐 비용 정직 명시 — recall 우위는 공짜가 아니다:**
  - `target_aware`: STATEFUL 장기양성 FPR=18% (4/22) ⚠초과 vs B1.5 9% (2/22). calib 예산 5%는 단기 위주 calib에서 동결되어 장기-양성 FPR을 직접 보장하지 않는다.
  - `target_agnostic`: STATEFUL 장기양성 FPR=0% (0/22) vs B1.5 27% (6/22). calib 예산 5%는 단기 위주 calib에서 동결되어 장기-양성 FPR을 직접 보장하지 않는다.

> ⚠ 소표본 caveat: C1 양성 풀 62세션·C3 test 40세션. 표본을 확대했으나 여전히 점추정이다. McNemar는 불일치쌍에만 의존하므로 표본이 작으면 검정력이 낮다(유의=강증거, 비유의≠반증).
