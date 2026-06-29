# stateful-guardrails

![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![LLM: local (Ollama)](https://img.shields.io/badge/LLM-local%20(Ollama)-success)
![Tests: 89 passed](https://img.shields.io/badge/tests-89%20passed-brightgreen)

[한국어](README.md) · **English**

> In conversational AI, individual messages may be weak complaints — but they accumulate into crises (churn, escalation).
> We built a **stateful crisis early-warning component** — cumulative risk score engine (`S_t = λ·S_{t-1} + signal_t`),
> three-stage escalation routing, and O(N) economics — then measured its effectiveness honestly against strong baselines.

This project has two deliverables. A **working safety component** — cumulative risk score engine, three-stage escalation, and audit trail running immediately with `sgr escalate`. And a **falsifiable measurement** of its effectiveness: does stateful genuinely outperform sliding-window? We asked against strong baselines using McNemar, bootstrap CI, and λ-sweep, and reported partial establishment + FPR cost as-is.

---

## Background / Motivation

**The structural blind spot of cumulative threats.** As AI agents enter production, *gradual manipulation* — individual messages that appear harmless but cumulatively push the AI past safe boundaries — has emerged as a real threat. The Meta customer-support chatbot incident (June 2026) is one example. The key insight is not whether an incident is single-turn or multi-turn, but that **"individually harmless → cumulatively dangerous" is structurally outside the reach of per-turn guardrails.**

What we attempted is not *blocking* such threats, but **detection and early warning**: does stateful tracking (accumulating full conversation history) catch anomalies earlier than stateless methods (per-turn or sliding-window)? We measured this falsifiably and report the answer honestly.

**Domain pivot — a deliberate judgment call.** Generating jailbreak or manipulation data directly conflicts with safety policy. Instead, we chose **customer-support crisis escalation as a safe proxy domain**: individual complaint messages are harmless per turn, but accumulated they signal a crisis — structurally isomorphic to cumulative manipulation. The measurement scaffold (signal design, baseline comparison, McNemar, operating-point alignment, CI) is domain-agnostic, making theoretical transfer to manipulation detection feasible.

---

## After Detection — Operational Value

> The escalation demo and cost comparison show what the component *enables* in practice.
> Measurement results (below) verify the effect numerically.
> The demo uses a synthetic session; costs are model estimates (no exaggeration).

### 1. Three-stage escalation — detection into action

The cumulative crisis score `S_t` maps to frozen thresholds `t1=0.7`/`t2=0.9` (no re-tuning):
`S_t<t1` = bot auto-reply / `t1≤S_t<t2` = agent handoff / `S_t≥t2` = manager (retention team) handoff.

```
$ sgr escalate --session c1-test-004

  turn  risk    S_t  STATEFUL stage     B1 (single-turn) stage
    0   0.00   0.00  bot                bot
    1   0.42   0.42  bot                bot          ← "still bounces no matter how many times I log in"
    2   0.55   0.84  AGENT handoff      bot          ← "third day contacting you, still nothing. Frustrating."
    3   0.90   1.00  MANAGER handoff    MANAGER handoff  ← "I'll cancel my account."

[Handoff recommendation]
  STATEFUL (cumulative): agent handoff = turn 2 / manager handoff = turn 3
  B1 (stateless single-turn): agent handoff = turn 3 / manager handoff = turn 3
  → Proactive: STATEFUL hands off to an agent 1 turn earlier than B1
    (accumulated weak complaints trigger human intervention *before* the explicit crisis declaration)
```

Stateless single-turn (B1) treats each turn independently and cannot decide *when* to hand off
cumulatively. Turn 2 "Frustrating" (risk 0.55<t1) stays a bot reply on a per-turn basis, but the
cumulative `S_t=0.84` crosses the agent-handoff threshold — handing off **one turn before the
customer declares "cancel."** Early detection is the action enabler. Every decision is auditable
(`sgr audit --session <id>`, ISC-4.2).

> Honesty discipline: not every C1 session shows this lead. When weak complaints arrive sparsely,
> the λ=0.7 decay disperses the accumulation and handoff timing matches the single-turn baseline in
> some sessions (reported as-is).

### 2. Economics — judge re-submission cost (model estimate)

STATEFUL references only O(1) fixed state (one scalar `S_{t-1}`) per turn. B1.5 re-feeds the last
K=5 turns, B2 re-feeds the full session to the judge every turn. Cumulative judge input tokens over
an N-turn session:

| N (turns) | STATEFUL O(N) | B1.5 O(N·K) | B2 O(N²) | B1.5/ST | B2/ST |
|---|---|---|---|---|---|
| 10 | 210 | 760 | 1,045 | ×3.6 | ×5.0 |
| 20 | 420 | 1,710 | 3,990 | ×4.1 | ×9.5 |
| 50 | 1,050 | 4,560 | 24,225 | ×4.3 | ×23.1 |
| 100 | 2,100 | 9,310 | 95,950 | ×4.4 | ×45.7 |

The B2/STATEFUL ratio grows monotonically with N (O(N²) vs O(N)) — for long sessions and online
operation, full re-submission (B2) is cost-prohibitive, and B1.5 still costs K×. This backs the
measurement conclusion's justification axis: "B2-level accuracy at 1/N of B2's cost."

> ⚠ caveat: **model estimate, not measured.** Per-turn tokens (≈19, from the bundled data avg ≈28
> Korean chars) and judge pricing are stated assumptions. Local Ollama's monetary cost is 0; the
> table shows *relative scale* if converted to a cloud judge. Reproduce: `sgr cost-model` →
> [`out/cost.md`](out/cost.md).

---

## One-line Conclusion (Honest)

**In one detector (target_aware), STATEFUL robustly beats stateless across operating-point alignment, confidence intervals, and the full λ range (McNemar p=0.000). However, the non-circular control (target_agnostic) does not establish, so self-fulfillment cannot be fully ruled out — and the recall advantage comes at a cost of 18% false-positive rate on long normal sessions.**

---

## Robustness Evidence

Three layers close the "you bought it with FPR" / "small-sample noise" objections:

1. **Operating-point alignment**: At equal test-FPR budgets, STATEFUL consistently beats B1.5 (≤5%: +19.4%p / ≤10%: +22.6%p / ≤20%: +38.7%p).
2. **Bootstrap CI**: 95% CI [+40.3%p, +66.1%p] vs B1.5 — lower bound excludes 0, sign is certain.
3. **λ-sweep all-positive**: Across λ=0.5, 0.7, 0.9, 1.0, the delta vs B1.5 stays positive (+32%p to +53%p), no sign reversal.

The non-circular control (target_agnostic, p=0.250, CI [-11.3%p, +0.0%p], non-positive across the λ range) reads as "the control worked, filtering out one side" — agnostic non-establishment partially supports that the target_aware signal is not arbitrary.

---

## Results

Source: [`out/mini.md`](out/mini.md) — C1 (cumulative crisis) positive test pool: 62 sessions (c1.test 47 + c1.calib 15 merged), C3 (normal resolution) test: 40 sessions (22 long-positive), K=5

### detector = `target_aware` — **Established (strengthened)**

| Comparison | Δrecall (all) | Δrecall (K+) | ΔTTD (all) | McNemar p |
|---|---|---|---|---|
| STATEFUL − B1 (per-turn) | +19.4%p | +29.6%p | −0.02 | 0.004 |
| STATEFUL − B1.5 (sliding-window) | **+53.2%p** | **+63.0%p** | **+0.30** | **0.000 ✓** |

> TTD = time-to-detect (success_turn − detect_turn), positive = STATEFUL detects earlier.
> Bootstrap 95% CI (vs B1.5): **[+40.3%p, +66.1%p]** — lower bound > 0, excludes 0.

False-positive cost (long-positive FPR): STATEFUL **18%** (4/22) vs B1.5 9% (2/22) ⚠ — the recall advantage is not free.

### detector = `target_agnostic` — **Not established**

| Comparison | Δrecall (all) | McNemar p |
|---|---|---|
| STATEFUL − B1 (per-turn) | +0.0%p | 1.000 |
| STATEFUL − B1.5 (sliding-window) | **−4.8%p** | **0.250** |

> 95% CI (vs B1.5): [-11.3%p, +0.0%p] — includes 0, not significant.
> ⚠ Small-sample caveat: McNemar relies only on discordant pairs; with few pairs, power is low (significant = strong evidence; non-significant ≠ disproof).

---

## Honest Interpretation

| Item | Detail |
|---|---|
| Established detector | `target_aware` only (vs B1.5: p=0.000, CI lower bound > 0, all-positive λ-sweep, operating-point aligned) |
| Not established | `target_agnostic` (no stateful advantage when the target concept is not referenced — control working as intended) |
| What establishment means | Sliding-window drops complaint signals outside the K-turn window; stateful infinite lookback catches them |
| Cost | target_aware long-positive FPR 18% — "long session → crisis" and "escalation → crisis" not fully separable |
| Self-fulfillment | agnostic non-establishment is not a full reversal control — circularity cannot be entirely ruled out (reported honestly) |
| Why agnostic fails | Semantic drift from the previous N turns is similar in both crisis and normal sessions — low discriminative power as a crisis signal |
| Confound discovered | In an earlier measurement, C3 (normal) sessions were systematically shorter than C1 (crisis), inflating stateful scores with session length → controlled by expanding long-positive controls to 22 sessions |

**Honestly reporting "partial establishment + FPR cost + agnostic non-establishment" is this project's conclusion.** Inheriting Mycelium's `graph_weight=0.0` principle — numbers are reported as-is, regardless of whether the result is favorable.

---

## Measurement Discipline (The Core Asset)

How we measured matters more than the numbers themselves. This is what positions the project not as "another honest negative report" but as **falsifiable experimental design capability**.

1. **Strong baselines** — B1 (per-turn stateless), B1.5 (sliding-window K=5), STATEFUL compared at equal FPR budget (5%). Directly answers "it's just sliding-window with information loss."
2. **Length confound detection and control** — C3 median 6 turns vs C1 median 5 turns. Expanded long-positive controls to 22 sessions (K-exceeding normal sessions) to boost length-control power.
3. **Holdout protocol** — λ=0.7, K=5, and thresholds (t1, t2) frozen from calibration-split only. No re-tuning during test-split evaluation.
4. **Self-fulfillment defense** — `target_aware` (cumulative cosine movement toward target concept) vs `target_agnostic` (semantic drift from previous N turns) run in parallel. One-sided establishment = data design has not leaked into detection axis (partially confirmed).
5. **Generation/evaluation model separation** — Data generation: claude-opus (Anthropic); evaluation/embedding: bge-m3 + qwen2.5:14b (Alibaba). Different families reduce generative-style circularity risk.
6. **McNemar test** — Establishment declared only at p<0.05 on the primary column. No establishment from point-estimate sign alone.
7. **Stratified K-within/K-over reporting** — Sessions with ≤K turns (35 sessions) and >K turns (27 sessions) reported separately. B1.5≈STATEFUL within-K (structurally equal) disclosed openly.
8. **Operating-point alignment** — Recall re-computed at equal test-FPR budgets. Directly closes "unequal operating points make the comparison unfair."
9. **Bootstrap CI** — 2,000 paired resamples, fixed seed (reproducible). Uncertainty exposed honestly alongside point estimates.
10. **λ-sweep** — Delta curve computed for λ∈{0.5, 0.7, 0.9, 1.0}. Sign reversals would be published as-is (honesty evidence). Result: [`out/lambda.md`](out/lambda.md)

---

## Architecture

Dependency direction: `interfaces → pipeline → adapters → core` (Clean Architecture, inherited from Mycelium)

```
interfaces/   CLI (typer, sgr commands) — I/O entry point
pipeline/     Judgment pipeline orchestration
              (message ingress → policy execution → escalation decision → audit log)
adapters/     External boundary: LLM/embedding provider (Ollama), state persistence (JSON), audit log
core/         Pure domain: Policy interface, SessionState, cumulative judgment algorithm
              (no external I/O or framework dependencies — numeric operations use stdlib math only)
```

**Accumulation formula:** `S_t = clip(λ·S_{t-1} + signal_t, 0, S_max)` (λ=0.7, exponential decay)

Baselines are not separate code paths — they are **modes of the same engine**:
`session_state=None` → B1 (per-turn), last-K sliding → B1.5, full accumulated state → STATEFUL.
Delta is measured between three paths on identical data under identical policy.

Design decisions (D-1~D-10): [`docs/DESIGN.md`](docs/DESIGN.md)
Execution plan + verification ISC: [`docs/PLAN.md`](docs/PLAN.md)

---

## Quick Start

### 1. Install

```bash
git clone <repo-url> stateful-guardrails
cd stateful-guardrails
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

### 2. Ollama + models

```bash
# Install from https://ollama.com, then:
ollama serve
ollama pull bge-m3        # embeddings (1.2 GB)
ollama pull qwen2.5:14b   # judge LLM (9 GB) — needed for eval only
```

### 3. Core commands

```bash
sgr --version                                          # version check (ISC-0.1)
sgr catalog                                            # policy catalog (category, stateless|stateful)
sgr scan --input data/c1.test.jsonl                    # single-pass scan (stateless mode)
sgr eval --mini --dataset data/ --report out/mini.md  # mini eval — thesis critical gate
```

### 4. Reproduce measurements

```bash
# Using bundled synthetic data (data/) + frozen parameters (data/calibration.json)
sgr eval --mini --dataset data/ --report out/mini.md
# Compare output against the bundled out/mini.md to confirm reproduction

# λ-sweep (ISC-5.6)
sgr eval --mini --lambda-sweep 0.5,0.7,0.9,1.0 --report out/lambda.md --dataset data/
```

---

## Data

`data/` contains only synthetic conversation sessions (no sensitive information):

| File | Contents |
|---|---|
| `c1.{calib,test}.jsonl` | Cumulative crisis escalation sessions (synthetic, includes Korean) |
| `c3.{calib,test}.jsonl` | Normal-resolution conversations + long-positive control sessions (synthetic) |
| `calibration.json` | Frozen parameters (λ, K, N, S_max, thresholds, FPR budget) |

No real customer data is included. Synthetic data plays the same role as Mycelium's `sample_vault/` — bundled so anyone can reproduce the evaluation immediately after cloning.

---

## Stack

Python 3.12 · typer · httpx · Ollama (`bge-m3` embeddings + `qwen2.5:14b` judge)
Numeric operations use only stdlib `math` — no external numeric dependencies in the core layer.

---

## License

MIT
