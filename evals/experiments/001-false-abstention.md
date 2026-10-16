# 001: Why does a small model say "not in the documents" when the answer is right there?

> Status: draft. Reference (gpt-5-nano) results and the human audit of judge verdicts are pending.

## Question

With the correct documents in its context, Qwen3 8B answered "Dokümanlarda bu bilgi yok." ("The documents don't contain this.") on 5 of 24 answerable questions. Why, and which fix is acceptable for a finance assistant?

## Setup

- **Model:** Qwen3 8B (Ollama 0.40.3, default Q4_K_M), temperature 0, `num_ctx` 16384. Measured on MacBook Air M4, 16 GB, fanless.
- **Data:** golden set v1, 36 questions (12 easy, 12 multi-hop, 12 no-answer) over SPK/BDDK legislation and 2025 KAP disclosures.
- **Context:** oracle. Each question gets the passages that contain its answer (no-answer questions get near-miss documents), so retrieval is not a factor.
- **Judge:** gpt-5-mini; exact abstentions are graded by rule.
- **Scores:** `score` = correct 1, partial 0.5, wrong 0. `risk score` = correct +1, partial +0.5, unnecessary "no answer" 0, wrong or made-up answer −1, because in finance a wrong answer costs more than no answer.

| Run | Prompt | Thinking |
| --- | --- | --- |
| E0 | v1: strict grounding ("if the answer is not in the documents, write only 'Dokümanlarda bu bilgi yok.'") | off |
| E1 | v2: v1 + "if the answer can be computed or inferred from the documents (sum, date to period, combining two documents), answer and say how in one sentence" | off |
| E2 | v1 | on |

## Result

| | E0 | E1 | E2 |
| --- | --- | --- | --- |
| Score | 0.78 | 0.78 | **0.82** |
| Risk score | 0.72 | 0.64 | **0.76** |
| Easy | 0.79 | 0.79 | 0.75 |
| Multi-hop | 0.54 | 0.63 | **0.88** |
| No-answer | 1.00 | 0.92 | 0.83 |
| Unnecessary "no answer" (of 24 answerable) | 5 | **2** | 4 |
| Made-up answer (of 12 no-answer) | 0 | 1 | 2 |
| Latency p50 / p95 | **5.4 / 24 s** | 6.5 / 22 s | 21 / 48 s |
| Mean output tokens | 37 | 66 | 339 |

Caveats: 36 questions, so one question moves the overall score by ~3 points; single run per setting. Three judge mistakes were found by hand (E0 q21, E1 q18, E2 q32), comparable in size to some of the differences above; the audited numbers will replace these.

Examples:

- **Multi-hop, E0 → E2 (q14).** Two disclosures list orders of 998,400 USD and 1,335,000 USD; the question asks for the total. E0: "not in the documents". E1: "998,400 USD" (only the first). E2: "2,333,400 USD (998,400 + 1,335,000)".
- **Wording gap, unchanged in all runs (q02).** The question asks about orders "in autumn 2025"; the document only gives the date 31.10.2025. All three runs: "not in the documents".
- **Side effect of v2 (q34).** "How many stores did Migros open in 2025?" The corpus only has December 2024 openings ("18 Migros ..."). E1 answered "18".

## Why?

*(Enes's analysis; evidence from the runs above.)*

| Hypothesis | Evidence | Status |
| --- | --- | --- |
| The strict grounding instruction pushes the model to abstain | Softening it (E1) cut unnecessary abstentions from 5 to 2 | Supported |
| The model does not bridge the gap between the question's wording and the document's wording | q02 ("autumn" vs a date) abstains under every setting | Supported |
| Limited capacity: the model cannot do multi-step work in a single pass | With thinking (E2) multi-hop rose from 0.54 to 0.88; the model can do it, but not in one step. Whether a larger model does it without thinking: see reference run | Partly; pending |
| Position of the information in the context | Prompts are short (max ~4.3k tokens); "lost in the middle" effects are usually reported at much longer contexts | Not tested; unlikely here |

Mechanism: thinking gives the model extra serial computation (it writes intermediate steps), which fixes multi-step questions. Whether an answer "is in the documents" is an interpretation question rather than a computation one; thinking did not reduce abstentions (5 → 4) and added two on easy questions. *(To check: read the thinking traces, which are now saved.)*

## Alternatives

- **Few-shot examples.** Add two examples to the prompt: one question whose answer must be derived from the documents and is answered, and one whose answer is genuinely absent and gets "no answer".
  *Why not now:* it changes several things at once (prompt length, content, and the answer format the model gets used to), so an improvement could not be attributed. Examples that resemble the test set would also risk leakage.
- **Quote first.** The model first extracts the relevant quotes, then decides.
  *Why not now:* the output format changes and the final answer has to be parsed out before judging. It is also close to thinking, so thinking had to be measured first. Now that thinking fixed multi-hop questions at 4× latency, quote-first is the natural next experiment: a cheaper, thinking-free variant of the same idea.
- **System prompt in English.** Qwen may follow instructions better in English.
  *Why not now:* a cheap, single-variable test, but all five failures were derivation cases (date to period, a sum, combining two documents), so the language hypothesis had lower priority.
- **A larger model.** Tests the capacity hypothesis directly.
  *Why not now (locally):* covered by the API reference run. Open 14B+ models are tight on a 16 GB Mac (qwen3:14b is ~9.3 GB before KV cache; 30B+ does not fit), so they move to the RTX 4090 in Level 2.
- **A separate "is the answer in the documents?" classifier** before generation (the same model asked yes/no, or a small decision model).
  *Why not now:* it adds a second model call or model and changes the pipeline rather than the prompt. It belongs with the Level 3 classification lab and the Level 4 router.

## What does this change in my system?

*(Draft.)* Keep the strict prompt (v1): an unnecessary "no answer" is acceptable, a made-up figure is not. Report risk score next to score, and treat thinking as a separate axis (accuracy vs. 4× latency) in Level 1.

## Post

Planned.
