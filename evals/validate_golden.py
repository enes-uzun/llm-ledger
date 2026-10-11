"""Check a golden set file against the downloaded corpus.

Checks: required fields, valid category, doc_ids exist, every evidence quote appears verbatim
(whitespace-normalized) in its document, and no_answer questions cite no supporting documents.

Usage: python evals/validate_golden.py [evals/golden_v1.jsonl]
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
CATEGORIES = {"easy", "multi_hop", "no_answer"}
REQUIRED = ["id", "category", "question", "answer", "doc_ids", "evidence", "related_doc_ids", "status"]


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def load_corpus() -> dict[str, str]:
    corpus = {}
    for path in RAW_DIR.glob("*/*.json"):
        if path.name.startswith("_"):
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        corpus[doc["doc_id"]] = norm(doc["text"])
    return corpus


def validate(path: Path) -> list[str]:
    corpus = load_corpus()
    errors, ids = [], set()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        qid = row.get("id", "?")
        missing = [k for k in REQUIRED if k not in row]
        if missing:
            errors.append(f"{qid}: missing fields {missing}")
            continue
        if qid in ids:
            errors.append(f"{qid}: duplicate id")
        ids.add(qid)
        if row["category"] not in CATEGORIES:
            errors.append(f"{qid}: unknown category {row['category']!r}")
        for doc_id in row["doc_ids"] + row["related_doc_ids"]:
            if doc_id not in corpus:
                errors.append(f"{qid}: unknown doc_id {doc_id}")
        if row["category"] == "no_answer":
            if row["doc_ids"] or row["evidence"]:
                errors.append(f"{qid}: no_answer questions must have empty doc_ids and evidence")
        elif not row["doc_ids"] or not row["evidence"]:
            errors.append(f"{qid}: answerable questions need doc_ids and evidence")
        for ev in row["evidence"]:
            if ev["doc_id"] not in row["doc_ids"]:
                errors.append(f"{qid}: evidence doc {ev['doc_id']} not in doc_ids")
            elif norm(ev["quote"]) not in corpus.get(ev["doc_id"], ""):
                errors.append(f"{qid}: quote not found in {ev['doc_id']}: {ev['quote'][:60]!r}")
    counts = Counter(r.get("category") for r in rows)
    print(f"{len(rows)} questions: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return errors


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "evals" / "golden_v1.jsonl"
    errors = validate(path)
    for e in errors:
        print("ERROR", e)
    if errors:
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
