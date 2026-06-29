# stateful-guardrails

![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![LLM: local (Ollama)](https://img.shields.io/badge/LLM-local%20(Ollama)-success)
![Tests: 89 passed](https://img.shields.io/badge/tests-89%20passed-brightgreen)

[한국어](README.md) · English

In conversational AI, any single message is a minor complaint, but once those complaints stack up across turns they turn into a crisis — churn, or an enraged customer. This repository holds two things: a crisis early-warning component that tracks that accumulation, and a measurement of whether the component actually works. The component is a cumulative risk score engine (`S_t = λ·S_{t-1} + signal_t`), three-stage escalation routing, and an O(N) structure whose per-turn cost stays flat no matter how long a session runs; you can run it immediately with `sgr escalate`. The measurement asks whether that component catches a crisis earlier than a sliding-window approach, testing it against strong baselines with a McNemar test, bootstrap confidence intervals, and a λ-sweep. The short version: in one detector the advantage clearly holds, in the other it does not, and the advantage carries a false-positive cost. The rest is written out below, as-is.

## Background / Motivation

As AI agents move into production, the gradual manipulation that per-turn guardrails wave through has become a real threat: individual messages look harmless, but accumulated over many turns they push the AI past its boundaries or steer it somewhere dangerous. The Meta customer-support chatbot incident of June 2026 is one such case. What matters is not whether the incident was single-turn or multi-turn, but that the structure itself — "individually harmless, cumulatively a crisis" — sits in the blind spot of any guardrail that looks at each turn in isolation.

What we attempted is not to block this cumulative threat but to notice it early. The goal was to measure, in a falsifiable way, whether a stateful approach that accumulates the entire conversation history catches anomalies sooner than stateless approaches that see only the current turn or the last few.

Generating jailbreak or manipulation data directly conflicts with safety policy. So we chose a structurally equivalent but safe proxy domain: customer-support crisis escalation. An individual complaint is harmless on its own but signals a crisis once it accumulates — isomorphic to cumulative manipulation — and the measurement scaffold (signal design, baseline comparison, McNemar, operating-point alignment, confidence intervals) is domain-agnostic, leaving the theoretical transfer to manipulation detection open. It was a deliberate call to recognize the safety-policy conflict in advance and route around it.

## What Detection Enables — Operational Value

Detection is worth something only when it leads to an action, not as an end in itself. The demo and cost comparison below show what the component enables, and the measurement section that follows verifies that effect numerically. Note up front that the demo uses a synthetic session and the costs are model estimates.

### Three-stage escalation

The cumulative crisis score `S_t` maps to frozen thresholds `t1=0.7` and `t2=0.9`, with no re-tuning. When `S_t` is below `t1` the bot replies automatically; between `t1` and `t2` the conversation goes to a human agent; at or above `t2` it goes to a manager on the retention team.

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

Stateless single-turn (B1) treats each turn independently and so cannot decide *when* to hand off on a cumulative basis. Turn 2's "Frustrating" carries a single-turn risk of 0.55, below `t1`, so it stays a bot reply — but the cumulative `S_t=0.84` crosses the agent-handoff threshold, and the conversation reaches a human one turn before the customer says "cancel." Early detection is precisely the action it enables. Every decision is auditable via `sgr audit --session <id>` (ISC-4.2).

Not every C1 session shows this lead, though. When weak complaints arrive sparsely, one turn at a time, the λ=0.7 decay disperses the accumulation, and in some sessions the handoff timing matches the single-turn baseline. Those cases are reported as-is too.

### Economics

STATEFUL references only one scalar (`S_{t-1}`) per turn, so its per-turn cost is fixed. B1.5 re-feeds the last K=5 turns and B2 re-feeds the entire session to the judge every turn. Comparing the cumulative judge input tokens over an N-turn session makes the difference plain.

| N (turns) | STATEFUL O(N) | B1.5 O(N·K) | B2 O(N²) | B1.5/ST | B2/ST |
|---|---|---|---|---|---|
| 10 | 210 | 760 | 1,045 | ×3.6 | ×5.0 |
| 20 | 420 | 1,710 | 3,990 | ×4.1 | ×9.5 |
| 50 | 1,050 | 4,560 | 24,225 | ×4.3 | ×23.1 |
| 100 | 2,100 | 9,310 | 95,950 | ×4.4 | ×45.7 |

The ratio against B2 grows monotonically with N (O(N²) vs O(N)), which means that for long sessions and online operation full re-submission (B2) is effectively cost-prohibitive and B1.5 still costs K times as much. This number backs the justification the measurement conclusion leans on: "B2-level accuracy at 1/N of B2's cost." The table is a model estimate, not a measurement: per-turn tokens are taken as roughly 19 (the bundled data's Korean user messages average about 28 characters), and judge pricing is an assumption. Local Ollama's actual monetary cost is 0; the table only shows the relative scale you would see if you moved to a cloud judge. Reproduce it with `sgr cost-model`; details are in [`out/cost.md`](out/cost.md).

## Measurement Results

Now the effect itself. The source is [`out/mini.md`](out/mini.md), comparing the C1 (cumulative crisis) positive test pool of 62 sessions (c1.test 47 + c1.calib 15 merged) against the C3 (normal resolution) test set of 40 sessions (22 long-positive), at K=5.

To lead with the core finding: in the `target_aware` detector, STATEFUL clearly beat sliding-window (B1.5).

| Comparison | Δrecall (all) | Δrecall (K+) | ΔTTD (all) | McNemar p |
|---|---|---|---|---|
| STATEFUL − B1 (per-turn) | +19.4%p | +29.6%p | −0.02 | 0.004 |
| STATEFUL − B1.5 (sliding-window) | +53.2%p | +63.0%p | +0.30 | 0.000 |

TTD here is success_turn minus detect_turn, so a positive value means STATEFUL detected on an earlier turn. The bootstrap 95% confidence interval for Δrecall against B1.5 is [+40.3%p, +66.1%p], whose lower bound clears 0, so the sign is certain.

We also checked separately that this advantage is not an artifact of mismatched operating points. Re-measuring recall after aligning thresholds to the same test-FPR budget, STATEFUL still leads B1.5 consistently — by +19.4%p at ≤5%, +22.6%p at ≤10%, and +38.7%p at ≤20%. Sweeping λ across 0.5, 0.7, 0.9, and 1.0, the delta against B1.5 stays between +32%p and +53%p without ever flipping sign. That closes the "you bought the advantage with FPR" and "small-sample noise" objections across three layers: operating-point alignment, the confidence interval, and the full λ range.

The recall advantage is not free, though. On the length-controlled long-positive sessions, STATEFUL's false-positive rate is 18% (4/22), higher than B1.5's 9% (2/22) — the price of not fully separating "a crisis because the session is long" from "a crisis because it escalates."

In the other detector, `target_agnostic`, the advantage did not hold. STATEFUL came in at +0.0%p versus B1 (p=1.000) and −4.8%p versus B1.5 (p=0.250), with a confidence interval of [−11.3%p, +0.0%p] that includes 0. Bear in mind that McNemar depends only on discordant pairs, so power is low when the sample is small. Significance is strong evidence, but non-significance is not disproof.

This asymmetry actually reads as the design working as intended. `target_agnostic` looks only at the semantic drift relative to the previous N turns, and that quantity rises similarly in crisis and normal sessions alike, giving it weak discriminative power as a crisis signal. That only the cumulative movement toward the target concept (`target_aware`) held, while target-agnostic drift did not, partially supports that the data design did not leak into the detection axis. It is not a full reversal control, however, so circularity cannot be entirely ruled out.

## One-line Conclusion

In one detector (`target_aware`), STATEFUL robustly beat stateless across operating-point alignment, the confidence interval, and the full λ range (McNemar p=0.000). But the non-circular control, `target_agnostic`, did not hold, so self-fulfillment cannot be entirely ruled out, and the recall advantage comes with an 18% false-positive cost on long normal sessions. This inherits Mycelium's `graph_weight=0.0` spirit: the numbers go down as they are, regardless of whether they flatter the project.

## Measurement Discipline

How we measured matters more than the numbers themselves, which is why we treated the measurement scaffold as falsifiable experimental design rather than just another honest negative report.

The comparison sits on fair, strong baselines. Per-turn stateless (B1), sliding-window K=5 (B1.5), and STATEFUL were aligned to the same FPR budget of 5%, directly answering "isn't this just sliding-window with lossy compression?" Parameters were fixed on the calibration split alone: λ=0.7, K=5, and the thresholds `t1` and `t2` were all frozen before the test split was ever seen, with no re-tuning during measurement.

Length confound was detected and controlled separately. C3 normal sessions had a median of 6 turns against C1 crisis sessions' 5, and because the accumulation formula grows with length, scores could inflate. So the "long-but-normal" long-positive control was expanded to 22 sessions to strengthen control power, and results were reported separately for the 35 within-K and 27 over-K sessions. Even the fact that B1.5 and STATEFUL are structurally near-identical within K is disclosed openly.

To guard against self-fulfillment, two detectors were run in parallel: cumulative cosine movement toward the target concept (`target_aware`) and semantic drift from the previous N turns (`target_agnostic`). If only one holds, that is grounds to say the data design did not bleed into the detection axis. Generation and evaluation models were also separated — data was generated with claude-opus (Anthropic) while evaluation and embedding used bge-m3 and qwen2.5:14b (Alibaba) — reducing the risk of generative style circling back into evaluation.

Establishment was decided by a test, not by the sign of a point estimate. We declare establishment only when the McNemar exact p on the decisive column (vs B1.5) is below 0.05, and we exposed the uncertainty alongside it with recall re-computed at matched operating points and a 2,000-iteration bootstrap confidence interval on a fixed seed. The λ delta curve was computed across the full 0.5, 0.7, 0.9, 1.0 range, and any sign reversal would have been published as-is. That result is in [`out/lambda.md`](out/lambda.md).

## Architecture

The dependency direction is `interfaces → pipeline → adapters → core`, the Clean Architecture inherited from Mycelium.

```
interfaces/   CLI (typer, sgr commands) — I/O entry point
pipeline/     Judgment pipeline orchestration
              (message ingress → policy execution → escalation decision → audit log)
adapters/     External boundary: LLM/embedding provider (Ollama), state persistence (JSON), audit log
core/         Pure domain: Policy interface, SessionState, cumulative judgment algorithm
              (no external I/O or framework dependencies — numeric operations use stdlib math only)
```

The accumulation formula is `S_t = clip(λ·S_{t-1} + signal_t, 0, S_max)`, an exponential decay with λ=0.7. The point worth noting is that the baselines are not separate code but modes of the same engine: `session_state=None` gives B1 (per-turn), last-K sliding gives B1.5, and referencing the accumulated state gives STATEFUL. The delta between the three paths is measured on identical data under an identical policy. The design decisions (D-1 through D-10) are in [`docs/DESIGN.md`](docs/DESIGN.md), and the execution plan plus verification ISC are in [`docs/PLAN.md`](docs/PLAN.md).

## Quick Start

First clone the repository, create a virtual environment, and install the dev dependencies.

```bash
git clone <repo-url> stateful-guardrails
cd stateful-guardrails
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Evaluation needs Ollama and two models. The judge LLM (`qwen2.5:14b`) is only used during eval.

```bash
# Install from https://ollama.com, then:
ollama serve
ollama pull bge-m3        # embeddings (1.2 GB)
ollama pull qwen2.5:14b   # judge LLM (9 GB) — needed for eval only
```

The core commands are below; `sgr eval --mini` is the thesis's critical gate.

```bash
sgr --version                                          # version check (ISC-0.1)
sgr catalog                                            # policy catalog (category, stateless|stateful)
sgr scan --input data/c1.test.jsonl                    # single-pass scan (stateless mode)
sgr eval --mini --dataset data/ --report out/mini.md  # mini eval — thesis critical gate
```

To reproduce the measurements, run the evaluation on the bundled synthetic data with the frozen parameters, then compare the output against the bundled `out/mini.md`. The λ-sweep reproduces the same way (ISC-5.6).

```bash
sgr eval --mini --dataset data/ --report out/mini.md
sgr eval --mini --lambda-sweep 0.5,0.7,0.9,1.0 --report out/lambda.md --dataset data/
```

## Data

`data/` contains only synthetic conversation sessions, with no sensitive information. `c1.{calib,test}.jsonl` holds cumulative crisis escalation sessions (synthetic, including Korean), `c3.{calib,test}.jsonl` holds normal-resolution conversations and long-positive control sessions, and `calibration.json` carries the frozen parameters (λ, K, N, S_max, thresholds, FPR budget). No real customer data is included. The synthetic data plays the same role as Mycelium's `sample_vault/` — bundled so anyone can reproduce the evaluation immediately after cloning.

## Stack

Python 3.12 · typer · httpx · Ollama (`bge-m3` embeddings + `qwen2.5:14b` judge). Numeric operations use only stdlib `math`, with no external numeric dependencies, keeping the core layer's dependencies minimal.

## License

MIT
