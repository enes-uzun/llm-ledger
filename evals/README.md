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

## Tools

```bash
.venv/bin/python evals/search.py "kredi notu" --source kap     # find documents and snippets
.venv/bin/python evals/search.py --show kap-1389746             # read a whole document
.venv/bin/python evals/validate_golden.py                       # check the golden set against the corpus
```
