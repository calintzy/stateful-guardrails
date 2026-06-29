# PLAN.md — stateful-guardrails 실행·보완 계획 (ralplan / deliberate)

> 본 문서는 `DESIGN.md`를 **대체하지 않는다**. DESIGN.md의 무엇을 어떻게 보완·구현·재배열할지의 실행 계획이다.
> 모드: **DELIBERATE** (pre-mortem + 확장 테스트 계획 포함). consensus 후속: Architect/Critic 리뷰 대상.
> 프로젝트 고정 사실(이름 stateful-guardrails / CLI `sgr` / 1인 수주 / 고객지원 위기 조기경보 도메인 / Ollama고정 / 평가규율=심장)은 변경하지 않는다.

---

## A. RALPLAN-DR 요약

### A.1 Principles (5)
1. **평가가 심장.** 모든 설계·순서 결정의 1차 기준은 "stateful vs stateless 델타를 *정직하게* 측정 가능한가"다. 코드 양·기능 수가 아니라 측정 규율이 산출물의 가치다.
2. **Thesis-first 수직 슬라이스.** thesis(C1 누적 위기 에스컬레이션에서 stateful>stateless)를 증명하는 최소 수직 슬라이스를 먼저 완성한다. 메모리게이트·에스컬레이션·서버데모는 thesis 증명 *이후* 가산.
3. **정직한 측정 = 반순환(anti-circular).** 델타가 "stateless가 못 잡게 데이터를 짠" 자기충족 산물이 되어선 안 된다. 데이터는 에스컬레이션 패턴 카탈로그 기반으로 생성하고, baseline은 *공정하게 강한* stateless로 둔다.
4. **Scope discipline (YAGNI 사다리).** 모든 기능은 thesis 기여도로 정당화한다. 기여 낮으면 cut. Non-goal(NG-1~7) 엄수.
5. **계승 규율.** Mycelium의 클린아키텍처·정직결론(graph_weight=0.0 정신)·`.ai.md` 레이어 가드·합성데이터 공개를 계승한다.

### A.2 Decision Drivers (top 3)
1. **델타의 정직한 측정 가능성** — 자기충족·약한baseline·threshold 게이밍 함정 회피가 프로젝트 신뢰의 사활.
2. **1인 수주 범위 내 완주** — 미완성 리스크가 최대 적. thesis slice를 먼저 de-risk.
3. **누적 알고리즘의 구체적 buildability** — 감쇠·임계 v1 공식이 명시되어야 Phase 2가 검증 가능. longitudinal 신호가 stateless의 per-turn max를 실제로 능가하는 *메커니즘*이 있어야 한다.

### A.2.5 Thesis 한정 & Baseline 정의 (B1 / B1.5 / B2) — [BLOCK-1 흡수 · sliding-window 보강]

**Thesis(최종 한정 — single-session):** *"online·**단일 세션 무한길이**·비용제약 환경(매 턴 전체 세션을 재판정할 수 없는 조건) 하에서, 누적 상태(stateful)는 stateless(per-turn·고정 sliding-window 포함) 대비 고객 대화의 위기 도달을 더 적은 비용으로·더 이른 턴에·무한 룩백으로 예측한다. 개별 메시지는 약한 불만이라 단발 판정은 놓치지만 누적은 잡는다."*
- **범위 한정(5번 처리):** 모든 ISC가 **단일 세션 내** 측정이므로 thesis는 **single-session 무한길이**로 한정한다. cross-session(세션 간) 추적의 정확도 우위는 **측정 없이 주장하지 않으며**, 추후 별도 "측정 가산" 항목으로만 분리한다(DESIGN 0장 longitudinal 공백 (2)는 미래 측정 가산으로 표기). 측정 없는 cross-session 정확도 우위 주장 금지.
- 정당성 축은 **정확도 단독이 아니라 비용/컨텍스트윈도우/online 조기탐지/무한 룩백**이다. 누적상태 없이 전체 세션을 한 번에 long-context judge에 넣으면(B2) 정확도는 stateful과 대등하거나 더 높을 수 있다 — 그래도 **정직 보고**하되, stateful의 정당성을 "B2는 매 턴 전체 재판정이 비용·윈도우상 불가한 online 운영에서 쓸 수 없다"로 재서술한다.

**검증 자세(확정 — 함의 4):** thesis는 "stateful이 이긴다"가 **아니라** "stateful의 가치를 반증 가능하게 검증한다"이다. **미성립(STATEFUL이 B1.5 못 이김)도 유효한 결과**이며, 그 경우 "왜 미성립인지를 엔지니어링 언어로 설명"하는 것이 산출물(graph_weight=0.0 정신). 가장 현실적 엔딩은 **"작은 우위 또는 미성립의 정직 보고"**이며, 그것으로 산출물 가치는 성립한다(측정 규율 자체가 가치).

**Baseline 4종(공정 강baseline 규율):**
- **B1 — per-turn stateless (max).** 각 메시지를 독립 판정, 최강 per-turn detector의 max. **고정사실 `session_state=None → 동일코드`로 공짜 산출**(별도 예산 0).
- **B1.5 — sliding-window stateless (window=K).** **최근 K턴만** judge에 투입하는 stateless·online·O(K) 저비용 중간 baseline. B1(per-turn)·B2(full-session) 양극단 사이의 *진짜 경쟁자*다. 누적식 `S_t=clip(λ·S_{t-1}+signal,0,S_max)`는 본질적으로 EWMA(손실 압축)이므로, **"stateful은 sliding-window의 손실 압축일 뿐"이라는 시니어 반론**을 막으려면 B1.5를 반드시 이긴다는 증거가 필요하다. STATEFUL의 잔여 우위는 **무한 룩백(K턴 밖 불만 신호 보존)·O(1) 상태 메모리·세션 경계 처리**에서 나온다.
- **B2 — full-session-context stateless (오프라인 상한선).** 누적상태 없이 **전체 세션을 한 번에 long-context judge에 투입**해 판정. ⚠️ **B1과 달리 `session_state=None`으로 공짜로 안 나온다** — 전체 세션 프롬프트 구성·long-context judge 호출의 **별도 경로·별도 구현·별도 예산**이 필요(Phase 2에 명시). 리포트엔 **upper-bound 참조군**으로 병기.
- **STATEFUL — 누적 상태 참조.** 우리 가설 대상. 판정 대상 델타는 **B1 대비(주장)·B1.5 대비(사활 반론)·B2 대비(정직 상한 대조)를 모두** 산출.

**동결 파라미터(frozen parameters) 정의 — 누수·게이밍 차단:** 평가 전 calibration-split에서만 정하고 test-split 평가 시 **동결**되는 파라미터 집합 = **{임계 t1·t2, 감쇠 λ, sliding-window 크기 K, 누적 상태 윈도우 N(최근 N턴 요약/대비 기준), 누적 상한 S_max}**. 이 5종(t1·t2·λ·K·N·S_max)은 calibration-split 파생 후 test-split에서 절대 재튜닝하지 않는다(ISC-2.6 split 동결로 강제). [Architect의 N·S_max 동결 명문화 + sliding-window K 동결을 함께 닫음.]

**STATEFUL의 sliding-window 대비 잔여 우위(명시 반론):** B1.5(window=K)가 stateful의 가장 강한 반론이다. K턴 안에서는 sliding-window가 stateful과 구조적으로 동등하거나 더 강하다(손실 없는 원문 K턴 vs 손실 압축된 누적 상태). stateful이 B1.5 대비 갖는 *잔여* 우위는 정확히 세 가지다 — (1) **무한 룩백:** 불만 신호가 K턴 이전에 심어지고 K턴 뒤에 위기로 관철되는 longitudinal 패턴을 sliding-window는 윈도우 밖으로 흘려 못 잡는다. (2) **O(1) 상태 메모리:** sliding-window는 O(K) 컨텍스트를 매 턴 judge에 재투입하나 stateful은 고정 크기 상태만 참조 — 무한 세션에서 비용 격차가 단조 증가. (3) **세션 경계 처리:** 세션 길이가 K를 초과하는 구간에서만 (1)(2)가 측정 가능하다(→ ISC-2.7로 자연 분포 생성 + K 초과 비율 공개 + K 이내/초과 분층 보고; K 이내에선 B1.5≈STATEFUL을 정직 보고). **이 셋 중 하나라도 측정으로 입증 못 하면 thesis는 "sliding-window의 손실 압축" 반론에 무방비이며, 그 경우 정직 보고한다(graph_weight=0.0 정신).**

> 결론 규율: STATEFUL이 B1.5를 못 이기면 **thesis 미성립을 정직 보고**(graph_weight=0.0 정신). B2와 대등/열위여도 서사 붕괴는 아니다 — "B1·B1.5 대비 우위 + B2와 동급 정확도를 **B2의 1/N 비용·고정윈도우·online·무한룩백**으로 달성"이면 thesis는 선다. 모든 경우 정직 보고.

### A.3 Viable Options

**Option A — DESIGN.md 선형 Phase 0→5 그대로.**
- Pros: 문서 일관, 각 phase 완결, 메모리게이트·에스컬레이션까지 풀 데모.
- Cons: **eval(심장)이 맨 마지막** → 시간 소진 시 thesis 미증명으로 끝날 위험 大. scope creep에 가장 취약.

**Option B — Thesis-first 재배열 (권장).**
- 순서: P0 → P1(stateless 카탈로그) → P2(stateful 엔진 + 누적 v1 공식) → **조기 미니-eval(C1+C3만)으로 델타 존재 증명** → 이후 메모리게이트(C2)·에스컬레이션(C4)·한국어 풀데이터셋·서버데모를 가산 phase로.
- Pros: thesis를 ~3-4주에 de-risk. 시간 부족으로 멈춰도 핵심 주장은 증명됨. 정직 측정 함정을 조기 노출.
- Cons: DESIGN의 phase 번호 재배열 필요. 메모리게이트(채용 어필 일부)가 뒤로 밀림.

**Option C — 메모리게이트(C2) 우선.** → **무효화.** C2(오염된 고객 컨텍스트 기록)의 탐지는 상당 부분 *쓰기 시점 콘텐츠의 stateless 검사*다. session-state 누적의 증명력이 C1보다 약하다. thesis 기여도가 낮으므로 우선 배치 근거 없음. (단, "직전 대화 상태에 비추어야만 왜곡"인 cross-message 오염으로 좁히면 stateful 기여가 살아나며 — 그 형태로만 C2를 유지한다.)

**선택: Option B.** A 대비 thesis de-risk 우선, C 대비 증명력 우선.

### A.4 최소 완주선 (필수 vs 가산) — [함의 2: 완주선 한 번 더 축소]

> 근거: codex·Critic 모두 scope 경고. **B1.5가 sliding-window 반론의 핵심 방어이므로 B2(full-session 상한선) 없이도 thesis는 성립**한다. 제일 먼저 무너질 곳은 알고리즘이 아니라 **한국어 데이터셋 + 평가 하니스**다. 따라서 완주선을 한 번 더 축소한다.

**최소 완주선(필수) — 이것만 끝나도 thesis는 선다:**
`C1/C3 + B1/B1.5/STATEFUL + holdout(calibration↔test split 동결) + 한국어 골드시드 10~20세션`
- 즉 카테고리는 **C1(누적 위기 에스컬레이션)·C3(정상 해결 대화·오탐 대조군)** 만, baseline은 **B1(per-turn)·B1.5(sliding-window)·STATEFUL** 셋만, 측정 규율은 **holdout 선캘리브레이션·동결**, 데이터는 **사람이 쓴 한국어 골드시드 10~20세션 + 그 증강**.

**가산(일정 흔들리면 컷):**
- **B2(full-session 상한선)** 와 **λ 민감도 곡선** — 정직성 보강이나 thesis 성립의 필요조건 아님.
- **C2(오염된 고객 컨텍스트 기록)·C4(매니저/이탈방지팀 에스컬레이션)** 카테고리.
- **LangGraph 메모리게이트**, **한국어 4카테고리 풀 데이터셋**, **에스컬레이션 3단계(봇 자동응대 / 상담사 이관 / 매니저 이관 — 도메인상 데모 가치 높은 핵심 활용 스토리)**, **선택적 서버 데모**.

**규율:** 가산 항목의 ISC는 **삭제하지 않고 `[가산]`으로 태깅**한다(가산 수행 시 그대로 사용). 특히 **B2 관련 ISC(ISC-1.5의 B2 등록·ISC-2.3/2.4/5.7의 B2 컬럼·ISC-5.6 λ-sweep)는 보존하되 `[가산]`**. 필수 ISC는 `[필수]`로 태깅한다(E장).

---

## B. 검증 결과 — DESIGN.md 약점·갭·과욕 (우선순위)

> 우선순위: P0=thesis 붕괴 위험 / P1=buildability·정확성 / P2=품질·완성도.

### [P0-1] eval이 Phase 5 맨 뒤 — 심장이 마지막에 뛴다
- **문제:** 프로젝트의 유일한 정량 주장(4.3 델타)이 6개 phase 중 마지막. Pre-mortem #1과 직결.
- **보완:** Option B로 재배열. P2 직후 **미니-eval 게이트**(C1 ~15세션 + C3 ~15세션, 한국어 일부)를 넣어 델타 부호·크기를 조기 확인. 이게 음수/0이면 즉시 메커니즘 재설계(매몰 전).

### [P0-2] 델타의 자기충족·소멸 순환 위험을 설계가 다루지 않음
- **문제:** C1을 "stateless가 못 잡게" 합성하면 델타는 데이터 산물(신뢰 붕괴). 반대로 누적이 per-turn max를 못 이기면 델타 0(서사 붕괴). DESIGN 4.3은 "정직 보고"만 언급, *순환 회피 방법*이 없다.
- **보완(필수):**
  1. C1을 **에스컬레이션 패턴 카탈로그**(반복 미해결로 인한 불만 누적·고객의 기대-실망 괴리 확대·이전 약속 위반/일관성 결여 누적 등 자연스러운 고객 불만 escalation 패턴)에서 생성 — "baseline 실패"를 목표로 삼지 않는다.
  2. **측정 프로토콜 고정(holdout):** C3를 **calibration-split/test-split로 분리**, 임계·λ는 calibration-split에서만 동일 FPR 예산(예: 5%)에 캘리브레이션 → **동결** 후 test-split에서 C1 recall·time-to-detect 비교. 누수·threshold 게이밍 차단(BLOCK-3).
  3. **baseline은 공정하게 강하게(B1+B1.5 필수, B2 가산):** stateless 강baseline = **B1(per-turn 최강 detector max) AND B1.5(sliding-window, window=K)** 가 필수 양축. **B2(full-session long-context judge 상한선)는 가산 상한선 참조군**(함의 2로 가산 강등 — B1.5가 sliding-window 반론의 핵심 방어이므로 B2 없이도 thesis 성립). 약한 baseline으로 델타 부풀리기 금지. 정직성 규율의 핵심(A.2.5·BLOCK-1).

### [P0-3] 누적 알고리즘 공식이 전부 Open Q로 미뤄짐 — Phase 2가 buildable하지 않음
- **문제:** D-1/D-2/D-5가 감쇠함수·임계·누적식을 모두 Q4로 연기. 그러나 Phase 2는 *구체 공식*이 있어야 ISC 검증이 된다. "데이터로 튜닝"은 시작 공식이 있어야 가능.
- **보완:** PLAN에서 **v1 기본 공식 명시**(튜닝 대상이되 buildable):
  - longitudinal score: `S_t = clip(λ·S_{t-1} + signal_t, 0, S_max)`, 지수감쇠 `λ=0.7` v1.
  - signal_t = detector 출력(개별 메시지의 불만·부정 감정·이탈 의사 0~1). 임계 t1·t2는 C3 FPR 예산으로 캘리브레이션(상기 P0-2).
  - **핵심 차별 신호(권장 기본 detector):** 단순 점수합이 아니라 **목표개념(위기 상태)을 향한 임베딩 드리프트**(누적 코사인 이동, target-aware)를 1급 신호로. 점수합만이면 stateless max가 종종 이겨 델타가 약하다.
  - **자기충족 방어 대조군(필수, BLOCK-2):** target-aware 단독은 데이터의 목표개념을 탐지축으로 흘리는 circular 위험 → **target-agnostic 변형**(목표개념 비참조, 직전 N턴 대비 의미 이동량)을 동일 프로토콜로 병렬 비교(ISC-2.5). 둘 다 우위면 자기충족 아님.

### [P0-4] 강baseline이 per-turn(B1)에 멈춤 — 중간 sliding-window(B1.5)·상한선(B2) 누락 [BLOCK-1 · sliding-window 보강]
- **문제:** 현 baseline은 B1(per-turn max)뿐. 그러나 누적 위기 에스컬레이션의 *공정한 강baseline*은 (1) **B1.5 = sliding-window stateless**(최근 K턴만 judge에 투입, online·O(K))와 (2) **B2 = full-session-context stateless**(전체 세션 long-context judge)도 포함해야 한다. **특히 B1.5가 사활적이다** — 누적식 `S_t=clip(λ·S_{t-1}+signal,0,S_max)`는 EWMA(손실 압축)이므로 "stateful은 sliding-window의 손실 압축일 뿐"이라는 시니어 반론에 B1.5 없이는 무방비. B1.5/B2를 빼면 "stateful이 강한 게 아니라 비교군이 약했다"는 반격에 노출.
- **보완(필수):**
  1. **B1.5(중간)·B2(상한선)를 별도 baseline으로 추가**(A.2.5 4종 정의). 주의: `session_state=None`은 **B1만 공짜**, B1.5는 최근 K턴 슬라이딩 윈도우 구성, B2는 전체 세션 프롬프트 구성 + long-context judge 별도 호출 경로라 **각각 별도 구현·예산**이 든다 → Phase 2 산출물·미니-eval 예산에 명시.
  2. **thesis를 online·single-session 무한길이·비용제약 하 stateful 우위로 한정**(A.2.5), STATEFUL의 B1.5 대비 잔여 우위는 **무한 룩백·O(1) 상태 메모리·세션 경계 처리**로 명시. B2는 **오프라인 상한선(upper bound) 참조군**. B1.5/B2와 대등해도 정직 보고하되 정당성을 정확도가 아닌 **비용/윈도우/online 조기탐지/무한룩백** 축으로 재서술.
  3. **사활점 게이트(ISC-2.3·2.4·5.7)를 B1 AND B1.5 대비 델타(필수) + B2 대비 델타(가산)**로 재정의(E장). B1.5를 못 이기면 thesis 미성립 정직 보고. (B2는 함의 2로 가산 강등 — 수행 시 상한선 대조군으로 병기.)
  4. **데이터 정직 분층(ISC-2.7) [함의 3: min>K 강제 → 자연 분포 + 분층 공개로 전환]:** 세션 길이를 **자연스러운 분포로 생성**(K 이내 세션도 포함)하되, **K 너머 장기복선 세션의 비율을 리포트에 공개**하고 결과를 **'K 이내 / K 초과'로 분층(stratified) 보고**한다. K 이내에서 B1.5≈STATEFUL(동등)임을 정직 보고하고, 우위가 K 초과에서만 나오면 그 조건을 명시한다. (인위적 제거 → 정직 분층 공개. 외부의 "동등 케이스를 빼고 우위를 보였다"는 인위성 공격 차단.)

### [P1-1] LangGraph "노드 삽입" 통합 가정이 부정확할 수 있음
- **문제:** DESIGN 2.3(c)는 "메모리 읽기/쓰기 엣지 사이에 게이트 노드 삽입". 그러나 LangGraph의 메모리 쓰기는 보통 그래프 엣지가 아니라 **Store/checkpointer 영속 계층**을 통한다. 쓰기 interception은 "노드 추가"가 아니라 `BaseStore` 래핑(put/get 데코레이트)일 가능성이 높다 — 이게 오히려 NG-2("앞단 미들웨어")와 일치.
- **상태:** *미검증 가정.* 단정하지 않는다.
- **보완:** Phase 3 진입 전 **1일 스파이크**로 실제 API 확인. 게이트를 **Store decorator(put=쓰기게이트, get=읽기배제)**로 재설계. 스파이크 실패 시 fallback: LangGraph 없는 자체 메모리 미들웨어 데모(NG 준수, thesis엔 무영향).

### [P1-2] C2(오염된 고객 컨텍스트 기록)의 "stateful" 정의가 모호 — thesis 기여 약화
- **문제:** 쓰기 콘텐츠의 왜곡 여부는 대체로 stateless. 그대로면 C2는 thesis(누적의 가치)를 지지하지 못하고 별개 기능.
- **보완:** C2를 **cross-message 오염**으로 좁힌다 — "단독으론 정상, 직전 대화 상태/세션 상태에 비추어야 의도 왜곡". 그래야 session_state 참조가 C2에서도 의미를 갖는다. 그 외 단발 왜곡 기록은 stateless 정책으로 분류해 thesis와 분리.

### [P1-3] ISC-2.3이 너무 약함 — "결과가 다름"은 방향을 증명하지 못함
- **문제:** "stateless/stateful 결과가 다름"은 stateful이 *더 나쁠 때도* 통과. thesis 검증 불가.
- **보완(계약 강화):** "stateful이 C1에서 stateless가 놓친 세션을 ≥1건 잡고(recall↑), 동일 FPR 예산 하 C3 오탐이 예산 내". 아래 ISC 재정의 참조.

### [P1-4] time-to-detect에 "위기 도달 턴(point-of-no-return)" 라벨이 스키마에 없음
- **문제:** "고객이 위기에 도달하기 전 몇 턴에 잡았나"(4.2)를 재려면 *위기 도달 턴* ground truth가 필요. D-8 스키마에 없다.
- **보완:** 레코드에 `success_turn`(고객이 위기에 도달—이탈 선언·격분·환불요구—하는 턴 인덱스) 필드 추가. time-to-detect = success_turn − detect_turn(= 위기 전 몇 턴 일찍 경고).

### [P1-5] C1·C4 합성의 현실성 — 순수 LLM 합성은 위험
- **문제(D-7 Threat 재판단):** 점진적·개별약함 불만 누적(C1)과 매니저/이탈방지팀 개입 케이스(C4)는 LLM이 캐리커처화하거나 거부하기 쉽다. "장난감 데이터" 리스크가 C1/C4에 집중.
- **보완:** **C1은 필수선** — 사람이 직접 쓴 골드 시드 10~20세션을 먼저 만들고 LLM은 그 주변 증강만(thesis 사활). **C4 골드시드는 가산선으로 분리** — C4(매니저/이탈방지팀 에스컬레이션)는 Phase 4 가산 phase이므로 골드시드도 필수 완주선에서 빼고 시간 허용 시 작성(Scope 일관: 필수=thesis slice). 현실성이 load-bearing인 카테고리는 합성에 전적으로 의존하지 않는다. 생성 시드·실패케이스 공개(D-7)는 유지.

### [P1-6] 권장 detector가 target-aware뿐 — 자기충족 위험 [BLOCK-2]
- **문제:** P0-3 권장 1순위 신호가 **target-aware**("목표개념을 향한 누적 코사인 이동")뿐이다. 평가 데이터의 "목표개념"을 알고 그쪽 이동을 재면, 데이터 설계가 곧 탐지축이 되는 **자기충족(circular)** 위험. "stateful이 잡았다"가 "우리가 정답을 detector에 흘렸다"와 구분 안 됨.
- **보완(필수):** **target-agnostic 변형을 동일 프로토콜로 비교**한다 — 목표개념을 참조하지 않고 **직전 N턴 대비 의미 이동량(semantic shift magnitude)** 만으로 longitudinal 신호를 만든다. target-aware vs target-agnostic 두 detector를 같은 B1/B2 대비 델타 표에 나란히 올려, target-agnostic도 우위를 내면 자기충족이 아님을 입증. Phase 2 ISC에 추가(ISC-2.5).

### [P1-7] 캘리브레이션·평가가 동일 C3 — 누수 + λ 민감도 미노출 [BLOCK-3]
- **문제(누수):** 현 설계는 ISC-1.4 임계 캘리브레이션과 ISC-2.3/2.4 평가가 **동일 C3**를 쓴다. 임계를 맞춘 데이터로 성능을 재면 낙관 편향(데이터 누수). **dev 튜닝 금지·holdout 캘리브레이션**이 명문화돼야 정직.
- **문제(λ 민감도):** Pre-mortem #2는 "λ 변화에 델타 부호가 뒤집힘"을 경보로 든다. 이를 **숨기지 말고 정직성 증거로 전환**해야 한다.
- **보완(필수):**
  1. **C3를 calibration-split / test-split로 분리.** 임계(FPR 예산)·λ는 **calibration-split에서만** 튜닝, 사활점 평가(ISC-2.3/2.4)는 **test-split + 동결된 임계/λ**로만. 분리·동결을 ISC로 강제(ISC-1.4 재정의, 신규 ISC-2.6).
  2. **λ 민감도 곡선(델타 vs λ)을 리포트 필수 산출물 ISC로 추가**(ISC-5.6). λ∈{0.5,0.7,0.9,1.0} 등에서 B1·B2 대비 델타를 표/곡선으로 게시. 부호가 뒤집히는 구간이 있으면 그대로 보고(정직성 증거).

### [P1-8] 데이터 생성 모델 ↔ 평가/detector 모델 동일계열 순환 [신규 anti-circular · 함의 1 · P2급 상관에서 격상]
- **문제:** 합성 C1을 만든 LLM과 평가하는 detector/judge(Ollama)가 비슷한 계열이면, STATEFUL이 탐지한 것이 "longitudinal 위기 신호"가 아니라 **"그 생성모델 합성 문체의 점진 패턴"** 일 수 있다(순환). target-aware/agnostic 대조(P1-6)·holdout(P1-7)와 별개 축의 순환이다. 비차단으로 스쳤던 **P2급 상관 항목을 정식 anti-circular 항목으로 격상**한다.
- **보완(필수):** 데이터 생성 모델군과 평가/detector 모델군을 **가급적 다른 계열로 분리**한다. 분리 불가 시(예: 둘 다 Ollama 단일 모델) 그 한계를 리포트에 **명시**한다(graph_weight=0.0 정직 규율). **생성·평가 모델 식별자를 리포트에 기록하고 동일계열 여부(같음|다름)를 명시**(ISC-2.8). 동일계열이면 "생성문체 순환 가능성"을 caveat로 자동 표기.

### [P2-1] Phase 0~5 풀스코프가 수주에 비현실적
- **문제:** 6 phase 각각 실질적. 특히 P3(LangGraph)·P4(에스컬레이션)·P5(4카테고리 한국어 데이터셋+하니스)는 각각 다일.
- **보완:** Option B + **A.4 최소 완주선**으로 필수를 한 번 더 축소. 필수 = `C1/C3 + B1/B1.5/STATEFUL + holdout + 한국어 골드시드 10~20세션`. **B2·λ곡선·C2/C4·P3(LangGraph)·P4·풀데이터셋·서버데모는 모두 가산·cut가능**. 완주 정의 = thesis(C1에서 STATEFUL vs B1·B1.5 델타) 증명 + 정직 리포트, 나머지는 시간 허용 시.

### [P2-2] 강한 stateless baseline ↔ 외부도구 정합성 미언급
- **문제:** 회의적 시니어: "당신의 stateless가 LLM Guard보다 약한 거 아니냐 → 델타 부풀림". 
- **보완:** stateless baseline의 detector를 문서화하고, 가능하면 1개 정책을 공개도구 카탈로그 개념(LLM Guard 차용)에 정렬해 "약한 허수아비 아님"을 명시.

### 기타(P2)
- D-5 임계 t1/t2가 expert-only 카테고리와 결합되는 우선순위(점수 vs 카테고리 강제승급) 규칙 명문화 필요.
- ✅ `sgr` CLI 명령 네이밍 통일 완료(DESIGN 5장의 `python -m ssm` 전건을 `sgr`로 치환, 고정사실: CLI=`sgr`).

---

## C. Pre-mortem — "6주 뒤 실패했다면 왜인가" (3)

**시나리오 1 — Scope creep으로 미완성.** P3(LangGraph)·P4에 갇혀 eval을 못 돌리고 thesis 미증명으로 종료.
- *조기경보:* 3주차 종료 시 P2(stateful 엔진) 미완 / 미니-eval 미실행.
- *완화:* Option B 강제. thesis slice 외 모든 것은 가산. 주차 게이트로 P2+미니eval을 4주차 데드라인에 못박는다.

**시나리오 2 — 델타가 자기충족 또는 소멸해 서사 붕괴.** C1을 baseline 실패하도록 짜서 수치 불신, 또는 누적이 per-turn max를 못 이겨 델타≈0.
- **변종 2b — K-window가 stateful과 동등해 잔여 우위 0.** sliding-window(B1.5, window=K)가 stateful을 따라잡아 STATEFUL−B1.5≈0 → "stateful은 sliding-window의 손실 압축일 뿐" 반론에 함락.
- *조기경보:* 미니-eval에서 델타가 임계 민감도에 좌우됨; **STATEFUL−B1.5 델타가 0 부근**이거나 자연 분포상 **K 초과(장기복선) 세션 표본이 너무 적어** 잔여 우위 측정력 부족.
- *완화:* 에스컬레이션 패턴 카탈로그 기반 C1 생성 + C3 FPR 선캘리브레이션 + 임베딩 드리프트 신호 + 공정 강baseline(B1·B1.5 필수, B2 가산). **세션 길이 자연 분포 + K 초과 비율 공개 + K 이내/초과 분층 보고(ISC-2.7)**로 무한 룩백 우위를 정직하게 노출(K 이내에선 B1.5≈STATEFUL을 그대로 보고). 그래도 STATEFUL−B1.5 델타 미미하면 **정직 보고**(graph_weight=0.0 정신)로 서사를 "측정 규율" 자체로 전환. **가장 현실적 엔딩이 "작은 우위 또는 미성립의 정직 보고"임을 처음부터 수용**한다 — 미성립도 유효 산출물(함의 4).

**시나리오 3 — LangGraph 통합이 막혀 시간 폭발.** "노드 삽입" 가정이 틀려 메모리 interception 구현이 늪이 됨.
- *조기경보:* Phase 3 스파이크 1일 내 PoC 실패.
- *완화:* 스파이크 선행. 게이트를 Store decorator로 재설계. 안되면 LangGraph 없는 자체 미들웨어 데모로 fallback(thesis 무영향, NG 준수).

---

## D. 확장 테스트 계획 (unit / integration / e2e / observability)

- **unit:** Policy.evaluate 결정성(동일 입력→동일 출력) / 감쇠공식 `S_t=clip(λ·S_{t-1}+signal,0,S_max)` 수학 정확성·경계 / KV 직렬화·역직렬화 라운드트립 / 카테고리·stateless|stateful 태깅 무결성 / time-to-detect 산식(success_turn−detect_turn).
- **integration:** B1 경로(`session_state=None` 공짜)/**B1.5 경로(최근 K턴만 judge 투입, O(K) sliding-window)**/STATEFUL 경로 분기 / **B2 경로(전체 세션→long-context judge 별도 호출)** 동작·예산 계측 / 프로세스 재시작 후 SessionState 복원 / 메모리 게이트 격리·통과 분기 / Store decorator의 put/get interception 동작 / FPR 캘리브레이션 루틴(**C3 calibration-split→임계 산출**) / **split 격리(calibration↔test 세션ID 누수 0)** / **세션 길이 자연 분포 + K 초과 비율 공개 + K 이내/초과 분층 보고 검증 게이트(ISC-2.7)** / **생성↔평가 모델 식별자 기록·동일계열 여부 명시(ISC-2.8)**.
- **e2e:** `sgr eval` 전 파이프라인(dataset→정책별 PR/F1+세션지표+**B1·B1.5·B2 델타표**→report.md) / `sgr demo-agent --scenario poisoning`(의도 왜곡 쓰기 quarantine, 본 메모리 미오염) / 에스컬레이션 3단계(봇 자동응대/상담사 이관/매니저 이관) 라벨링 전구간 / 미니-eval 게이트(**한국어 C1 포함, B1·B1.5·B2 델타 산출, target-aware·target-agnostic 병렬**) / **λ-sweep 곡선 생성**.
- **observability:** 감사 로그 완전성(모든 판정·조치·증거 추적가능) / **리포트 재현성**(seed 고정 시 동일 수치 — 정직성 증거) / time-to-detect 계측 노출 / 실패케이스(FP/FN) 덤프 / 캘리브레이션에 쓰인 임계·FPR을 리포트에 명시.

---

## E. 수락 기준 (ISC 이진: 실행명령 → 기대출력 → pass/fail)

> DESIGN 5장 ISC를 계승·강화. 재배열은 Option B 순서. ISC ID 재번호 금지(DESIGN 원번호 유지 + 신규 prefix).

> **필수/가산 태깅 규율(함의 2):** 각 ISC에 `[필수]`(최소 완주선 A.4) 또는 `[가산]`(일정 흔들리면 컷)을 표기. **B2 관련·λ-sweep·C2/C4·P3~P5 ISC는 삭제하지 않고 `[가산]`으로 보존**(가산 수행 시 그대로 사용).

### Phase 0 — 스캐폴딩·클린레이어
- **ISC-0.1 [필수]:** `sgr --version` → 버전 문자열 → pass/fail
- **ISC-0.2 [필수]:** `pytest tests/test_layering.py` (core가 adapters/langgraph import 안 함) → 통과 → pass/fail
- **ISC-0.3 [필수]:** `sgr ping-llm --provider ollama` → 모델 응답 1줄 → pass/fail

### Phase 1 — Stateless 카탈로그 + baseline
- **ISC-1.2 [필수]:** `pytest tests/test_policies.py` → 전 정책 계약 통과 → pass/fail
- **ISC-1.3 [필수]:** `sgr catalog` → 각 정책에 `(category, stateless|stateful)` 태그 → pass/fail
- **ISC-1.4 (재정의·holdout 캘리브레이션) [필수] [BLOCK-3]:** `sgr scan --mode stateless --input C3.calib.jsonl` → **C3 calibration-split에서만** FPR ≤ 5%로 캘리브레이션된 임계 출력(test-split 미사용 명시) → pass/fail
- **신규 ISC-1.5 (B1/B1.5/B2 baseline 정의) [B1·B1.5 필수 / B2 가산]:** `sgr catalog --baselines` → B1(per-turn max, `session_state=None` 공짜)·**B1.5(sliding-window, window=K, O(K) stateless)** 등록 **[필수]** + B2(full-session long-context judge, 별도 경로) 등록 **[가산]** → pass/fail

### Phase 2 — Stateful 엔진 + 미니-eval 게이트 (thesis de-risk)
- **ISC-2.2 [필수]:** `pytest tests/test_state_persistence.py` (재시작 후 상태 복원) → 통과 → pass/fail
- **ISC-2.3 (재정의·B1 AND B1.5 필수 / B2 가산) [BLOCK-1·sliding-window 보강]:** `pytest tests/test_stateful_delta.py` → **test-split**에서 STATEFUL이 **B1 대비** C1 recall↑(놓친 세션을 잡음) **AND B1.5(sliding-window, window=K) 대비도 recall↑** **[필수]**(못 이기면 thesis 미성립 → 정직 보고) **AND** 동일 FPR 예산 하 C3 오탐 예산 내; **B2(상한선) 대비 델타 산출·기록은 [가산]**(수행 시 B2와 대등/열위여도 통과 — A.2.5 정직 규율) → 통과 → pass/fail
  - *델타 컬럼:* recall·time-to-detect 표에 **STATEFUL−B1 / STATEFUL−B1.5**(필수) **/ STATEFUL−B2**(가산) 컬럼 기록. STATEFUL−B1.5가 핵심 사활 컬럼(무한 룩백 잔여 우위).
  - *유의성 강화:* "≥1건"이 아니라 **유의미 마진(효과크기, 예: recall 델타 + 부트스트랩 신뢰구간)** 으로 보고하되, **소표본 caveat**(미니-eval 세션 수가 작아 점추정임)를 리포트에 명시.
- **신규 ISC-2.4 (미니-eval 심장 게이트·B1/B1.5 필수, B2 가산) [BLOCK-1]:** `sgr eval --mini --dataset data/mini/ --report out/mini.md` → C1 recall·time-to-detect의 **STATEFUL−B1 / STATEFUL−B1.5 델타 컬럼**(필수, 부호·크기 명시) **+ STATEFUL−B2 컬럼(가산, 수행 시)** 생성. **B1.5도 못 이기면 thesis 미성립을 리포트에 정직 명시**(graph_weight=0.0 정신) → 존재 → pass/fail
  - *한국어 필수:* 미니-eval 데이터에 **사람이 쓴 한국어 C1 골드시드 10~20세션 + 증강 필수 포함**(최소 완주선 A.4, 차별점 조기 증명).
- **신규 ISC-2.5 (target-agnostic 대조군) [필수] [BLOCK-2]:** `sgr eval --mini --detectors target_aware,target_agnostic` → 두 detector(목표개념 향한 누적 코사인 이동 vs 직전 N턴 대비 의미 이동량)의 B1/B1.5 대비 델타를 **나란히** 표기(B2 대비는 가산) → 존재 → pass/fail
- **신규 ISC-2.6 (split 동결·누수 차단) [필수] [BLOCK-3]:** `pytest tests/test_split_isolation.py` → 임계·λ·**K·N·S_max(동결 파라미터 5종)** 는 calibration-split 파생, ISC-2.3/2.4 평가는 test-split + **동결 파라미터**만 사용(calibration-split 세션 ID가 test에 누수 없음) → 통과 → pass/fail
- **ISC-2.7 (세션 길이 자연 분포 + 장기복선 비율 공개 + 분층 보고) [필수] [함의 3: min>K 강제 → 정직 분층 공개로 전환]:** `pytest tests/test_dataset_stratified.py`(또는 `sgr data-validate --dataset data/mini/`) → (a) C1 세션 길이를 **자연스러운 분포**로 생성(K 이내 세션도 포함 — 인위적 제거 금지), (b) **K 너머 장기복선 세션 비율을 리포트에 명시 공개**, (c) 평가 결과를 **'K 이내 세션 / K 초과 세션'으로 분층(stratified)** 산출 → 검증 통과 → pass/fail
  - *정직 규율:* **K 이내 세션에서 B1.5≈STATEFUL(동등)임을 그대로 보고**한다. STATEFUL의 우위가 **K 초과 세션에서만** 나타나면 그 조건을 정직 명시한다(인위적 제거가 아니라 정직 분층 공개로 sliding-window 반론·인위성 공격에 답함).
  - *위치 규율:* 미니-eval(Phase 2)·풀 데이터셋(Phase 5) **양쪽 생성·보고 파이프라인의 게이트**. K는 동결 파라미터이므로 데이터 생성 시점에 확정돼 있어야 분층 경계가 고정된다.
- **신규 ISC-2.8 (생성↔평가 모델 분리·anti-circular) [필수] [함의 1]:** `sgr eval --mini --report out/mini.md` 리포트에 **데이터 생성 모델 식별자 / 평가·detector 모델 식별자 기록 + 동일계열 여부(같음|다름) 명시** → 존재 → pass/fail
  - *분리 규율:* 생성 모델군과 평가/detector 모델군을 **가급적 다른 계열로 분리**. 분리 불가(동일계열)면 "생성문체 순환 가능성" caveat를 리포트에 **자동 표기**(graph_weight=0.0 정직 규율). 비차단으로 스쳤던 P2급 상관을 정식 anti-circular 항목으로 격상.

### Phase 3 — 메모리 게이트 + LangGraph (스파이크 선행, 가산)
- **신규 ISC-3.0 (스파이크) [가산]:** LangGraph 메모리 interception PoC 1일 내 동작 또는 fallback 결정 문서화 → 결론 존재 → pass/fail
- **ISC-3.1 [가산]:** `sgr demo-agent --scenario poisoning` → 의도 왜곡 쓰기 quarantine·본 메모리 미오염 로그 → pass/fail
- **ISC-3.2 [가산]:** `pytest tests/test_memory_gate.py` (격리/통과 분기, cross-message 오염 케이스 포함) → 통과 → pass/fail

### Phase 4 — 에스컬레이션 3단계(봇 자동응대 / 상담사 이관 / 매니저·이탈방지팀 이관) + 감사 로그 (가산)
> 가산 phase이나 본 도메인(고객지원 위기 조기경보)에선 데모 가치가 높은 핵심 활용 스토리다(최소 완주선은 불변).
- **ISC-4.2 [가산]:** `sgr audit --session <id>` → 판정·조치·증거 추적 레코드 → pass/fail
- **ISC-4.3 [가산]:** `pytest tests/test_escalation.py` (C4 전건 expert=2[매니저·이탈방지팀] 분류) → 통과 → pass/fail

### Phase 5 — 풀 평가 하니스·리포트 (심장 확장, 가산)
- **ISC-5.2 (강화) [가산]:** 리포트에 stateful vs stateless 델타 표 + **캘리브레이션 임계·FPR 명시** → 존재 → pass/fail
- **ISC-5.3 [가산]:** `sgr eval --show-failures` → 대표 FP/FN N건 + 원인 → pass/fail
- **ISC-5.4 [가산]:** 4카테고리 각 한국어 세션 ≥1건 검증(한국어 4카테고리 풀 — 가산) → pass/fail
- **신규 ISC-5.5 (재현성) [가산]:** seed 고정 2회 실행 시 리포트 수치 동일 → pass/fail
- **신규 ISC-5.6 (λ 민감도 곡선) [가산] [BLOCK-3]:** `sgr eval --lambda-sweep 0.5,0.7,0.9,1.0 --report out/lambda.md` → λ별 **STATEFUL−B1·STATEFUL−B1.5**(+B2 가산) 델타 곡선/표 생성(부호 반전 구간 있으면 그대로 표기 — 정직성 증거) → 존재 → pass/fail
- **신규 ISC-5.7 (B1.5·B2 병기·델타 컬럼) [B1.5 필수 컬럼 / B2 가산 컬럼]:** `sgr eval --baselines B1,B1.5,B2` 리포트에 **STATEFUL−B1 / STATEFUL−B1.5 델타 컬럼(필수)** + **STATEFUL−B2 컬럼·B2(오프라인 상한선) 대비 비용/턴당호출/online 가능성 대비표(가산)** + **B1.5(sliding-window) 대비 STATEFUL의 무한룩백·O(1)상태 우위 대비표** + **K 이내/초과 분층 컬럼(ISC-2.7)** 병기. B1.5도 못 이기면 thesis 미성립을 정직 보고 → 존재 → pass/fail

---

## F. ADR — 채택 결정 기록

- **Decision:** Option B(thesis-first 재배열) + 누적 v1 공식 명시(`S_t=clip(λ·S_{t-1}+signal,0,S_max)`, λ=0.7, 임베딩 드리프트 1급 신호) + anti-circular 데이터·측정 프로토콜(에스컬레이션 패턴 카탈로그 생성 + **C3 holdout split 선캘리브레이션** + **공정 강baseline: B1 AND B1.5(sliding-window, window=K) 필수, B2 가산 상한선**). **최소 완주선(A.4) = `C1/C3 + B1/B1.5/STATEFUL + holdout + 한국어 골드시드 10~20세션`** — B2·λ곡선·C2/C4·LangGraph게이트·한국어 4카테고리 풀·에스컬레이션·서버데모는 **가산(컷 가능, ISC는 `[가산]`으로 보존)**(함의 2). **Thesis는 online·single-session 무한길이·비용제약 하 stateful 우위로 한정**(cross-session 정확도 우위는 측정 없이 주장 금지·추후 측정 가산; B1.5는 사활 반론·B2는 오프라인 상한선 참조군). **thesis 진술은 "이긴다"가 아니라 "반증 가능하게 검증한다" — 미성립도 유효 산출물(함의 4)**. STATEFUL의 sliding-window 대비 잔여 우위 = **무한 룩백·O(1) 상태·세션 경계**. **동결 파라미터 5종{t1·t2, λ, K, N, S_max}** calibration-split 파생·동결. **데이터 세션 길이는 자연 분포로 생성 + K 초과 장기복선 비율 공개 + K 이내/초과 분층 보고(ISC-2.7, 함의 3 — min>K 강제 폐기)**. 자기충족 방어로 **target-aware/target-agnostic 병렬 대조** + **데이터 생성↔평가/detector 모델 동일계열 분리·식별자 기록(ISC-2.8, 함의 1)**, λ 민감도 곡선을 정직성 가산 산출물로 게시.
- **Decision Drivers:** 델타의 정직 측정 가능성 / 수주 내 완주 / 누적 알고리즘 buildability.
- **Alternatives considered:** A(선형 Phase 0→5 — eval 최후, scope creep 취약) / C(C2 메모리게이트 우선 — stateful 증명력 약해 무효화). **Baseline 대안:** B1 단독(per-turn) — "sliding-window의 손실 압축" 반론에 무방비라 기각, B1.5 추가; B2 필수 — scope 과중·B1.5만으로 thesis 성립이라 가산 강등(함의 2); cross-session thesis — 측정 ISC 부재로 over-claim이라 single-session으로 한정. **데이터 대안:** 세션 길이 min>K 강제 — "동등 케이스를 빼고 우위를 보였다"는 인위성 공격에 취약해 기각, 자연 분포 + 분층 공개로 전환(함의 3).
- **Why chosen:** thesis를 ~4주에 de-risk하고, 미완성이어도 핵심 주장이 증명되며, 정직 측정 함정(순환·약baseline·sliding-window 손실압축 반론·게이밍)을 측정 프로토콜로 구조적으로 차단하기 때문.
- **Consequences:** (+) thesis 조기 검증, 완주 리스크↓(최소 완주선 축소로 더 낮아짐), 정직성 강화(B1.5 sliding-window·holdout·target-agnostic·생성↔평가 모델 분리·분층 공개로 반격 면역). (−) DESIGN phase 번호 재배열, 메모리게이트·서버데모·B2·λ곡선 후순위(채용 어필 일부 지연), v1 파라미터는 추후 튜닝 부채로 남음, B1.5 별도 구현이 미니-eval 비용을 약간 키움(O(K) 저비용이라 부담 작음), thesis가 "정확도 우위"가 아닌 "비용/online/무한룩백 우위"·single-session으로 한정돼 서사 강도는 정직성과 맞바꿈. **가장 현실적 엔딩 = "작은 우위 또는 미성립의 정직 보고"임을 처음부터 수용**한다(함의 4) — 미성립도 "왜 미성립인지 엔지니어링 언어로 설명"이 유효 산출물(graph_weight=0.0 정신). 생성·평가 모델 분리 불가 시(Ollama 단일계열) 순환 한계를 리포트 caveat로 정직 노출(함의 1).
- **Follow-ups (→ open-questions):** λ·t1·t2 데이터 튜닝(Q4), detector 기본값 확정(Q2), 데이터셋 규모·골드시드 수(Q3), LangGraph interception 스파이크 결과(신규, 가산), 데모 도메인 고객 이탈/격분 위기 시나리오 여부(Q1), 공개 리포명(Q7), **데이터 생성 모델군 ↔ 평가/detector 모델군 분리 가능성·분리 불가 시 한계 표기 방식(신규, 함의 1)**, **K 초과 장기복선 세션 목표 비율·분층 표본 충분성(신규, 함의 3)**.

---

## G. 실행 순서 요약 (Option B)
P0(스캐폴딩) → P1(stateless 카탈로그 + C3 FPR holdout 캘리브레이션) → **P2(stateful 엔진 + 미니-eval 델타 게이트: B1/B1.5/STATEFUL · 한국어 골드시드 10~20세션 · target-aware/agnostic · 분층(ISC-2.7) · 모델분리(ISC-2.8)) ← thesis 사활점** → **[여기까지가 최소 완주선(A.4) = C1/C3 + B1/B1.5/STATEFUL + holdout + 한국어 골드시드 10~20세션]** → P3(LangGraph 스파이크→메모리게이트) → P4(에스컬레이션·감사) → P5(풀 데이터셋·한국어 4카테고리·리포트). **B2·λ곡선·C2/C4·P3~P5는 가산(시간 흔들리면 컷, ISC는 `[가산]` 보존)**.
