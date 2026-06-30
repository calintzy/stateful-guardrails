# DESIGN.md — Stateful Escalation Early-Warning (가칭)

> 대화형 AI를 위한 **stateful 위기 조기경보 미들웨어**.
> 단발(stateless) 판정이 못 잡는 *시간에 걸친 위기*(누적 위기 에스컬레이션·오염된 고객 컨텍스트 기록)를, 한국어 합성 데이터셋으로 정량 측정하며 더 일찍 잡는 고객지원 대화 신뢰성 계층. 도메인 무관 범용 프레임워크.

본 문서는 첫 포트폴리오 프로젝트 **Mycelium**(로컬 하이브리드 RAG + GraphRAG)의 설계 규율을 계승한다: `D-결정` 형식, 정직한 측정(정직결론 명시), 클린 아키텍처, 합성 데이터만 공개(프라이버시 D-7 계승).

---

## 0. 한 줄 정의와 포지셔닝

**한 줄 정의:** LangGraph 기반 멀티에이전트의 메시지·메모리 흐름 사이에 끼어, 세션에 걸친 누적 위기(고객 불만 누적 → 격분·환불/해지·이탈)를 stateful하게 예측하고 위험도에 따라 사람(상담사·매니저)에게 에스컬레이션하는 위기 조기경보 미들웨어.

**포지셔닝(확정) — "framework를 만들었다"가 아니라 "공정하게 물었다".**
이 프로젝트의 산출물은 도구가 아니라 **반증 가능한 가설검증**이다. "위기 조기경보 미들웨어를 만들었다"가 아니라, **"stateful 상태가 longitudinal 위기 탐지에 *정말로* 가치가 있는지를, 의도적으로 강하게 세운 baseline(특히 B1.5 sliding-window) 상대로 공정하게 묻고, 그 답을 정직하게 보고했다"**가 본 프로젝트의 정체성이다. thesis는 "stateful이 이긴다"가 **아니라** "stateful의 가치를 반증 가능하게 검증한다"이다. 따라서 **미성립(STATEFUL이 B1.5를 못 이김)도 유효한 결과**이며, 그 경우 "왜 미성립인지를 엔지니어링 언어로 설명"하는 것이 곧 산출물이다(Mycelium graph_weight=0.0 정신 계승). 가장 현실적인 엔딩은 **"작은 우위 또는 미성립의 정직 보고"**이며, 그것으로 충분하다 — 측정 규율 자체가 가치이기 때문이다.
**(README 방향 메모:** 공개 README도 "내가 만든 안전 프레임워크" 톤이 아니라 **"대화형 AI의 위기 조기경보 — 강한 baseline 상대로 stateful이 정말 더 일찍 잡는가를 공정하게 검증한 실험과 그 정직한 결론"** 톤으로 작성한다. 채용 타깃은 고객지원 AI·CX·에이전트 품질이다.)

**서사 톤(확정):**
- ✅ "stateless 판정은 필요하나 *longitudinal* 위기엔 불충분하다."
- ❌ "stateless의 한계를 넘는다" (strawman — 시니어가 반격)

**우리가 공격하는 "stateless"의 정의(strawman 회피):** "대화상태를 전혀 못 본다"가 **아니다**. NeMo Colang처럼 세션 내 dialog state를 추적하는 도구도 있다. 우리가 지목하는 공백은 정확히 **"longitudinal 위기 추적 부재"** — 즉 (1) 누적 위기점수(turn 간 불만 신호 누적·감쇠), (2) 세션 간 추적, (3) 오염된 고객 컨텍스트 기록 방어가 없다는 것. 이 셋이 본 프로젝트의 공격면이다.

**주장 톤(확정):**
- ✅ 기존 생태계는 (1) 메모리·대화품질 **통합이 약하고**, (2) **자기 데이터 기반 평가가 빈약하며**, (3) **누적 불만/위기 시나리오와 한국어 CX 커버리지에 공백**이 있다.
- ❌ "기존은 다 못한다."

**경쟁 지형 요약(리서치 완료) — guardrails = 나쁜 대화 결과를 막는 가드레일(에스컬레이션 조기경보 포함):**

| 도구군 | 강점 | 본 프로젝트가 메우는 공백 |
|---|---|---|
| NeMo Guardrails | 입출력 레일(단발 필터) + Colang dialog flow로 **세션 내** 다중턴 대화상태 추적 | 입출력 레일은 현재 메시지만 보는 단발 필터(stateless). dialog flow는 있으나 **누적 위기점수·세션간(cross-session) 추적·오염된 고객 컨텍스트 기록 방어는 미지원**(완료 flow는 5초 후 삭제·인메모리 한정, 1차 출처 확인). 자기 데이터로 정확도 측정 안 함, 한국어 CX 공백 |
| Guardrails AI · LLM Guard | 단발 입출력 가드레일, 스캐너 카탈로그(LLM Guard 35종) | **stateless**(longitudinal 불만 누적 추적 부재), 자기 데이터로 정확도 측정 안 함, 한국어 CX 공백 |
| Letta · Mem0 · Zep | 성숙한 장기 메모리 | 위기 조기경보 기능 전무 — 메모리는 중립 저장소 |
| LangGraph · CrewAI · AutoGen | 오케스트레이션 | 가드레일은 PII·HITL 기본 수준 |
| AGrail (ACL 2025) | 메모리+가드레일 통합 선행연구(유일) | 연구 프로토타입, expert-in-the-loop·멀티에이전트 없음 |

**흡수할 개념(차용, 재발명 아님):**
- LLM Guard → 스캐너 **카탈로그** 개념
- Llama Guard → MLCommons **14 카테고리** 위해 분류 체계
- Presidio → **익명화 파이프라인** 구조
- Guardrails AI → **validate-and-reask**(탐지 후 재작성)

---

## 1. Non-goals — 무엇을 의도적으로 안 만드는가

> "어디를 의도적으로 안 만들었는지"가 이 프로젝트의 핵심 강점이다(재발명 함정 회피, codex 자문 반영). "플랫폼"이 아니라 "미들웨어"다.

| # | 안 만드는 것 | 이유 / 대신 쓰는 것 |
|---|---|---|
| NG-1 | **오케스트레이션 엔진** | LangGraph를 그대로 사용. 그래프 실행은 재발명하지 않는다. |
| NG-2 | **메모리 스토어(벡터DB/장기기억 DB)** | 자체 DB 혁신 아님. 기존 스토어 앞단에 **품질-aware memory middleware**(읽기/쓰기에 위기 게이트를 끼우는 계층)만 둔다. |
| NG-3 | **새 LLM·임베딩 모델 학습** | provider-agnostic 어댑터로 기존 모델 호출만. |
| NG-4 | **프로덕션급 분산/스케일 인프라** | 1인 포트폴리오. CLI 단일 프로세스 + 선택적 단일 서버. SQLite 수준 영속성. |
| NG-5 | **실데이터 수집·실서비스 운영** | 합성 데이터셋만 공개(Mycelium D-7 계승). 실제 고객 상담 로그 등 민감 실데이터 배제. |
| NG-6 | **범용 PII 익명화 엔진 풀구현** | Presidio 구조를 *차용*하되 데모 범위의 최소 스캐너만. PII 자체는 본 프로젝트의 차별점이 아님. |
| NG-7 | **자동 모델 미세조정/강화학습 루프** | 평가는 측정·리포트까지. 자동 개선 루프는 Open Question으로 남김. |

---

## 2. 아키텍처

### 2.1 클린 레이어와 책임

Mycelium의 의존성 방향 계승: `interfaces → pipeline → adapters → core`. 의존성은 항상 안쪽(core)을 향하고, core는 외부를 모른다.

```
interfaces/        CLI(주), 선택적 서버(FastAPI). 사용자/운영자 진입점.
   │  (호출)
pipeline/          판정 파이프라인 오케스트레이션. 메시지 인입 → 정책 실행 →
   │               에스컬레이션 결정 → 감사로그. LangGraph 노드로 끼는 어댑터.
adapters/          외부 경계: LLM provider(OpenAI/Anthropic/Ollama),
   │               메모리 스토어, 영속 상태 저장소, 감사로그 싱크.
core/              순수 도메인: Policy 인터페이스, 위기 판정 로직,
                   세션 상태 모델, 에스컬레이션 정책, 데이터셋 스키마.
                   외부 I/O·프레임워크 의존 없음(테스트 용이).
```

각 레이어 디렉토리에는 `.ai.md`를 두어 허용·금지 import를 명시한다(CLAUDE.md `.ai.md` 규율). 예: `core/`는 `adapters/`·`langgraph`를 import 금지.

### 2.2 데이터 흐름

```
[메시지 인입]
   │  (고객 발화 또는 에이전트 간 메시지)
   ▼
[컨텍스트 로드]  ── 세션 상태 저장소에서 과거 판정 이력·누적 신호 로드
   │
   ▼
[Stateful 판정 엔진]
   ├─ 단발 스캐너들(stateless 정책) 실행 → per-message 불만/이탈 신호
   ├─ 누적 신호 갱신(이전 상태 + 현재 신호) → longitudinal 위기점수
   └─ 종합 위험도 산출(0~2단계)
   │
   ▼
[조치 결정]
   ├─ 0 봇 자동응대(통과/마스킹/재작성=validate-and-reask)
   ├─ 1 상담사 이관 큐로
   └─ 2 매니저(또는 이탈방지팀) 에스컬레이션
   │
   ▼
[메모리 게이트]  ── 고객 컨텍스트 기록 *쓰기* 전 검사/격리(왜곡 요약 방어).
   │               의심 콘텐츠는 격리(quarantine) 버킷으로, 본 메모리 미오염.
   ▼
[감사 로그]  ── 모든 판정·조치·에스컬레이션을 추적 가능한 레코드로 기록
```

### 2.3 핵심 추상화

**(a) Policy 인터페이스 (core)**
모든 정책은 동일 계약을 따른다. stateless·stateful 모두 같은 인터페이스, 차이는 `state` 참조 여부.

```python
class Policy(Protocol):
    id: str                      # 안정적 정책 ID (리포트 키, 절대 재번호 금지)
    category: RiskCategory       # MLCommons 14 카테고리 매핑 + 자체 확장
    def evaluate(self,
                 message: Message,
                 session_state: SessionState | None  # None이면 stateless 모드
                 ) -> PolicySignal:  # score, evidence, suggested_action
        ...
```

**(b) Stateful 판정 엔진 — 과거 상태 참조 방식**
세션마다 `SessionState`(누적 신호 벡터/카운터·최근 N 메시지 요약·정책별 누적 점수)를 유지. 엔진은 현재 메시지 신호를 과거 상태에 누적·감쇠(decay) 적용해 longitudinal 위기점수를 만든다. 핵심: **단발로는 약한 불만이지만 누적되면 위기인 패턴**(점진적 에스컬레이션)을 잡는다. 동일 baseline을 `session_state=None`으로 호출하면 stateless 비교군이 된다(2.4·4장 평가의 증명 축).

**(c) 메모리 게이트가 LangGraph에 끼는 방식**
LangGraph 그래프에서 메모리 읽기/쓰기 엣지 사이에 게이트 노드를 삽입. 쓰기 게이트는 검사 후 통과/격리를 결정하고, 읽기 게이트는 격리·왜곡 의심 항목을 컨텍스트 주입에서 배제. LangGraph 자체는 손대지 않고 노드만 추가(NG-1·NG-2 준수).

### 2.4 stateless baseline의 위치

baseline은 별도 코드가 아니라 **같은 엔진의 한 모드**다(`session_state=None`). 이로써 "stateful 덕분에 잡은 것"과 "stateless도 잡는 것"을 동일 정책·동일 데이터로 분리 측정한다. 이 비교가 프로젝트의 핵심 증명이다(4장).

---

## 3. 핵심 설계 결정 (D-1 ~ D-11)

> 형식: `Why / Alt considered / Threat / Mitigation / Open` (CLAUDE.md 규칙).

### D-1. stateful 상태 저장 방식 — 세션 단위 영속 상태 객체 + 경량 KV 영속화
- **Why:** longitudinal 판정은 세션에 걸친 누적 신호가 필요. 인메모리만으론 프로세스 종료 시 소실, 풀 DB는 NG-4 과잉.
- **Alt considered:** (1) 순수 인메모리(영속성 없음) (2) 전용 시계열 DB (3) 기존 메모리 스토어에 상태도 같이 저장.
- **Threat:** 상태 스키마가 정책과 강결합되면 정책 추가 시 마이그레이션 지옥.
- **Mitigation:** 상태를 정책별 네임스페이스 KV(`policy_id → 누적 신호`)로 느슨하게 보관, SQLite/JSON 어댑터 뒤로 추상화. core는 저장 매체를 모름.
- **Open:** 상태 보존 기간(세션 종료 정의)·감쇠 함수 형태(선형 vs 지수)는 데이터로 튜닝 → Open Questions Q4.

### D-2. 누적 위기 에스컬레이션 탐지 알고리즘 접근 — 신호 누적 + 임계, 단 탐지기는 교체형
- **Why:** 점진적 에스컬레이션은 "개별 메시지 약한 불만 + 추세 위기" 구조. 핵심은 *추세*를 점수화하는 것.
- **Alt considered:** (1) 임베딩 유사도 누적(드리프트 측정) (2) LLM 분류기로 매 턴 불만/이탈 라벨 후 누적 (3) 규칙 기반 키워드 카운팅.
- **Threat:** 단일 방식 고정 시 한쪽 약점(임베딩=의미 드리프트엔 강하나 표현 위장에 약함 / LLM=비용·지연 / 규칙=회피 쉬움)에 종속.
- **Mitigation:** 누적·임계 **프레임워크는 고정**, 턴별 신호 생산자(detector)를 `Policy` 인터페이스 뒤 **교체형**으로. 임베딩/LLM/규칙을 정책으로 꽂아 평가에서 비교.
- **Open:** 어느 detector를 기본값으로 할지는 평가 결과로 결정 → Open Questions Q2.

### D-3. 오염된 고객 컨텍스트 기록 게이트 위치 — 쓰기 경로에 격리(quarantine) 우선
- **Why:** 왜곡 기록은 *쓰기* 시점에 막는 게 최선(읽기 차단은 사후약방문, 이미 후속 응대에 노출 가능).
- **Alt considered:** (1) 읽기 시점 필터만 (2) 쓰기 차단(거부) (3) 쓰기 격리 후 사람 검토.
- **Threat:** 과격한 쓰기 차단은 정상 메모리 손실(오탐 비용 큼). 격리 버킷이 방치되면 운영 부담.
- **Mitigation:** 기본은 **격리 후 통과 보류** + 읽기 게이트에서 격리 항목 배제. 위험도 2는 매니저 검토 큐로(D-5 연계).
- **Open:** 격리 항목 자동 만료/승격 정책 → Open Questions Q4.

### D-4. 정책 카탈로그 구조 — 카테고리 분류 + stateless/stateful 플래그 (LLM Guard 대비 차별)
- **Why:** LLM Guard식 스캐너 카탈로그는 유용하나 전부 stateless·선형. 차별점은 **각 정책에 시간성(stateful) 차원과 표준 카테고리를 부여**하는 것.
- **Alt considered:** (1) LLM Guard처럼 평면 스캐너 리스트 (2) 카테고리 트리만 (3) 정책마다 임의 메타데이터.
- **Threat:** 카탈로그가 LLM Guard의 단순 재현이면 차별성 소멸 → "또 하나의 가드레일".
- **Mitigation:** 모든 정책을 `(MLCommons 14 카테고리 매핑, stateless|stateful, suggested_action)`로 태깅. 카탈로그 자체가 "어떤 위기 신호가 longitudinal인가"를 드러내는 산출물이 되게 한다.
- **Open:** 카테고리를 MLCommons 그대로 둘지 한국 CX 맥락 위기를 확장할지 → Open Questions Q5.

### D-5. 에스컬레이션 3단계 트리거 기준 — 위험도 점수 임계 + 정책 권고 결합
- **Why:** expert-in-the-loop(상담사·매니저 이관)가 채용공고 핵심 요구. 봇 자동응대/상담사/매니저 3단계를 명확한 트리거로 분리해야 신뢰 가능.
- **Alt considered:** (1) 이진(통과/이관)만 (2) LLM이 에스컬레이션 자율 결정 (3) 점수 임계 고정 규칙.
- **Threat:** 임계만으론 맥락 부족, LLM 자율은 비결정적·감사 곤란.
- **Mitigation:** 결정적 임계를 1차 게이트로(재현·감사 가능), 정책의 `suggested_action`을 승급 신호로 결합. 모든 에스컬레이션은 사유·증거와 함께 감사 로그.
  - 0 봇 자동응대: 종합 위험도 < t1 이고 어떤 정책도 매니저 권고 없음.
  - 1 상담사 이관: t1 ≤ 위험도 < t2, 또는 누적 신호 추세 경고.
  - 2 매니저(이탈방지팀) 이관: 위험도 ≥ t2, 또는 컨텍스트 오염 확정, 또는 정책이 manager-only 카테고리(예: 법적 위협·VIP 이탈) 표시.
- **Open:** 임계값 t1·t2와 manager-only 카테고리 목록 → Open Questions Q4·Q5.

### D-6. LLM provider 추상화 — provider-agnostic 어댑터(OpenAI/Anthropic/Ollama 교체형)
- **Why:** Mycelium 계승. 포트폴리오는 비용 0(로컬 Ollama)으로도 돌아가야 하고, 평가 재현성을 위해 provider 교체가 쉬워야.
- **Alt considered:** (1) 단일 provider 고정 (2) LangChain LLM 추상화 그대로 의존 (3) 자체 얇은 어댑터.
- **Threat:** 두꺼운 추상화는 유지비, 얇으면 provider별 기능 차이(함수호출 등) 누수.
- **Mitigation:** core는 `LLMAdapter` 인터페이스(`complete`/`classify`)만 의존. 구현은 adapters에. 평가는 로컬 Ollama 기본, 클라우드는 선택.
- **Open:** 평가 공식 수치를 어느 모델로 고정 게시할지(재현성 vs 성능) → Open Questions Q6.

### D-7. 데이터셋 — 합성 전용, 4 카테고리, 공개 (Mycelium 프라이버시 D-7 계승)
- **Why:** 실데이터(특히 실제 고객 상담 로그)는 프라이버시·동의 문제. 합성만으로도 에스컬레이션 패턴은 충분히 표현 가능하고 공개 가능.
- **Alt considered:** (1) 공개 벤치마크 차용 (2) 실대화 익명화 (3) 순수 합성.
- **Threat:** 합성이 비현실적이면 "장난감 데이터"로 평가 신뢰 하락.
- **Mitigation:** 합성 시드를 문서화(생성 프롬프트·규칙 공개)하고, 대표 실패 케이스(false positive/negative)를 같이 공개해 현실성 입증. 한국어 포함.
- **Open:** 데이터셋 규모(샘플 수)·합성 생성 방식(수작업 vs LLM 생성+검수) → Open Questions Q3.

### D-8. 데이터셋 스키마·분할·지표 — 세션 단위 레코드 + 정책별 라벨
- **Why:** longitudinal 위기는 단일 메시지가 아니라 **세션(메시지 시퀀스)** 단위로 라벨해야 측정 가능.
- **Alt considered:** (1) 메시지 단위 라벨만 (2) 세션 단위 라벨만 (3) 둘 다.
- **Threat:** 세션만 라벨하면 어느 턴에서 탐지했는지(조기 탐지)를 못 잰다.
- **Mitigation:** 레코드 = `{session_id, messages[], turn_labels[], session_label, category, expected_action}`. 메시지·세션 양 레벨 라벨 보유. train/dev/test 분할은 세션 단위로(누수 방지).
- **Open:** 분할 비율·교차검증 여부 → Open Questions Q3.

### D-9. 한국어 처리 — 한국어를 1급 시민으로, 다국어 정책은 언어 태깅
- **Why:** 기존 생태계의 명확한 공백이자 채용 타깃(국내 CX) 적합성. 차별점.
- **Alt considered:** (1) 영어 우선, 한국어 후순위 (2) 번역 후 영어 정책 재사용 (3) 한국어 네이티브 정책·데이터.
- **Threat:** 번역 경유는 불만·뉘앙스 손실. 한국어 토큰화·정규화 미흡 시 규칙 정책 무력화.
- **Mitigation:** 데이터셋과 정책 평가 모두 한국어 케이스 포함, 신호에 언어 태그 부착. LLM/임베딩 detector는 다국어 모델 사용으로 번역 우회.
- **Open:** 한국어 전용 정규화/형태소 처리 깊이를 어디까지 → Open Questions Q5.

### D-10. 인터페이스 — CLI 주, 서버 선택 (Mycelium 계승)
- **Why:** 포트폴리오 재현성·데모 용이성. 평가 파이프라인은 CLI로 충분.
- **Alt considered:** (1) 서버 우선 (2) 노트북 (3) CLI 우선.
- **Threat:** CLI만으론 멀티에이전트 흐름 데모가 빈약해 보일 수 있음.
- **Mitigation:** CLI로 평가·리포트 전체 재현, 선택적 FastAPI 서버로 LangGraph 에이전트 데모(에스컬레이션 큐 가시화).
- **Open:** 데모를 고객 이탈/격분 위기 시나리오로 입힐지 중립 도메인으로 둘지 → Open Questions Q1.

### D-11. 장기-양성 오탐 개선 시도 — signed 신호 + calib 보강 (미채택, holdout이 기각)
- **배경:** 표본을 87→200세션으로 확대 재측정하자 장기-양성(긴 정상 대화) 오탐이 31%(17/55)로 드러났다. 누적식이 길이에 약하다는 한계.
- **진단(실측):** 길이·신호 개수는 주범이 아니었다. 정상-장기 S_t가 0.10~0.16에 몰려 있는데 임계(0.11)가 그 한가운데를 지났다. 원인은 ① 양수부만 누적(`max(0,Δ)`)해 정상 대화의 등락이 상쇄되지 않음, ② 임계가 단기 위주 calib(장기-양성 5개)에서 낮게 산출됨.
- **개선 설계:** ① signed 신호(`signal = Δcos`, 음수부도 반영)로 등락 상쇄, ② calib에 장기-양성 보강(5→19개)으로 임계가 '긴 정상 대화 기저'를 반영. dev에서 설계 확정.
- **dev 결과(낙관):** signed가 양수부 대비 같은 오탐 예산에서 recall +15%p, Δ(STATEFUL−B1.5)가 +51.3→+65.2%p로 커 보였다.
- **holdout 검증(새 200세션, 1회):** 기존과 시나리오가 겹치지 않는 holdout을 새로 생성해 동결값으로 단 1회 평가. 결과 — **장기-양성 오탐은 31%→5%(3/55)로 해결**됐으나 **핵심 우위 Δ(STATEFUL−B1.5)=−0.9%p, McNemar p=1.000(b=12,c=13)로 미재현**.
- **Threat:** dev 낙관(+65%p)에 안주해 채택했다면, test 정보가 새어든 과적합 결론을 발표할 뻔했다.
- **Mitigation:** codex 자문(agent-council)으로 "기존 200은 이미 설계에 정보를 줬으니 새 holdout이 필요하다"를 받아들여, 새 holdout 1회 검증으로 걸렀다. 발견 — **'낮은 오탐'과 'recall 우위'는 트레이드오프**다. 오탐을 5%로 누르는 임계 상향이 위기 recall을 같이 죽였다.
- **결정:** 검증된 기존 양수부 신호(+51.3%p, holdout 외 dev 기준)를 **유지**한다. signed/보강 calib은 미채택. `out/holdout_final.md`에 전 과정 보존.
- **Open:** 작동점을 분리(임계를 낮춰 recall을 살리되 오탐을 다른 메커니즘으로 통제 — 예: 순간신호 게이트·baseline-corrected score)하는 길은 *또 다른 새 holdout*에서 검증해야 함 → 향후 과제.

---

## 4. 평가 프로토콜 (프로젝트의 심장)

> codex 자문: 프로젝트의 심장은 **기능 수가 아니라 평가 규율**이다. 이게 없으면 "룰엔진 하드코딩"으로 보이고, 있으면 구현이 거칠어도 진짜 엔지니어로 보인다.

### 4.1 데이터셋 4 카테고리 스키마

| 카테고리 | 정의 | 핵심 측정 목적 |
|---|---|---|
| C1. 누적 위기 에스컬레이션 (longitudinal escalation) | 개별 턴은 약한 불만, 누적으로 위기(격분·환불/해지·이탈 선언) 도달 | stateful의 존재 이유 — 조기·정확 예측 |
| C2. 오염된 고객 컨텍스트 기록 | 후속 응대 왜곡 목적의 잘못된 고객상태 요약 쓰기 | 쓰기 게이트 격리 정확도 |
| C3. 정상 해결 대화 (오탐 대조군) | 불만 없거나 초기 마찰이 정상 해소되어 위기 미도달, 표면은 유사 | false positive 측정 — 과탐 비용 |
| C4. expert escalation needed | 매니저/이탈방지팀 직접 개입이 정답인 케이스(예: 법적 위협·심각 컴플레인·VIP 이탈) | 에스컬레이션 트리거 정밀도 |

공통 레코드 스키마(D-8): `{session_id, messages[], turn_labels[], session_label, category, expected_action, lang}`. 한국어 케이스 포함(D-9).

### 4.2 측정 지표

- **정책별 precision / recall / F1** — 카탈로그의 각 정책 단위로 공개(D-4).
- **세션 단위 지표(C1·C2)** — 세션 분류 PR/F1 + **조기 탐지 지표**(고객이 위기에 도달하기 전, 몇 번째 턴에 잡았는가 / time-to-detect).
- **오탐율(C3)** — 정상 해결 대화 false positive rate. 과탐 비용을 명시적으로 노출.
- **에스컬레이션 정밀도(C4)** — 매니저로 올린 것 중 실제 매니저 필요 비율 + 놓친 expert 케이스(치명적 FN).

### 4.3 핵심 증명 — stateful vs stateless baseline

같은 데이터·같은 정책을 baseline 4종으로 실행(2.4, 상세는 PLAN A.2.5):
- **B1 — per-turn stateless**(`session_state=None`): 각 메시지 독립 판정(공짜 산출).
- **B1.5 — sliding-window stateless**(window=K): 최근 K턴만 judge에 투입(online·O(K) 저비용). 누적식이 본질적으로 EWMA(손실 압축)이므로 "stateful은 sliding-window의 손실 압축일 뿐" 반론을 막는 **사활 경쟁자**.
- **B2 — full-session-context stateless**(오프라인 상한선): 누적상태 없이 전체 세션을 한 번에 long-context judge에 투입(별도 경로·예산).
- **STATEFUL**: 누적 상태 참조.

**검증 자세(확정):** 아래 가설은 "증명할 목표"가 아니라 **반증 가능한 질문**이다 — 강한 baseline(B1·B1.5) 상대로 stateful의 가치를 공정하게 묻고, 미성립이면 미성립을 엔지니어링 언어로 설명하는 것이 산출물이다(graph_weight=0.0 정신).

**반순환 — 데이터 생성↔평가 모델 분리(확정):** 합성 데이터를 만든 LLM과 평가/detector 모델(Ollama)이 동일 계열이면, STATEFUL이 탐지한 것이 "longitudinal 위기"가 아니라 "그 생성모델 합성 문체의 점진 패턴"일 수 있다(순환). 따라서 데이터 생성 모델군과 평가/detector 모델군을 **가급적 다른 계열로 분리**하고, 분리 불가 시 그 한계를 리포트에 명시한다(상세 ISC는 PLAN ISC-2.8).

가설(한정·single-session): **online·single-session 무한길이·비용제약(매 턴 전체 재판정 불가) 하에서** STATEFUL이 C1(누적 위기 에스컬레이션)·C2(오염된 컨텍스트 기록)에서 **B1 대비 그리고 B1.5(sliding-window) 대비** recall·time-to-detect 우위, C3(정상)에서 오탐 증가는 허용 범위. STATEFUL의 B1.5 대비 잔여 우위는 **무한 룩백·O(1) 상태 메모리·세션 경계 처리**에서 나온다(K턴 안에서는 sliding-window가 동등/우세). **B2(상한선) 대비**는 정직 대조군 — STATEFUL이 B2와 대등/열위여도, 정당성은 정확도가 아니라 **B2의 1/N 비용·고정 윈도우·online 조기탐지**에 있다. cross-session(세션 간) 추적의 정확도 우위는 **측정 ISC가 없으므로 주장하지 않으며**, 추후 측정 가산 항목으로만 분리한다. **이 델타(특히 STATEFUL−B1.5)가 프로젝트의 정량적 주장 전부다.** B1.5를 못 이기면 thesis 미성립을, 우위가 미미하거나 오탐 비용이 과하면 **정직하게 그대로 보고**한다(Mycelium 정직결론 규율 계승 — graph_weight=0.0 사례처럼).

### 4.4 실패 케이스 공개

대표 false positive / false negative를 카테고리별로 골라 원인 분석과 함께 공개. "거친 구현이라도 평가 정직성"을 증명하는 산출물.

---

## 5. 빌드 단계 (Phase 0 ~ 5) — 이진 검증 기준

> 형식: `실행명령 → 기대출력 → pass/fail` (CLAUDE.md ISC 규칙). ISC ID는 재번호 금지.

### Phase 0 — 스캐폴딩 & 클린 레이어 골격
- 산출물: 레이어 디렉토리(`core/pipeline/adapters/interfaces`), 각 `.ai.md`, `LLMAdapter`·`Policy` 인터페이스 스텁, Ollama 어댑터 1개, CLI 진입점.
- **ISC-0.1:** `sgr --version` → 버전 문자열 출력 → pass/fail
- **ISC-0.2:** `pytest tests/test_layering.py` (core가 adapters/langgraph import 안 함 검증) → 통과 → pass/fail
- **ISC-0.3:** `sgr ping-llm --provider ollama` → 모델 응답 1줄 → pass/fail

### Phase 1 — Stateless 정책 카탈로그 + baseline 엔진
- 산출물: 단발 정책 N개(카테고리 태깅), `session_state=None` 판정 경로, 정책별 신호 출력.
- **ISC-1.1:** `sgr scan --input samples/single.jsonl` → 정책별 score JSON → pass/fail
- **ISC-1.2:** `pytest tests/test_policies.py` → 전 정책 계약 테스트 통과 → pass/fail
- **ISC-1.3:** 카탈로그 덤프 `sgr catalog` → 각 정책에 `(category, stateless|stateful)` 태그 표시 → pass/fail

### Phase 2 — Stateful 판정 엔진 + 세션 상태 영속화
- 산출물: `SessionState`, 누적·감쇠 로직, KV 영속 어댑터(SQLite/JSON), 누적 위기 detector(교체형 최소 1종).
- **ISC-2.1:** `sgr scan-session --input samples/longitudinal.jsonl` → 세션 단위 누적 점수·탐지 턴 출력 → pass/fail
- **ISC-2.2:** 프로세스 재시작 후 상태 복원 테스트 `pytest tests/test_state_persistence.py` → 통과 → pass/fail
- **ISC-2.3:** 동일 입력을 stateless/stateful 두 모드로 실행 시 결과가 다름을 보이는 회귀 테스트 → 통과 → pass/fail

### Phase 3 — 메모리 게이트 + LangGraph 통합 데모
- 산출물: 쓰기 격리 게이트, 읽기 배제 게이트, LangGraph 그래프에 게이트 노드 삽입한 데모 에이전트.
- **ISC-3.1:** `sgr demo-agent --scenario context-corruption` → 왜곡 쓰기가 quarantine으로 분류, 본 메모리 미오염 로그 → pass/fail
- **ISC-3.2:** `pytest tests/test_memory_gate.py` → 격리/통과 분기 통과 → pass/fail

### Phase 4 — 에스컬레이션 3단계 + 감사 로그 (핵심 활용 스토리)

> 도메인 특성상 이 단계는 **부차가 아니라 핵심 활용 스토리**다 — "봇이 위기를 조기에 감지해 적시에 사람에게 넘긴다"가 고객지원 도메인의 데모 가치이기 때문이다. 따라서 thesis 입증 후 **가산이되 데모 가치 높음**으로 격상한다. 단, 최소 완주선은 여전히 C1/C3 + B1/B1.5/STATEFUL + holdout + 한국어 골드시드이며, Phase 4는 그 이후 우선 가산 항목이다.

- 산출물: 위험도 임계 게이트(0/1/2 = 봇 자동응대/상담사 이관/매니저 이관), 매니저 큐(파일/DB), 감사 로그 레코드.
- **ISC-4.1:** `sgr scan-session --input samples/escalation.jsonl` → 각 세션에 0/1/2 라벨 + 사유 → pass/fail
- **ISC-4.2:** 감사 로그 조회 `sgr audit --session <id>` → 판정·조치·증거 추적 레코드 출력 → pass/fail
- **ISC-4.3:** C4 케이스가 모두 매니저(2)로 분류되는지 `pytest tests/test_escalation.py` → 통과 → pass/fail

### Phase 5 — 평가 하니스 + 리포트 (심장)
- 산출물: 4 카테고리 합성 데이터셋(한국어 포함), 평가 러너, 정책별 PR/F1 리포트, stateful vs stateless 비교표, 실패 케이스 문서.
- **ISC-5.1:** `sgr eval --dataset data/ --report out/report.md` → 정책별 PR/F1 + 세션 지표 표 생성 → pass/fail
- **ISC-5.2:** 리포트에 stateful vs stateless 델타 표 포함 → 존재 → pass/fail
- **ISC-5.3:** `sgr eval --show-failures` → 대표 FP/FN 케이스 N건 출력 → pass/fail
- **ISC-5.4:** 데이터셋에 한국어 세션 ≥1건 카테고리별 존재 검증 → pass/fail

---

## 6. Open Questions (개발자 본인 결정 필요)

> 임의 결정하지 않고 trade-off와 함께 남긴다. `.omc/plans/open-questions.md`에도 동기화 권장.

- **Q1. 데모 도메인:** 고객 이탈/격분 위기 시나리오로 입힐지 vs 중립 도메인 유지.
  - *trade-off:* 이탈/격분 위기 = 채용 타깃 적합·서사 강력하나 시나리오 톤 주의(실서비스 아님 명시 필요). 중립 = 안전·범용성 강조하나 타깃 어필 약화.
- **Q2. 누적 위기 detector 기본값:** 임베딩 유사도 기반 vs LLM 분류 기반 (vs 규칙).
  - *trade-off:* 임베딩 = 빠르고 비용 0(로컬), 의미 드리프트 강하나 표현 위장에 약함 / LLM = 정밀·맥락 강하나 비용·지연·비결정성 / 규칙 = 투명하나 회피 쉬움. 평가로 결정 권장.
- **Q3. 데이터셋 규모·생성 방식:** 수작업 큐레이션 vs LLM 합성+사람 검수, 카테고리당 샘플 수, 분할 비율.
  - *trade-off:* 수작업 = 품질·현실성 높으나 느림 / LLM 합성 = 빠르나 비현실·편향 위험(검수 필수). 규모 작으면 지표 신뢰 하락.
- **Q4. 임계값·시간 파라미터:** 감쇠 함수(선형 vs 지수), 세션 종료 정의, 에스컬레이션 임계 t1·t2, 격리 만료 정책.
  - *trade-off:* 공격적 임계 = recall↑·오탐↑(C3 비용) / 보수적 = 오탐↓·놓침↑(치명적 FN). 데이터로 튜닝하되 게시 값은 고정해 재현성 확보.
- **Q5. 카테고리·한국어 깊이:** MLCommons 14 그대로 vs 한국 CX 맥락 위기 확장, manager-only 카테고리 목록, 한국어 형태소/정규화 처리 깊이.
  - *trade-off:* 표준 준수 = 비교 용이·신뢰 / 확장 = 차별성·국내 적합성↑하나 평가 복잡·표준 이탈.
- **Q6. 평가 공식 수치 고정 모델:** 로컬 Ollama(무료·재현) vs 클라우드(성능).
  - *trade-off:* 로컬 = 누구나 재현·비용 0하나 성능 한계로 수치 보수적 / 클라우드 = 수치 좋으나 비용·키 필요로 재현 장벽.
- **Q7. 프로젝트 이름:** 현재 폴더명 `stateful-safety`는 작업용 가칭. 공개 리포 명칭 미정.
  - *trade-off:* 기능 직설형(검색·이해 쉬움) vs Mycelium 같은 브랜드형(기억·정체성). 첫 프로젝트 톤과 일관성 고려.
- **Q8. 자동 개선 루프 포함 여부(NG-7 관련):** 평가→정책 자동 튜닝 루프를 범위에 넣을지.
  - *trade-off:* 포함 = 인상적이나 1인 수 주 범위 초과 위험·평가 오염 가능 / 제외 = 범위 안전·평가 정직성 보존(권장 기본값).

---

## 7. 계승 규율 체크리스트 (Mycelium → 본 프로젝트)

- [x] `D-결정` 형식(Why/Alt/Threat/Mitigation/Open)
- [x] 정직한 측정 — 우위 미미 시 그대로 보고(graph_weight=0.0 정신)
- [x] 클린 아키텍처(interfaces→pipeline→adapters→core), `.ai.md` 레이어 가드
- [x] provider-agnostic LLM 어댑터(OpenAI/Anthropic/Ollama)
- [x] 합성 데이터만 공개, 실데이터·민감정보 배제(D-7)
- [x] CLI 주 인터페이스 + 선택적 서버
- [x] 이진 검증(ISC) 기반 Phase 게이트
