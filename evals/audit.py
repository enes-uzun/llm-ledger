"""Human audit of LLM-judge verdicts.

export: collect judge verdicts from result files into one CSV for review. Answers graded by
        rule (exact abstentions) are skipped, and identical answers to the same question across
        runs appear once.
apply:  after filling the `human_verdict` column (correct / partial / incorrect, empty = agree
        with the judge), write corrected copies of the result files and print judge agreement.

Usage:
  python evals/audit.py export evals/results/A.jsonl evals/results/B.jsonl -o evals/audits/001.csv
  python evals/audit.py apply evals/audits/001.csv
"""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_eval import SCORES, abstains, print_summary, summarize  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIELDS = ["key", "runs", "id", "category", "question", "gold", "answer",
          "judge_verdict", "judge_reason", "human_verdict", "note"]


def load(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def export(paths: list[Path], out: Path) -> None:
    items: dict[tuple, dict] = {}
    for path in paths:
        for r in load(path):
            if abstains(r["answer"]):
                continue
            key = (r["id"], r["answer"].strip())
            if key in items:
                items[key]["runs"].append(path.name)
                if items[key]["judge_verdict"] != r["verdict"]:
                    items[key]["judge_verdict"] += f" / {r['verdict']}"
                continue
            items[key] = {"id": r["id"], "category": r["category"], "question": r["question"],
                          "gold": r["gold"], "answer": r["answer"], "judge_verdict": r["verdict"],
                          "judge_reason": r["reason"], "runs": [path.name]}
    rows = sorted(items.values(), key=lambda x: (x["id"], x["judge_verdict"]))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for i, row in enumerate(rows, 1):
            w.writerow({**row, "key": i, "runs": " ".join(row["runs"]), "human_verdict": "", "note": ""})
    print(f"{len(rows)} verdicts to review -> {out}")


def apply(audit: Path) -> None:
    with audit.open(encoding="utf-8", newline="") as f:
        reviewed = list(csv.DictReader(f))
    bad = [r["key"] for r in reviewed if r["human_verdict"].strip() and r["human_verdict"].strip() not in SCORES]
    if bad:
        raise SystemExit(f"invalid human_verdict in rows {bad}; use correct / partial / incorrect or leave empty")

    fixes, agree, total = {}, 0, 0
    for r in reviewed:
        human = r["human_verdict"].strip()
        for run in r["runs"].split():
            total += 1
            fixes[(run, r["id"], r["answer"].strip())] = human or None
    for run in sorted({r["runs"].split()[0] for r in reviewed} | {x for r in reviewed for x in r["runs"].split()}):
        path = ROOT / "evals" / "results" / run
        rows = load(path)
        changed = 0
        for row in rows:
            human = fixes.get((run, row["id"], row["answer"].strip()))
            if human is None:
                if (run, row["id"], row["answer"].strip()) in fixes:
                    agree += 1
                continue
            if human == row["verdict"]:
                agree += 1
            else:
                row["judge_verdict"], row["verdict"] = row["verdict"], human
                changed += 1
        out = path.with_name(path.stem + ".audited.jsonl")
        out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        meta = json.loads(path.with_suffix(".summary.json").read_text(encoding="utf-8"))
        meta = {k: v for k, v in meta.items() if not isinstance(v, dict)}
        meta["audited"] = audit.name
        summary = summarize(rows, meta)
        out.with_suffix(".summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{run}: {changed} verdicts changed")
        print_summary(summary)
    print(f"\njudge agreement with human review: {agree}/{total} judge-graded verdicts")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("results", nargs="+", type=Path)
    e.add_argument("-o", "--out", type=Path, required=True)
    a = sub.add_parser("apply")
    a.add_argument("audit", type=Path)
    args = p.parse_args()
    if args.cmd == "export":
        export(args.results, args.out)
    else:
        apply(args.audit)


if __name__ == "__main__":
    main()
