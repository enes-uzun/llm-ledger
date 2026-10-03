# ADR-0001: Corpus selection

- Status: accepted
- Date: 2026-10-04

## Context

Every lab in this repo (tokenizer, quantization, RAG, serving, fine-tuning, agent, security) is measured on one shared Turkish finance corpus, so the choice of corpus shapes nine months of experiments. Constraints:

- **Public data only.** Nothing from an employer; the repo is public.
- **Small enough to hand-label.** A 30-question golden set has to be written by hand, with the supporting documents identified for each question. A corpus of a few hundred documents keeps that feasible.
- **Reproducible without redistributing.** Raw text is not committed, so the corpus must be rebuildable from scripts.

Candidates checked (2026-10-02/03):

| Source | Legal basis | Scriptable? |
| --- | --- | --- |
| mevzuat.gov.tr (SPK, BDDK legislation) | Not protected by copyright (Law No. 5846, Art. 31) | Yes: listing endpoint plus clean HTML text per document |
| KAP disclosures | No published terms of use found; content belongs to disclosing companies | Yes, via the undocumented endpoints behind kap.org.tr; rate-limited (HTTP 429) |
| SPK / BDDK websites directly | No terms found; legislation itself is Art. 31 | SPK pages are JS-rendered; same texts are on mevzuat.gov.tr |
| TCMB reports | Republishing allowed with attribution; commercial use requires written permission | Yes |

## Decision

A two-source corpus of 322 documents:

1. **Mevzuat (172 docs):** every SPK and BDDK communiqué and regulation listed on mevzuat.gov.tr, plus the Capital Markets Law (6362) and the Banking Law (5411). Long, structured, article-based text (median ~28k chars, max ~851k).
2. **KAP (150 docs):** a stratified, seeded sample of 2025 material event disclosures across 8 subjects, at most 2 per company (112 companies). The 6 free-text subjects only include disclosures published in both Turkish and English (115 docs); dividend and capital change disclosures are structured forms (35 docs). Short, fact-dense text (median ~630 chars).

Both are fetched by scripts in `data/`; `data/manifest.csv` records each document's URL and a SHA-256 of its text.

## Alternatives considered

- **Mevzuat only.** Legally the cleanest and fully stable. Rejected because it would remove things later labs need: there is no parallel English text for the tokenizer lab, metadata (company, disclosure type, date) is too thin for the metadata-filtering step, there is no natural label for the Level 3 intent classifier, and there are no short factual documents for "no answer in corpus" questions.
- **Adding TCMB reports.** Long narrative text would help Contextual Retrieval, but mevzuat already supplies long documents, and the commercial-use restriction adds a caveat for no new capability. Deferred.
- **500 documents.** Rejected for now: the bottleneck in Month 0 is the hand-written golden set, not corpus size. Easy to grow in Level 2.
- **Two KAP periods (e.g. 2024 vs 2025) for a temporal test split.** Rejected in favour of a single, simpler range; can be revisited if a temporal evaluation becomes relevant.

## Consequences

- **Easier:** TR/EN token comparison on 115 real parallel documents; realistic mixed corpus (very long legal text next to short disclosures) for chunking and retrieval experiments; disclosure subject as a free, public label set; KAP dates and companies enable metadata filtering.
- **Harder:** two text types need different chunking strategies; structured KAP forms are "label/value" text that retrieval may handle poorly.
- **Risks to watch:**
  - KAP endpoints are undocumented and may change or block; the manifest preserves what was used.
  - Some material event disclosures name board members. Golden set questions must never target individuals.
  - Mevzuat texts change when amended; hashes in the manifest detect drift, and re-downloading may require updating golden set answers.
