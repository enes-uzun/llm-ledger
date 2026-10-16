# llm-ledger

Measured LLM experiments on Turkish finance data: tokenization, quantization, RAG, serving, fine-tuning, agents, security.

Every lab answers one question and ends with a measurement table, an explanation of *why* the result came out that way, and the alternatives that were considered.

## Labs

| # | Lab | Question | Status |
| --- | --- | --- | --- |
| 01 | [Tokenizer](labs/01-tokenizer/) | How much more does Turkish finance text cost in tokens than English? | planned |
| 02 | [Quantization](labs/02-quantization/) | What do Q4/Q5/Q8 cost in memory, speed and quality on a 16 GB laptop? | planned |
| 03 | [RAG](labs/03-rag/) | Which retrieval techniques actually help on Turkish finance text? | planned |
| 04 | [Serving](labs/04-serving/) | How do vLLM and llama.cpp compare under concurrent load? | planned |
| 05 | [Fine-tuning](labs/05-finetune/) | Prompt vs RAG vs QLoRA for Turkish finance intent classification | planned |
| 06 | [Agent](labs/06-agent/) | What breaks in a framework-free agent loop, and how to defend it? | planned |
| 07 | [Security](labs/07-security/) | How much does a guardrail reduce indirect prompt injection success? | planned |
| 08 | [Platform](labs/08-platform/) | What does a reference LLM platform for a finance org look like, and what does it cost? | planned |

## Baseline (Month 0)

Golden set v1: 36 questions over the corpus (12 easy, 12 multi-hop, 12 with no answer in the documents). The answer passages are given in context, so these numbers measure answer generation, not retrieval. Verdicts by an LLM judge (gpt-5-mini), audited by hand.

| Model | Reasoning | Score | Risk score | Latency p50 / p95 | Cost / question |
| --- | --- | --- | --- | --- | --- |
| Qwen3 8B, local (Q4_K_M, MacBook Air M4, fanless) | off | 0.81 | 0.78 | 5.4 / 24 s | $0 |
| Qwen3 8B, local | on | 0.78 | 0.72 | 21 / 48 s | $0 |
| gpt-5-nano (API reference) | minimal | 0.64 | 0.58 | 1.0 / 2.6 s | $0.00006 |
| gpt-5-nano (API reference) | medium | **0.97** | **0.94** | 6.2 / 21 s | $0.0005 |
| gpt-5-mini | minimal | 0.58 | 0.56 | 0.9 / 1.5 s | $0.0003 |

Score: correct 1, partial 0.5, wrong 0. Risk score: wrong or made-up answers count −1 and "not in the documents" counts 0, because in finance a wrong answer costs more than no answer. Full write-up: [experiment 001](evals/experiments/001-false-abstention.md).

## Layout

```text
data/    download scripts (raw data is never committed)
evals/   golden sets and metric code
labs/    one folder per experiment; start from labs/_template/
adr/     architecture decision records
notes/   notes from videos and papers
posts/   write-up drafts
```

## Data policy

Only publicly available data is used (e.g. KAP disclosures, SPK/BDDK regulations, TCMB reports). Sources and their terms of use are listed in [data/README.md](data/README.md). Raw data, model weights and API keys are never committed.

## Hardware

Local runs: MacBook Air M4, 16 GB unified memory, fanless (llama.cpp/Metal, Ollama, MLX). CUDA-only work (vLLM, QLoRA) runs on a rented RTX 4090. Each lab notes where it was measured.

## License

[MIT](LICENSE)
