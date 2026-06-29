# stateful-guardrails

![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![LLM: local (Ollama)](https://img.shields.io/badge/LLM-local%20(Ollama)-success)
![Tests: 89 passed](https://img.shields.io/badge/tests-89%20passed-brightgreen)

[한국어](README.md) · English

Any single complaint a customer sends a chatbot looks minor ("not working again"). But once they stack up, they tip into a crisis — the customer leaves or gets seriously angry. An ordinary safety check that reads each message in isolation (stateless) can't see that *build-up* by design.

If an ordinary safety check is a *checkpoint that sees every passerby for the first time*, this is a *security guard who remembers a regular's behavior* (stateful) — it accumulates the conversation's context and, once even mild complaints pile up, flags a crisis and routes bot → human agent → manager (one command: `sgr escalate`).

This repo holds that **component** plus an **honest measurement** of whether it actually beats the single-shot approach. The results are reported as-is: in one detector the advantage clearly held, in another it did not, and catching crises better came at the cost of more false alarms on fine conversations.

## Background / Motivation

As AI agents move into production, a new threat surfaced — each message looks harmless, but nudging a little at a time across many turns can push the AI over a line it shouldn't cross (**gradual manipulation**; the June 2026 Meta customer-support chatbot incident is one case). The structure itself — "harmless one by one, a crisis once accumulated" — is the blind spot of any safety check that reads each message in isolation.

The goal is not to *block* this cumulative threat but to *notice it early*. Generating manipulation or jailbreak data directly conflicts with safety policy, so we picked a structurally identical but safe substitute: customer-support crisis escalation. The measurement methods (signal design, baselines, statistical tests) don't depend on the topic, leaving room to carry the work over to manipulation detection later.

## From Detection to Response — Operational Value

Detecting a crisis is not the point in itself; it earns its keep only when it leads to an actual *response*. The demo and cost comparison below show where this component can be used, and the measurement section that follows verifies the effect numerically. Note up front that the demo is a synthetic (made-up) conversation and the costs are estimates.

### Three-stage escalation

The cumulative crisis score `S_t` is read against two pre-frozen thresholds, `t1=0.7` and `t2=0.9`, to choose the handling path automatically (no re-tuning). When `S_t` is below `t1` the bot replies automatically; between `t1` and `t2` it goes to a human agent; at or above `t2` it goes to a manager on the retention team.

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

The single-shot approach (B1) looks at each turn on its own, so it cannot decide *when* to hand off on a cumulative basis. Turn 2's "Frustrating," read in isolation, carries a crisis score of 0.55 — below `t1` — so it stays a bot reply; but the accumulated score so far, `S_t=0.84`, crosses the agent-handoff threshold. As a result, the conversation reaches a human one turn before the customer ever says "cancel." This is exactly where an early signal turns straight into a response. Every decision can be traced afterward via `sgr audit --session <id>` (ISC-4.2).

That said, not every crisis conversation shows this lead. When weak complaints arrive sparsely, one turn at a time, the score cools off gradually at λ=0.7, the accumulation disperses, and in some conversations the handoff timing matches the single-shot baseline. Those cases are reported as-is too.

### Economics (cost)

The cumulative approach (STATEFUL) only has to carry one number per turn (`S_{t-1}`), so its per-turn cost does not grow as the conversation lengthens. B1.5 re-feeds the last 5 turns (K=5) and B2 re-feeds the entire conversation to the judge every turn. Comparing the cumulative tokens (the processing load) that go into the judge over an N-turn conversation makes the difference plain.

| N (turns) | STATEFUL O(N) | B1.5 O(N·K) | B2 O(N²) | B1.5/ST | B2/ST |
|---|---|---|---|---|---|
| 10 | 210 | 760 | 1,045 | ×3.6 | ×5.0 |
| 20 | 420 | 1,710 | 3,990 | ×4.1 | ×9.5 |
| 50 | 1,050 | 4,560 | 24,225 | ×4.3 | ×23.1 |
| 100 | 2,100 | 9,310 | 95,950 | ×4.4 | ×45.7 |

How to read the table: the two rightmost columns are how many times more expensive each method is versus the cumulative approach. The longer the conversation (the larger N), the wider the gap — B2 goes from ×5.0 to ×45.7 against cumulative. In other words, for long conversations or live operation, re-feeding the whole thing every turn (B2) is effectively cost-prohibitive, and re-feeding just the last few turns (B1.5) still costs K times as much. This number backs the justification the measurement conclusion leans on: "B2-level accuracy at 1/N of B2's cost." But this table is an estimate, not a real measurement: each turn is taken as roughly 19 tokens (the bundled data's Korean messages average about 28 characters), and judge pricing is an assumption. Run it on local Ollama and the actual money cost is zero; the table only shows the relative scale you would see if you moved to a cloud judge. Reproduce it with `sgr cost-model`; details are in [`out/cost.md`](out/cost.md).

## Measurement Results

> **In plain terms:** We re-measured with the test set grown from 87 to 200 conversations (more coin tosses, more trust in the result). The core advantage held and got sturdier; the weakness (mistaking long normal chats for crises) showed up more clearly at 18%→31%, and we left it in as-is; and the "doesn't know what a crisis is" control gained nothing from accumulating, confirming the result isn't rigged.

Now the effect itself. The source numbers are in [`out/mini.md`](out/mini.md). The comparison takes 115 conversations where a crisis actually occurred (C1 positive test: c1.test 100 + 15 merged from c1.calib) and 100 conversations that resolved normally (C3 test, 55 of which are a "long-but-normal" control), set against the approach that looks at the last 5 turns (K=5).

First, two terms unpacked. **Recall** is the rate of "how many real crises were caught without missing them," and **false-positive rate (FPR)** is the rate of "mistaking a fine conversation for a crisis." A good crisis detector has to do both at once — catch many crises, but not wrongly flag the fine ones.

To lead with the core finding: in one detector called `target_aware`, the cumulative approach (STATEFUL) clearly beat the single-shot approach that looks at the last 5 turns (B1.5).

| Comparison | Δrecall (all) | Δrecall (K+) | ΔTTD (all) | McNemar p |
|---|---|---|---|---|
| STATEFUL − B1 (per-turn) | +21.7%p | +34.0%p | −0.11 | 0.000 |
| STATEFUL − B1.5 (sliding-window) | +51.3%p | +62.3%p | +0.25 | 0.000 |

How to read the table: each number is the difference in "how much better the cumulative approach was than the single-shot one" (%p, percentage points), and positive means cumulative is better. The rightmost McNemar p is "the probability this difference is chance," and the smaller it is (typically below 0.05), the stronger the evidence that it is not chance. ΔTTD is "how many turns earlier the cumulative approach caught it than the single-shot one," and positive means earlier (success_turn − detect_turn). And when we re-compute the recall difference against the single-shot approach (B1.5) 2,000 times over reshuffled samples (a bootstrap confidence interval), the whole range comes out as [+41.7%p, +60.9%p] — all above 0, meaning the direction of the difference does not flip by chance.

We also checked separately that this advantage is not an illusion from "setting the bar too loose." When we align both sides to the same rate of wrongly flagging fine conversations (FPR) and re-measure recall, cumulative still leads single-shot consistently — by +10.4%p at FPR ≤5%, +28.7%p at ≤10%, and +22.6%p at ≤20%. And sweeping the key setting (λ) across 0.5, 0.7, 0.9, and 1.0 to see whether the conclusion wobbles (the λ-sweep), the difference against single-shot (B1.5) stays between +30%p and +51%p and never once flips sign. That closes the "you bought the advantage by allowing false positives" and "it's just small-sample chance" objections across three layers: operating-point alignment, the confidence interval, and the full λ range.

That recall advantage was not free, though. On the "long-but-normal" long conversations, the cumulative approach mistook a fine conversation for a crisis 31% of the time (17 of 55), higher than the single-shot approach's (B1.5) 4% (2 of 55). That is the price of not fully separating "the score went up because the conversation is long" from "the score went up because it really is a crisis."

In the other detector, `target_agnostic`, the advantage did not hold. Cumulative came in at +0.0%p versus single-shot B1 (p=1.000) and −7.8%p versus single-shot B1.5 (p=0.004), with a confidence interval of [−13.0%p, −3.5%p] that sits entirely below 0. This is not merely "no difference" (non-significant): in this approach, which has no notion of what a crisis is, cumulative actually falls significantly behind the single-shot baseline — a result we reinforced by expanding the sample to 200. It makes plain that "if you don't know what a crisis is, accumulating buys you nothing," and it strengthens the evidence that the success of the crisis-aware detector (`target_aware`) is not a self-fulfilling artifact of answers planted in the data.

This asymmetry actually reads as the design working as intended. `target_agnostic` only looks at "how much the direction of the talk shifted compared with the previous few turns." But that quantity rises similarly in crisis and normal conversations alike, so it has weak power to single out a crisis. That only the approach watching movement accumulating toward the target (the crisis) held (`target_aware`), while the one watching direction-agnostic change did not (`target_agnostic`), partially supports that the data was not stacked in favor of one particular detector. It is not a perfect reverse control, however, so we cannot entirely rule out that the result fell out of the data design by itself (circularity).

## One-line Conclusion

In one detector (`target_aware`), the cumulative approach (STATEFUL) robustly beat the single-shot approach (stateless) — even after matching false-positive rates, even after resampling 2,000 times, even after changing the setting (McNemar p=0.000). But the control we put in to screen for circularity, `target_agnostic`, did not hold, so circularity cannot be entirely ruled out, and catching crises better raised the rate of wrongly flagging long normal conversations to 31%. This inherits Mycelium's `graph_weight=0.0` spirit: the numbers go down as they are, whether or not they flatter the project.

## Measurement Discipline

How we measured matters more than the numbers themselves, and that is the real heart of this project. So we did not stop at "honestly reporting what didn't work" — we treated the measurement as an experimental design that exposes itself if it is wrong.

**We set up fair comparison baselines.** There are three: the single-shot approach that looks only at each message (B1), the single-shot approach that looks at the last 5 turns (B1.5), and the cumulative approach (STATEFUL). All three were aligned to the same 5% rate of wrongly flagging fine conversations, so they could answer head-on the objection "isn't this just the same as looking at the last few turns?"

**The settings were fixed in advance and never touched again.** λ=0.7, K=5, and the handoff thresholds `t1` and `t2` were all set on a separate calibration dataset before the test data was ever seen, and were not adjusted during measurement (because tuning settings while looking at the test data inflates the score).

**We controlled for conversation length skewing the result.** Normal conversations (C3) had a median length of 6 turns versus 5 for crisis conversations (C1). Because the cumulative approach raises its score the longer a conversation runs, it could mistakenly flag something "because it's long." So we expanded the "long-but-normal" control to 55 conversations to strengthen the check, and reported the 62 that ended within the last 5 turns separately from the 53 that ran past 5. We even disclose openly that within 5 turns, the single-shot approach (B1.5) and the cumulative approach are structurally near-identical.

**We checked that the result was not rigged to come out by itself.** We ran two detectors in parallel — `target_aware`, which watches movement accumulating toward the target (the crisis), and `target_agnostic`, which only watches how much the talk changed versus the previous few turns regardless of direction. If only one holds, that is grounds to say the data was not stacked in favor of one particular detector. We also separated the AI that made the data from the AI that evaluates it — data was generated with claude-opus (Anthropic) while evaluation and embedding used bge-m3 and qwen2.5:14b (Alibaba) — to reduce the risk of the generator's writing style circling back into the evaluation.

**"It won" was decided by a statistical test, not by eye.** Only when "the probability this difference is chance" (the McNemar test) on the most important comparison (versus single-shot B1.5) came in below 0.05 did we declare it established, and we exposed the uncertainty alongside it with the FPR-matched re-comparison and a 2,000-iteration confidence interval on a fixed seed. We also drew the difference curve for the setting (λ) across the full 0.5, 0.7, 0.9, 1.0 range, and had any sign flipped anywhere, we would have published it as-is. That result is in [`out/lambda.md`](out/lambda.md).

## Architecture

The dependency direction is `interfaces → pipeline → adapters → core` — the outer layers (CLI, external integrations) depend on the inner ones (pure computation) and never the reverse. This is the Clean Architecture inherited from Mycelium.

```
interfaces/   CLI (typer, sgr commands) — I/O entry point
pipeline/     Judgment pipeline orchestration
              (message ingress → policy execution → escalation decision → audit log)
adapters/     External boundary: LLM/embedding provider (Ollama), state persistence (JSON), audit log
core/         Pure domain: Policy interface, SessionState, cumulative judgment algorithm
              (no external I/O or framework dependencies — numeric operations use stdlib math only)
```

The accumulation formula is `S_t = clip(λ·S_{t-1} + signal_t, 0, S_max)` — it weighs recent signals more heavily to build up the crisis score while gradually forgetting older ones at a rate of λ=0.7 (an EWMA, an exponentially weighted moving average). The point worth noting is that the baselines are not separate code but modes of the same engine: ignore past state and you get B1 (single-shot), slide over the last K turns and you get B1.5, reference the accumulated state and you get STATEFUL. The delta between the three paths is measured on identical data under an identical policy. The design decisions (D-1 through D-10) are in [`docs/DESIGN.md`](docs/DESIGN.md), and the execution plan plus verification criteria (ISC) are in [`docs/PLAN.md`](docs/PLAN.md).

## Quick Start

This repository is best handed to an AI coding agent (Claude Code, Codex, Cursor, etc.) — it will clone, install, run, and report back on its own. Just paste the instruction below.

> Clone this repo and install it into a Python 3.12 virtualenv with `pip install -e ".[dev]"`. Pull `bge-m3` and `qwen2.5:14b` via Ollama and start `ollama serve`, then run `sgr escalate -s c1-test-001` to show the cumulative crisis-escalation demo, and `sgr eval --mini --dataset data/` to reproduce the measurements and compare against the bundled `out/mini.md`.

To run it yourself, or as a command reference (all local, zero external API calls):

```bash
pip install -e ".[dev]"              # install (Python 3.12)
ollama pull bge-m3                   # embeddings — always needed
ollama pull qwen2.5:14b              # judge — eval only

sgr escalate -s c1-test-001          # ★ cumulative crisis tracking + 3-stage handoff demo
sgr audit    -s c1-test-001          # audit trail for the decision above
sgr eval --mini --dataset data/      # ★ make-or-break check: cumulative vs baselines (stats)
sgr eval --mini --lambda-sweep 0.5,0.7,0.9,1.0 --dataset data/ --report out/lambda.md
sgr catalog                          # policy catalog  ·  sgr cost-model  cost table
```

## Data

The `data/` directory contains only synthetic (made-up) conversation sessions, with no sensitive information. `c1.{calib,test}.jsonl` holds cumulative crisis escalation sessions (synthetic, including Korean), `c3.{calib,test}.jsonl` holds normal-resolution conversations and the "long-but-normal" control sessions, and `calibration.json` carries the frozen parameters (λ, K, N, S_max, thresholds, FPR budget). No real customer data is included. This synthetic data plays the same role as Mycelium's `sample_vault/` — bundled so anyone can reproduce the evaluation immediately after cloning.

## Stack

Python 3.12 · typer · httpx · Ollama (`bge-m3` embeddings + `qwen2.5:14b` judge). Numeric operations use only stdlib `math`, with no external numeric dependencies, keeping the core layer's dependencies minimal.

## License

MIT
