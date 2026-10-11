"""Grep-style search over the downloaded corpus, for writing and reviewing golden set questions.

Usage:
  python evals/search.py "sermaye artırımı"            # documents containing the phrase, with snippets
  python evals/search.py "fitch" --source kap           # restrict to one source
  python evals/search.py --show kap-1466689             # print a whole document
"""

import argparse
import json
import re
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def fold(text: str) -> str:
    """Case-fold Turkish text so that 'İ'/'i' and 'I'/'ı' match their lowercase forms."""
    return text.replace("İ", "i").replace("I", "ı").lower()


def load_docs(source: str | None) -> list[dict]:
    pattern = f"{source}/*.json" if source else "*/*.json"
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(RAW_DIR.glob(pattern)) if not p.name.startswith("_")]


def snippets(text: str, query: str, width: int, limit: int) -> list[str]:
    folded = fold(text)
    out = []
    for m in re.finditer(re.escape(fold(query)), folded):
        start, end = max(0, m.start() - width), min(len(text), m.end() + width)
        out.append(text[start:end].replace("\n", " "))
        if len(out) == limit:
            break
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("query", nargs="?", help="phrase to search for (case-insensitive)")
    parser.add_argument("--source", choices=["kap", "mevzuat"])
    parser.add_argument("--show", metavar="DOC_ID", help="print one document in full")
    parser.add_argument("--width", type=int, default=120, help="characters of context around a hit")
    parser.add_argument("--snippets", type=int, default=2, help="snippets per document")
    args = parser.parse_args()

    docs = load_docs(args.source)
    if args.show:
        doc = next((d for d in docs if d["doc_id"] == args.show), None)
        if doc is None:
            raise SystemExit(f"{args.show} not found")
        print(f"{doc['doc_id']} | {doc['category']} | {doc['date']}\n{doc['title']}\n{doc['url']}\n")
        print(doc["text"])
        if doc.get("text_en"):
            print("\n--- English ---\n" + doc["text_en"])
        return
    if not args.query:
        parser.error("give a query or --show DOC_ID")

    hits = []
    for doc in docs:
        n = fold(doc["text"]).count(fold(args.query))
        if n:
            hits.append((n, doc))
    hits.sort(key=lambda h: -h[0])
    print(f"{len(hits)} documents contain {args.query!r}\n")
    for n, doc in hits:
        print(f"{doc['doc_id']}  ({n} hits)  {doc['title'][:90]}")
        for s in snippets(doc["text"], args.query, args.width, args.snippets):
            print(f"    ...{s}...")
        print()


if __name__ == "__main__":
    main()
