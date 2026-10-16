# evals

Golden sets and metric code shared by all labs. Every experiment writes its results in the same format so runs can be compared side by side.

## Golden set

[`golden_v1.jsonl`](golden_v1.jsonl) holds the questions every system in this repo is measured on. One question per line:

```json
{
  "id": "q01",
  "category": "easy",
  "question": "Fitch 2025 başında THY'nin kredi notunu nasıl değiştirdi?",
  "answer": "Fitch, Türk Hava Yolları'nın notunu BB-'den BB'ye yükseltti; görünüm Durağan olarak teyit edildi.",
  "doc_ids": ["kap-1389746"],
  "evidence": [{"doc_id": "kap-1389746", "quote": "kredi notunu BB-'den BB'ye yükseltmiştir"}],
  "related_doc_ids": [],
  "status": "draft"
}
```

| Field | Meaning |
| --- | --- |
| `category` | `easy` (one document, one fact), `multi_hop` (two documents, or a fact plus the rule behind it), `no_answer` (the corpus does not contain the answer) |
| `doc_ids` | Documents that contain the answer. Retrieval metrics (Recall@k, MRR) are computed against this list. Empty for `no_answer`. |
| `evidence` | Verbatim quotes from those documents that support the answer |
| `related_doc_ids` | For `no_answer`: near-miss documents a system is likely to retrieve and over-trust |
| `status` | `draft` or `reviewed` |

`no_answer` questions are deliberately close to the corpus (a company that is in it, a fact that is almost there) to test whether a system says "not in the documents" instead of guessing.

### How it was built

The questions were drafted by an LLM (Claude) from the corpus, then reviewed and edited by hand. Each question has evidence quotes copied from the source, and `validate_golden.py` checks that every quote still appears in its document. Known risk: questions drafted from the documents may reuse their wording, which favours lexical retrieval (BM25). The draft paraphrases where possible; the review pass is meant to make the wording sound like a real user.

All questions are about companies, regulations and numbers; none target individuals.

## Running an eval

```bash
.venv/bin/python evals/run_eval.py --backend ollama --model qwen3:8b
.venv/bin/python evals/run_eval.py --backend openai --model <model> --price-in <usd/1M> --price-out <usd/1M>
```

- **Context mode: oracle.** Each question gets the passages of its gold documents (for `no_answer`: the near-miss documents). Short documents are passed whole; long ones as ±2,000-character windows around the evidence quotes. This isolates answer generation from retrieval, so model and quantization runs are comparable; retrieval is measured separately.
- **Local models** run through Ollama's native API with `num_ctx=16384` and thinking off by default. Ollama's default context is 4,096 tokens and silently truncates longer prompts, which would cut the documents.
- **Scoring:** correct = 1, partial = 0.5, incorrect = 0. An answer that says "Dokümanlarda bu bilgi yok." is graded by rule (right for `no_answer`, wrong otherwise); everything else goes to an LLM judge.
- **Output:** `evals/results/<timestamp>_<model>.jsonl` (answers, latency, tokens, cost, verdict and judge reasoning per question) and `.summary.json` (score per category, p50/p95 latency, cost per question, run settings).

### Judge choice

Before the first run, the judge prompt was tested on 7 hand-labelled gradings × 3 repeats:

| Judge | Agreement with hand labels |
| --- | --- |
| gpt-5-nano | 18/21 |
| gpt-5-mini | 21/21 |

The first prompt version let gpt-5-nano accept "BB'den BB'ye" for a reference of "BB-'den BB'ye" and was inconsistent across repeats at every reasoning effort. The fix was twofold: grade only the values the question asks for, copied exactly, and use gpt-5-mini. A proper calibration against human labels on the full set is planned for Level 2.

## Tools

```bash
.venv/bin/python evals/search.py "kredi notu" --source kap     # find documents and snippets
.venv/bin/python evals/search.py --show kap-1389746             # read a whole document
.venv/bin/python evals/validate_golden.py                       # check the golden set against the corpus
```
